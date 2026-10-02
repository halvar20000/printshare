// Web build (development previews only): printables.com refuses to be shown in an iframe - open it in a new tab.
import { forwardRef, useImperativeHandle } from "react";
import { Linking, Text, View } from "react-native";

export const PRINTABLES_HOME = "https://www.printables.com/";
export const printablesModelId = (url?: string | null) =>
  (url ?? "").match(/^https:\/\/(?:www\.)?printables\.com\/(?:[a-z]{2}\/)?model\/(\d+)/)?.[1] ?? null;
export type PrintablesWebHandle = { goBack(): void; goForward(): void; reload(): void };
export type NavState = { url: string; canGoBack: boolean; canGoForward: boolean };

export const PrintablesWeb = forwardRef<PrintablesWebHandle, {
  onNav: (s: Partial<NavState>) => void; onDownload: (url: string) => void;
}>(function PrintablesWeb(_props, ref) {
  useImperativeHandle(ref, () => ({ goBack() {}, goForward() {}, reload() {} }), []);
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24 }}>
      <Text style={{ color: "#888", textAlign: "center" }} onPress={() => Linking.openURL(PRINTABLES_HOME)}>
        printables.com (only in the Android/iOS app)
      </Text>
    </View>
  );
});
