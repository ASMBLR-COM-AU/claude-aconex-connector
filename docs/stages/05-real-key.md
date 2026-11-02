# Stage 5: Real key

**Job:** connect the gateway to the real Aconex and check every tool against a
real project, read-only.

## Set-up (2 Nov 2026)

- **Aconex account:** a testing key (the Aconex skill's), signed in as the
  `revradar` bot in the ASMBLR organisation. It is an **organisation admin**:
  fine for testing, but production needs a plain account with only the
  permissions on the stage 0 list.
- **Test project:** 41 Warrs Road Maribyrnong (25WAR, ID 2013297249), approved
  in `fly.toml`. A real job, read only. 2,856 documents, 354 people.
- **Deferred security steps** (Fly tokens out of the build session, `main`
  protected): see PLAN.md. Must be done before go-live.

## What went wrong on the way in

1. **Keys pasted into Fly were "staged", not applied.** The Fly dashboard can
   save secrets without restarting the app; `fly secrets deploy` applies them.
   Added to the runbook.
2. **Keys in swapped boxes.** The skill's combined `id:secret` login went in the
   secret box and the Aconex username in the ID box. The gateway now recognises
   a combined login in either box, passes on Aconex's own reason for a refused
   login, and logs the *shape* of the keys at start-up (never the values).

## Results against the real project

| Tool | Result |
|---|---|
| `gateway_account` | ✅ |
| `list_projects` | ✅ (now shows every project name, marked approved or not) |
| `search_register` (words, status, discipline) | ✅ 359 For Construction structural |
| `search_register` inside files | ✅ "N16" matched no titles, so the gateway searched the drawings itself: 214 found |
| `search_register` `created_by` | ✅ after fix: field is `author`, holds the company ("Smart Drafting": 716) |
| `search_register` current drawings | ✅ |
| `revision_history` | ✅ |
| `document_details` | ✅ |
| `register_fields` | ✅ after fix (each field once) |
| `current_drawing_set_rule` | ✅ (raw codes for types and statuses; readable enough for now) |
| `document_event_log` | ✅ |
| `document_transmittals` | ✅ after fix (readable dates) |
| `saved_register_searches` | ✅ after fix (one entry per search) |
| `documents_changed_since` | ✅ after fix (reads Aconex's attribute-style rows) |
| `search_project_directory` | ✅ (other companies' emails are hidden by Aconex, as documented) |
| `get_person`, `get_company`, `search_aconex_directory` | ✅ |
| `list_mailing_groups` | ✅ (none on this project) |
| `list_project_fields` | ❌ 403 `API_NOT_AUTHORIZED_FOR_PROJECT`: needs an extra permission, even for an admin account |
| `get_logo` | ❌ 404 `URL_UNKNOWN`: the address in Oracle's guide doesn't exist |
| `related_document_changes` | ❌ Aconex's reply isn't JSON (was 406 before the fix) |

## Done when

- [x] Claude finds real drawings on the test project through the gateway.
- [x] The key appears nowhere but Fly secrets (start-up log shows only its shape).
- [x] Every stage 2 tool tried against the real project; fixes deployed and
      re-checked.
- [ ] Decide what to do with the three tools that don't work (see above).
