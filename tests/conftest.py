import pytest


@pytest.fixture(autouse=True)
def gateway_env(monkeypatch):
    """Every test: a throwaway audit log, two approved projects, gateway on."""
    monkeypatch.setenv("AUDIT_DB", ":memory:")
    monkeypatch.setenv("ALLOWED_PROJECTS", "1001,1002")
    monkeypatch.delenv("GATEWAY_OFF", raising=False)
    # Stage 1-3 tests talk to the tools directly; stage 4 tests turn sign-in on.
    monkeypatch.setenv("GATEWAY_NO_SIGNIN", "1")
