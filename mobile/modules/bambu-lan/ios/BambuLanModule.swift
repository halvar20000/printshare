import ExpoModulesCore

/// The iOS app is the separate Swift app; this Expo app talks to Bambu printers directly on Android only.
public class BambuLanModule: Module {
  public func definition() -> ModuleDefinition {
    Name("BambuLan")
    Events("onMessage", "onState")
    AsyncFunction("certAsync") { (_: String) -> [String: Any]? in nil }
    AsyncFunction("probeAsync") { (_: [String], _: Int) -> [[String: String]] in [] }
    AsyncFunction("connectAsync") { (_: String, _: String, _: String) -> Bool in
      throw Exception(name: "unsupported", description: "Bambu printers are reached through a bridge on iOS")
    }
    AsyncFunction("publishAsync") { (_: String, _: String) in }
    AsyncFunction("disconnectAsync") { (_: String) in }
    AsyncFunction("uploadAsync") { (_: String, _: String, _: String, _: String) -> [String: Any] in
      throw Exception(name: "unsupported", description: "Bambu printers are reached through a bridge on iOS")
    }
  }
}
