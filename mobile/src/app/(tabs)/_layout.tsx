import Ionicons from "@expo/vector-icons/Ionicons";
import { Tabs } from "expo-router/js-tabs";
import type { ColorValue } from "react-native";

import { useApp } from "@/lib/app";
import { useColors } from "@/lib/theme";

export default function TabsLayout() {
  const { t } = useApp();
  const c = useColors();
  const icon = (name: React.ComponentProps<typeof Ionicons>["name"]) =>
    function TabIcon({ color, size }: { color: ColorValue; size: number }) {
      return <Ionicons name={name} color={color} size={size} />;
    };
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: c.accent, headerTitleStyle: { color: c.text } }}>
      <Tabs.Screen name="index" options={{ title: t("tabPrint"), tabBarIcon: icon("cube-outline"), headerShown: false }} />
      <Tabs.Screen name="discover" options={{ title: t("tabDiscover"), tabBarIcon: icon("search"), headerShown: false }} />
      <Tabs.Screen name="jobs" options={{ title: t("tabJobs"), tabBarIcon: icon("list-outline") }} />
      <Tabs.Screen name="printers" options={{ title: t("tabPrinters"), tabBarIcon: icon("print-outline") }} />
      <Tabs.Screen name="settings" options={{ title: t("tabSettings"), tabBarIcon: icon("settings-outline") }} />
    </Tabs>
  );
}
