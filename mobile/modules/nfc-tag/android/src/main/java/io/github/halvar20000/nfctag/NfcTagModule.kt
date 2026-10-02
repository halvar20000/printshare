package io.github.halvar20000.nfctag

import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.NfcV
import android.os.Handler
import android.os.Looper
import android.util.Base64
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.CodedException
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.ByteArrayOutputStream

/** Reads the memory of an NFC-V (ISO 15693) tag, e.g. an OpenPrintTag spool (ICODE SLIX2, 80 blocks × 4 bytes).
 *  Read only: no write or lock commands are ever sent. The app parses the bytes (NDEF → CBOR, lib/openprinttag.ts). */
class NfcTagModule : Module() {
  private val main = Handler(Looper.getMainLooper())
  private var pending: Promise? = null
  private var timeout: Runnable? = null

  override fun definition() = ModuleDefinition {
    Name("NfcTag")

    /** "on", "off" (switched off in the settings) or "none" (no NFC hardware) */
    Function("status") {
      val adapter = appContext.reactContext?.let { NfcAdapter.getDefaultAdapter(it) }
      when {
        adapter == null -> "none"
        adapter.isEnabled -> "on"
        else -> "off"
      }
    }

    /** Waits for an NFC-V tag (reader mode, max timeoutMs) and resolves {uid: hex as reported, data: base64, blockSize}. */
    AsyncFunction("readAsync") { timeoutMs: Int, promise: Promise ->
      val activity = appContext.currentActivity
      val adapter = activity?.let { NfcAdapter.getDefaultAdapter(it) }
      if (activity == null || adapter == null) {
        promise.reject(CodedException("ERR_NFC_UNAVAILABLE", "this phone has no NFC", null)); return@AsyncFunction
      }
      if (!adapter.isEnabled) {
        promise.reject(CodedException("ERR_NFC_OFF", "NFC is switched off", null)); return@AsyncFunction
      }
      finish(null, CodedException("ERR_NFC_CANCELLED", "a new read started", null))
      pending = promise
      adapter.enableReaderMode(activity, { tag -> onTag(tag) },
        NfcAdapter.FLAG_READER_NFC_V or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK, null)
      val t = Runnable { finish(null, CodedException("ERR_NFC_TIMEOUT", "no tag found", null)) }
      timeout = t
      main.postDelayed(t, timeoutMs.toLong())
    }.runOnQueue(Queues.MAIN)

    AsyncFunction("cancelAsync") {
      finish(null, CodedException("ERR_NFC_CANCELLED", "cancelled", null))
    }.runOnQueue(Queues.MAIN)

    OnActivityEntersBackground {
      main.post { finish(null, CodedException("ERR_NFC_CANCELLED", "app in background", null)) }
    }
  }

  private fun onTag(tag: Tag) {                 // NFC thread: reading may take a moment
    val result = try {
      read(tag)
    } catch (e: Exception) {
      main.post { finish(null, CodedException("ERR_NFC_READ", "could not read the tag (${e.message}) - hold the phone still on it", e)) }
      return
    }
    main.post { finish(result, null) }
  }

  private fun read(tag: Tag): Map<String, Any> {
    val v = NfcV.get(tag) ?: throw IllegalStateException("not an NFC-V tag")
    v.use { nfc ->
      nfc.connect()
      var blockSize = 4
      var blocks = 256
      // Get System Information (0x2B): [flags, info flags, UID×8, (DSFID), (AFI), (blocks-1, size-1), …]
      try {
        val info = nfc.transceive(byteArrayOf(0x02, 0x2B))
        if (info.isNotEmpty() && info[0].toInt() and 1 == 0) {
          val flags = info[1].toInt()
          var i = 10
          if (flags and 1 != 0) i++                  // DSFID
          if (flags and 2 != 0) i++                  // AFI
          if (flags and 4 != 0 && info.size > i + 1) {
            blocks = (info[i].toInt() and 0xFF) + 1
            blockSize = (info[i + 1].toInt() and 0x1F) + 1
          }
        }
      } catch (_: Exception) { /* not supported: read until the tag says no */ }
      val out = ByteArrayOutputStream()
      for (b in 0 until minOf(blocks, 256)) {
        val r = try { nfc.transceive(byteArrayOf(0x02, 0x20, b.toByte())) } catch (e: Exception) {
          if (b == 0) throw e else break
        }
        if (r.isEmpty() || r[0].toInt() and 1 != 0) break         // error flag: end of memory
        out.write(r, 1, r.size - 1)
      }
      return mapOf(
        "uid" to tag.id.joinToString("") { "%02x".format(it) },
        "data" to Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP),
        "blockSize" to blockSize,
      )
    }
  }

  private fun finish(result: Map<String, Any>?, error: CodedException?) {
    timeout?.let { main.removeCallbacks(it) }
    timeout = null
    val p = pending ?: return
    pending = null
    appContext.currentActivity?.let { a -> NfcAdapter.getDefaultAdapter(a)?.disableReaderMode(a) }
    if (result != null) p.resolve(result) else p.reject(error ?: CodedException("ERR_NFC", "failed", null))
  }
}
