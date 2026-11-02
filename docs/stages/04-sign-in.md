# Stage 4: Sign-in

**Job:** only approved people can use the gateway, each signing in with their
company account, and every request records who made it.

## How it works

The gateway runs its own sign-in for Claude and hands the "who are you" step
to the company's sign-in service:

1. In Claude, the person clicks **Connect** on the gateway connector.
2. Claude asks the gateway where to sign in, registers itself, and sends the
   person to the gateway, which sends them on to Google (or Microsoft).
3. They log in as usual. Google sends them back with proof of their email.
4. The gateway checks the email is approved and gives Claude a pass that only
   works for this gateway.

Why this design (rather than Claude signing in with Google directly): Google
doesn't support what Claude needs for direct sign-in, the same code works for
Google and Microsoft, and the gateway learns each person's verified email for
the audit log and, in stage 7, the mail filter.

## What was built

- `gateway/signin.py`: the hand-off to Google or Microsoft (OpenID Connect,
  with PKCE), the approved-people check, and the gateway's own passes. The
  standard sign-in endpoints come from the MCP library.
- `gateway/guard.py`: `ALLOWED_EMAILS` and `ALLOWED_DOMAINS`. Empty means nobody.
- Every request now needs a pass, except `/health`. The audit log records the
  signed-in email, and every sign-in attempt (allowed or refused).
- `docs/runbook.md`: approving people, setting up Google and Microsoft, adding
  the gateway to Claude.

## Safety details

- **Passes last an hour** and renew automatically for two weeks. Each renewal
  retires the old pass (a stolen old one stops working).
- **Passes are stored scrambled** (as hashes), so a copy of the database can't
  be used to sign in.
- **Removing someone** from the approved list cuts them off at their next
  request once that change is deployed. Their pass can't be renewed.
- **Only Claude can register:** the gateway only sends people back to Claude's
  own sign-in address (and to Claude Code on the person's own computer).
- **Unverified emails are refused**, as are identities meant for another app.
- The ID token's signature isn't checked: it comes straight from Google over
  HTTPS in exchange for the gateway's secret, which the OpenID Connect standard
  accepts instead. Issuer, audience, expiry and a one-time value are checked.

## Done when

- [x] Tests (14 new, 74 total): a full sign-in run the way Claude does it;
      refused when not approved, unverified, or for another app; only Claude
      can register; renewals retire old passes; removal cuts off; passes stored
      scrambled; `/health` stays public.
- [ ] Live with Google: Lachie connects from Claude and the audit log shows
      `lachie@asmblr.com.au` (needs the Google setup in the runbook).
- [ ] Works when added on a Claude **Team** account and an **Enterprise** account.
- [ ] Someone not approved is refused (live).

## Not done yet

- Microsoft sign-in is built but untested: needs a Microsoft tenant.
- Claude's newer "published identity" (CIMD) option isn't supported by the MCP
  library yet, so the connector uses "Register automatically". Each connection
  adds a small registration record; tidy-up can come later if it grows.

## For the video

Show clicking Connect in Claude, the Google login, and the audit log line with
the real email. Then show a non-approved account being refused.
