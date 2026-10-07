import Ionicons from "@expo/vector-icons/Ionicons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";

import { Badge, Banner, Empty, tap } from "@/components/ui";
import { isExternal, type JobSummary } from "@/lib/api";
import { useApp } from "@/lib/app";
import { ago, jobName, printTime } from "@/lib/format";
import { radius, space, useColors } from "@/lib/theme";

export default function Jobs() {
  const { api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!api) return;
    try {
      const [j, ps] = await Promise.all([api.jobs(), api.printers()]);
      setJobs(j);
      setNames(Object.fromEntries(ps.map(p => [p.id, p.name])));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [api]);

  useFocusEffect(useCallback(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [load]));

  return (
    <FlatList
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{ padding: space, gap: 10, maxWidth: 640, width: "100%", alignSelf: "center" }}
      data={jobs ?? []}
      keyExtractor={j => j.id}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={c.accent}
        onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      ListHeaderComponent={error ? <Banner kind="error" text={error} /> : null}
      ListEmptyComponent={jobs ? <Empty icon="file-tray-outline" title={t("jobsEmpty")} sub={t("jobsEmptySub")} /> : null}
      renderItem={({ item: j }) => {
        // a running print shows how far it is (server 0.40.0), also one started on the printer itself
        const progress = j.state === "started" && j.progress != null ? `${Math.round(j.progress)} %` : null;
        const meta = [names[j.printer ?? ""] ?? j.printer, progress, j.print_time ? printTime(j.print_time) : null,
          j.filament_g != null ? `${j.filament_g.toFixed(1)} g` : null, ago(t, j.created)].filter(Boolean).join(" · ");
        const kind = j.state === "error" ? "error" : j.state === "finished" || j.state === "done" ? "ok"
          : j.state === "cancelled" ? "warn" : j.state === "started" || j.state === "sliced" ? "accent" : "neutral";
        return (
          <Pressable onPress={() => { tap(); router.push(`/job/${j.id}`); }} accessibilityRole="button"
            style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", padding: 14, borderRadius: radius,
              backgroundColor: pressed ? c.input : c.card })}>
            <Ionicons name={j.state === "error" ? "alert-circle-outline" : isExternal(j) ? "print-outline" : "cube-outline"} size={26}
              color={j.state === "error" ? c.danger : c.accent} style={{ marginRight: 12 }} />
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={{ color: c.text, fontSize: 16, fontWeight: "500" }} numberOfLines={1}>{jobName(j.file, j.link)}</Text>
              <Text style={{ color: c.sub, fontSize: 13, marginTop: 3 }} numberOfLines={1}>{meta}</Text>
            </View>
            <Badge text={t.table.jobStates[j.state] ?? j.state} kind={kind} />
          </Pressable>
        );
      }}
    />
  );
}
