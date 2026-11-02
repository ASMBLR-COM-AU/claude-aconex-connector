"""The gateway's only way to reach Aconex.

Deliberately narrow: it can GET, and it can POST only to search endpoints on
an allowlist (Aconex runs some searches as POST). There is no general "send
anything" method, so a tool can't write to Aconex by accident. Later stages
that need a write (drafts) add one specific, named method for it.

Everything about login and the live API's quirks is carried over from the
Aconex skill's script, which was checked against the live API in Oct 2026.
"""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

DEFAULT_API_URL = "https://api.aconex.com/api"
DEFAULT_TOKEN_URL = "https://constructionandengineering.oraclecloud.com/auth/token"

ACCEPT_XML = "application/xml"
ACCEPT_JSON = "application/json"

TIMEOUT_S = 60
TOKEN_MARGIN_S = 120  # renew the token this long before Aconex says it expires

# POST endpoints that only search. Anything else is refused before it leaves
# the gateway. Patterns match the path after the API base URL.
SEARCH_ONLY_POSTS = (
    re.compile(r"^/projects/[^/]+/register/search$"),
)

_SEGMENT = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


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

    @property
    def connected(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            client_id=os.environ.get("ACONEX_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("ACONEX_CLIENT_SECRET", "").strip(),
            api_url=os.environ.get("ACONEX_API_URL", "").strip() or DEFAULT_API_URL,
            token_url=os.environ.get("ACONEX_TOKEN_URL", "").strip() or DEFAULT_TOKEN_URL,
        )


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
        self._http = httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S)
        self._token: str | None = None
        self._token_expires = 0.0

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
                f"Aconex refused the gateway's login (HTTP {response.status_code}). "
                "The API client may have been revoked or its secret rotated."
            )
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise AconexError("The Aconex login server sent back no access token.")
        self._token = token
        self._token_expires = time.monotonic() + float(body.get("expires_in", 3600)) - TOKEN_MARGIN_S

    async def _send(self, method: str, path: str, params: dict | None, accept: str,
                    json_body: dict | None = None) -> httpx.Response:
        url = self.settings.api_url + path
        logged_in_again = False
        while True:
            if self._token is None or time.monotonic() >= self._token_expires:
                await self._login()
            try:
                response = await self._http.request(
                    method, url, params=params, json=json_body,
                    headers={"Authorization": f"Bearer {self._token}", "Accept": accept},
                )
            except httpx.HTTPError as err:
                raise AconexError(f"Couldn't reach Aconex ({err}).") from None
            if response.status_code == 401 and not logged_in_again:
                logged_in_again, self._token = True, None
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

    async def search_post(self, path: str, body: dict, accept: str = ACCEPT_JSON) -> httpx.Response:
        """POST to an endpoint that only searches. Refuses any other path."""
        if not any(p.match(path) for p in SEARCH_ONLY_POSTS):
            raise AconexError(f"The gateway doesn't allow POST to {path}.")
        return await self._send("POST", path, None, accept, json_body=body)

    async def aclose(self) -> None:
        await self._http.aclose()


def parse_xml(content: bytes) -> ET.Element:
    try:
        return ET.fromstring(content)
    except ET.ParseError as err:
        raise AconexError(f"Aconex sent back something that isn't XML ({err}).") from None
