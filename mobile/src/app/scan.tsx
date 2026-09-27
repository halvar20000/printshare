import Ionicons from "@expo/vector-icons/Ionicons";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Button, Empty } from "@/components/ui";
import { useApp } from "@/lib/app";
import { checkServer, parsePairing } from "@/lib/pairing";
import { useColors } from "@/lib/theme";

export default function Scan() {
  const { t, setServer } = useApp();
  const c = useColors();
  const router = useRouter();
  const [permission, requestPermission] = useCameraPermissions();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const handled = useRef(false);

  const onScan = async (data: string) => {
    if (handled.current) return;
    const s = parsePairing(data);
    if (!s) { setMessage(t("invalidQr")); return; }
    handled.current = true;
    setBusy(true);
    try {
      await setServer(await checkServer(s, t));
      if (router.canDismiss()) router.dismissAll(); else router.replace("/");
    } catch (e) {
      setMessage((e as Error).message);
      handled.current = false;
    } finally {
      setBusy(false);
    }
  };

  const close = (
    <Pressable onPress={() => router.back()} hitSlop={12} accessibilityRole="button" accessibilityLabel="Close"
      style={{ position: "absolute", top: 12, right: 16, zIndex: 2 }}>
      <Ionicons name="close-circle" size={34} color="#fff" />
    </Pressable>
  );

  if (!permission?.granted) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}>
        <Empty icon="camera-outline" title={t("scanTitle")} sub={t("cameraNeeded")}>
          <Button title={t("allowCamera")} onPress={requestPermission} />
          <Button kind="plain" title={t("cancelBtn")} onPress={() => router.back()} style={{ marginTop: 8 }} />
        </Empty>
      </SafeAreaView>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <CameraView style={StyleSheet.absoluteFill} facing="back"
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={busy ? undefined : r => onScan(r.data)} />
      <SafeAreaView style={{ flex: 1 }}>
        {close}
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <View style={{ width: 240, height: 240, borderRadius: 24, borderWidth: 3, borderColor: "#fff" }} />
        </View>
        <View style={{ padding: 24, alignItems: "center" }}>
          {busy ? <ActivityIndicator color="#fff" /> : null}
          <Text style={{ color: "#fff", fontSize: 16, textAlign: "center", marginTop: 8 }}>
            {message || t("scanTitle")}
          </Text>
        </View>
      </SafeAreaView>
    </View>
  );
}
