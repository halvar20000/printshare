// Web build: the browser's own video element.
import { createElement } from "react";
import { View } from "react-native";

export function VideoPlayer({ uri }: { uri: string }) {
  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      {createElement("video", { src: uri, controls: true, autoPlay: true, playsInline: true, loop: true,
        style: { width: "100%", height: "100%", objectFit: "contain", background: "#000" } })}
    </View>
  );
}
