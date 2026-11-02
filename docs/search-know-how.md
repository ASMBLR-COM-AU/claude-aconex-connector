# Search know-how

How people who use Aconex every day actually find things, and where the
gateway builds that in. Each tip is either done automatically by the code,
taught in the tool's description (what Claude reads when it picks a tool), or
given as a hint when a search comes back empty. Each has a test.

## Documents

| Tip | Built in as | Test (`tests/test_stage2.py`) |
|---|---|---|
| **Text on the drawing:** anything printed on a drawing rather than in its title (a door number like 1DG203, a room, grid line, equipment tag) is found by putting it in the main search with "search file content" ticked | Automatic: if free words match no number or title, the gateway searches inside the files and says so. Also in the description, with the door number example | `test_door_number_is_found_on_the_drawing_automatically` |
| **Old revisions:** "show document history" returns superseded revisions; without it only current ones appear | Description, and a hint when nothing is found | `test_empty_search_explains_what_to_try` |
| **Created by:** filter by the company that created the document | A `created_by` filter, using the project's own "Created By" field from the register schema | `test_created_by_uses_the_projects_own_field` |
| **Status needs its ID:** a status name finds nothing; its ID works | Automatic: the gateway looks the name up | `test_search_register_builds_the_live_query` |
| **Each project names things differently:** discipline, type and status values | Description, and a hint pointing at `register_fields` | `test_unknown_status_lists_the_real_ones` |
| **Escape only quotes:** escaping anything else breaks matches | Automatic | `test_quotes_in_search_words_are_escaped` |

Confirmed against the real Aconex (2 Nov 2026): "Created By" is the search
field `author` and holds the company name (e.g. "Smart Drafting"); searching
inside files finds text printed on drawings ("N16" found 214 stair shop
drawings that have no N16 in their titles).

## Mail (to build in stage 7)

From the user, 2 November 2026:

- **Pick the box:** inbox or sent, as in Aconex.
- **Filter down by who:** the From column (the person), the From organisation,
  and the recipients. This is how to get closest to what the person asking
  actually means.
- **Filter by mail type** (RFI, Transmittal, General Correspondence...).
- **Free text** in the main search bar as well.

Built in stage 7 (`search_mail`): each is its own filter (box received/sent/all,
from_person, from_company, to_person, mail_type, status, mail_number,
since/until, words), explained in the tool's description, with hints when
nothing comes back. Confirmed live 2 Nov 2026: sender's company and sender
match on part of the name ("LVL", "Baysinger"); dates only match as
`[YYYYMMDD TO YYYYMMDD]`; mail types and statuses search by ID, so the gateway
looks the names up. Known from the Aconex
skill's live testing:

- There's no "since" filter: results are newest first and filtered as they come.
- Every recipient comes back in one list, each tagged To, Cc or Bcc.
- Mail types and reasons for issue differ per project (`mail-types`).
- Confidential mail is hidden from the service account.
