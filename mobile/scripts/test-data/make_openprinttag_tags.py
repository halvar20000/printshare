"""OpenPrintTag test tags following specs.openprinttag.org (NFC Type 5 CC, NDEF TLV, MIME record, meta/main/aux CBOR)."""
import cbor2, uuid, struct, base64, json
MIME = b"application/vnd.openprinttag"

def tag(main, aux, total=320, aux_size=32, cc8=False, extra_record=None):
    cc = bytes([0xE1, 0x40, (total - 4) // 8, 0x01]) if not cc8 else bytes([0xE2, 0x40, 0x00, 0x01, 0, 0, 0, (total - 8) // 8])
    tlv_hdr = 4                                   # 03 FF xx xx
    rec_hdr = 1 + 1 + 4 + len(MIME)               # not short record
    pre = len(cc) + tlv_hdr + (len(extra_record) if extra_record else 0) + rec_hdr
    payload_size = total - pre - 1                # terminator
    # aux at the end, aligned to 4-byte blocks in tag memory
    aux_off = payload_size - aux_size
    while (pre + aux_off) % 4: aux_off -= 1
    meta = cbor2.dumps({2: aux_off, 3: aux_size})
    m = cbor2.dumps(main)
    a = b"\x00" * aux_size if aux is None else b"\xbf" + b"".join(cbor2.dumps(k) + cbor2.dumps(v) for k, v in aux.items()) + b"\xff"
    payload = bytearray(payload_size)
    payload[0:len(meta)] = meta
    payload[len(meta):len(meta) + len(m)] = m
    payload[aux_off:aux_off + len(a)] = a
    rec = bytes([0x02 | 0x40 | (0x00 if extra_record else 0x80), len(MIME)]) + struct.pack(">I", len(payload)) + MIME + bytes(payload)
    msg = (extra_record or b"") + rec
    mem = cc + bytes([0x03, 0xFF]) + struct.pack(">H", len(msg)) + msg + b"\xfe"
    return mem.ljust(total, b"\x00")

main = {0: uuid.UUID("473bb8cd-e129-45b8-9fcf-da1c3add9c47").bytes, 7: "1", 8: 0, 9: 0, 10: "PLA Galaxy Black",
        11: "Prusament", 14: 1739371290, 16: 1000, 17: 1012, 18: 100, 19: bytes.fromhex("3d3e3d"), 27: 0.2, 28: [5],
        34: 205, 35: 220, 36: 170, 37: 40, 38: 60, 40: 40, 41: 20, 42: 75, 29: 1.24}
uri_rec = bytes([0x91, 0x01, 0x0c, 0x55, 0x04]) + b"prusa3d.com"     # a URI record before ours (MB, SR, TNF=1 "U")
out = {
  "galaxy": tag(main, {0: 120.5, 4: "Shelf B3", 1: "abc"}),
  "fresh_aux_zero": tag(main, None),
  "cc8_with_uri": tag({**main, 9: 1, 10: "PETG Jet Black", 19: bytes.fromhex("24292a"), 52: "PETG", 30: 2.85}, {0: 10}, total=512, cc8=True, extra_record=uri_rec),
}
json.dump({k: base64.b64encode(v).decode() for k, v in out.items()}, open("/tmp/opttest/tags.json", "w"))
print({k: len(v) for k, v in out.items()})
