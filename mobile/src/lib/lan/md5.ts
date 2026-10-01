// MD5 (RFC 1321) over bytes, incremental - the Centauri's upload protocol wants the file's MD5 with every chunk.
// Not for security; plain TypeScript so it works the same in the app, the web build and node tests.

const S = [7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
  5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
  6, 10, 15, 21];
const K = Array.from({ length: 64 }, (_, i) => Math.floor(Math.abs(Math.sin(i + 1)) * 2 ** 32) >>> 0);

export class Md5 {
  private h = new Uint32Array([0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476]);
  private buf = new Uint8Array(64);
  private bufLen = 0;
  private total = 0;
  private w = new Uint32Array(16);

  update(data: Uint8Array): this {
    let i = 0;
    this.total += data.length;
    if (this.bufLen) {
      const take = Math.min(64 - this.bufLen, data.length);
      this.buf.set(data.subarray(0, take), this.bufLen);
      this.bufLen += take;
      i = take;
      if (this.bufLen < 64) return this;
      this.block(this.buf, 0);
      this.bufLen = 0;
    }
    for (; i + 64 <= data.length; i += 64) this.block(data, i);
    if (i < data.length) {
      this.buf.set(data.subarray(i), 0);
      this.bufLen = data.length - i;
    }
    return this;
  }

  hex(): string {
    const bits = this.total * 8;
    const pad = new Uint8Array(((this.bufLen < 56 ? 56 : 120) - this.bufLen) + 8);
    pad[0] = 0x80;
    const lo = bits >>> 0, hi = Math.floor(bits / 2 ** 32) >>> 0;
    const n = pad.length;
    for (let j = 0; j < 4; j++) {
      pad[n - 8 + j] = (lo >>> (8 * j)) & 0xff;
      pad[n - 4 + j] = (hi >>> (8 * j)) & 0xff;
    }
    const total = this.total;
    this.update(pad);
    this.total = total;
    let out = "";
    for (const v of this.h) for (let j = 0; j < 4; j++) out += ((v >>> (8 * j)) & 0xff).toString(16).padStart(2, "0");
    return out;
  }

  private block(d: Uint8Array, o: number): void {
    const w = this.w;
    for (let j = 0; j < 16; j++) {
      w[j] = d[o + 4 * j] | (d[o + 4 * j + 1] << 8) | (d[o + 4 * j + 2] << 16) | (d[o + 4 * j + 3] << 24);
    }
    let [a, b, c, e] = this.h;
    for (let i = 0; i < 64; i++) {
      let f: number, g: number;
      if (i < 16) { f = (b & c) | (~b & e); g = i; }
      else if (i < 32) { f = (e & b) | (~e & c); g = (5 * i + 1) % 16; }
      else if (i < 48) { f = b ^ c ^ e; g = (3 * i + 5) % 16; }
      else { f = c ^ (b | ~e); g = (7 * i) % 16; }
      const tmp = e;
      e = c;
      c = b;
      const x = (a + f + K[i] + w[g]) >>> 0;
      b = (b + ((x << S[i]) | (x >>> (32 - S[i])))) >>> 0;
      a = tmp;
    }
    this.h[0] = (this.h[0] + a) >>> 0;
    this.h[1] = (this.h[1] + b) >>> 0;
    this.h[2] = (this.h[2] + c) >>> 0;
    this.h[3] = (this.h[3] + e) >>> 0;
  }
}

export const md5Hex = (data: Uint8Array) => new Md5().update(data).hex();
