// A video from a URL: the system's video element inside a WebView (no extra native module).
import { View } from "react-native";
import { WebView } from "react-native-webview";

export function VideoPlayer({ uri }: { uri: string }) {
  const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;height:100%;background:#000}video{width:100%;height:100%;object-fit:contain}</style></head>
<body><video src="${uri.replace(/"/g, "&quot;")}" controls autoplay playsinline loop></video></body></html>`;
  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <WebView source={{ html }} originWhitelist={["*"]} allowsInlineMediaPlayback mediaPlaybackRequiresUserAction={false}
        style={{ flex: 1, backgroundColor: "#000" }} />
    </View>
  );
}
