"""The gateway's only way to reach Aconex.

Deliberately narrow: it can GET, it can POST only to search endpoints on an
allowlist (Aconex runs some searches as POST), and it has exactly one write:
`save_draft`, which always asks Aconex for an unsent draft (`is_draft=true`
is fixed in the code). There is no way to send mail or change anything else.

Belt and braces: `check_outgoing` runs inside the HTTP client on every request
just before it leaves, and refuses anything that isn't a read, an allowlisted
search or an `is_draft=true` draft. A bug elsewhere can't get past it.

Everything about login and the live API's quirks is carried over from the
Aconex skill's script, which was checked against the live API in Oct 2026.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

DEFAULT_API_URL = "https://api.aconex.com/api"
DEFAULT_TOKEN_URL = "https://constructionandengineering.oraclecloud.com/auth/token"

ACCEPT_XML = "application/xml"
ACCEPT_JSON = "application/json"

TIMEOUT_S = 60
TOKEN_MARGIN_S = 120  # renew the token this long before Aconex says it expires

# Aconex allows 5 requests a second and 10 at once for the WHOLE company, shared
# with every other system that uses the API. The gateway takes less than that
# by default so it never crowds them out.
DEFAULT_PER_SECOND = 3.0
DEFAULT_AT_ONCE = 4
THROTTLE_WAITS_S = (5, 15)  # Aconex answers 503 while it's limiting requests

# POST endpoints that only search. Anything else is refused before it leaves
# the gateway. Patterns match the path after the API base URL.
SEARCH_ONLY_POSTS = (
    re.compile(r"^/projects/[^/]+/register/search$"),
)

# The only Aconex write: saving an UNSENT draft (a new mail or a reply).
DRAFT_POSTS = (
    re.compile(r"^/projects/[A-Za-z0-9_\-]{1,64}/mail$"),
    re.compile(r"^/projects/[A-Za-z0-9_\-]{1,64}/mail/[A-Za-z0-9_\-]{1,64}/reply$"),
)

_SEGMENT = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class Refused(Exception):
    """A request the gateway will never send. Deliberately not an AconexError,
    so nothing catches it by accident and carries on."""


def check_outgoing(request: httpx.Request, settings: "Settings") -> None:
    """The last check before ANY request leaves for Aconex, run by the HTTP
    client itself, so it covers every code path (including future ones).

    Allowed, and nothing else:
      - the login request to Aconex's sign-in server;
      - GET (reading);
      - POST to a search endpoint on the allowlist;
      - POST that saves a draft, and only with exactly `is_draft=true`.
    So no code in the gateway can send mail, even by mistake."""
    url = request.url
    method = request.method.upper()
    token_url = httpx.URL(settings.token_url)
    if method == "POST" and (url.scheme, url.host, url.path) == (token_url.scheme, token_url.host, token_url.path):
        return
    api = httpx.URL(settings.api_url)
    base = api.path.rstrip("/")
    if (url.scheme, url.host) != (api.scheme, api.host) or not url.path.startswith(base + "/"):
        raise Refused(f"The gateway only talks to Aconex. Refused {method} {url.host}.")
    path = url.path[len(base):]
    if method == "GET":
        return
    if method == "POST" and any(p.match(path) for p in SEARCH_ONLY_POSTS) and not url.query:
        return
    if (method == "POST" and any(p.match(path) for p in DRAFT_POSTS)
            and list(url.params.multi_items()) == [("is_draft", "true")]):
        return
    raise Refused(f"The gateway never sends {method} {path} to Aconex (only reads, searches "
                  "and unsent drafts are allowed).")


class AconexError(Exception):
    """A problem worth telling the person about, in plain words."""


class NotConnected(AconexError):
    pass


def seg(value: object, what: str = "ID") -> str:
    """One path segment from a caller-supplied ID. Only letters, digits, `_`
    and `-` are allowed, so an ID can never change which endpoint is called
    (no `/`, `..`, `?` or `#`)."""
    text = str(value).strip()
    if not _SEGMENT.match(text):
        raise AconexError(f"That doesn't look like a valid Aconex {what}: {text!r}.")
    return text


@dataclass(frozen=True)
class Settings:
    client_id: str = ""
    client_secret: str = ""
    api_url: str = DEFAULT_API_URL
    token_url: str = DEFAULT_TOKEN_URL
    per_second: float = DEFAULT_PER_SECOND
    at_once: int = DEFAULT_AT_ONCE
    throttle_waits: tuple = THROTTLE_WAITS_S

    @property
    def connected(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls) -> "Settings":
        client_id, client_secret = _value("ACONEX_CLIENT_ID"), _value("ACONEX_CLIENT_SECRET")
        combined = _value("ACONEX_CREDENTIALS_B64") or _value("ACONEX_USERBOUND_CLIENT_CREDENTIALS_B64")
        # The Aconex skill's keys can be one base64 value of "client_id:secret".
        # Use it when given on its own, or when it was pasted into either the ID
        # or the secret box (whatever is in the other box is then not part of
        # the login; it's usually the Aconex username from the same file).
        pair = (_decode_pair(client_id) or _decode_pair(client_secret)
                or (None if client_secret else _decode_pair(combined)))
        if pair:
            client_id, client_secret = pair
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            api_url=os.environ.get("ACONEX_API_URL", "").strip() or DEFAULT_API_URL,
            token_url=os.environ.get("ACONEX_TOKEN_URL", "").strip() or DEFAULT_TOKEN_URL,
            per_second=float(os.environ.get("ACONEX_PER_SECOND", "") or DEFAULT_PER_SECOND),
            at_once=int(os.environ.get("ACONEX_AT_ONCE", "") or DEFAULT_AT_ONCE),
        )


def describe_keys() -> str:
    """The shape of the Aconex keys in the environment, for diagnosing a
    refused login. Never includes the values."""
    parts = []
    for name in ("ACONEX_CLIENT_ID", "ACONEX_CLIENT_SECRET", "ACONEX_CREDENTIALS_B64",
                 "ACONEX_USERBOUND_CLIENT_CREDENTIALS_B64"):
        value = _value(name)
        if value:
            kind = "a combined id:secret login" if _decode_pair(value) else "a plain value"
            parts.append(f"{name}: {len(value)} characters, {kind}")
    settings = Settings.from_env()
    parts.append(f"login uses: client ID of {len(settings.client_id)} characters, "
                 f"secret of {len(settings.client_secret)} characters")
    return "; ".join(parts)


def _value(name: str) -> str:
    """A setting, without surrounding spaces or quotes pasted along with it."""
    return os.environ.get(name, "").strip().strip("'\"").strip()


def _decode_pair(value: str) -> tuple[str, str] | None:
    """(client_id, secret) from base64 of "client_id:secret", else None."""
    if not value:
        return None
    try:
        text = base64.b64decode(value + "=" * (-len(value) % 4), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    client_id, sep, secret = text.partition(":")
    return (client_id, secret) if sep and client_id and secret else None


class Pacer:
    """Queues requests so no more than `per_second` start each second and no
    more than `at_once` are in flight. Extra requests wait their turn rather
    than being refused."""

    def __init__(self, per_second: float, at_once: int):
        self._gap = 1.0 / per_second
        self._next = 0.0
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(at_once)

    @asynccontextmanager
    async def turn(self):
        async with self._slots:
            async with self._lock:
                now = time.monotonic()
                start = max(now, self._next)
                self._next = start + self._gap
            if start > now:
                await asyncio.sleep(start - now)
            yield


def _problem(response: httpx.Response, path: str) -> str:
    hint = {
        400: "Aconex didn't accept the request (for a search, check the filters)",
        403: "the gateway's Aconex account isn't allowed to see that (it may not "
             "be on that project, or lacks a permission)",
        404: "not found: check the project, document or other ID",
        503: "Aconex is busy or limiting requests: try again in a minute",
    }.get(response.status_code, "Aconex returned an error")
    detail = " ".join(response.text.split())[:200]
    return f"{hint}. HTTP {response.status_code} for {path}" + (f": {detail}" if detail else "")


class AconexClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        async def guard(request: httpx.Request) -> None:
            check_outgoing(request, settings)

        self._http = httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S,
                                       event_hooks={"request": [guard]}, follow_redirects=False)
        self._token: str | None = None
        self._token_expires = 0.0
        self._pacer = Pacer(settings.per_second, settings.at_once)

    # ── login ───────────────────────────────────────────────────────

    async def _login(self) -> None:
        if not self.settings.connected:
            raise NotConnected(
                "The gateway isn't connected to Aconex yet: no Aconex keys are set."
            )
        try:
            response = await self._http.post(
                self.settings.token_url,
                data={"grant_type": "client_credentials"},
                auth=(self.settings.client_id, self.settings.client_secret),
            )
        except httpx.HTTPError as err:
            raise AconexError(f"Couldn't reach the Aconex login server ({err}).") from None
        if response.status_code != 200:
            raise AconexError(
                f"Aconex refused the gateway's login (HTTP {response.status_code}"
                f"{_login_reason(response)}). Check the client ID and secret in Fly's "
                "secrets; the API client may also have been revoked or its secret rotated."
            )
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise AconexError("The Aconex login server sent back no access token.")
        self._token = token
        self._token_expires = time.monotonic() + float(body.get("expires_in", 3600)) - TOKEN_MARGIN_S

    async def _send(self, method: str, path: str, params: dict | None, accept: str,
                    json_body: dict | None = None, content: bytes | None = None,
                    content_type: str = "", retry_when_busy: bool = True) -> httpx.Response:
        url = self.settings.api_url + path
        logged_in_again = False
        waits = list(self.settings.throttle_waits) if retry_when_busy else []
        while True:
            if self._token is None or time.monotonic() >= self._token_expires:
                await self._login()
            try:
                headers = {"Authorization": f"Bearer {self._token}", "Accept": accept}
                if content_type:
                    headers["Content-Type"] = content_type
                async with self._pacer.turn():
                    response = await self._http.request(
                        method, url, params=params, json=json_body, content=content, headers=headers,
                    )
            except httpx.HTTPError as err:
                raise AconexError(f"Couldn't reach Aconex ({err}).") from None
            if response.status_code == 401 and not logged_in_again:
                logged_in_again, self._token = True, None
                continue
            if response.status_code == 503 and waits:
                await asyncio.sleep(waits.pop(0))
                continue
            if response.status_code >= 400:
                raise AconexError(_problem(response, path))
            return response

    # ── the only ways to ask Aconex for something ───────────────────

    async def get(self, path: str, params: dict | None = None, accept: str = ACCEPT_XML) -> httpx.Response:
        return await self._send("GET", path, params, accept)

    async def get_xml(self, path: str, params: dict | None = None, accept: str = ACCEPT_XML) -> ET.Element:
        return parse_xml((await self.get(path, params, accept)).content)

    async def get_json(self, path: str, params: dict | None = None, accept: str = ACCEPT_JSON):
        response = await self.get(path, params, accept)
        try:
            return response.json()
        except ValueError:
            raise AconexError("Aconex sent back something that isn't JSON.") from None

    async def get_file(self, path: str, params: dict | None = None,
                       max_bytes: int = 25 * 1024 * 1024) -> tuple[bytes, str]:
        """Download a file. Returns (content, file name). Aconex sends every
        file as application/octet-stream and percent-encodes the name (live)."""
        response = await self.get(path, params, accept="application/octet-stream")
        if len(response.content) > max_bytes:
            raise AconexError(f"That file is {len(response.content) // (1024 * 1024)} MB, over the "
                              f"gateway's {max_bytes // (1024 * 1024)} MB limit.")
        return response.content, file_name(response.headers.get("content-disposition", ""))

    async def search_post(self, path: str, body: dict, accept: str = ACCEPT_JSON) -> httpx.Response:
        """POST to an endpoint that only searches. Refuses any other path."""
        if not any(p.match(path) for p in SEARCH_ONLY_POSTS):
            raise AconexError(f"The gateway doesn't allow POST to {path}.")
        return await self._send("POST", path, None, accept, json_body=body)

    async def save_draft(self, project: str, body: bytes, boundary: str, reply_to: str = "") -> str:
        """The gateway's only write: save an UNSENT mail draft and return its
        mail ID. `is_draft=true` is fixed here and there is no way to send: a
        person opens the draft in Aconex and presses Send. Never repeated when
        Aconex is busy, so a draft can't be saved twice (live format: the
        Aconex skill, Oct 2026)."""
        path = f"/projects/{seg(project, 'project ID')}/mail"
        if reply_to:
            path += f"/{seg(reply_to, 'mail ID')}/reply"
        response = await self._send(
            "POST", path, {"is_draft": "true"}, "application/vnd.aconex.mail.v2+xml",
            content=body, content_type=f'multipart/mixed; boundary="{boundary}"',
            retry_when_busy=False)
        root = parse_xml(response.content)
        mail_id = (root.findtext("NewMailId") or "").strip()
        if root.get("sendStatus") != "Drafted" or not mail_id:
            raise AconexError(
                f"Aconex didn't confirm a draft (sendStatus={root.get('sendStatus') or 'none'}). "
                "Check Mail > Drafts and Mail > Sent in Aconex.")
        return mail_id

    async def aclose(self) -> None:
        await self._http.aclose()


def file_name(disposition: str) -> str:
    """The file name from a Content-Disposition header, decoded."""
    from urllib.parse import unquote

    star = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.I)
    plain = re.search(r'filename="?([^";]+)"?', disposition, re.I)
    found = star or plain
    name = unquote(found.group(1).strip().strip('"')) if found else ""
    return name.replace("/", "_").replace("\\", "_") or "document"


def _login_reason(response: httpx.Response) -> str:
    """Aconex's own reason for refusing a login (e.g. invalid_client). It never
    contains the keys."""
    try:
        body = response.json()
        reason = " ".join(str(body.get(k, "")) for k in ("error", "error_description")).strip()
    except ValueError:
        reason = " ".join(response.text.split())
    return f": {reason[:160]}" if reason else ""


def parse_xml(content: bytes) -> ET.Element:
    try:
        return ET.fromstring(content)
    except ET.ParseError as err:
        raise AconexError(f"Aconex sent back something that isn't XML ({err}).") from None
