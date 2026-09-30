// Small, native-feeling building blocks shared by all screens.
import Ionicons from "@expo/vector-icons/Ionicons";
import * as Haptics from "expo-haptics";
import { useMemo, useState, type ComponentProps, type ReactNode } from "react";
import {
  ActivityIndicator, Modal, Platform, Pressable, ScrollView, SectionList, StyleSheet, Text, TextInput, View,
  type StyleProp, type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { radius, space, useColors } from "@/lib/theme";

export type IconName = ComponentProps<typeof Ionicons>["name"];

export const tap = () => {
  if (Platform.OS !== "web") Haptics.selectionAsync().catch(() => {});
};

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const c = useColors();
  return <View style={[{ backgroundColor: c.card, borderRadius: radius, overflow: "hidden" }, style]}>{children}</View>;
}

export function Section({ title, children, footer }: { title?: string; children: ReactNode; footer?: string }) {
  const c = useColors();
  return (
    <View style={{ marginBottom: 22 }}>
      {title ? <Text style={[s.sectionTitle, { color: c.sub }]}>{title}</Text> : null}
      <Card>{children}</Card>
      {footer ? <Text style={[s.footer, { color: c.sub }]}>{footer}</Text> : null}
    </View>
  );
}

export function Divider() {
  const c = useColors();
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: c.line, marginLeft: space }} />;
}

/** A list row: label on the left, value / control on the right. */
export function Row({ icon, label, value, sub, onPress, onLongPress, right, danger, chevron = !!onPress }: {
  icon?: IconName; label: string; value?: string | null; sub?: string | null; onPress?: () => void;
  onLongPress?: () => void; right?: ReactNode; danger?: boolean; chevron?: boolean;
}) {
  const c = useColors();
  return (
    <Pressable
      onPress={onPress ? () => { tap(); onPress(); } : undefined}
      onLongPress={onLongPress ? () => { tap(); onLongPress(); } : undefined}
      delayLongPress={500}
      disabled={!onPress && !onLongPress}
      accessibilityRole={onPress || onLongPress ? "button" : undefined}
      style={({ pressed }) => [s.row, pressed && (onPress || onLongPress) ? { backgroundColor: c.input } : null]}
    >
      {icon ? <Ionicons name={icon} size={22} color={danger ? c.danger : c.accent} style={{ marginRight: 12 }} /> : null}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={[s.rowLabel, { color: danger ? c.danger : c.text }]} numberOfLines={1}>{label}</Text>
        {sub ? <Text style={[s.rowSub, { color: c.sub }]} numberOfLines={2}>{sub}</Text> : null}
      </View>
      {value ? <Text style={[s.rowValue, { color: c.sub }]} numberOfLines={1}>{value}</Text> : null}
      {right}
      {chevron ? <Ionicons name="chevron-forward" size={18} color={c.sub} style={{ marginLeft: 6 }} /> : null}
    </Pressable>
  );
}

export function Button({ title, onPress, kind = "primary", icon, loading, disabled, style }: {
  title: string; onPress: () => void; kind?: "primary" | "secondary" | "danger" | "plain";
  icon?: IconName; loading?: boolean; disabled?: boolean; style?: StyleProp<ViewStyle>;
}) {
  const c = useColors();
  const bg = { primary: c.accent, secondary: c.accentSoft, danger: c.dangerSoft, plain: "transparent" }[kind];
  const fg = { primary: c.accentText, secondary: c.accent, danger: c.danger, plain: c.accent }[kind];
  const off = disabled || loading;
  return (
    <Pressable
      onPress={() => { tap(); onPress(); }}
      disabled={off}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      style={({ pressed }) => [s.button, { backgroundColor: bg, opacity: off ? 0.45 : pressed ? 0.8 : 1 }, style]}
    >
      {loading ? <ActivityIndicator color={fg} style={{ marginRight: 8 }} />
        : icon ? <Ionicons name={icon} size={20} color={fg} style={{ marginRight: 8 }} /> : null}
      <Text style={[s.buttonText, { color: fg }]}>{title}</Text>
    </Pressable>
  );
}

