"""Optionaler Zugangsschutz – für den Betrieb außerhalb des eigenen Heimnetzes.

- `API_KEY` gesetzt: `/v1/*` und `/api/*` verlangen `Authorization: Bearer <API_KEY>` (Home Assistant, Discord-Bot,
  Skripte) oder eine Dashboard-Anmeldung.
- `DASHBOARD_PASSWORD` gesetzt: Anmeldung im Dashboard mit diesem Passwort. Ohne eigenes Passwort meldet man sich mit
  dem API-Schlüssel an.
- Beides leer (Standard): alles offen wie bisher – gedacht fürs Heimnetz.

Die Anmeldung ist ein signiertes Cookie (HMAC, 30 Tage). Der Signaturschlüssel liegt in `data/session.key` und
enthält einen Fingerabdruck von Passwort und API-Schlüssel – ändert sich eins davon, sind alle Anmeldungen ungültig.
Offen bleiben `/health`, das Dashboard selbst (zeigt dann die Anmeldung) und `/api/auth/*`."""

import hashlib
import hmac
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings

COOKIE = "wn_session"
SESSION_SECONDS = 30 * 24 * 3600
PROTECTED = ("/v1/", "/api/")
OPEN = ("/api/auth/",)


def auth_required(settings: Settings) -> bool:
    return bool(settings.api_key or settings.dashboard_password)


def login_secret(settings: Settings) -> str:
    """Womit man sich im Dashboard anmeldet."""
    return settings.dashboard_password or settings.api_key


class SessionSigner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._key: bytes | None = None

    @property
    def path(self) -> Path:
        return self.settings.data_dir / "session.key"

    def _base_key(self) -> bytes:
        if self._key is None:
            try:
                self._key = bytes.fromhex(self.path.read_text().strip())
            except (OSError, ValueError):
                self._key = secrets.token_bytes(32)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(self._key.hex())
                try:
                    self.path.chmod(0o600)
                except OSError:
                    pass
        return self._key

    def _mac(self, expires: int) -> str:
        fingerprint = f"{self.settings.api_key}\0{self.settings.dashboard_password}".encode()
        key = hmac.new(self._base_key(), fingerprint, hashlib.sha256).digest()
        return hmac.new(key, str(expires).encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expires = int(time.time()) + SESSION_SECONDS
        return f"{expires}.{self._mac(expires)}"

    def valid(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        expires, mac = token.split(".", 1)
        if not expires.isdigit() or int(expires) < time.time():
            return False
        return hmac.compare_digest(mac, self._mac(int(expires)))


def check_secret(given: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def _cookie(scope: Scope, name: str) -> str | None:
    for part in _header(scope, b"cookie").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


def is_authenticated(scope: Scope, settings: Settings, signer: SessionSigner) -> bool:
    if not auth_required(settings):
        return True
    scheme, _, token = _header(scope, b"authorization").partition(" ")
    if scheme.lower() == "bearer" and settings.api_key and check_secret(token.strip(), settings.api_key):
        return True
    return signer.valid(_cookie(scope, COOKIE))


class AuthMiddleware:
    """Reines ASGI (kein BaseHTTPMiddleware), damit Server-Sent Events und Uploads ungepuffert durchlaufen."""

    def __init__(self, app: ASGIApp, settings: Settings, signer: SessionSigner):
        self.app = app
        self.settings = settings
        self.signer = signer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (scope["type"] != "http" or not path.startswith(PROTECTED) or path.startswith(OPEN)
                or is_authenticated(scope, self.settings, self.signer)):
            await self.app(scope, receive, send)
            return
        # Link aus BasaltNotes o. Ä. im Browser → zur Anmeldung, danach zurück
        if scope.get("method") == "GET" and "text/html" in _header(scope, b"accept"):
            query = scope.get("query_string", b"").decode()
            target = path + (f"?{query}" if query else "")
            response = RedirectResponse(f"/dashboard/?next={quote(target, safe='')}", status_code=303)
        else:
            response = JSONResponse({"error": {"message": "Anmeldung erforderlich (API-Schlüssel oder Dashboard-"
                                                          "Login).", "type": "AuthError"}},
                                    status_code=401, headers={"WWW-Authenticate": "Bearer"})
        await response(scope, receive, send)
