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
| Aconex login | One service account (re-confirmed 2 Nov 2026, after learning Aconex also supports per-person sign-in) | Simpler than per-person logins |
| Feature scope | [docs/features.md](docs/features.md): 46 features now, 9 later, the rest ruled out | Chosen from every feature in Oracle's Aconex API guides |
| Mail scope | Whole project: anyone approved can search all project mail the gateway's account can see (changed 2 Nov 2026; was "only mail the person is on"). Confidential mail stays hidden. Every search and mail opened is logged under the person | Tracing the history of an issue needs everything, not just one person's mail |
| Rate limit | Gateway queues requests to stay under Aconex's 5 a second, 10 at once | That limit is shared by the whole company |
| Drafts | Saved by the service account, with the person's signature added. The person opens it and sends from their own account | Nothing is sent without a person pressing Send |
| Claude plans | Must work on both Team and Enterprise | Both let an owner add a custom connector that members sign into |
| Language | Python, reusing the logic from the existing Aconex skill | Already proven against the live Aconex API |
| Video | One video covering every stage | |

## Still to decide

- Nothing open right now. Sign-in (stage 4) uses Google Workspace for testing
  and supports Microsoft Entra ID by settings alone.

## The stages

Each stage has one job and a "done when" test. A stage doesn't start until the
one before passes its test. Each stage gets its own folder, its own tests and a
short note. Earlier stages never depend on later ones.

Stages 1–4 are fully in our control. Stage 0 runs alongside them with the
Aconex administrator. Feature names below match [docs/features.md](docs/features.md).

| Stage | What gets built | Done when (film this) |
|---|---|---|
| **0. Aconex checks** (parallel) | Aconex admin creates the service account and API client, with these permissions: search organisation mail, Global Directory, create mail (for drafts). Oracle service request for the activity log, if we keep it | Confirmed: the service account can search company mail **through the API**; a colleague can open its draft, and sending shows **their** name |
| **1. Skeleton** ✅ | This repo, plus a "hello" gateway deployed on Fly. Nothing secret | The Fly address answers. No keys anywhere |
| **2. Projects, people and register** ✅ | Read-only tools for projects, directory, companies, mailing groups, custom fields, logos, register search, revisions, details, drawings, content search, event log, transmittals, saved searches, changes since a date, related documents. Tested against a **fake** Aconex. No file downloads yet | Tests pass. Every tool is read-only. No "call any API" option exists |
| **3. Logging, limits, off switch** ✅ | Audit log, request queue (5 a second), approved project list, kill switch | Every request appears in the log. A burst of requests is queued, not refused. Flipping the switch stops everything |
| **4. Sign-in** ✅ (Team; Enterprise still to try) | Staff sign in through Claude's connector. Only approved people get in | Works on a Team account and an Enterprise account. A non-approved person is refused |
| **5. Real key** ✅ (testing key, test project) | Service account key goes into Fly secrets, pointed at a **test** Aconex project | Claude finds a real drawing. The key appears nowhere but Fly secrets |
| **6. Files** ✅ (register documents; mail attachments in 7, package and workflow files in 9) | Downloads: documents (choosing PDF or DWG), mail attachments and their markups, package attachments, workflow files. Includes deciding how a file reaches Claude through the connector | Claude reads a real drawing's contents. A file can only be fetched by the person who asked for it |
| **7. Mail** ✅ (claude.ai check to do) | Mail search across the whole project (inbox, sent or everything; filters for sender, sender's company, recipient, type, words), open a mail, its thread, attachments as real files, types, saved searches, what's new | Claude traces the history of an issue across the project's mail on the test project |
| **8. Drafts** | Save and update drafts (preview, approve, save) with the person's signature | Person opens the draft and sends it. Aconex shows it came from them |
| **9. Reviews and packages** | Workflows, workflow files, deliverable reviews, review issues, package reviews, packages | Claude answers "what's overdue for review on this job?" correctly against the test project |
| **10. Field** | Defects, checklists, daily reports, safety observations, areas and subcontractors (read only) | Claude summarises open defects for an area correctly |
| **11. Audit trail** | Aconex's company-wide activity log, if we keep it (see open question 1 in features.md) | Only the people allowed to see it can |
| **12. Pilot and attack test** | Nothing new. One project, a few users, fake "trick" emails | The tricks fail, the log makes sense, pilot users sign off |

**Later:** inspection and test plans, models (BIM), supplier documents,
document markups.

**Rule:** the real Aconex key doesn't go onto Fly until sign-in (stage 4) is
working. Before that, the gateway only talks to a fake Aconex.

**Deferred for testing (decided 2 Nov 2026), must be done before anyone other
than Lachie uses the gateway or a production key goes in:**

1. Remove the Fly tokens from the Claude build environment, so the session
   that writes code can't also deploy (and so read the Aconex key).
2. Protect `main` on GitHub so every change needs Lachie's approval before
   GitHub deploys it.

Until then, the Aconex key used is a testing key on a test project.

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
