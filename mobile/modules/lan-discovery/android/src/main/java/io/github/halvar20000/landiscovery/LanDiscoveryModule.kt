package io.github.halvar20000.landiscovery

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.SocketTimeoutException

/** Finding printers on the home Wi-Fi: the phone's IPv4 address on the Wi-Fi (for the subnet scan in JS) and a UDP probe
 *  (Elegoo's SDCP discovery: "M99999" to port 3000, every Centauri Carbon answers with a JSON description).
 *  Async functions run on Expo's background queue, so blocking sockets are fine here. */
class LanDiscoveryModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("LanDiscovery")

    /** {address, prefix} of the Wi-Fi (or Ethernet) network, null when the phone isn't on one (e.g. mobile data). */
    AsyncFunction("wifiAddressAsync") {
      val ctx = appContext.reactContext ?: return@AsyncFunction null
      val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
      @Suppress("DEPRECATION")
      for (network in cm.allNetworks) {
        val caps = cm.getNetworkCapabilities(network) ?: continue
        if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
            !caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) continue
        val link = cm.getLinkProperties(network) ?: continue
        val v4 = link.linkAddresses.firstOrNull { it.address is Inet4Address && !it.address.isLoopbackAddress } ?: continue
        return@AsyncFunction mapOf("address" to v4.address.hostAddress, "prefix" to v4.prefixLength)
      }
      null
    }

    /** Sends `message` to each target (broadcast or unicast addresses) three times within the first half of `timeoutMs`
     *  and collects every answer until the time is up: [{address, data}]. */
    AsyncFunction("udpProbeAsync") { message: String, port: Int, targets: List<String>, timeoutMs: Int ->
      val out = mutableListOf<Map<String, String>>()
      val seen = HashSet<String>()
      DatagramSocket().use { sock ->
        sock.broadcast = true
        sock.soTimeout = 150
        val payload = message.toByteArray(Charsets.UTF_8)
        val addresses = targets.mapNotNull { runCatching { InetAddress.getByName(it) }.getOrNull() }
        val start = System.currentTimeMillis()
        val deadline = start + timeoutMs.coerceIn(500, 10000)
        var sent = 0
        val buf = ByteArray(8192)
        while (System.currentTimeMillis() < deadline) {
          if (sent < 3 && System.currentTimeMillis() >= start + sent * timeoutMs / 6) {
            for (a in addresses) runCatching { sock.send(DatagramPacket(payload, payload.size, a, port)) }
            sent++
          }
          val packet = DatagramPacket(buf, buf.size)
          try {
            sock.receive(packet)
          } catch (_: SocketTimeoutException) {
            continue
          }
          val from = packet.address?.hostAddress ?: continue
          val data = String(packet.data, packet.offset, packet.length, Charsets.UTF_8)
          if (data == message) continue                       // our own broadcast echoed back
          if (seen.add("$from|$data")) out.add(mapOf("address" to from, "data" to data))
        }
      }
      out
    }
  }
}
