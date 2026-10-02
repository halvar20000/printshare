import ExpoModulesCore
import WebKit

/// Logging out of a website shown in the app's WebView (Printables, issue #16): deletes all website data of the
/// default WKWebsiteDataStore (cookies, localStorage, caches).
public class WebDataModule: Module {
  public func definition() -> ModuleDefinition {
    Name("WebData")

    AsyncFunction("clearAsync") { (promise: Promise) in
      let store = WKWebsiteDataStore.default()
      store.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: Date(timeIntervalSince1970: 0)) {
        promise.resolve(true)
      }
    }.runOnQueue(.main)
  }
}
