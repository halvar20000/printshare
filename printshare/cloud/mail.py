"""Login codes by e-mail (cloud mode). Brevo's transactional API; a log mailer for tests and development."""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

log = logging.getLogger("printshare.mail")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
SENDER = {"name": "PocketPrint3D", "email": "no-reply@pocketprint3d.com"}

TEXTS = {
    "de": ("Dein PocketPrint3D-Code: {code}",
           "Hallo,\n\ndein Anmeldecode für PocketPrint3D lautet:\n\n    {code}\n\nEr ist 10 Minuten gültig. "
           "Wenn du dich nicht anmelden wolltest, ignoriere diese E-Mail einfach.\n\nPocketPrint3D – https://pocketprint3d.com"),
    "en": ("Your PocketPrint3D code: {code}",
           "Hello,\n\nyour PocketPrint3D login code is:\n\n    {code}\n\nIt is valid for 10 minutes. "
           "If you didn't try to log in, just ignore this e-mail.\n\nPocketPrint3D – https://pocketprint3d.com"),
}


class MailError(Exception):
    pass


class Mailer(Protocol):
    def send_code(self, email: str, code: str, lang: str = "en") -> None: ...


def _texts(code: str, lang: str) -> tuple[str, str]:
    subject, body = TEXTS.get(lang if lang in TEXTS else "en")
    return subject.format(code=code), body.format(code=code)


class LogMailer:
    """Development/tests: keeps the mails in memory and logs that one was sent (never the code itself)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_code(self, email: str, code: str, lang: str = "en") -> None:
        subject, body = _texts(code, lang)
        self.sent.append((email, subject, body))
        log.info("login code for %s created (log mailer - not sent)", email)


class BrevoMailer:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise MailError("Brevo API key missing")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=15)

    def send_code(self, email: str, code: str, lang: str = "en") -> None:
        subject, body = _texts(code, lang)
        try:
            r = self.client.post(BREVO_URL, headers={"api-key": self.api_key, "accept": "application/json"},
                                 json={"sender": SENDER, "to": [{"email": email}], "subject": subject,
                                       "textContent": body, "tags": ["login-code"]})
        except httpx.HTTPError as e:
            raise MailError(f"mail service not reachable: {type(e).__name__}") from e
        if r.status_code >= 300:
            log.error("Brevo answered %s: %s", r.status_code, r.text[:300])
            raise MailError("the e-mail could not be sent - please try again later")
