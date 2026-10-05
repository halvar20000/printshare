package io.github.halvar20000.bambulan

import android.net.Uri
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/** Bambu Lab printers in LAN-only mode straight from the phone (beginner mode without a bridge): the protocol work is
 *  in BambuCore / BambuMqtt (plain Java, tested against a real P1S). Async functions run on Expo's background queue,
 *  so blocking sockets are fine here. Reports arrive as "onMessage" events, connection changes as "onState". */
class BambuLanModule : Module() {
  private val links = ConcurrentHashMap<String, BambuMqtt>()

  override fun definition() = ModuleDefinition {
    Name("BambuLan")
    Events("onMessage", "onState")

    /** {serial, issuer, bambu} of the printer's TLS certificate, null when nothing answers on port 8883. */
    AsyncFunction("certAsync") { host: String ->
      val c = BambuCore.readCert(host, BambuCore.MQTT_PORT, 4000) ?: return@AsyncFunction null
      mapOf("serial" to c[0], "issuer" to c[1], "bambu" to BambuCore.isBambu(c))
    }

    /** Bambu printers among the hosts: [{address, serial}]. */
    AsyncFunction("probeAsync") { hosts: List<String>, timeoutMs: Int ->
      BambuCore.probe(hosts, BambuCore.MQTT_PORT, timeoutMs).map { mapOf("address" to it[0], "serial" to it[1]) }
    }

    /** Opens (or keeps) the MQTT connection; throws when the printer refuses the access code. */
    AsyncFunction("connectAsync") { host: String, serial: String, code: String ->
      val old = links[host]
      if (old != null && old.connected()) return@AsyncFunction true
      old?.close()
      val link = BambuMqtt(host, serial, code, object : BambuMqtt.Listener {
        override fun message(payload: String) = sendEvent("onMessage", mapOf("host" to host, "payload" to payload))
        override fun state(connected: Boolean, error: String?) =
          sendEvent("onState", mapOf("host" to host, "connected" to connected, "error" to error))
      })
      links[host] = link
      true
    }

    AsyncFunction("publishAsync") { host: String, json: String ->
      val link = links[host] ?: throw IllegalStateException("not connected to the printer")
      link.publish(json)
    }

    AsyncFunction("disconnectAsync") { host: String ->
      links.remove(host)?.close()
    }

    /** Wraps the G-code file (file:// URI from expo-file-system) into a .gcode.3mf and uploads it by FTPS;
     *  {filaments, size}. */
    AsyncFunction("uploadAsync") { host: String, code: String, uri: String, remoteName: String ->
      val ctx = appContext.reactContext ?: throw IllegalStateException("no context")
      val gcode = File(Uri.parse(uri).path ?: uri)
      val out = File(ctx.cacheDir, "bambu-${System.currentTimeMillis()}.gcode.3mf")
      try {
        val filaments = BambuCore.wrap3mf(gcode, out)
        BambuCore.upload(host, code, out, remoteName, null)
        mapOf("filaments" to filaments, "size" to out.length().toDouble())
      } finally {
        out.delete()
      }
    }
  }
}
