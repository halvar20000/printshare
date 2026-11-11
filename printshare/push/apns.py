"""Apple Push Notification service: one HTTP/2 client, JWT (ES256) from the team's .p8 key, refreshed every 50 minutes.

Configured only on the cloud server (env PRINTSHARE_APNS_KEY = the .p8 file's path or its PEM text,
PRINTSHARE_APNS_KEY_ID, PRINTSHARE_APNS_TEAM_ID, PRINTSHARE_APNS_TOPIC = the app's bundle id). Never in the repository.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}
JWT_MAX_AGE_S = 50 * 60       # Apple: refresh between 20 and 60 minutes


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load_key(value: str) -> ec.EllipticCurvePrivateKey:
    """The .p8 key from its PEM text or a file path."""
    text = value.strip()
    if "BEGIN" not in text:
        text = Path(text).read_text()
    key = serialization.load_pem_private_key(text.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("the APNs key must be an EC (P-256) key from Apple's developer portal")
    return key


def es256_jwt(key: ec.EllipticCurvePrivateKey, key_id: str, team_id: str, now: float | None = None) -> str:
    header = _b64(json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"iss": team_id, "iat": int(now or time.time())}, separators=(",", ":")).encode())
    der = key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{header}.{claims}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


@dataclass
class Result:
    status: int
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def gone(self) -> bool:
        """The token is dead for good: forget it (410, or a token APNs doesn't know)."""
        return self.status == 410 or self.reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic")


class APNs:
    def __init__(self, key: str, key_id: str, team_id: str, topic: str, client: httpx.AsyncClient | None = None,
                 hosts: dict[str, str] | None = None) -> None:
        self.key = load_key(key)
        self.key_id, self.team_id, self.topic = key_id, team_id, topic
        self.hosts = hosts or HOSTS
        self._client = client
        self._jwt: tuple[str, float] | None = None

    def _token(self) -> str:
        now = time.time()
        if self._jwt is None or now - self._jwt[1] > JWT_MAX_AGE_S:
            self._jwt = (es256_jwt(self.key, self.key_id, self.team_id, now), now)
        return self._jwt[0]

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(http2=True, timeout=15)
        return self._client

    async def send(self, token: str, env: str, payload: dict[str, Any], push_type: str = "alert",
                   priority: int = 10, collapse_id: str | None = None, expiration: int | None = None) -> Result:
        topic = self.topic + (".push-type.liveactivity" if push_type == "liveactivity" else "")
        headers = {"authorization": f"bearer {self._token()}", "apns-topic": topic, "apns-push-type": push_type,
                   "apns-priority": str(priority)}
        if collapse_id:
            headers["apns-collapse-id"] = collapse_id[:64]
        if expiration is not None:
            headers["apns-expiration"] = str(int(expiration))
        url = f"{self.hosts.get(env, self.hosts['production'])}/3/device/{token}"
        try:
            r = await self.client().post(url, content=json.dumps(payload, separators=(",", ":")), headers=headers)
        except httpx.HTTPError as e:
            return Result(0, f"network: {e}"[:200])
        reason = ""
        if r.status_code != 200:
            try:
                reason = str(r.json().get("reason") or "")
            except ValueError:
                reason = r.text[:100]
        return Result(r.status_code, reason)
