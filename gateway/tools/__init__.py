"""Shared plumbing for the gateway's menu of tools."""

from __future__ import annotations

import functools
from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from gateway.aconex import AconexError

# Tells Claude (and the person approving tool use) that a tool only reads.
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


def read_tool(server: MCPServer, description: str):
    """Register a read-only tool. Aconex problems come back to Claude as a
    plain message rather than a crash."""

    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except AconexError as err:
                raise ToolError(str(err)) from None

        server.tool(description=description, annotations=READ_ONLY)(wrapper)
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
