import ExpoModulesCore

/// The iOS app is the separate Swift app; this Expo app reads NFC tags on Android only.
public class NfcTagModule: Module {
  public func definition() -> ModuleDefinition {
    Name("NfcTag")
    Function("status") { "none" }
    AsyncFunction("readAsync") { (_: Int, promise: Promise) in
      promise.reject("ERR_NFC_UNAVAILABLE", "NFC reading is only built for Android here")
    }
    AsyncFunction("cancelAsync") { }
  }
}
