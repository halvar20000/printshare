import ExpoModulesCore

/// The iOS app is the separate Swift app; this Expo app finds printers on the Wi-Fi on Android only.
public class LanDiscoveryModule: Module {
  public func definition() -> ModuleDefinition {
    Name("LanDiscovery")
    AsyncFunction("wifiAddressAsync") { () -> [String: Any]? in nil }
    AsyncFunction("udpProbeAsync") { (_: String, _: Int, _: [String], _: Int) -> [[String: String]] in [] }
  }
}
