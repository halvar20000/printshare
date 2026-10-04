// Printer secrets sealed for one bridge, scheme "pp3d-seal-v1" (docs/BRIDGE.md section 7, server: printshare/bridge/seal.py).
// The cloud passes the blob on without being able to read it:
//   ephemeral X25519 key e → shared = X25519(e, bridge public key)
//   key = HKDF-SHA256(shared, salt = e.public ‖ bridge public key, info = "pp3d-seal-v1", 32 bytes)
//   blob = base64(e.public ‖ ChaCha20-Poly1305(key, nonce = 12 zero bytes, JSON))
// The random source comes from the caller (expo-crypto in the app, node's crypto in tests).
import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { x25519 } from "@noble/curves/ed25519.js";
import { hkdf } from "@noble/hashes/hkdf.js";
import { sha256 } from "@noble/hashes/sha2.js";

const INFO = new TextEncoder().encode("pp3d-seal-v1");
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export function toBase64(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | ((bytes[i + 1] ?? 0) << 8) | (bytes[i + 2] ?? 0);
    out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63] + (i + 1 < bytes.length ? B64[(n >> 6) & 63] : "=")
      + (i + 2 < bytes.length ? B64[n & 63] : "=");
  }
  return out;
}

export function fromBase64(text: string): Uint8Array {
  const clean = text.replace(/[^A-Za-z0-9+/]/g, "");
  const out = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let bits = 0, value = 0, j = 0;
  for (const ch of clean) {
    value = (value << 6) | B64.indexOf(ch);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[j++] = (value >> bits) & 255;
    }
  }
  return out.subarray(0, j);
}

export type SealSecrets = { address?: string; password?: string; api_key?: string; access_code?: string;
  camera_url?: string };          // own camera (RTSP / HTTP); "" removes it

/** Seal `data` for the bridge with this public key (base64, 32 bytes). `random(n)` must be cryptographically secure. */
export function seal(publicKeyB64: string, data: SealSecrets, random: (n: number) => Uint8Array): string {
  const pk = fromBase64(publicKeyB64);
  if (pk.length !== 32) throw new Error("the bridge has no valid key - update it");
  const esk = random(32);
  const epk = x25519.getPublicKey(esk);
  const shared = x25519.getSharedSecret(esk, pk);
  const salt = new Uint8Array(64);
  salt.set(epk, 0);
  salt.set(pk, 32);
  const key = hkdf(sha256, shared, salt, INFO, 32);
  const ct = chacha20poly1305(key, new Uint8Array(12)).encrypt(new TextEncoder().encode(JSON.stringify(data)));
  const out = new Uint8Array(32 + ct.length);
  out.set(epk, 0);
  out.set(ct, 32);
  esk.fill(0);
  return toBase64(out);
}
