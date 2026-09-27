import { getShareExtensionKey } from "expo-share-intent";

// Share-extension deep links carry no route; land on the home tab, where ShareHandler picks them up.
export function redirectSystemPath({ path }: { path: string; initial: boolean }) {
  try {
    if (path.includes(`dataUrl=${getShareExtensionKey()}`)) return "/";
    return path;
  } catch {
    return "/";
  }
}
