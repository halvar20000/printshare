import Ionicons from "@expo/vector-icons/Ionicons";
import * as Clipboard from "expo-clipboard";
import * as DocumentPicker from "expo-document-picker";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Linking, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Badge, Banner, Button, Card, Divider, Empty, Row, tap } from "@/components/ui";
import type { JobSummary } from "@/lib/api";
import { useApp } from "@/lib/app";
import { ago, extractLink, jobName, printTime } from "@/lib/format";
import { radius, space, useColors } from "@/lib/theme";

export default function Home() {
  const { server, api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<JobSummary[]>([]);

  useFocusEffect(useCallback(() => {
    api?.jobs().then(j => setRecent(j.slice(0, 3))).catch(() => {});
  }, [api]));

  const go = (l: string) => {
    const found = extractLink(l);
    if (!found) return setError(t("needLink"));
    setError("");
    setLink("");
    router.push({ pathname: "/prepare", params: { link: found } });
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
        <Empty icon="cube-outline" title={t("notConnectedTitle")} sub={t("notConnectedSub")}>
          <Button title={t("connectNow")} icon="link" onPress={() => router.push("/connect")} />
        </Empty>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ padding: space, paddingBottom: 40, maxWidth: 640, width: "100%", alignSelf: "center" }}>
        <Text style={{ color: c.text, fontSize: 32, fontWeight: "800", marginTop: 12 }}>{t("homeTitle")}</Text>
        <Text style={{ color: c.sub, fontSize: 16, lineHeight: 22, marginTop: 8, marginBottom: 22 }}>{t("homeSub")}</Text>

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
          <Row icon="folder-open-outline" label={t("pickFile")} sub={t("pickFileSub")} onPress={pick} />
          <Divider />
          <Row icon="compass-outline" label={t("browsePrintables")} sub={t("browsePrintablesSub")}
            onPress={() => Linking.openURL("https://www.printables.com/model")} />
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
                      kind={j.state === "error" ? "error" : j.state === "started" ? "ok" : j.state === "sliced" ? "accent" : "neutral"} />
                  </Pressable>
                </View>
              ))}
            </Card>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
