// Cloud spools (server 0.17.0): the spools of a PocketPrint3D account for users without their own Spoolman.
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Switch, View } from "react-native";

import { Banner, Button, Divider, Empty, Row, Screen, Section } from "@/components/ui";
import { useApp } from "@/lib/app";
import { CLOUD_SPOOLS, openSpoolman, spoolLabel, type Spool } from "@/lib/spoolman";
import { useColors } from "@/lib/theme";

export default function SpoolsScreen() {
  const { server, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const [spools, setSpools] = useState<Spool[] | null>(null);
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState("");

  useFocusEffect(useCallback(() => {
    if (!server) return;
    openSpoolman(server, CLOUD_SPOOLS).spools(archived)
      .then(l => { setSpools(l); setError(""); }).catch(e => setError((e as Error).message));
  }, [server, archived]));

  const add = <Button title={t("spoolAdd")} icon="add" onPress={() => router.push({ pathname: "/spool/[id]", params: { id: "new" } })} />;
  if (!spools && !error) return <ActivityIndicator color={c.accent} style={{ marginTop: 40 }} />;
  return (
    <Screen footer={add}>
      {error ? <Banner kind="error" text={error} /> : null}
      {spools && !spools.length && !archived ? <Empty icon="disc-outline" title={t("spoolsEmpty")} sub={t("spoolsEmptySub")} /> : null}
      {spools?.length ? (
        <Section>
          {spools.map((s, i) => (
            <View key={s.id} style={{ opacity: s.archived ? 0.5 : 1 }}>
              {i ? <Divider /> : null}
              <Row label={spoolLabel(s)}
                sub={[s.material, s.remaining_g != null ? t("spoolLeft", { g: Math.round(s.remaining_g) }) : null, s.location]
                  .filter(Boolean).join(" · ")}
                onPress={() => router.push({ pathname: "/spool/[id]", params: { id: String(s.id) } })}
                right={<View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: s.color || c.track,
                  marginLeft: 8, borderWidth: 1, borderColor: c.line }} />} />
            </View>
          ))}
        </Section>
      ) : null}
      <Section>
        <Row icon="archive-outline" label={t("spoolsArchived")} right={<Switch value={archived} onValueChange={setArchived} />} />
      </Section>
    </Screen>
  );
}
