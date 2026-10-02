"""Printer secrets sealed for one bridge (docs/BRIDGE.md section 7), scheme "pp3d-seal-v1".

The app encrypts e.g. {"address", "password"} with the bridge's public key; the cloud passes the blob on without being
able to read it. Built from primitives every platform has (Swift CryptoKit, @noble in JS, `cryptography` in Python):
  ephemeral X25519 key pair (e) → shared = X25519(e, bridge public key)
  key = HKDF-SHA256(shared, salt = e.public ‖ bridge public, info = "pp3d-seal-v1", 32 bytes)
  blob = base64(e.public ‖ ChaCha20-Poly1305(key, nonce = 12 zero bytes, plaintext))
The key is new for every message, so the fixed nonce is safe.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

INFO = b"pp3d-seal-v1"
NONCE = bytes(12)
MAX_BLOB = 16 * 1024


class SealError(ValueError):
    pass


def _raw_public(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def keypair() -> tuple[str, str]:
    """(private, public), both base64 of the 32 raw bytes."""
    priv = X25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return base64.b64encode(raw).decode(), base64.b64encode(_raw_public(priv.public_key())).decode()


def _key(shared: bytes, epk: bytes, pk: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=epk + pk, info=INFO).derive(shared)


def seal(public_key: str, data: dict[str, Any]) -> str:
    """What the apps do (here for tests and tools)."""
    pk = base64.b64decode(public_key)
    eph = X25519PrivateKey.generate()
    epk = _raw_public(eph.public_key())
    key = _key(eph.exchange(X25519PublicKey.from_public_bytes(pk)), epk, pk)
    return base64.b64encode(epk + ChaCha20Poly1305(key).encrypt(NONCE, json.dumps(data).encode(), None)).decode()


def unseal(private_key: str, blob: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(blob or "", validate=True)
    except ValueError as e:
        raise SealError("sealed data is not base64") from e
    if not 32 + 16 < len(raw) <= MAX_BLOB:
        raise SealError("sealed data has the wrong size")
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(private_key))
    pk = _raw_public(priv.public_key())
    epk, ct = raw[:32], raw[32:]
    try:
        key = _key(priv.exchange(X25519PublicKey.from_public_bytes(epk)), epk, pk)
        data = json.loads(ChaCha20Poly1305(key).decrypt(NONCE, ct, None))
    except Exception as e:  # noqa: BLE001 - wrong key, tampered or garbage
        raise SealError("sealed data could not be opened (sealed for another bridge?)") from e
    if not isinstance(data, dict):
        raise SealError("sealed data must be an object")
    return data
