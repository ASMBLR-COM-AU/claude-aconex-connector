"""The Aconex Gateway: an MCP server that Claude connects to as a custom connector.

Stage 1 (skeleton): one harmless `ping` tool and a /health page. No Aconex
access and no secrets yet.
"""

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

VERSION = "0.1.0"


def build_server() -> MCPServer:
    server = MCPServer(
        name="aconex-gateway",
        version=VERSION,
        instructions="Gateway to Oracle Aconex. Stage 1: only a test tool is available.",
    )

    @server.tool(description="Check the gateway is reachable. Returns a short message.")
    def ping() -> str:
        return f"Aconex Gateway {VERSION} is running."

    @server.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": VERSION})

    return server


def allowed_hosts() -> list[str]:
    """Host names the gateway answers to. Anything else is refused, which
    blocks a class of browser attacks (DNS rebinding)."""
    hosts = ["localhost:*", "127.0.0.1:*"]
    public = os.environ.get("PUBLIC_HOST", "").strip()
    if public:
        hosts.append(public)
    return hosts


def build_app():
    return build_server().streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts()),
    )
