# Stage 7: Mail

**Job:** search and read the project's mail, across the whole project, with
the filters people use in Aconex, and get mail attachments as real files.

## Decisions

- **Whole project, not just the person's own mail** (Lachie, 2 Nov 2026), so
  Claude can trace the history of an issue. Everyone approved can read all
  project mail the gateway's account can see. Confidential mail stays hidden.
  Every search and every mail opened is logged under the person.
- **Search tips built in** (see docs/search-know-how.md): received or sent,
  sender's company, sender, recipient, mail type, status, mail number, dates,
  free words.

## Found against the real Aconex (2 Nov 2026), before building

- The account's mailboxes are **company-wide**: "Inbox" is all mail sent to
  ASMBLR on the project (Michael Baysinger's LVL transmittals included) and
  "Sentbox" all mail ASMBLR sent (including Lachie's). "All" combines both.
- In Aconex no company sees other companies' mail, so this *is* everything the
  company can see.
- Not available: an "all boxes" setting (quietly returns the inbox), the
  `mail/search` address in Oracle's guide (doesn't exist), and `effective_user`
  (ignored).
- Search fields that work: `fromtradingname` (partial), `fromuserfullname`
  (partial), `touserfullname`, `subject`, `docno`, plain words, `sentdate` only
  as `[YYYYMMDD TO YYYYMMDD]`, and type/status/reason by ID (Transmittal = 23).
  Not working: `corrdata` (body), `mailRecipients`, `hasAttachments`.

## The menu

| Tool | What it does |
|---|---|
| `search_mail` | Received, sent or all; filters above; newest first; each mail once |
| `read_mail` | Sender, To/Cc/Bcc, type, reason, status, body, attachments 50 at a time |
| `mail_thread` | The conversation a mail belongs to |
| `mail_fields` | Mail types, statuses, reasons, searchable fields |
| `saved_mail_searches` | Saved mail searches by name |
| `get_mail_attachment` | Any attachment as a real file, by the same 15-minute link as documents |

## Fixed after the first live run

- LSGP-TRANSMIT-000143 has **2,856 attachments** and takes ~50 seconds for
  Aconex to send. Attachments are now listed 50 at a time with a count.
- Mail status was being read from an attachment; now from the mail itself.
- "In reply to" only appears when it points at a different mail.
- The thread is asked for directly: 2.4 seconds instead of 52.
- Some attached drawings come from another company's register (no document
  ID); `get_mail_attachment` handles every kind.

## How live checks were run

Read-only checks ran inside the gateway's code with its key, on a separate
temporary Fly machine that removes itself afterwards. A first attempt ran on
the live machine and overloaded it (256 MB); it was restarted within minutes.
Lesson: never run checks on the live machine.

## Done when

- [x] Tests: whole-project search, every filter, paging, reading, thread,
      fields, saved searches, attachments as files, unapproved project
      refused (106 total).
- [x] Live (2 Nov 2026): search, filters, read, thread, fields and saved
      searches checked on 41 Warrs Road.
- [ ] Live in claude.ai: Claude traces the history of an issue across the
      project's mail and hands over an attachment as a file.

## For the video

Ask Claude in claude.ai: "What has LVL sent us on Warrs Road, and what's in
the latest transmittal?", then "get me S161 from that transmittal".
