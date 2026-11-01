# Aconex Gateway: project plan

A small app that lets Claude work in Aconex safely. The app holds the Aconex
keys, gives Claude a fixed menu of actions, and checks every request. Claude
never sees the keys and can't do anything that isn't on the menu.

## How it works

```
Staff member ──(work login)──▶ Claude (Team or Enterprise)
                                   │  fixed menu only
                                   ▼
                          Aconex Gateway (on Fly.io)
                          • who is asking?
                          • is this on the menu?
                          • is this project allowed?
                          • filter mail to what this person is on
                          • write it in the audit log
                                   │  only the gateway holds the key
                                   ▼
                          Aconex (service account)
                                   ▲
                 person opens the draft in Aconex and presses Send
```

## Decisions so far

| Decision | Choice | Why |
|---|---|---|
| Where the code lives | This repo (private), separate from the skill | The code enforces the rules now, not Claude's instructions |
| Hosting | Fly.io | Simple, a few dollars a month, no AWS/Azure needed |
| Key storage | Fly secrets | Encrypted, free, built in. Only the running app can read them; they can't be read back out. Anyone who can deploy to the Fly app could get at them, so only IT gets deploy access |
| Aconex login | One service account | Simpler than per-person logins |
| Mail privacy | Gateway filters mail to what the person is on (From/To/Cc) before Claude sees it | Enforced by code, not by asking Claude nicely |
| Drafts | Saved by the service account, with the person's signature added. The person opens it and sends from their own account | Nothing is sent without a person pressing Send |
| Claude plans | Must work on both Team and Enterprise | Both let an owner add a custom connector that members sign into |
| Language | Python, reusing the logic from the existing Aconex skill | Already proven against the live Aconex API |
| Video | One video covering every stage | |

## Still to decide

- **Sign-in provider (stage 4).** How staff prove who they are. Likely the
  company's existing Microsoft 365 or Google Workspace login (free to use for
  sign-in), or a small service with a free tier.
- **Where the audit log is kept (stage 3).** Probably a small file database on
  Fly (costs cents a month).

## The stages

Each stage has one job and a "done when" test. A stage doesn't start until the
one before passes its test. Each stage gets its own folder, its own tests and a
short note. Earlier stages never depend on later ones.

Stages 1–4 are fully in our control. Stage 0 runs alongside them with the
Aconex administrator.

| Stage | What gets built | Done when (film this) |
|---|---|---|
| **0. Aconex checks** (parallel) | Aconex admin creates the service account and its API client | Confirmed: the service account can see company mail **through the API**; a colleague can open its draft and sending shows **their** name |
| **1. Skeleton** | This repo, plus a "hello" gateway deployed on Fly. Nothing secret | The Fly address answers. No keys anywhere |
| **2. Document tools** | Read-only menu: search register, revision history, document details, download, directory. Tested against a **fake** Aconex | Tests pass. No "call any API" option exists |
| **3. Logging, limits, off switch** | Audit log, rate limits, approved project list, kill switch | Every request appears in the log. Flipping the switch stops everything |
| **4. Sign-in** | Staff sign in through Claude's connector. Only approved people get in | Works on a Team account and an Enterprise account. A non-approved person is refused |
| **5. Real key** | Service account key goes into Fly secrets, pointed at a **test** Aconex project | Claude finds a real drawing. The key appears nowhere but Fly secrets |
| **6. Mail** | Mail search and open, filtered to the signed-in person | Person A sees their mail. "Show me B's mail" in any wording returns nothing. Bcc, group mail and forwards tested |
| **7. Drafts** | Save draft (preview, approve, save) with the person's signature | Person opens the draft and sends it. Aconex shows it came from them |
| **8. Pilot and attack test** | Nothing new. One project, a few users, fake "trick" emails | The tricks fail, the log makes sense, pilot users sign off |

**Rule:** the real Aconex key doesn't go onto Fly until sign-in (stage 4) is
working. Before that, the gateway only talks to a fake Aconex.

## Video notes

- Film each stage's "done when" test as it passes. That's the spine of the video.
- Keep a short diary per stage: what we decided and why, and anything that went wrong.
- Never show on screen: keys, Fly secrets, the gateway's address, or real
  project mail and drawings. Use the test Aconex project.

## Costs (rough)

- Fly.io: a few US dollars a month for one small always-on machine. Check
  https://fly.io/calculator before relying on this.
- Fly secrets: no extra charge.
- Claude: the company's existing Team or Enterprise plan.
