"""Stage 1 tests: the skeleton answers."""

import anyio
from mcp.client.client import Client
from starlette.testclient import TestClient

from gateway.server import build_app, build_server


def test_ping_is_on_the_menu():
    async def run():
        async with Client(build_server()) as client:
            tools = await client.list_tools()
            return [t.name for t in tools.tools]

    assert "ping" in anyio.run(run)


def test_ping_answers():
    async def run():
        async with Client(build_server()) as client:
            result = await client.call_tool("ping", {})
            return result.content[0].text

    assert "running" in anyio.run(run)


def test_health_page():
    with TestClient(build_app()) as http:
        response = http.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_host_is_refused():
    with TestClient(build_app(), base_url="http://evil.example") as http:
        response = http.post("/mcp", json={})
    assert response.status_code in (400, 403, 421)
