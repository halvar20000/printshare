// printables.com inside the app (issue #16, like the iOS app 0.7.90): the user logs in on the website itself - neither
// the app nor the server sees the password or the cookies (Prusa's terms forbid handing them over). The login stays
// (persistent cookies + DOM storage). On a model page "print with PocketPrint3D" opens the app's model page; the server
// then downloads the files without a login, as always. Website downloads are not saved but lead there too.
import { forwardRef, useImperativeHandle, useRef } from "react";
import { Linking } from "react-native";
import { WebView } from "react-native-webview";

export const PRINTABLES_HOME = "https://www.printables.com/";
export const printablesModelId = (url?: string | null) =>
  (url ?? "").match(/^https:\/\/(?:www\.)?printables\.com\/(?:[a-z]{2}\/)?model\/(\d+)/)?.[1] ?? null;
// file downloads of the website (signed links on files.printables.com, model files)
const isDownload = (url: string) =>
  /^https:\/\/files\.printables\.com\//.test(url) || /\.(stl|3mf|obj|step|stp|zip|gcode|bgcode)(\?|#|$)/i.test(url);

// Printables changes the address with history.pushState (no navigation): report every change to the app
const WATCH_URL = `(function(){
  var last = "";
  function tell(){ if (location.href !== last) { last = location.href;
    window.ReactNativeWebView.postMessage(JSON.stringify({type: "url", url: last})); } }
  ["pushState", "replaceState"].forEach(function(k){ var o = history[k];
    history[k] = function(){ var r = o.apply(this, arguments); tell(); return r; }; });
  addEventListener("popstate", tell); tell();
})(); true;`;

export type PrintablesWebHandle = { goBack(): void; goForward(): void; reload(): void };
export type NavState = { url: string; canGoBack: boolean; canGoForward: boolean };

export const PrintablesWeb = forwardRef<PrintablesWebHandle, {
  onNav: (s: Partial<NavState>) => void; onDownload: (url: string) => void;
}>(function PrintablesWeb({ onNav, onDownload }, ref) {
  const web = useRef<WebView>(null);
  useImperativeHandle(ref, () => ({
    goBack: () => web.current?.goBack(), goForward: () => web.current?.goForward(), reload: () => web.current?.reload(),
  }), []);
  return (
    <WebView ref={web} source={{ uri: PRINTABLES_HOME }} style={{ flex: 1 }}
      // the login must survive app restarts: no incognito, persistent cookies and DOM storage
      incognito={false} sharedCookiesEnabled thirdPartyCookiesEnabled domStorageEnabled cacheEnabled
      allowsBackForwardNavigationGestures pullToRefreshEnabled
      injectedJavaScript={WATCH_URL}
      onNavigationStateChange={e => onNav({ url: e.url, canGoBack: e.canGoBack, canGoForward: e.canGoForward })}
      onMessage={e => {
        try {
          const m = JSON.parse(e.nativeEvent.data);
          if (m?.type === "url" && typeof m.url === "string") onNav({ url: m.url });
        } catch { /* not ours */ }
      }}
      onShouldStartLoadWithRequest={req => {
        if (/^(mailto|tel):/i.test(req.url)) {
          Linking.openURL(req.url).catch(() => {});
          return false;
        }
        if (isDownload(req.url)) {              // Android has no onFileDownload: stop it here
          onDownload(req.url);
          return false;
        }
        return true;
      }}
      onFileDownload={e => onDownload(e.nativeEvent.downloadUrl)}
      // links with target=_blank: same view instead of a second window
      onOpenWindow={e => web.current?.injectJavaScript(`location.href = ${JSON.stringify(e.nativeEvent.targetUrl)}; true;`)} />
  );
});
