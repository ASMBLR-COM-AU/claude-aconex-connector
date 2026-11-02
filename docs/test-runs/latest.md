# Test run 2026-11-02 07:24 UTC
**23 of 23 passed.** Project 2013297249, reads-only.
| | Area | Check | Seconds | Result |
|---|---|---|---|---|
| ✅ | basics | gateway answers | 0.0 | {'result': 'Aconex Gateway 0.9.1 is running.'} |
| ✅ | basics | test project is listed and approved | 2.4 | 41 WARRS ROAD MARIBYRNONG; 0 other projects not approved |
| ✅ | basics | gateway's Aconex account | 0.0 | Aconex account found |
| ✅ | people | find Baysinger in the project directory | 0.6 | 1 found |
| ✅ | people | find people from ASMBLR | 0.2 | 3 people |
| ✅ | register | find drawing EL-CSH12 by number | 0.4 | EL-CSH12 rev 7: Precast Elevation |
| ✅ | register | its revision history | 0.2 | 2 revisions |
| ✅ | register | its details | 0.5 | details returned |
| ✅ | register | search inside drawings for reinforcement | 0.3 | 1124 documents, e.g. .Stairform Method statement 2014 |
| ✅ | register | register fields | 1.2 | fields |
| ✅ | register | documents changed in the last 90 days | 0.1 | since 2026-08-04 |
| ✅ | files | get the PDF of EL-CSH12 (link works once) | 1.1 | real PDF, 260 KB; second download refused |
| ✅ | mail | search all project mail | 0.5 | 10 mails; totals {'received': 10, 'sent': 8} |
| ✅ | mail | mail from Baysinger | 0.6 | 2 mails |
| ✅ | mail | mail from ASMBLR | 0.7 | 8 mails |
| ✅ | mail | open a mail, with its Aconex link | 0.8 | asmblr-TRANSMIT-000008: Transmittal Update |
| ✅ | mail | its thread | 0.5 | thread returned |
| ✅ | mail | mail types | 0.4 | 1 mail types |
| ✅ | drafts | preview a draft (nothing saved) | 1.0 | to Michael Baysinger (LVL Structures Group Pty Ltd); signature added; not saved |
| ✅ | safety | a project that isn't approved is refused | 0.0 | project 1 refused |
| ✅ | safety | save_draft refuses a made-up code | 0.0 | refused |
| ✅ | safety | the outgoing check refuses writes | 0.0 | send, draft (in test mode) and delete all refused before leaving |
| ✅ | live site | outside view | 0.1 | health says only ok; security headers present; /mcp needs sign-in |
