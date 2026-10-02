package io.github.halvar20000.webdata

import android.webkit.CookieManager
import android.webkit.WebStorage
import expo.modules.kotlin.Promise
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** Logging out of a website shown in the app's WebView (Printables, issue #16): react-native-webview can't clear its
 *  cookies on Android, so this deletes all WebView cookies and website data (localStorage, IndexedDB …). */
class WebDataModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("WebData")

    AsyncFunction("clearAsync") { promise: Promise ->
      val cookies = CookieManager.getInstance()
      cookies.removeAllCookies { removed ->
        cookies.flush()
        WebStorage.getInstance().deleteAllData()
        promise.resolve(removed)
      }
    }.runOnQueue(Queues.MAIN)
  }
}
