"""Set up the Aconex Connector for a new company, in that company's own Fly account.

    python3 scripts/new_company.py

Asks a few questions, then writes a folder deploy-<company>/ with:
  fly.toml       the company's gateway settings (no keys: those go into Fly
                 secrets with scripts/set-keys.sh, typed by the company's IT)
  testrun.json   facts from the company's test project, for scripts/test-run.sh
  SETUP.md       the setup checklist with the company's own addresses filled in

Nothing is created in Fly, Aconex, Google, Microsoft or Claude by this script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "deploy" / "fly.template.toml"
CHECKLIST = ROOT / "deploy" / "SETUP.template.md"

GOOGLE = "https://accounts.google.com"
ACONEX_SITES = {"au1": "Australia", "us1": "United States", "uk1": "United Kingdom",
                "ca1": "Canada", "mea": "Middle East", "hk1": "Asia (Hong Kong)",
                "cn1": "China", "ksa1": "Saudi Arabia"}
FLY_REGIONS = {"syd": "Sydney", "sin": "Singapore", "lhr": "London", "iad": "Virginia",
               "lax": "Los Angeles", "yyz": "Toronto", "fra": "Frankfurt"}

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
APP = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
EMAIL = re.compile(r"^[^@\s,]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
DOMAIN = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
PROJECT = re.compile(r"^\d{4,20}$")
TENANT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class SetupError(ValueError):
    """A setting that can't be right; the message says why."""


def split(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,\s]+", text or "") if part.strip()]


def settings(company: str, projects: str, emails: str = "", domains: str = "",
             signin: str = "google", tenant: str = "", aconex_site: str = "au1",
             region: str = "syd", app: str = "") -> dict:
    """Checks every answer and returns the values for the template."""
    slug = company.strip().lower()
    if not SLUG.match(slug):
        raise SetupError("Company short name: 3 to 32 lowercase letters, digits or dashes, "
                         "e.g. 'smith-builders'.")
    app = (app or f"aconex-gateway-{slug}").strip().lower()
    if not APP.match(app):
        raise SetupError(f"Fly app name {app!r}: lowercase letters, digits or dashes only.")

    project_ids = split(projects)
    if not project_ids or not all(PROJECT.match(p) for p in project_ids):
        raise SetupError("Projects: one or more Aconex project IDs (numbers), comma-separated. "
                         "Start with ONE test project.")
    email_list = [e.lower() for e in split(emails)]
    domain_list = [d.lower().lstrip("@") for d in split(domains)]
    if bad := [e for e in email_list if not EMAIL.match(e)]:
        raise SetupError(f"Not an email address: {', '.join(bad)}")
    if bad := [d for d in domain_list if not DOMAIN.match(d)]:
        raise SetupError(f"Not a domain: {', '.join(bad)}")
    if not email_list and not domain_list:
        raise SetupError("Approve at least one person (an email) or a whole domain. "
                         "Start with a few named people for the pilot.")
    if any(d in ("gmail.com", "googlemail.com", "outlook.com", "hotmail.com") for d in domain_list):
        raise SetupError("Approving a public email domain would let anyone in. "
                         "Approve the company's own domain or named emails.")

    signin = signin.strip().lower()
    if signin == "google":
        issuer = GOOGLE
    elif signin == "microsoft":
        if not TENANT.match(tenant.strip()):
            raise SetupError("Microsoft sign-in needs the company's tenant ID (a GUID like "
                             "0a1b2c3d-...). It's on the Entra admin centre's overview page.")
        issuer = f"https://login.microsoftonline.com/{tenant.strip().lower()}/v2.0"
    else:
        raise SetupError("Sign-in: 'google' or 'microsoft'.")

    if aconex_site not in ACONEX_SITES:
        raise SetupError(f"Aconex site: one of {', '.join(ACONEX_SITES)} (the start of the "
                         "company's Aconex web address, e.g. au1 for au1.aconex.com).")
    if region not in FLY_REGIONS:
        raise SetupError(f"Fly region: one of {', '.join(FLY_REGIONS)}.")

    return {
        "slug": slug, "app": app, "region": region,
        "projects": ",".join(project_ids), "projects_note": "",
        "emails": ",".join(email_list), "domains": ",".join(domain_list),
        "issuer": issuer, "signin": signin,
        "aconex_web": f"https://{aconex_site}.aconex.com",
        "public_url": f"https://{app}.fly.dev",
    }


def render(values: dict) -> dict[str, str]:
    """The files for deploy-<company>/, as {name: text}."""
    fly = TEMPLATE.read_text(encoding="utf-8").format(**values)
    checklist = CHECKLIST.read_text(encoding="utf-8")
    for key, value in values.items():
        checklist = checklist.replace("{" + key + "}", str(value))
    signin_steps = "google" if values["signin"] == "google" else "microsoft"
    checklist = re.sub(r"<!-- if (google|microsoft) -->(.*?)<!-- end -->",
                       lambda m: m.group(2) if m.group(1) == signin_steps else "",
                       checklist, flags=re.S)
    facts = {"project": values["projects"].split(",")[0],
             "drawing": "FILL IN: a drawing number on the test project, e.g. A-1001",
             "drawing_title_word": "FILL IN: one word from that drawing's title",
             "words_inside_files": "FILL IN: a word printed inside documents but not in their titles",
             "person": "FILL IN: a surname in the project directory",
             "company": "FILL IN: the company's name as Aconex shows it"}
    return {"fly.toml": fly, "SETUP.md": checklist, "testrun.json": json.dumps(facts, indent=2) + "\n"}


def ask(question: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    return input(f"{question}{shown}: ").strip() or default


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="folder to write (default deploy-<company>)")
    args = parser.parse_args()

    print("Aconex Connector: new company setup. Nothing is created yet; this writes a folder.\n")
    while True:
        try:
            company = ask("Company short name (e.g. smith-builders)")
            projects = ask("Aconex project ID(s) to approve (start with one test project)")
            emails = ask("Approved people's emails (comma-separated)")
            domains = ask("Or approve whole email domains (optional, e.g. smithbuilders.com.au)")
            signin = ask("Sign-in: google or microsoft", "microsoft")
            tenant = ask("Microsoft tenant ID") if signin.lower() == "microsoft" else ""
            site = ask(f"Aconex site ({'/'.join(ACONEX_SITES)})", "au1")
            region = ask(f"Fly region ({'/'.join(FLY_REGIONS)})", "syd")
            values = settings(company, projects, emails, domains, signin, tenant, site, region)
            break
        except SetupError as err:
            print(f"\n  ✗ {err}\n  Let's try again.\n")
        except (EOFError, KeyboardInterrupt):
            print("\nStopped. Nothing was written.")
            return 1

    out = Path(args.out or f"deploy-{values['slug']}")
    if out.exists():
        print(f"{out}/ already exists. Move it or choose --out, then run again.")
        return 1
    out.mkdir(parents=True)
    for name, text in render(values).items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"\nWritten to {out}/:\n  fly.toml, testrun.json, SETUP.md\n"
          f"Next: open {out}/SETUP.md and work through it with the company's IT person.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
