# Stage 2: Projects, people and register

**Job:** give Claude read-only tools for projects, people and the document
register, tested against a fake Aconex. No real keys, no file downloads.

## What was built

- `gateway/aconex/client.py`: the gateway's only connection to Aconex. It can
  read (GET), and it can POST only to search endpoints on a short allowlist.
  There is no general "send anything" method. Every ID Claude passes in is
  checked (letters, digits, `_` and `-` only), so an ID can't redirect a
  request to a different part of Aconex.
- `gateway/tools/people.py`: 9 tools for projects, people and companies.
- `gateway/tools/register.py`: 10 tools for the document register.
- `tests/fake_aconex.py`: a fake Aconex that answers like the real one and
  records every request, so tests can prove what the gateway sends.

Every tool is marked read-only, which Claude shows to the person using it.

## The menu (17 tools after stage 5, plus `ping`)

| Tool | Feature in docs/features.md |
|---|---|
| `list_projects` | List my projects |
| `search_project_directory` | Search a project's directory |
| `get_person` | Look up a person (on a project, or Aconex-wide) |
| `gateway_account` | Look up a person ("who am I") |
| `list_mailing_groups` | See mailing groups and members |
| `search_aconex_directory` | Search the Aconex-wide directory |
| `get_company` | Look up a company |
| `list_project_fields` | See a project's custom fields |
| `search_register` | Search the register, search inside documents, current drawing set |
| `revision_history` | Revision history |
| `document_details` | Document details |
| `register_fields` | Register fields and allowed values |
| `current_drawing_set_rule` | Current drawing set |
| `document_event_log` | Document event log |
| `document_transmittals` | Which transmittals a document went out on |
| `saved_register_searches` | Use saved register searches |
| `documents_changed_since` | What's changed since a date |

## Done when

- [x] Tests pass (41): the menu is exactly the list above, every Aconex tool is
      marked read-only, nothing named like send/delete/upload/create exists,
      only GETs and the one allowlisted search POST reach Aconex, bad IDs never
      leave the gateway.
- [x] No "call any API" tool.
- [x] No keys anywhere.

## Found while building

- **Aconex can't list "everything related to this document".** Its Related
  Items API only checks one pair of documents or lists link changes over a
  date range, so `related_document_changes` does the date range.
- **The project directory:** Oracle's guide lists search filters, but the live
  API rejected them when the Aconex skill tested it. The gateway fetches the
  whole directory and filters it itself.

## To confirm against the real Aconex (stage 5)

These shapes come from Oracle's guides only. The tools return every field they
find rather than relying on exact names, but each needs a real check:

- Aconex-wide directory, person and company lookups, project custom fields
  (and whether a read-only account can read them)
- Mailing groups (JSON), logos
- Register schema field names, current drawing set rule, event log, saved
  searches
- `document_transmittals`: the search body names and the reply
- `documents_changed_since`: the date format Aconex expects
- `related_document_changes`: the reply format
- Inside-file search (`content_search`) and the "Created By" field's name
  (see docs/search-know-how.md)

Already checked live by the Aconex skill: login, projects, register search
(query syntax, paging, sorting, status IDs, history), document details, the
project directory.

## Added after stage 3: search know-how

Tips from daily Aconex use are now built into `search_register` (automatic
inside-file search when nothing matches, a `created_by` filter, hints when a
search is empty). See [docs/search-know-how.md](../search-know-how.md).

## For the video

Show the tool list in the test run, then the "only reads reach Aconex" test and
the bad-ID test. Explain the allowlist in the connection code: there is simply
no code path that writes.
