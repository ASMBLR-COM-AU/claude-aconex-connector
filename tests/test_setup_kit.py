"""The setup kit for a new company: scripts/new_company.py and scripts/set-keys.sh."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import new_company  # noqa: E402

GOOD = dict(company="smith-builders", projects="1234567", emails="Jo@Smith.com.au")


def test_our_own_settings_come_from_the_same_template():
    """Rendering the template with this gateway's values gives fly.toml exactly,
    so the template can't drift from what's proven live."""
    values = new_company.settings("asmblr", "2013297249", "lachie@asmblr.com.au", app="aconex-gateway")
    values["projects_note"] = "  # 41 Warrs Road Maribyrnong (25WAR), test project"
    rendered = new_company.render(values)["fly.toml"]
    assert rendered.split("\n", 2)[2] == (ROOT / "fly.toml").read_text()


def test_a_company_gets_its_own_app_and_address():
    files = new_company.render(new_company.settings(**GOOD))
    assert 'app = "aconex-gateway-smith-builders"' in files["fly.toml"]
    assert 'PUBLIC_HOST = "aconex-gateway-smith-builders.fly.dev"' in files["fly.toml"]
    assert 'ALLOWED_EMAILS = "jo@smith.com.au"' in files["fly.toml"]
    assert "SECRET" not in files["fly.toml"].replace("SIGNIN_CLIENT_SECRET are Fly secrets", "")


def test_checklist_is_filled_in_for_the_chosen_sign_in():
    google = new_company.render(new_company.settings(**GOOD))["SETUP.md"]
    assert "https://aconex-gateway-smith-builders.fly.dev/auth/callback" in google
    assert "Google Cloud" in google and "Entra" not in google
    microsoft = new_company.render(new_company.settings(
        **GOOD, signin="microsoft", tenant="0a1b2c3d-1111-2222-3333-444455556666"))
    assert "Entra" in microsoft["SETUP.md"] and "Google Cloud" not in microsoft["SETUP.md"]
    assert ("login.microsoftonline.com/0a1b2c3d-1111-2222-3333-444455556666/v2.0"
            in microsoft["fly.toml"])
    for text in (google, microsoft["SETUP.md"]):
        leftovers = [w for w in text.split() if w.startswith("{") and '"status"' not in w]
        assert not leftovers, leftovers


@pytest.mark.parametrize("change,message", [
    ({"company": "Smith Builders!"}, "short name"),
    ({"projects": ""}, "project IDs"),
    ({"projects": "1234567,abc"}, "project IDs"),
    ({"emails": "not-an-email"}, "Not an email"),
    ({"emails": "", "domains": ""}, "at least one person"),
    ({"emails": "", "domains": "gmail.com"}, "public email domain"),
    ({"signin": "microsoft"}, "tenant ID"),
    ({"signin": "okta"}, "google' or 'microsoft"),
    ({"aconex_site": "xx9"}, "Aconex site"),
])
def test_wrong_answers_are_refused_with_a_reason(change, message):
    with pytest.raises(new_company.SetupError, match=message):
        new_company.settings(**{**GOOD, **change})


def test_set_keys_sends_values_to_fly_and_never_shows_them(tmp_path):
    fake_fly = tmp_path / "fly"
    received = tmp_path / "received"
    fake_fly.write_text(f"#!/bin/sh\necho \"$@\" > {received}.args\ncat > {received}\n")
    fake_fly.chmod(fake_fly.stat().st_mode | stat.S_IEXEC)
    secrets = "aconex-id\naconex-secret-123\n  signin-id \nsignin-secret-456\n"
    result = subprocess.run([str(ROOT / "scripts" / "set-keys.sh"), "smith-app"], input=secrets,
                            capture_output=True, text=True,
                            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"})
    assert result.returncode == 0, result.stderr
    assert received.read_text() == ("ACONEX_CLIENT_ID=aconex-id\nACONEX_CLIENT_SECRET=aconex-secret-123\n"
                                     "SIGNIN_CLIENT_ID=signin-id\nSIGNIN_CLIENT_SECRET=signin-secret-456\n")
    assert "secrets import --stage -a smith-app" in (tmp_path / "received.args").read_text()
    for value in ("aconex-secret-123", "signin-secret-456", "aconex-id"):
        assert value not in result.stdout + result.stderr


# ── Early Access, Field, and adding jobs ────────────────────────────

import jobs  # noqa: E402


def test_live_sites_use_the_live_api_and_ea1_its_own():
    au = new_company.render(new_company.settings(**GOOD))
    assert 'ACONEX_API_URL = "https://api.aconex.com/api"' in au["fly.toml"]
    assert 'ENABLE_FIELD = "0"' in au["fly.toml"]
    assert "EA Lobby" not in au["SETUP.md"] and "see Field issues" not in au["SETUP.md"]
    ea = new_company.render(new_company.settings(**GOOD, aconex_site="ea1", field=True))
    assert 'ACONEX_WEB_URL = "https://ea1.aconex.com"' in ea["fly.toml"]
    assert 'ACONEX_API_URL = "https://ea1.aconex.com/api"' in ea["fly.toml"]
    assert 'ACONEX_TOKEN_URL = "https://constructionandengineering-ea.oraclecloud.com/auth/token"' in ea["fly.toml"]
    assert 'ENABLE_FIELD = "1"' in ea["fly.toml"]
    assert "EA Lobby" in ea["SETUP.md"] and "see Field issues" in ea["SETUP.md"]
    assert "<!--" not in ea["SETUP.md"]


def test_jobs_add_list_remove(tmp_path, capsys):
    folder = tmp_path / "deploy-smith"
    folder.mkdir()
    files = new_company.render(new_company.settings(**GOOD))
    (folder / "fly.toml").write_text(files["fly.toml"])
    assert jobs.main([str(folder), "add", "7654321"]) == 0
    assert 'ALLOWED_PROJECTS = "1234567,7654321"' in (folder / "fly.toml").read_text()
    assert "fly deploy" in capsys.readouterr().out
    assert jobs.main([str(folder), "add", "7654321"]) == 1          # already there
    assert jobs.main([str(folder), "add", "12; rm -rf"]) == 1       # not a project ID
    assert jobs.main([str(folder), "remove", "1234567"]) == 0
    assert 'ALLOWED_PROJECTS = "7654321"' in (folder / "fly.toml").read_text()
    capsys.readouterr()
    assert jobs.main([str(folder), "list"]) == 0
    assert capsys.readouterr().out.strip() == "7654321"


def test_jobs_keeps_the_note_after_the_projects(tmp_path):
    text = (ROOT / "fly.toml").read_text()
    assert jobs.change(text, "add", "1111111").count("test project") == 1
    assert 'ALLOWED_PROJECTS = "2013297249,1111111"  #' in jobs.change(text, "add", "1111111")
