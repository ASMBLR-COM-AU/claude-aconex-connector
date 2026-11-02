import pytest


@pytest.fixture(autouse=True)
def gateway_env(monkeypatch):
    """Every test: a throwaway audit log, two approved projects, gateway on."""
    monkeypatch.setenv("AUDIT_DB", ":memory:")
    monkeypatch.setenv("ALLOWED_PROJECTS", "1001,1002")
    monkeypatch.delenv("GATEWAY_OFF", raising=False)
