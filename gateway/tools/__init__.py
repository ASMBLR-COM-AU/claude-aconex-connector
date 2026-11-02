"""Shared plumbing for the gateway's menu of tools.

Every Aconex tool is registered through `read_tool`, which applies the
stage 3 controls (off switch, approved projects, audit log) before and after
the tool runs. A tool can't opt out.
"""

from __future__ import annotations

import functools
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from gateway.aconex import AconexClient, AconexError
from gateway.aconex.client import Refused
from gateway.guard import UNKNOWN_PERSON, AuditLog, Policy

DEFAULT_PER_MINUTE = 30

# Tells Claude (and the person approving tool use) that a tool only reads.
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
# The one tool that writes to Aconex (stage 8: saving an unsent draft). Marked
# as a write so Claude asks the person before using it.
WRITES_DRAFT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)

SWITCHED_OFF = "The Aconex gateway has been switched off by IT. Nothing was looked up."


class PersonLimit:
    """At most `per_minute` tool calls per person in any 60 seconds. Aconex's
    speed limit is shared by the whole company (and every other system it
    connects to Aconex), so one person, or a runaway chat, can't use it all up."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._calls: dict[str, deque] = {}

    @classmethod
    def from_env(cls) -> "PersonLimit":
        return cls(int(os.environ.get("PERSON_CALLS_PER_MINUTE", "") or DEFAULT_PER_MINUTE))

    def allow(self, person: str) -> bool:
        now = time.monotonic()
        calls = self._calls.setdefault(person, deque())
        while calls and calls[0] <= now - 60:
            calls.popleft()
        if len(calls) >= self.per_minute:
            return False
        calls.append(now)
        return True


@dataclass
class Gateway:
    aconex: AconexClient
    policy: Policy
    audit: AuditLog
    limiter: PersonLimit = field(default_factory=PersonLimit.from_env)


def current_person() -> str:
    """The signed-in person's email (stage 4), from the pass Claude presented."""
    token = get_access_token()
    return (token.subject if token and token.subject else UNKNOWN_PERSON)


def not_approved(project_id: str) -> str:
    return (f"Project {project_id} isn't switched on for the gateway. Ask IT to approve it, "
            "or use list_projects to see the projects that are.")


def read_tool(server: MCPServer, gw: Gateway, description: str,
              annotations: ToolAnnotations = READ_ONLY):
    """Register a tool behind the gateway's controls (read-only unless told
    otherwise)."""

    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(**kwargs):
            project = str(kwargs.get("project_id", "") or "").strip()
            person = current_person()
            started = time.monotonic()

            def audit(outcome: str, detail: str = "") -> None:
                gw.audit.record(person=person, tool=fn.__name__, project=project,
                                arguments=kwargs, outcome=outcome, detail=detail,
                                ms=int((time.monotonic() - started) * 1000))

            if gw.policy.switched_off:
                audit("blocked", "gateway switched off")
                raise ToolError(SWITCHED_OFF)
            if project and not gw.policy.project_allowed(project):
                audit("blocked", "project not approved")
                raise ToolError(not_approved(project))
            if not gw.limiter.allow(person):
                audit("blocked", "over the per-person limit")
                raise ToolError(f"That's more than {gw.limiter.per_minute} Aconex requests in a "
                                "minute from one person. Wait a minute, then try again.")
            try:
                result = await fn(**kwargs)
            except Refused as err:
                audit("blocked", f"refused at the outgoing check: {err}")
                raise ToolError(str(err)) from None
            except ToolError as err:
                audit("error", str(err))
                raise
            except AconexError as err:
                audit("error", str(err))
                raise ToolError(str(err)) from None
            except Exception as err:
                audit("crash", f"{type(err).__name__}: {err}")
                raise
            audit("ok")
            return result

        server.tool(description=description, annotations=annotations)(wrapper)
        return fn

    return decorate


def parse_when(value: str, what: str) -> datetime:
    """A date ('2026-11-01') or date-time from Claude, as UTC."""
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"{what} should be a date like 2026-11-01, not {value!r}.") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
