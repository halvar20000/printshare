import { useColorScheme } from "react-native";

const light = {
  bg: "#F2F2F7", card: "#FFFFFF", text: "#111114", sub: "#6B6B73", line: "#E2E2E8",
  accent: "#2F6FED", accentText: "#FFFFFF", accentSoft: "#E4ECFD",
  ok: "#1E8E3E", okSoft: "#E3F4E8", warn: "#B25E00", warnSoft: "#FFF3DC", danger: "#D12F2F", dangerSoft: "#FDE6E6",
  input: "#F2F2F7", track: "#E5E5EA",
};
const dark: typeof light = {
  bg: "#000000", card: "#1C1C1E", text: "#F2F2F7", sub: "#9A9AA2", line: "#2C2C30",
  accent: "#5B8DF6", accentText: "#FFFFFF", accentSoft: "#17243F",
  ok: "#4CC06A", okSoft: "#16301D", warn: "#F0A33A", warnSoft: "#33260F", danger: "#FF5C5C", dangerSoft: "#3A1717",
  input: "#2C2C2E", track: "#3A3A3C",
};

export type Colors = typeof light;

export function useColors(): Colors {
  return useColorScheme() === "dark" ? dark : light;
}

export const radius = 14;
export const space = 16;
