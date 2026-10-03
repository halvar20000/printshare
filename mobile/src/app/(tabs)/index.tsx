import Ionicons from "@expo/vector-icons/Ionicons";
import * as Clipboard from "expo-clipboard";
import * as DocumentPicker from "expo-document-picker";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Badge, Banner, Button, Card, Divider, Empty, Row, tap, useContentWidth } from "@/components/ui";
import { WEB_APP, type JobSummary } from "@/lib/api";
import { useApp } from "@/lib/app";
import { ago, extractLink, jobName, makerWorldId, printTime } from "@/lib/format";
import { radius, space, useColors } from "@/lib/theme";

export default function Home() {
  const { server, api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<JobSummary[]>([]);
  const [noPrinter, setNoPrinter] = useState(false);
  const [dragging, setDragging] = useState(false);
  const width = useContentWidth();

  // desktop browsers: drop a model file anywhere on the page
  useEffect(() => {
    if (Platform.OS !== "web" || !server || typeof window === "undefined") return;
    let depth = 0;
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
    const enter = (e: DragEvent) => { if (hasFiles(e)) { e.preventDefault(); depth++; setDragging(true); } };
    const over = (e: DragEvent) => { if (hasFiles(e)) e.preventDefault(); };
    const leave = (e: DragEvent) => { if (hasFiles(e) && --depth <= 0) { depth = 0; setDragging(false); } };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setDragging(false);
      const file = e.dataTransfer?.files?.[0];
      if (!file) return;
      if (!/\.(stl|3mf|obj|step|stp)$/i.test(file.name)) { setError(t("dropWrongType")); return; }
      setError("");
      router.push({ pathname: "/prepare", params: { fileUri: URL.createObjectURL(file), fileName: file.name } });
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [server, router, t]);

  useFocusEffect(useCallback(() => {
    api?.jobs().then(j => setRecent(j.slice(0, 3))).catch(() => {});
    if (api && server?.cloud) api.printers().then(p => setNoPrinter(!p.length)).catch(() => {});
    else setNoPrinter(false);
  }, [api, server]));

  const go = (l: string) => {
    const found = extractLink(l);
    if (!found) return setError(t("needLink"));
    setError("");
    setLink("");
    const mw = makerWorldId(found);
    if (mw) router.push({ pathname: "/model/[source]/[id]", params: { source: "makerworld", id: mw } });
    else router.push({ pathname: "/prepare", params: { link: found } });
  };
  const paste = async () => {
    const found = extractLink(await Clipboard.getStringAsync().catch(() => ""));
    if (found) go(found); else setError(t("clipboardEmpty"));
  };
  const pick = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: "*/*", copyToCacheDirectory: true, multiple: false });
    if (res.canceled || !res.assets?.[0]) return;
    const a = res.assets[0];
    router.push({ pathname: "/prepare", params: { fileUri: a.uri, fileName: a.name } });
  };

  if (!server) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}>
        <Empty icon="cube-outline" title={t("notConnectedTitle")} sub={t(WEB_APP ? "notConnectedSubWeb" : "notConnectedSub")}>
          <Button title={t("connectNow")} icon="mail-outline" onPress={() => router.push("/connect")} />
          <Pressable onPress={() => router.push({ pathname: "/connect", params: { mode: "own" } })} accessibilityRole="link"
            style={{ marginTop: 18, padding: 8 }}>
            <Text style={{ color: c.sub, fontSize: 14, textAlign: "center", textDecorationLine: "underline" }}>{t("ownServerLink")}</Text>
          </Pressable>
        </Empty>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ padding: space, paddingBottom: 40, maxWidth: width, width: "100%", alignSelf: "center" }}>
        <Text style={{ color: c.text, fontSize: 32, fontWeight: "800", marginTop: 12 }}>{t("homeTitle")}</Text>
        <Text style={{ color: c.sub, fontSize: 16, lineHeight: 22, marginTop: 8, marginBottom: 22 }}>{t("homeSub")}</Text>

        {noPrinter ? (
          <Card style={{ padding: 16, marginBottom: 16, borderWidth: 2, borderColor: c.accent }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <Ionicons name="print-outline" size={24} color={c.accent} />
              <Text style={{ color: c.text, fontSize: 17, fontWeight: "700", flex: 1 }}>{t("firstPrinterTitle")}</Text>
            </View>
            <Text style={{ color: c.sub, fontSize: 15, lineHeight: 21, marginTop: 6, marginBottom: 12 }}>{t(WEB_APP ? "firstPrinterSubWeb" : "firstPrinterSub")}</Text>
            {WEB_APP ? (
              // in the browser a printer is reached through a bridge
              <Button title={t("bridgeConnect")} icon="git-network-outline" onPress={() => router.push("/bridges")} />
            ) : (
              <Button title={t("addPrinterNow")} icon="add-circle-outline"
                onPress={() => router.push({ pathname: "/cloud-printer/[id]", params: { id: "new" } })} />
            )}
          </Card>
        ) : null}
        {error ? <Banner kind="warn" text={error} /> : null}
        <Card style={{ padding: 12 }}>
          <View style={{ flexDirection: "row", alignItems: "center", backgroundColor: c.input, borderRadius: 10 }}>
            <Ionicons name="link" size={20} color={c.sub} style={{ marginLeft: 12 }} />
            <TextInput value={link} onChangeText={v => { setLink(v); setError(""); }}
              placeholder={t("linkPlaceholder")} placeholderTextColor={c.sub}
              autoCapitalize="none" autoCorrect={false} keyboardType="url" returnKeyType="go"
              onSubmitEditing={() => go(link)} accessibilityLabel={t("linkPlaceholder")}
              style={{ flex: 1, color: c.text, fontSize: 16, paddingHorizontal: 10, paddingVertical: 14 }} />
          </View>
          <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
            <Button kind="secondary" icon="clipboard-outline" title={t("paste")} onPress={paste} style={{ flex: 1 }} />
            <Button title={t("next")} icon="arrow-forward" onPress={() => go(link)} disabled={!link.trim()} style={{ flex: 1 }} />
          </View>
        </Card>

        <Card style={{ marginTop: 16 }}>
          <Row icon="folder-open-outline" label={t("pickFile")} sub={t(Platform.OS === "web" ? "pickFileSubWeb" : "pickFileSub")} onPress={pick} />
          <Divider />
          <Row icon="search" label={t("searchModels")} sub={t("searchModelsSub")} onPress={() => router.navigate("/discover")} />
        </Card>

        {recent.length ? (
          <>
            <Text style={{ color: c.sub, fontSize: 13, textTransform: "uppercase", letterSpacing: 0.4, margin: space, marginTop: 26, marginBottom: 6 }}>
              {t("recent")}
            </Text>
            <Card>
              {recent.map((j, i) => (
                <View key={j.id}>
                  {i ? <Divider /> : null}
                  <Pressable onPress={() => { tap(); router.push(`/job/${j.id}`); }} accessibilityRole="button"
                    style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", padding: 14, backgroundColor: pressed ? c.input : "transparent" })}>
                    <View style={{ width: 40, height: 40, borderRadius: radius / 1.5, backgroundColor: c.accentSoft, alignItems: "center", justifyContent: "center", marginRight: 12 }}>
                      <Ionicons name="cube" size={20} color={c.accent} />
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text style={{ color: c.text, fontSize: 16 }} numberOfLines={1}>{jobName(j.file, j.link)}</Text>
                      <Text style={{ color: c.sub, fontSize: 13, marginTop: 2 }} numberOfLines={1}>
                        {[j.print_time ? printTime(j.print_time) : null, ago(t, j.created)].filter(Boolean).join(" · ")}
                      </Text>
                    </View>
                    <Badge text={t.table.jobStates[j.state] ?? j.state}
                      kind={j.state === "error" ? "error" : j.state === "finished" ? "ok" : j.state === "cancelled" ? "warn"
                        : j.state === "started" || j.state === "sliced" ? "accent" : "neutral"} />
                  </Pressable>
                </View>
              ))}
            </Card>
          </>
        ) : null}
      </ScrollView>
      {dragging ? (
        <View pointerEvents="none" style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, margin: 12,
          borderRadius: radius, borderWidth: 3, borderStyle: "dashed", borderColor: c.accent, backgroundColor: c.accentSoft,
          alignItems: "center", justifyContent: "center" }}>
          <Ionicons name="cloud-upload-outline" size={56} color={c.accent} />
          <Text style={{ color: c.text, fontSize: 20, fontWeight: "700", marginTop: 10 }}>{t("dropHere")}</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}
