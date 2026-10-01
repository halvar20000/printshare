// File + network layer for talking to printers on the home Wi-Fi (cloud mode: the app relays, docs/CLOUD.md).
// This file is used on the web build and in node tests (fetch, FormData, Blob); io.native.ts on the phone.

export type GcodeFile = {
  name: string;
  size: number;
  bytes(): Promise<Uint8Array>;
  /** multipart POST of the whole file (Moonraker); the phone streams it from disk */
  upload(url: string, fieldName: string, fields: Record<string, string>,
         onProgress?: (sent: number) => void): Promise<HttpResult>;
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
                        data: Uint8Array): Promise<HttpResult> {
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) form.append(k, v);
  form.append(fieldName, new Blob([data as BlobPart], { type: "application/octet-stream" }), fileName);
  const r = await fetch(url, { method: "POST", body: form });
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
      upload: (u, fieldName, fields) => postForm(u, fields, fieldName, name, data),
      release: () => {},
    };
  },
  postChunk: postForm,
};
