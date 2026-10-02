// Search Printables / Thingiverse and open a model (spec MQ-05). MakerWorld can't be searched from outside: a card
// sends the user there (share a model back to the app), and a MakerWorld link typed here opens its model page.
import Ionicons from "@expo/vector-icons/Ionicons";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, FlatList, Linking, Pressable, Text, TextInput, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Banner, Button, Card, Empty, Segmented, tap } from "@/components/ui";
import type { ModelHit, SortKey, Source } from "@/lib/api";
import { useApp } from "@/lib/app";
import { compact, extractLink, makerWorldId } from "@/lib/format";
import { radius, space, useColors } from "@/lib/theme";

const MAX_W = 900;

export default function Discover() {
  const { api, t, server } = useApp();
  const c = useColors();
  const router = useRouter();
  const params = useLocalSearchParams<{ q?: string }>();
  const { width } = useWindowDimensions();
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState<Source["id"]>("printables");
  const [sort, setSort] = useState<SortKey>("relevant");
  const [input, setInput] = useState(params.q ?? "");
  const [query, setQuery] = useState(params.q ?? "");
  const [hits, setHits] = useState<ModelHit[]>([]);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const req = useRef(0);

  useEffect(() => {
    api?.sources().then(setSources).catch(() => setSources([]));
  }, [api]);

  const load = useCallback(async (q: string, p: number, src: Source["id"], srt: SortKey) => {
    if (!api || !q.trim()) return;
    const id = ++req.current;
    setLoading(true);
    setError("");
    try {
      const r = await api.search(q, src, p, srt);
      if (id !== req.current) return;
      setHits(prev => {
        if (p === 1) return r.results;
        const seen = new Set(prev.map(h => h.id));
        return [...prev, ...r.results.filter(h => !seen.has(h.id))];
      });
      setPage(p);
      setMore(r.has_more);
    } catch (e) {
      if (id === req.current) setError((e as Error).message);
    } finally {
      if (id === req.current) setLoading(false);
    }
  }, [api]);

  // a pairing / deep link can open the tab with ?q=
  const initial = useRef(params.q ?? "");
  useEffect(() => {
    if (initial.current) load(initial.current, 1, "printables", "relevant");
  }, [load]);

  const submit = (q = input) => {
    const v = q.trim();
    if (!v) return;
    const mw = makerWorldId(extractLink(v));
    if (mw) {
      setInput("");
      router.push({ pathname: "/model/[source]/[id]", params: { source: "makerworld", id: mw } });
      return;
    }
    setInput(v);
    if (v !== query) setHits([]);
    setQuery(v);
    load(v, 1, source, sort);
  };
  const changeSource = (v: Source["id"]) => {
    setSource(v);
    setHits([]);
    load(query, 1, v, sort);
  };
  const changeSort = (k: SortKey) => {
    setSort(k);
    load(query, 1, source, k);
  };

  const available = sources.filter(s => s.available);
  // only the owner of a home server can add the token; cloud users can't do anything about it
  const tvMissing = !server?.cloud && sources.some(s => s.id === "thingiverse" && !s.available);
  const inner = Math.min(width, MAX_W) - space * 2;
  const cols = inner > 560 ? 3 : 2;
  const cardW = (inner - (cols - 1) * 12) / cols;

  if (!server) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}>
        <Empty icon="search" title={t("notConnectedTitle")} sub={t("notConnectedSub")} />
      </SafeAreaView>
    );
  }

  const header = (
    <View style={{ marginBottom: 12 }}>
      <Text style={{ color: c.text, fontSize: 32, fontWeight: "800", marginTop: 12, marginBottom: 14 }}>{t("discoverTitle")}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", backgroundColor: c.card, borderRadius: 12, paddingHorizontal: 12 }}>
        <Ionicons name="search" size={20} color={c.sub} />
        <TextInput value={input} onChangeText={setInput} placeholder={t("searchPlaceholder")} placeholderTextColor={c.sub}
          returnKeyType="search" onSubmitEditing={() => submit()} autoCorrect={false} clearButtonMode="while-editing"
          accessibilityLabel={t("searchPlaceholder")}
          style={{ flex: 1, color: c.text, fontSize: 17, paddingVertical: 13, marginLeft: 8 }} />
      </View>
      {/* the website itself with the user's own Printables login (issue #16) */}
      <Pressable onPress={() => { tap(); router.push("/printables"); }} accessibilityRole="button"
        accessibilityLabel={t("printablesWebOpen")}
        style={{ flexDirection: "row", alignItems: "center", marginTop: 10, paddingVertical: 10, paddingHorizontal: 12,
          borderRadius: 12, backgroundColor: c.card }}>
        <Ionicons name="globe-outline" size={20} color={c.accent} style={{ marginRight: 10 }} />
        <View style={{ flex: 1 }}>
          <Text style={{ color: c.text, fontSize: 15, fontWeight: "600" }}>{t("printablesWebOpen")}</Text>
          <Text style={{ color: c.sub, fontSize: 13 }}>{t("printablesWebOpenSub")}</Text>
        </View>
        <Ionicons name="chevron-forward" size={18} color={c.sub} />
      </Pressable>
      {available.length > 1 ? (
        <View style={{ marginTop: 12 }}>
          <Segmented values={available.map(s => s.id)} value={source} onChange={changeSource}
            labels={Object.fromEntries(available.map(s => [s.id, s.name]))} />
        </View>
      ) : null}
      <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
        {(["relevant", "popular", "makes"] as SortKey[]).map(k => {
          const on = k === sort;
          return (
            <Pressable key={k} onPress={() => { tap(); changeSort(k); }} accessibilityRole="button" accessibilityState={{ selected: on }}
              style={{ paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: on ? c.accent : c.card }}>
              <Text style={{ color: on ? c.accentText : c.text, fontSize: 14, fontWeight: on ? "600" : "400" }}>
                {t(k === "relevant" ? "sortRelevant" : k === "popular" ? "sortPopular" : "sortMakes")}
              </Text>
            </Pressable>
          );
        })}
      </View>
      {error ? <View style={{ marginTop: 12 }}><Banner kind="error" text={error} /></View> : null}
    </View>
  );

  const empty = loading ? null : query ? (
    <Empty icon="search" title={t("noResults")} sub={t("noResultsSub")} />
  ) : (
    <View style={{ paddingTop: 8 }}>
      <Text style={{ color: c.sub, fontSize: 13, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 10, marginLeft: 4 }}>
        {t("suggestions")}
      </Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {t("suggestionList").split("|").map(s => (
          <Pressable key={s} onPress={() => { tap(); submit(s); }} accessibilityRole="button"
            style={{ paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: c.card }}>
            <Text style={{ color: c.text, fontSize: 15 }}>{s}</Text>
          </Pressable>
        ))}
      </View>
      <Card style={{ padding: 16, marginTop: 24 }}>
        <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 6 }}>
          <Ionicons name="globe-outline" size={20} color={c.accent} style={{ marginRight: 8 }} />
          <Text style={{ color: c.text, fontSize: 16, fontWeight: "700" }}>{t("makerworldTitle")}</Text>
        </View>
        <Text style={{ color: c.sub, fontSize: 14, lineHeight: 20, marginBottom: 12 }}>{t("makerworldText")}</Text>
        <Button kind="secondary" title={t("makerworldOpen")} icon="open-outline" onPress={() => Linking.openURL("https://makerworld.com")} />
      </Card>
      {tvMissing ? <Text style={{ color: c.sub, fontSize: 13, marginTop: 24, lineHeight: 18 }}>{t("thingiverseHint")}</Text> : null}
    </View>
  );

  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: c.bg }}>
      <FlatList
        key={cols}
        data={hits}
        numColumns={cols}
        keyExtractor={h => `${h.source}-${h.id}`}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={{ padding: space, paddingTop: 0, maxWidth: MAX_W, width: "100%", alignSelf: "center" }}
        columnWrapperStyle={{ gap: 12 }}
        ItemSeparatorComponent={() => <View style={{ height: 12 }} />}
        ListHeaderComponent={header}
        ListEmptyComponent={empty}
        ListFooterComponent={loading ? <ActivityIndicator color={c.accent} style={{ margin: 24 }} /> : <View style={{ height: 24 }} />}
        onEndReachedThreshold={0.6}
        onEndReached={() => { if (more && !loading) load(query, page + 1, source, sort); }}
        renderItem={({ item: h }) => (
          <Pressable onPress={() => { tap(); router.push({ pathname: "/model/[source]/[id]", params: { source: h.source, id: h.id } }); }}
            accessibilityRole="button" accessibilityLabel={h.name}
            style={({ pressed }) => ({ width: cardW, borderRadius: radius, backgroundColor: c.card, overflow: "hidden", opacity: pressed ? 0.85 : 1 })}>
            <Image source={h.thumbnail ? { uri: h.thumbnail } : undefined} contentFit="cover" transition={150}
              recyclingKey={`${h.source}-${h.id}`}
              style={{ width: cardW, height: cardW * 0.75, backgroundColor: c.track }} />
            <View style={{ padding: 10 }}>
              <Text style={{ color: c.text, fontSize: 15, fontWeight: "600", lineHeight: 19 }} numberOfLines={2}>{h.name}</Text>
              {h.author ? <Text style={{ color: c.sub, fontSize: 13, marginTop: 3 }} numberOfLines={1}>{h.author}</Text> : null}
              <View style={{ flexDirection: "row", gap: 10, marginTop: 6 }}>
                {h.likes != null ? <Text style={{ color: c.sub, fontSize: 12 }}>♥ {compact(h.likes)}</Text> : null}
                {h.downloads != null ? <Text style={{ color: c.sub, fontSize: 12 }}>↓ {compact(h.downloads)}</Text> : null}
              </View>
            </View>
          </Pressable>
        )}
      />
    </SafeAreaView>
  );
}
