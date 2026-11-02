"""Stage 3: the gateway's controls, applied to every tool call.

- Audit log: who asked for what, on which project, and how it went. Kept in a
  small database file (on an encrypted Fly volume) and echoed to Fly's logs.
- Approved projects: tools only work on projects IT has switched on.
- Off switch: one setting turns every tool off.

All three are read from the environment when the gateway starts, so they are
changed with `fly secrets set` (see docs/runbook.md), not by anything Claude
can reach.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("gateway.audit")

UNKNOWN_PERSON = "unknown (sign-in arrives in stage 4)"
MAX_ARGUMENTS_CHARS = 1000


@dataclass(frozen=True)
class Policy:
    allowed_projects: frozenset[str] = field(default_factory=frozenset)
    switched_off: bool = False

    @classmethod
    def from_env(cls) -> "Policy":
        raw = os.environ.get("ALLOWED_PROJECTS", "")
        projects = frozenset(p.strip() for p in raw.split(",") if p.strip())
        off = os.environ.get("GATEWAY_OFF", "").strip().lower() in ("1", "true", "yes", "on")
        return cls(allowed_projects=projects, switched_off=off)

    def project_allowed(self, project_id: str) -> bool:
        return str(project_id).strip() in self.allowed_projects


class AuditLog:
    """One row per tool call. Writes are tiny, so plain sqlite is enough."""

    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS calls (
                    id INTEGER PRIMARY KEY,
                    at TEXT NOT NULL,
                    person TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    project TEXT,
                    arguments TEXT,
                    outcome TEXT NOT NULL,
                    detail TEXT,
                    ms INTEGER
                )"""
            )

    @classmethod
    def from_env(cls) -> "AuditLog":
        return cls(os.environ.get("AUDIT_DB", "audit.db"))

    def record(self, *, person: str, tool: str, project: str, arguments: dict,
               outcome: str, detail: str = "", ms: int = 0) -> None:
        row = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "person": person,
            "tool": tool,
            "project": project or None,
            "arguments": json.dumps(arguments, default=str)[:MAX_ARGUMENTS_CHARS],
            "outcome": outcome,
            "detail": detail[:500],
            "ms": ms,
        }
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO calls (at, person, tool, project, arguments, outcome, detail, ms) "
                "VALUES (:at, :person, :tool, :project, :arguments, :outcome, :detail, :ms)", row)
        log.info(json.dumps({"audit": row}))

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            cursor = self._db.execute(
                "SELECT at, person, tool, project, arguments, outcome, detail, ms "
                "FROM calls ORDER BY id DESC LIMIT ?", (limit,))
            names = [c[0] for c in cursor.description]
            return [dict(zip(names, r)) for r in cursor.fetchall()]


def main() -> None:
    """Print the latest calls: `python -m gateway.guard [how many]`.
    On Fly: `fly ssh console -C "python -m gateway.guard 50"`."""
    import sys

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    for row in reversed(AuditLog.from_env().recent(limit)):
        print(f"{row['at']}  {row['outcome']:<7}  {row['person']}  {row['tool']}"
              f"  project={row['project'] or '-'}  {row['ms']}ms  {row['arguments']}"
              + (f"  [{row['detail']}]" if row["detail"] else ""))


if __name__ == "__main__":
    main()
