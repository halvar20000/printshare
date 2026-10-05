// File + network layer for talking to printers on the home Wi-Fi (cloud mode: the app relays, docs/CLOUD.md).
// This file is used on the web build and in node tests (fetch, FormData, Blob); io.native.ts on the phone.

export type GcodeFile = {
  name: string;
  size: number;
  /** file:// address on the phone (native code that reads the file itself, e.g. the Bambu upload) */
  uri?: string;
  bytes(): Promise<Uint8Array>;
  /** multipart POST of the whole file (Moonraker, OctoPrint); the phone streams it from disk */
  upload(url: string, fieldName: string, fields: Record<string, string>,
         onProgress?: (sent: number) => void, headers?: Record<string, string>): Promise<HttpResult>;
  /** the file as the raw body of a PUT (PrusaLink) */
  put(url: string, headers: Record<string, string>, onProgress?: (sent: number) => void): Promise<HttpResult>;
  release(): void;
};
export type HttpResult = { status: number; body: string };

export interface LanIo {
  /** G-code from the PocketPrint3D cloud (with the session token) */
  download(url: string, headers: Record<string, string>, name: string): Promise<GcodeFile>;
  /** multipart POST of a piece of a file (Centauri: 1 MB chunks) */
  postChunk(url: string, fields: Record<string, string>, fieldName: string, fileName: string,
            data: Uint8Array): Promise<HttpResult>;
}

async function postForm(url: string, fields: Record<string, string>, fieldName: string, fileName: string,
                        data: Uint8Array, headers: Record<string, string> = {}): Promise<HttpResult> {
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) form.append(k, v);
  form.append(fieldName, new Blob([data as BlobPart], { type: "application/octet-stream" }), fileName);
  const r = await fetch(url, { method: "POST", body: form, headers });
  return { status: r.status, body: await r.text() };
}

export const lanIo: LanIo = {
  async download(url, headers, name) {
    const r = await fetch(url, { headers });
    if (!r.ok) throw new Error(`download failed (HTTP ${r.status})`);
    const data = new Uint8Array(await r.arrayBuffer());
    return {
      name, size: data.length,
      bytes: async () => data,
      upload: (u, fieldName, fields, _progress, headers) => postForm(u, fields, fieldName, name, data, headers),
      put: async (u, headers) => {
        const r = await fetch(u, { method: "PUT", headers, body: data as BodyInit });
        return { status: r.status, body: await r.text() };
      },
      release: () => {},
    };
  },
  postChunk: (url, fields, fieldName, fileName, data) => postForm(url, fields, fieldName, fileName, data),
};
