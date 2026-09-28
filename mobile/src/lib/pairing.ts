import { Api, normalizeUrl, type Server } from "./api";
import type { T } from "./i18n";

/** Pairing QR code / deep link from `printshare pair`: printshare://connect?url=…&token=… */
export function parsePairing(data: string): Server | null {
  const m = data.trim().match(/^printshare:\/\/+connect\?(.*)$/i);
  if (!m) return null;
  const q = new URLSearchParams(m[1]);
  const url = normalizeUrl(q.get("url") ?? "");
  const remote = normalizeUrl(q.get("remote") ?? "");
  return url ? { url, token: q.get("token") ?? "", ...(remote ? { remoteUrl: remote } : {}) } : null;
}

/** Throws ApiError with a friendly message when neither address can be used. */
export async function checkServer(server: Server, t: T): Promise<Server> {
  const remote = normalizeUrl(server.remoteUrl ?? "");
  const s: Server = { url: normalizeUrl(server.url), token: server.token.trim(), ...(remote ? { remoteUrl: remote } : {}) };
  await new Api(s, t).info();
  return s;
}
