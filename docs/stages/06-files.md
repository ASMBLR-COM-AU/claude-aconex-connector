# Stage 6: Files

**Job:** get the real file (the PDF, or a DWG on multi-file documents) from
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
| claude.ai chat | to test | to test |
| Cowork | to test (optional) | to test (optional) |

Claude Code read the drawing correctly: title block (EL-CSH12 rev 7, SmartDrafting
for Hamilton Marino Builders, "Approval – not for construction"), columns
C122–C132 on grids 2, K, 5 and 6, levels Basement 1 (RL 32.300) to Roof
(RL 67.950).

## Scope

Register documents only. Mail attachments move to stage 7 (they must respect
the per-person mail filter); package and workflow files to stage 9.
