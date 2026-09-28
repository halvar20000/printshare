// App-wide state: server connection, language, API client.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { AppState as RNAppState } from "react-native";

import { Api, resetRoutes, type Server } from "./api";
import { makeT, resolveLang, type LangPref, type T } from "./i18n";
import { getItem, getJSON, setItem, setJSON } from "./storage";

type AppState = {
  ready: boolean;
  server: Server | null;
  api: Api | null;
  t: T;
  langPref: LangPref;
  setServer: (s: Server | null) => Promise<void>;
  setLangPref: (l: LangPref) => Promise<void>;
};

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [server, setServerState] = useState<Server | null>(null);
  const [langPref, setLangState] = useState<LangPref>("auto");

  useEffect(() => {
    (async () => {
      const [s, l] = await Promise.all([getJSON<Server>("ps_server"), getItem("ps_lang")]);
      if (s?.url) setServerState(s);
      if (l === "de" || l === "en" || l === "auto") setLangState(l);
      setReady(true);
    })();
  }, []);

  // back in the foreground: maybe we left home (or came back) -> find the working address again
  useEffect(() => {
    const sub = RNAppState.addEventListener("change", s => { if (s === "active") resetRoutes(); });
    return () => sub.remove();
  }, []);

  const t = useMemo(() => makeT(resolveLang(langPref)), [langPref]);
  const api = useMemo(() => (server ? new Api(server, t) : null), [server, t]);

  const setServer = useCallback(async (s: Server | null) => {
    setServerState(s);
    await (s ? setJSON("ps_server", s) : setItem("ps_server", null));
  }, []);
  const setLangPref = useCallback(async (l: LangPref) => {
    setLangState(l);
    await setItem("ps_lang", l);
  }, []);

  const value = useMemo(() => ({ ready, server, api, t, langPref, setServer, setLangPref }),
    [ready, server, api, t, langPref, setServer, setLangPref]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

/** Last choices per printer, so the form opens with what was used before (spec 4). */
export type PrinterPrefs = { filament?: string; process?: string; bed_type?: string };
export const loadPrefs = (printer: string) => getJSON<PrinterPrefs>(`ps_prefs_${printer}`);
export const savePrefs = (printer: string, p: PrinterPrefs) => setJSON(`ps_prefs_${printer}`, p);
export const loadLastPrinter = () => getItem("ps_printer");
export const saveLastPrinter = (id: string) => setItem("ps_printer", id);
