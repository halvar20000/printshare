import { Api, normalizeUrl, type Server } from "./api";
import type { T } from "./i18n";

/** Pairing QR code / deep link from `printshare pair`: printshare://connect?url=…&token=… */
export function parsePairing(data: string): Server | null {
  const m = data.trim().match(/^printshare:\/\/+connect\?(.*)$/i);
  if (!m) return null;
  const q = new URLSearchParams(m[1]);
  const url = normalizeUrl(q.get("url") ?? "");
  return url ? { url, token: q.get("token") ?? "" } : null;
}

/** Throws ApiError with a friendly message when the server can't be used. */
export async function checkServer(server: Server, t: T): Promise<Server> {
  const s = { url: normalizeUrl(server.url), token: server.token.trim() };
  await new Api(s, t).info();
  return s;
}
