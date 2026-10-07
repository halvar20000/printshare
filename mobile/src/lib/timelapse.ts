// "Always make a time-lapse" (server 0.40.0): the switch before printing starts on. An own server keeps the setting
// too (GET/PUT /api/timelapse/config), so it also records prints started on the printer itself; the phone's copy is
// the default for the switch (and the only copy in the cloud).
import { ApiError, type Api, type Server } from "./api";
import { getItem, setItem } from "./storage";

const key = (server: Server) => `ps_timelapse_always_${(server.email ?? server.url).replace(/[^\w.-]/g, "_")}`;

export const loadTimelapseAlways = async (server: Server) => (await getItem(key(server))) === "1";

export const saveTimelapseAlways = (server: Server, on: boolean) => setItem(key(server), on ? "1" : null);

/** The server's setting (own servers); `old` = server before 0.40.0 (404), null = unknown (offline, cloud). */
export async function serverTimelapseAlways(api: Api, server: Server): Promise<boolean | "old" | null> {
  if (server.cloud) return null;
  try {
    return (await api.timelapseConfig()).always;
  } catch (e) {
    return e instanceof ApiError && e.status === 404 ? "old" : null;
  }
}
