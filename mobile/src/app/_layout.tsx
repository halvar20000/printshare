import { DarkTheme, DefaultTheme, Stack, ThemeProvider, useRouter } from "expo-router";
import { ShareIntentProvider, useShareIntentContext } from "expo-share-intent";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { Platform, useColorScheme } from "react-native";

import { AppProvider, useApp } from "@/lib/app";
import { extractLink, makerWorldId } from "@/lib/format";
import { useColors } from "@/lib/theme";

SplashScreen.preventAutoHideAsync().catch(() => {});

/** Links or files shared from Safari, Chrome, Files … open the prepare screen (MQ-01, MQ-03). */
function ShareHandler() {
  const { ready, server } = useApp();
  const router = useRouter();
  const { hasShareIntent, shareIntent, resetShareIntent } = useShareIntentContext();

  useEffect(() => {
    if (!ready || !hasShareIntent) return;
    if (!server) {
      router.push("/connect");  // the shared item waits until the server is connected
      return;
    }
    const file = shareIntent.files?.[0];
    const link = shareIntent.webUrl || extractLink(shareIntent.text);
    if (file) {
      router.push({ pathname: "/prepare", params: { fileUri: file.path, fileName: file.fileName ?? "model.stl" } });
    } else if (link && makerWorldId(link)) {
      router.push({ pathname: "/model/[source]/[id]", params: { source: "makerworld", id: makerWorldId(link)! } });
    } else if (link) {
      router.push({ pathname: "/prepare", params: { link } });
    }
    resetShareIntent();
  }, [ready, server, hasShareIntent, shareIntent, router, resetShareIntent]);
  return null;
}

function Root() {
  const { ready, t } = useApp();
  const c = useColors();
  const scheme = useColorScheme();
  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => {});
  }, [ready]);
  if (!ready) return null;
  const base = scheme === "dark" ? DarkTheme : DefaultTheme;
  const theme = { ...base, colors: { ...base.colors, primary: c.accent, background: c.bg, card: c.card, text: c.text, border: c.line } };
  return (
    <ThemeProvider value={theme}>
      <StatusBar style="auto" />
      <ShareHandler />
      <Stack screenOptions={{ headerTintColor: c.accent, headerTitleStyle: { color: c.text }, headerBackButtonDisplayMode: "minimal" }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="prepare" options={{ title: t("prepareTitle") }} />
        <Stack.Screen name="job/[id]" options={{ title: "" }} />
        <Stack.Screen name="model/[source]/[id]" options={{ title: "" }} />
        <Stack.Screen name="preview/[id]" options={{ title: t("previewTitle") }} />
        <Stack.Screen name="printer/[id]" options={{ title: "" }} />
        <Stack.Screen name="camera/[id]" options={{ title: "" }} />
        <Stack.Screen name="control/[id]" options={{ title: "" }} />
        <Stack.Screen name="cloud-printer/[id]" options={{ title: "" }} />
        <Stack.Screen name="model3d" options={{ title: "" }} />
        <Stack.Screen name="spoolman" options={{ title: t("spoolman") }} />
        <Stack.Screen name="spools" options={{ title: t("spools") }} />
        <Stack.Screen name="printables" options={{ title: "Printables" }} />
        <Stack.Screen name="manyfold" options={{ title: "Manyfold" }} />
        <Stack.Screen name="spool/[id]" options={{ title: "" }} />
        <Stack.Screen name="connect" options={{ title: t("connectTitle"), presentation: "modal" }} />
        <Stack.Screen name="scan" options={{ title: t("scanTitle"), presentation: "fullScreenModal", headerShown: false }} />
      </Stack>
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <ShareIntentProvider options={{ resetOnBackground: false, disabled: Platform.OS === "web" }}>
      <AppProvider>
        <Root />
      </AppProvider>
    </ShareIntentProvider>
  );
}
