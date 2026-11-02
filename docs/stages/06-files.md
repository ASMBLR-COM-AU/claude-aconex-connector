# Stage 6: Files

**Job:** on command, get the real file (the PDF, or a DWG on multi-file documents) from
Aconex to Claude, not a summary of it.

## How the Aconex skill did it

The skill's script ran on the same computer as Claude (Claude Code or Cowork),
saved the PDF into a folder, and Claude opened that file with its own PDF
reader. A connector runs elsewhere (on Fly), so the file has to come back
inside the tool's reply, or Claude has to fetch it from a link.

## What Claude's connectors accept (research, 2 Nov 2026)

- Claude's connector docs list text and image tool replies, up to about 150,000
  characters, within 4 minutes. PDFs aren't mentioned.
- Bug reports: claude.ai chat and Desktop rejected a PDF inside a tool reply
  (closed by Anthropic on 6 Oct 2026 as completed, with no detail); Claude Code
  saves it to a file and tells Claude where it is.

## The experiment

Two temporary tools, `test_pdf_in_reply` (the PDF inside the reply) and
`test_pdf_download_link` (a link: random, stored scrambled, 15 minutes, at
most 5 downloads, re-checked against the off switch and approvals when used).
Tried on EL-CSH12 rev 7 "Precast Elevation", 41 Warrs Road (261 KB).

| Claude surface | PDF inside the reply | Download link |
|---|---|---|
| Claude Code (cloud session, 2 Nov 2026) | ✅ saved as a file and read; byte-identical to the link's copy | ✅ Claude fetched it itself and read it |
| claude.ai chat (2 Nov 2026) | ❌ "Resources of type 'application/pdf' are not currently supported" | ⚠️ Claude's workspace is blocked from fly.dev (403); its web fetch gets the text only |
| claude.ai chat, after adding `aconex-gateway.fly.dev` to the organisation's allowed domains (2 Nov 2026) | ❌ (unchanged) | ✅ Claude's workspace downloaded the real PDF (`%PDF-1.6`, 267 KB) and read every reinforcement note |
| Cowork | not tested | not tested |

Claude Code read the drawing correctly: title block (EL-CSH12 rev 7, SmartDrafting
for Hamilton Marino Builders, "Approval – not for construction"), columns
C122–C132 on grids 2, K, 5 and 6, levels Basement 1 (RL 32.300) to Roof
(RL 67.950).

## Pictures of pages (tried, not used)

A third test tool drew a page as a picture. claude.ai showed it, and Claude
could read the title block, levels and main dimensions, but not the small
reinforcement notes at full-sheet size. Lachie's call: pictures won't cut it,
the real PDF is needed.

Also learned: on these drawings the notes are drawn by AutoCAD as lines, not
stored as text, so pulling text out of the PDF finds almost nothing. Claude
has to look at the real PDF at high resolution, in its own workspace.

## The result: one tool, `get_document_file`

- Takes a **document number** (current revision, or a named `revision`) or a
  document ID from a search, and optionally a `file_name` for one file of a
  multi-file document (e.g. the DWG).
- Returns a **download link**: random, stored scrambled, tied to the file and
  the person, 15 minutes, at most 5 downloads, re-checked against the off
  switch and approvals when used, every download logged.
- Its description tells Claude to download it into its workspace and **give
  the person the file in the chat**, and to open it at high resolution to read
  it. If the workspace can't reach the gateway, Claude gives the person the link.
- **claude.ai needs two organisation settings** (see the runbook): code
  execution on, and `aconex-gateway.fly.dev` on the allowed domains.
- The three test tools and the picture libraries are removed.

## Done when

- [x] claude.ai: Claude gets the real PDF and reads it (2 Nov 2026).
- [x] Claude Code: Claude gets the real PDF and reads it (2 Nov 2026).
- [x] Tests: by number, by older revision, by ID, another file of the document,
      unknown number explained, unapproved project gets no link, link limits,
      re-checks when used, stored scrambled (11 tests, 89 total).
- [ ] Live: "get me the PDF of EL-CSH12" in claude.ai puts the file in the chat.

## Scope

Register documents only. Mail attachments move to stage 7 (they must respect
the per-person mail filter); package and workflow files to stage 9.
