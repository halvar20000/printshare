// Model details from Printables / Thingiverse -> prepare print (spec MQ-06, MQ-10). MakerWorld (server 0.17.1): only
// downloadable with the user's own account -> button to MakerWorld, the 3MF comes back through the share menu.
import Ionicons from "@expo/vector-icons/Ionicons";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Linking, Pressable, Text, View, useWindowDimensions } from "react-native";

import { Badge, Banner, Button, Divider, Empty, Row, Screen, Section, tap } from "@/components/ui";
import type { ModelDetail } from "@/lib/api";
import { useApp } from "@/lib/app";
import { compact } from "@/lib/format";
import { space, useColors } from "@/lib/theme";

const SOURCE_NAMES: Record<string, string> = { printables: "Printables", thingiverse: "Thingiverse", makerworld: "MakerWorld" };

export default function Model() {
  const { source, id } = useLocalSearchParams<{ source: string; id: string }>();
  const { api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const [model, setModel] = useState<ModelDetail | null>(null);
  const [error, setError] = useState("");
  const [slide, setSlide] = useState(0);
  const [full, setFull] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api.model(source, id)
      .then(m => { if (alive) { setModel(m); setError(""); } })
      .catch(e => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [api, source, id, attempt]);

  if (!model) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}>
        {error ? <Empty icon="cloud-offline-outline" title={error}>
          <Button kind="secondary" title={t("tryAgain")} onPress={() => setAttempt(a => a + 1)} />
        </Empty> : <ActivityIndicator size="large" color={c.accent} />}
      </View>
    );
  }

  const w = Math.min(width, 640);
  const imgW = w - space * 2;
  const sliceable = model.files.filter(f => f.sliceable).length;
  const r = model.recommended;
  const text = [model.summary, model.description].filter(Boolean).join("\n\n");
  const long = text.length > 400;
  const srcName = SOURCE_NAMES[model.source] ?? model.source;
  const external = model.download === "external";
  const hours = (h: number) => `${Math.floor(h)} h ${Math.round((h % 1) * 60)} min`;

  return (
    <Screen footer={external ? (
      <Button title={t("openOn", { source: srcName })} icon="open-outline" onPress={() => Linking.openURL(model.url)} />
    ) : <>
      <Button title={t("printThis")} icon="print-outline" disabled={sliceable === 0}
        onPress={() => router.push({ pathname: "/prepare", params: { link: model.url } })} />
      <Button kind="plain" title={t("openOn", { source: srcName })} icon="open-outline" onPress={() => Linking.openURL(model.url)} />
    </>}>
      {model.images.length ? (
        <View style={{ marginBottom: 14 }}>
          <FlatList
            data={model.images}
            horizontal
            pagingEnabled
            showsHorizontalScrollIndicator={false}
            keyExtractor={(u, i) => `${i}-${u}`}
            onMomentumScrollEnd={e => setSlide(Math.round(e.nativeEvent.contentOffset.x / imgW))}
            style={{ width: imgW, borderRadius: 14, overflow: "hidden" }}
            renderItem={({ item }) => (
              <Image source={{ uri: item }} contentFit="cover" transition={150}
                style={{ width: imgW, height: imgW * 0.75, backgroundColor: c.track }} />
            )}
          />
          {model.images.length > 1 ? (
            <View style={{ flexDirection: "row", justifyContent: "center", gap: 6, marginTop: 8 }}>
              {model.images.slice(0, 12).map((_, i) => (
                <View key={i} style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: i === slide ? c.accent : c.track }} />
              ))}
            </View>
          ) : null}
        </View>
      ) : null}

      <Text style={{ color: c.text, fontSize: 24, fontWeight: "800" }}>{model.name}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 6, marginBottom: 16 }}>
        {model.author ? <Text style={{ color: c.sub, fontSize: 15 }}>{t("by", { author: model.author })}</Text> : null}
        <Badge text={srcName} kind="accent" />
      </View>

      <View style={{ flexDirection: "row", gap: 22, marginBottom: 20, paddingHorizontal: 4 }}>
        {([["heart", model.likes, "likes"], ["download", model.downloads, "downloads"], ["hammer", model.makes, "makes"]] as const)
          .filter(([, v]) => v != null)
          .map(([icon, v, key]) => (
            <View key={key} style={{ alignItems: "center" }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                <Ionicons name={`${icon}-outline`} size={16} color={c.sub} />
                <Text style={{ color: c.text, fontSize: 17, fontWeight: "700" }}>{compact(v)}</Text>
              </View>
              <Text style={{ color: c.sub, fontSize: 12 }}>{t(key)}</Text>
            </View>
          ))}
      </View>

      {external ? <Banner kind="info" icon="information-circle-outline" text={t("externalDownload", { source: srcName })} /> : null}

      <Section>
        {external ? null : <Row icon="document-outline" label={sliceable === 1 ? t("printableFile")
          : sliceable ? t("printableFiles", { n: sliceable }) : t("noPrintableFiles")} />}
        {model.license ? <>{external ? null : <Divider />}<Row icon="ribbon-outline" label={t("license")} sub={model.license} /></> : null}
        {model.category ? <><Divider /><Row icon="pricetag-outline" label={t("category")} value={model.category} /></> : null}
      </Section>

      {Object.keys(r).length ? (
        <Section title={t("authorSettings")}>
          {[r.material ? [t("material"), r.material] : null,
            r.nozzle ? [t("nozzle"), r.nozzle] : null,
            r.layer_height ? [t("layerHeight"), r.layer_height] : null,
            r.weight_g ? [t("weight"), `${Math.round(r.weight_g)} g`] : null,
            r.print_hours ? [t("printTimeAuthor"), hours(r.print_hours)] : null,
          ].filter((x): x is string[] => !!x).map(([k, v], i) => (
            <View key={k}>{i ? <Divider /> : null}<Row label={k} value={v} /></View>
          ))}
        </Section>
      ) : null}

      {model.variants?.length ? (
        <Section title={t("variants")}>
          {model.variants.map((v, i) => (
            <View key={v.id}>
              {i ? <Divider /> : null}
              <Row label={v.title || `#${v.id}`}
                sub={[v.materials.join(", "), v.weight_g ? `${v.weight_g} g` : null, v.print_hours ? hours(v.print_hours) : null,
                  v.needs_ams ? t("needsAms") : null].filter(Boolean).join(" · ")}
                right={<View style={{ flexDirection: "row", gap: 3, marginLeft: 8 }}>
                  {v.colors.slice(0, 6).map((col, k) => <View key={k} style={{ width: 12, height: 12, borderRadius: 6,
                    backgroundColor: col, borderWidth: 1, borderColor: c.line }} />)}
                </View>} />
            </View>
          ))}
        </Section>
      ) : null}

      {text ? (
        <Section title={t("description")}>
          <View style={{ padding: space }}>
            <Text style={{ color: c.text, fontSize: 15, lineHeight: 22 }} numberOfLines={full || !long ? undefined : 8}>{text}</Text>
            {long ? (
              <Pressable onPress={() => { tap(); setFull(f => !f); }} style={{ marginTop: 8 }} accessibilityRole="button">
                <Text style={{ color: c.accent, fontSize: 15 }}>{t(full ? "showLess" : "showMore")}</Text>
              </Pressable>
            ) : null}
          </View>
        </Section>
      ) : null}
    </Screen>
  );
}
