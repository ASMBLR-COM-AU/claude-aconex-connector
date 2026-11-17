"""Approve or remove a job (an Aconex project) for one company's connector.

    python3 scripts/jobs.py deploy-smith-builders list
    python3 scripts/jobs.py deploy-smith-builders add 1234567890
    python3 scripts/jobs.py deploy-smith-builders remove 1234567890

Edits ALLOWED_PROJECTS in that folder's fly.toml and prints the one command
that puts the change live. Nothing changes in Fly or Aconex until that runs.
The connector's Aconex user must also be added to a new project in Aconex,
or the connector won't see it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LINE = re.compile(r'^(\s*ALLOWED_PROJECTS = ")([^"]*)(".*)$', re.M)
PROJECT = re.compile(r"^\d{4,20}$")


class JobsError(ValueError):
    pass


def config(folder: str) -> Path:
    path = Path(folder)
    path = path if path.name == "fly.toml" else path / "fly.toml"
    if not path.is_file():
        raise JobsError(f"No fly.toml in {folder}. Give the company's deploy folder, e.g. deploy-smith-builders.")
    return path


def current(text: str) -> list[str]:
    found = LINE.search(text)
    if not found:
        raise JobsError("This fly.toml has no ALLOWED_PROJECTS line.")
    return [p.strip() for p in found.group(2).split(",") if p.strip()]


def change(text: str, action: str, project: str) -> str:
    projects = current(text)
    if not PROJECT.match(project):
        raise JobsError(f"{project!r} isn't an Aconex project ID (a number, e.g. 1879048400).")
    if action == "add":
        if project in projects:
            raise JobsError(f"{project} is already approved.")
        projects.append(project)
    else:
        if project not in projects:
            raise JobsError(f"{project} isn't approved, so there's nothing to remove.")
        projects.remove(project)
    return LINE.sub(lambda m: m.group(1) + ",".join(projects) + m.group(3), text, count=1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", help="the company's deploy folder (or its fly.toml)")
    parser.add_argument("action", choices=["list", "add", "remove"])
    parser.add_argument("project", nargs="?", default="", help="Aconex project ID")
    args = parser.parse_args(argv)
    try:
        path = config(args.folder)
        text = path.read_text(encoding="utf-8")
        if args.action == "list":
            projects = current(text)
            print("\n".join(projects) if projects else "No jobs approved yet.")
            return 0
        if not args.project:
            raise JobsError(f"Which project? e.g. jobs.py {args.folder} {args.action} 1234567890")
        path.write_text(change(text, args.action, args.project.strip()), encoding="utf-8")
    except JobsError as err:
        print(f"✗ {err}", file=sys.stderr)
        return 1
    done = "approved" if args.action == "add" else "removed"
    print(f"✓ {args.project} {done} in {path}. Now approved: {', '.join(current(path.read_text())) or 'none'}.")
    print(f"To put it live:  fly deploy . --config {path.as_posix()} --ha=false --remote-only")
    if args.action == "add":
        print("And in Aconex: add the connector's user to that project, or it won't be visible.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