export function Segmented<V extends string>({ values, value, labels, onChange }: {
  values: V[]; value: V | null; labels: Record<string, string>; onChange: (v: V) => void;
}) {
  const c = useColors();
  return (
    <View style={[s.seg, { backgroundColor: c.track }]} accessibilityRole="radiogroup">
      {values.map(v => {
        const on = v === value;
        return (
          <Pressable key={v} onPress={() => { tap(); onChange(v); }} accessibilityRole="radio"
            accessibilityState={{ checked: on }}
            style={[s.segItem, on && { backgroundColor: c.card, shadowOpacity: 0.12 }]}>
            <Text style={{ color: c.text, fontWeight: on ? "600" : "400", fontSize: 14 }}>{labels[v] ?? v}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Label + control stacked, used inside a Card. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  const c = useColors();
  return (
    <View style={{ paddingHorizontal: space, paddingVertical: 12 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 8 }}>
        <Text style={{ color: c.text, fontSize: 16 }}>{label}</Text>
        {hint ? <Text style={{ color: c.sub, fontSize: 14 }}>{hint}</Text> : null}
      </View>
      {children}
    </View>
  );
}

export function Stepper({ value, min, max, step = 1, onChange, format }: {
  value: number; min: number; max: number; step?: number; onChange: (v: number) => void; format?: (v: number) => string;
}) {
  const c = useColors();
  const btn = (icon: IconName, next: number, off: boolean) => (
    <Pressable onPress={() => { tap(); onChange(next); }} disabled={off} hitSlop={8}
      accessibilityRole="button" accessibilityLabel={icon === "remove" ? "−" : "+"}
      style={[s.stepBtn, { backgroundColor: c.track, opacity: off ? 0.35 : 1 }]}>
      <Ionicons name={icon} size={20} color={c.text} />
    </Pressable>
  );
  return (
    <View style={{ flexDirection: "row", alignItems: "center" }}>
      {btn("remove", Math.max(min, value - step), value <= min)}
      <Text style={{ color: c.text, fontSize: 17, fontWeight: "600", minWidth: 64, textAlign: "center" }}>
        {format ? format(value) : value}
      </Text>
      {btn("add", Math.min(max, value + step), value >= max)}
    </View>
  );
}

export function Banner({ kind = "info", text, icon }: { kind?: "info" | "warn" | "error" | "ok"; text: string; icon?: IconName }) {
  const c = useColors();
  const [bg, fg, ic] = {
    info: [c.accentSoft, c.accent, "information-circle"], warn: [c.warnSoft, c.warn, "warning"],
    error: [c.dangerSoft, c.danger, "alert-circle"], ok: [c.okSoft, c.ok, "checkmark-circle"],
  }[kind] as [string, string, IconName];
  return (
    <View style={[s.banner, { backgroundColor: bg }]} accessibilityRole="alert">
      <Ionicons name={icon ?? ic} size={20} color={fg} style={{ marginRight: 10, marginTop: 1 }} />
      <Text style={{ color: c.text, flex: 1, fontSize: 15, lineHeight: 21 }}>{text}</Text>
    </View>
  );
}

export function Badge({ text, kind = "neutral" }: { text: string; kind?: "neutral" | "ok" | "warn" | "error" | "accent" }) {
  const c = useColors();
  const [bg, fg] = { neutral: [c.track, c.sub], ok: [c.okSoft, c.ok], warn: [c.warnSoft, c.warn],
    error: [c.dangerSoft, c.danger], accent: [c.accentSoft, c.accent] }[kind];
  return (
    <View style={{ backgroundColor: bg, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 }}>
      <Text style={{ color: fg, fontSize: 13, fontWeight: "600" }}>{text}</Text>
    </View>
  );
}

export function ProgressBar({ value }: { value: number }) {
  const c = useColors();
  return (
    <View style={{ height: 8, borderRadius: 4, backgroundColor: c.track, overflow: "hidden" }}
      accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: 100, now: Math.round(value) }}>
      <View style={{ width: `${Math.max(0, Math.min(100, value))}%`, height: "100%", backgroundColor: c.accent }} />
    </View>
  );
}

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  const c = useColors();
  return (
    <Card style={{ flex: 1, padding: 14 }}>
      <Text style={{ color: c.sub, fontSize: 13 }}>{label}</Text>
      <Text style={{ color: c.text, fontSize: 22, fontWeight: "700", marginTop: 4 }} numberOfLines={1}
        adjustsFontSizeToFit>{value}</Text>
      {sub ? <Text style={{ color: c.sub, fontSize: 13, marginTop: 2 }}>{sub}</Text> : null}
    </Card>
  );
}

export function Empty({ icon, title, sub, children }: { icon: IconName; title: string; sub?: string; children?: ReactNode }) {
  const c = useColors();
  return (
    <View style={{ alignItems: "center", paddingVertical: 48, paddingHorizontal: 24 }}>
      <Ionicons name={icon} size={48} color={c.sub} />
      <Text style={{ color: c.text, fontSize: 18, fontWeight: "600", marginTop: 12, textAlign: "center" }}>{title}</Text>
      {sub ? <Text style={{ color: c.sub, fontSize: 15, marginTop: 6, textAlign: "center" }}>{sub}</Text> : null}
      {children ? <View style={{ marginTop: 20, alignSelf: "stretch" }}>{children}</View> : null}
    </View>
  );
}

export function Screen({ children, footer, refreshControl }: {
  children: ReactNode; footer?: ReactNode; refreshControl?: ComponentProps<typeof ScrollView>["refreshControl"];
}) {
  const c = useColors();
  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled"
        refreshControl={refreshControl}
        contentContainerStyle={{ padding: space, paddingBottom: footer ? 24 : 48, maxWidth: 640, width: "100%", alignSelf: "center" }}>
        {children}
      </ScrollView>
      {footer ? (
        <SafeAreaView edges={["bottom"]} style={{ backgroundColor: c.bg, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line }}>
          <View style={{ padding: space, paddingBottom: 8, gap: 10, maxWidth: 640, width: "100%", alignSelf: "center" }}>{footer}</View>
        </SafeAreaView>
      ) : null}
    </View>
  );
}

export type Choice = { value: string; label: string; group?: string; sub?: string };

/** Full-screen picker with search and optional groups (materials, quality, plates …). */
export function PickerSheet({ visible, title, choices, value, onPick, onClose, searchLabel, closeLabel }: {
  visible: boolean; title: string; choices: Choice[]; value: string | null; onPick: (v: string) => void;
  onClose: () => void; searchLabel: string; closeLabel: string;
}) {
  const c = useColors();
  const [q, setQ] = useState("");
  const sections = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const groups = new Map<string, Choice[]>();
    for (const ch of choices) {
      if (needle && !`${ch.label} ${ch.group ?? ""}`.toLowerCase().includes(needle)) continue;
      const g = ch.group ?? "";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g)!.push(ch);
    }
    return [...groups].map(([g, data]) => ({ title: g, data }));
  }, [choices, q]);
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }} edges={["top", "bottom"]}>
        <View style={s.sheetHead}>
          <Text style={{ color: c.text, fontSize: 17, fontWeight: "600", flex: 1 }}>{title}</Text>
          <Pressable onPress={onClose} hitSlop={12} accessibilityRole="button">
            <Text style={{ color: c.accent, fontSize: 17 }}>{closeLabel}</Text>
          </Pressable>
        </View>
        {choices.length > 8 ? (
          <View style={[s.search, { backgroundColor: c.input }]}>
            <Ionicons name="search" size={18} color={c.sub} />
            <TextInput value={q} onChangeText={setQ} placeholder={searchLabel} placeholderTextColor={c.sub}
              style={{ flex: 1, color: c.text, fontSize: 16, marginLeft: 8, paddingVertical: 8 }}
              autoCorrect={false} autoCapitalize="none" clearButtonMode="while-editing" />
          </View>
        ) : null}
        <SectionList
          sections={sections}
          keyExtractor={i => i.value}
          keyboardShouldPersistTaps="handled"
          stickySectionHeadersEnabled={false}
          contentContainerStyle={{ paddingHorizontal: space, paddingBottom: 40 }}
          renderSectionHeader={({ section }) => section.title
            ? <Text style={[s.sectionTitle, { color: c.sub, marginTop: 16 }]}>{section.title}</Text> : <View style={{ height: 8 }} />}
          renderItem={({ item, index, section }) => {
            const first = index === 0, last = index === section.data.length - 1;
            const on = item.value === value;
            return (
              <Pressable onPress={() => { tap(); onPick(item.value); onClose(); }} accessibilityRole="button"
                accessibilityState={{ selected: on }}
                style={({ pressed }) => [s.row, {
                  backgroundColor: pressed ? c.input : c.card,
                  borderTopLeftRadius: first ? radius : 0, borderTopRightRadius: first ? radius : 0,
                  borderBottomLeftRadius: last ? radius : 0, borderBottomRightRadius: last ? radius : 0,
                  borderBottomWidth: last ? 0 : StyleSheet.hairlineWidth, borderBottomColor: c.line,
                }]}>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: c.text, fontSize: 16 }}>{item.label}</Text>
                  {item.sub ? <Text style={{ color: c.sub, fontSize: 13, marginTop: 2 }}>{item.sub}</Text> : null}
                </View>
                {on ? <Ionicons name="checkmark" size={22} color={c.accent} /> : null}
              </Pressable>
            );
          }}
        />
      </SafeAreaView>
    </Modal>
  );
}

