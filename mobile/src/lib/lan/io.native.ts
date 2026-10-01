// Phone version of io.ts: the G-code goes to the cache directory and is uploaded from there by the native
// networking stack (no big strings through the JS bridge).
import { Directory, File, Paths, UploadType } from "expo-file-system";

import type { LanIo } from "./io";

export type { GcodeFile, HttpResult, LanIo } from "./io";

const dir = () => {
  const d = new Directory(Paths.cache, "printer-upload");
  if (!d.exists) d.create({ intermediates: true });
  return d;
};

export const lanIo: LanIo = {
  async download(url, headers, name) {
    const file = await File.downloadFileAsync(url, new File(dir(), name), { headers, idempotent: true });
    return {
      name, size: file.size ?? 0,
      bytes: () => file.bytes(),
      upload: async (u, fieldName, fields, onProgress, headers) => {
        const r = await file.upload(u, { httpMethod: "POST", uploadType: UploadType.MULTIPART, fieldName,
          mimeType: "application/octet-stream", parameters: fields, headers,
          onProgress: onProgress ? p => onProgress(p.bytesSent) : undefined });
        return { status: r.status, body: r.body };
      },
      put: async (u, headers, onProgress) => {
        const r = await file.upload(u, { httpMethod: "PUT", uploadType: UploadType.BINARY_CONTENT, headers,
          onProgress: onProgress ? p => onProgress(p.bytesSent) : undefined });
        return { status: r.status, body: r.body };
      },
      release: () => { try { file.delete(); } catch { /* already gone */ } },
    };
  },
  async postChunk(url, fields, fieldName, fileName, data) {
    // the chunk file needs the real file name: the printer stores the upload under it
    const chunkDir = new Directory(dir(), `chunk-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
    chunkDir.create();
    const chunk = new File(chunkDir, fileName);
    try {
      chunk.write(data);
      const r = await chunk.upload(url, { httpMethod: "POST", uploadType: UploadType.MULTIPART, fieldName,
        mimeType: "application/octet-stream", parameters: fields });
      return { status: r.status, body: r.body };
    } finally {
      try { chunkDir.delete(); } catch { /* best effort */ }
    }
  },
};
