// The model file for the 3D view, as base64 (web build: fetch). The phone version is modelFile.native.ts.
export async function loadModelBase64(url: string, headers: Record<string, string>, _name: string,
                                      maxBytes: number): Promise<{ b64: string; size: number }> {
  const r = await fetch(url, { headers });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const bytes = new Uint8Array(await r.arrayBuffer());
  if (bytes.length > maxBytes) throw new RangeError(String(bytes.length));
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return { b64: btoa(bin), size: bytes.length };
}
