// printables.com in the app with the user's own login (issue #16): likes, collections, everything of the website.
// "Print with PocketPrint3D" on a model page opens the app's model page (the server downloads without a login).
import Ionicons from "@expo/vector-icons/Ionicons";
import { Stack, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Platform, Pressable, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import WebData from "../../modules/web-data/src/WebDataModule";
import { PrintablesWeb, printablesModelId, type NavState, type PrintablesWebHandle } from "@/components/PrintablesWeb";
import { Button, tap } from "@/components/ui";
import { useApp } from "@/lib/app";
import { getItem, setItem } from "@/lib/storage";
import { space, useColors } from "@/lib/theme";

const HINT_KEY = "ps_printables_hint_seen";

function NavButton({ icon, label, enabled, onPress }: {
  icon: "chevron-back" | "chevron-forward"; label: string; enabled: boolean; onPress: () => void;
}) {
  const c = useColors();
  return (
    <Pressable onPress={() => { tap(); onPress(); }} disabled={!enabled} accessibilityRole="button" accessibilityLabel={label}
      hitSlop={8} style={{ padding: 8, opacity: enabled ? 1 : 0.3 }}>
      <Ionicons name={icon} size={26} color={c.accent} />
    </Pressable>
  );
}

export default function PrintablesScreen() {
  const { t } = useApp();
  const c = useColors();
  const router = useRouter();
  const web = useRef<PrintablesWebHandle>(null);
  const [nav, setNav] = useState<NavState>({ url: "", canGoBack: false, canGoForward: false });
  const [hint, setHint] = useState(false);
  const [downloadHintAt, setDownloadHintAt] = useState<string | null>(null);   // shown for this page only
  const [key, setKey] = useState(0);              // remount after logging out
  const modelId = printablesModelId(nav.url);

  useEffect(() => { getItem(HINT_KEY).then(v => setHint(v !== "1")); }, []);
  const closeHint = () => { setHint(false); setItem(HINT_KEY, "1"); };

  const openModel = (id: string) => router.push({ pathname: "/model/[source]/[id]", params: { source: "printables", id } });
  const onDownload = () => {
    if (modelId) openModel(modelId);
    else setDownloadHintAt(nav.url);
  };

  const logout = async () => {
    try { await WebData.clearAsync(); } catch { /* web build */ }
    setNav({ url: "", canGoBack: false, canGoForward: false });
    setKey(k => k + 1);
  };
  const menu = () => {
    tap();
    const ask = () => {
      if (Platform.OS === "web") { if (globalThis.confirm?.(t("printablesLogoutConfirm"))) logout(); return; }
      Alert.alert(t("printablesLogout"), t("printablesLogoutConfirm"), [
        { text: t("cancelBtn"), style: "cancel" },
        { text: t("printablesLogout"), style: "destructive", onPress: logout },
      ]);
    };
    if (Platform.OS === "web") { ask(); return; }
    Alert.alert("Printables", undefined, [
      { text: t("webReload"), onPress: reload },
      { text: t("printablesLogout"), style: "destructive", onPress: ask },
      { text: t("cancelBtn"), style: "cancel" },
    ]);
  };

  const back = useCallback(() => web.current?.goBack(), []);
  const forward = useCallback(() => web.current?.goForward(), []);
  const reload = useCallback(() => web.current?.reload(), []);


  return (
    <SafeAreaView edges={["bottom"]} style={{ flex: 1, backgroundColor: c.bg }}>
      <Stack.Screen options={{ title: "Printables", headerRight: () => (
        <Pressable onPress={menu} accessibilityRole="button" accessibilityLabel={t("printablesMenu")} hitSlop={10}>
          <Ionicons name="ellipsis-horizontal-circle" size={26} color={c.accent} />
        </Pressable>
      ) }} />
      {hint ? (
        <Pressable onPress={closeHint} accessibilityRole="button" accessibilityLabel={t("printablesWebHint")}
          style={{ flexDirection: "row", alignItems: "flex-start", backgroundColor: c.card, padding: 12,
            borderBottomWidth: 1, borderColor: c.line }}>
          <Ionicons name="information-circle-outline" size={20} color={c.accent} style={{ marginRight: 8, marginTop: 1 }} />
          <Text style={{ color: c.text, fontSize: 14, lineHeight: 19, flex: 1 }}>{t("printablesWebHint")}</Text>
          <Ionicons name="close" size={20} color={c.sub} style={{ marginLeft: 8 }} />
        </Pressable>
      ) : null}
      <PrintablesWeb key={key} ref={web} onNav={s => setNav(n => ({ ...n, ...s }))} onDownload={onDownload} />
      {downloadHintAt != null && downloadHintAt === nav.url ? (
        <Pressable onPress={() => setDownloadHintAt(null)} accessibilityRole="button"
          style={{ backgroundColor: c.card, padding: 12, borderTopWidth: 1, borderColor: c.line }}>
          <Text style={{ color: c.text, fontSize: 14, lineHeight: 19 }}>{t("printablesDownloadHint")}</Text>
        </Pressable>
      ) : null}
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space / 2, paddingVertical: 8,
        borderTopWidth: 1, borderColor: c.line, backgroundColor: c.card, gap: 4 }}>
        <NavButton icon="chevron-back" label={t("webBack")} enabled={nav.canGoBack} onPress={back} />
        <NavButton icon="chevron-forward" label={t("webForward")} enabled={nav.canGoForward} onPress={forward} />
        <Button title={t("printablesPrintThis")} icon="print-outline" disabled={!modelId}
          onPress={() => modelId && openModel(modelId)} style={{ flex: 1, marginLeft: 6 }} />
      </View>
    </SafeAreaView>
  );
}
