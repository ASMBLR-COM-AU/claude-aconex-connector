"""Run the gateway: python -m gateway"""

import logging
import os
import pwd

import uvicorn

from gateway.aconex.client import describe_keys
from gateway.server import build_app

RUN_AS = "gateway"


def drop_root() -> None:
    """On Fly the container starts as root so it can hand the storage volume
    (mounted root-owned) to the `gateway` user. It then switches to that user
    for good, before reading any setting or serving anything."""
    if os.getuid() != 0:
        return
    user = pwd.getpwnam(RUN_AS)
    db = os.environ.get("AUDIT_DB", "")
    folder = os.path.dirname(db)
    if folder and os.path.isdir(folder):
        os.chown(folder, user.pw_uid, user.pw_gid)
        if os.path.exists(db):
            os.chown(db, user.pw_uid, user.pw_gid)
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)


if __name__ == "__main__":
    drop_root()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("gateway").info("Aconex keys (shape only): %s", describe_keys())
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
