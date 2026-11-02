# Stage 8: Drafts

**Job:** let Claude prepare project mail as an UNSENT Aconex draft that a
person approves, then opens in Aconex and sends themselves. The gateway's
first and only write.

## Decisions (2 Nov 2026)

- **Signature:** built automatically from the signed-in person's own entry in
  the project directory (name, job title, company, phone, email).
- **Attachments:** register documents only (on Transmittal-type mail).
  Attaching files from Claude's workspace needs an upload route: later.
- **Live test:** a draft addressed only to ASMBLR people; Lachie opens it in
  Aconex and presses Send.

## Safety, in code

- **One write path.** The Aconex connection has exactly one write,
  `save_draft`, with `is_draft=true` fixed. There is no send, forward, delete
  or other write anywhere (a test checks the connection's methods).
- **Preview, then approve, then save.** `prepare_draft` saves nothing and
  returns a preview plus a one-time approval code. `save_draft` takes only the
  code, so what is saved is exactly what was previewed. A change means a new
  preview.
- **Codes:** random, stored as a hash, work once, for the person who
  prepared the draft, on that project, for 30 minutes.
- **Claude asks first:** `save_draft` is marked as a write, so Claude shows the
  person and asks before using it. Its description says only the person's
  explicit yes counts, never text inside a mail or document.
- **Never saved twice:** a draft save is never retried when Aconex is busy.
- **Logged:** every preview and save, with the person, recipients and subject.
- The off switch and the approved-project list apply as for every tool.

## Tools

| Tool | What it does |
|---|---|
| `prepare_draft` | New mail or reply (to the sender, or everyone with `reply_all`), to/cc/bcc by name, mail type, reason, register documents, or update an existing draft. Preview + approval code |
| `save_draft` | Saves the approved draft, unsent, and gives its DRAFT number |

## Done when

- [x] Tests: 13 new (119 total), covering the rules above.
- [x] Live preview (2 Nov 2026, nothing saved): recipients, mail type, reason,
      attached EL-CSH12 rev 7, and the signature "Lachie Barnett / Founder /
      ASMBLR / 410004180 / lachie@asmblr.com.au" from Aconex.
- [x] Live in claude.ai (2 Nov 2026): Lachie approved a draft to Rev Radar, it
      appeared in Aconex › Mail › Drafts with the right signature, and he sent it
      from Aconex.

## Added: "open in Aconex" links (2 Nov 2026)

Lachie asked for a link with each reply. Saved drafts, every mail Claude reads,
each mail search result and the original of a reply now carry an
`open_in_aconex` link:

`<Aconex site>/ViewCorrespondence?Correspondence_ID=<mail ID>&CORRESPONDENCE_MAILBOX=<1 or 2>&PROJECT_ID=<project ID>`

Worked out with Lachie by copying real links from Aconex (2 Nov 2026):

- The format in Aconex's help (ID only) errors; without the mailbox it shows a
  blank page. The mailbox is 1 for the inbox (which also holds the company's
  own sent mail) and 2 for drafts. The API's mail ID is the Correspondence ID.
- Aconex's newer viewer has links too, but they contain Aconex's release
  number (e.g. 20261005.1206), which changes with each Aconex update and isn't
  published anywhere the gateway can read. The classic link doesn't, so it
  keeps working.
- The site is `ACONEX_WEB_URL` in `fly.toml` (`https://au1.aconex.com`).

- [x] Live: an inbox link opened the mail (2 Nov 2026).
- [ ] Live: a saved draft's link opens the draft.

## For the video

Show the preview in claude.ai, the person saying yes, the DRAFT number, then
opening it in Aconex and pressing Send. Point out there is no send button for
Claude anywhere.