const s = StyleSheet.create({
  sectionTitle: { fontSize: 13, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6, marginLeft: space },
  footer: { fontSize: 13, marginTop: 6, marginHorizontal: space, lineHeight: 18 },
  row: { flexDirection: "row", alignItems: "center", paddingHorizontal: space, paddingVertical: 13, minHeight: 50 },
  rowLabel: { fontSize: 16 },
  rowSub: { fontSize: 13, marginTop: 2 },
  rowValue: { fontSize: 16, marginLeft: 12, maxWidth: "55%" },
  button: { flexDirection: "row", alignItems: "center", justifyContent: "center", borderRadius: radius, minHeight: 52, paddingHorizontal: 18 },
  buttonText: { fontSize: 17, fontWeight: "600" },
  seg: { flexDirection: "row", borderRadius: 10, padding: 3 },
  segItem: { flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: 8, shadowColor: "#000", shadowOffset: { width: 0, height: 1 }, shadowRadius: 2, shadowOpacity: 0 },
  stepBtn: { width: 40, height: 36, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  banner: { flexDirection: "row", alignItems: "flex-start", padding: 12, borderRadius: 12, marginBottom: 14 },
  sheetHead: { flexDirection: "row", alignItems: "center", paddingHorizontal: space, paddingVertical: 14 },
  search: { flexDirection: "row", alignItems: "center", marginHorizontal: space, borderRadius: 10, paddingHorizontal: 10 },
});
