// Phone: download into the cache directory (with the login header) and read it as base64 natively.
import { Directory, File, Paths } from "expo-file-system";

export async function loadModelBase64(url: string, headers: Record<string, string>, name: string,
                                      maxBytes: number): Promise<{ b64: string; size: number }> {
  const dir = new Directory(Paths.cache, "model-3d");
  if (!dir.exists) dir.create({ intermediates: true });
  const file = await File.downloadFileAsync(url, new File(dir, name.replace(/[^\w.-]+/g, "_")), { headers, idempotent: true });
  try {
    const size = file.size ?? 0;
    if (size > maxBytes) throw new RangeError(String(size));
    return { b64: await file.base64(), size };
  } finally {
    try { file.delete(); } catch { /* cache */ }
  }
}
