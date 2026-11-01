"""Run the gateway: python -m gateway"""

import os

import uvicorn

from gateway.server import build_app

if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
