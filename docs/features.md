# Feature scope

What the gateway will let Claude do in Aconex, chosen on 2 November 2026 from
every feature in Oracle's Aconex API guides (89 features, about 750 API calls).

- **45 need now, 9 later, 35 don't need** (mark read/unread dropped after review).
- **Login:** one service account (see PLAN.md).
- Anything not listed as "Need now" or "Later" is not built. If it's not on
  the gateway's menu, Claude can't do it.

Tags: *read only* never changes Aconex. *Changes things* writes to Aconex.
*Admin permission* means the service account needs an extra Aconex permission.

## Decisions on the open questions (2 Nov 2026)

1. **Audit trail:** admins only, not every user. To be confirmed at stage 11.
   Oracle has to switch it on through a service request.
2. **Mark mail read or unread:** dropped. With a service account it would
   change the service account's own read status, not the person's.
3. **Confidential mail:** not shown. The service account won't get the
   "view any confidential mail" permission.
4. **Project custom fields:** built in stage 2, then tested at stage 5 with a
   read-only account before granting any extra permission.

## Things to know

- **Aconex's own logs will show the service account**, not the person: for
  example a document's event log will say the service account downloaded it.
  The gateway's audit log records which person asked.
- **"Search my mail" and "Search all company mail, filtered to the person"
  become one tool** with a service account: search company mail, then keep only
  mail the person sent or received.
- **Rate limit:** Aconex allows 5 requests a second and 10 at once for the
  whole company. The gateway must queue requests.
- **Not possible in any Aconex API:** approving workflows, approving mail
  waiting for approval, completing tasks.

## Projects and people

**Need now**

- **List my projects** (read only): Every project the account can see, with address, dates and access level.
  - API: `GET /api/projects`
- **Search a project's directory** (read only): Find people and mailing groups on a project by name, company or job title.
  - API: `GET /api/projects/{id}/directory`
- **Look up a person** (read only): One person's contact and company details on a project.
  - API: `GET /api/projects/{id}/users/{userId}`; `GET /api/user (who am I)`
- **See mailing groups and members** (read only): Which people are in each project mailing group.
  - API: `GET /api/mailinggroups/{projectId}`; `GET /api/projects/{id}/groups/{groupId}`
- **Search the Aconex-wide directory** (read only, admin permission): Find people at other companies across all of Aconex. Needs the Global Directory permission.
  - API: `GET /api/directory`; `GET /api/users/{userId}`
- **Look up a company** (read only, admin permission): Another company's details.
  - API: `GET /api/organizations/{orgId}`
- **See a project's custom fields** (read only, admin permission): The extra fields a project has set up. Oddly, the docs say this needs the permission to create fields.
  - API: `GET /api/projects/{id}/projectField`
- **Project and company logos** (read only): Download logo images.
  - API: `GET /api/project/logo`; `GET /api/organization/logo`


## Document register

**Need now**

- **Search the register** (read only): Find documents by number, title, discipline, type or status. Current revisions by default.
  - API: `GET /api/projects/{id}/register`
- **Revision history** (read only): Every revision of a document, oldest to newest.
  - API: `GET /api/projects/{id}/register?show_document_history=true`
- **Document details** (read only): Every field recorded against one revision: author, status, review source, file type and so on.
  - API: `GET /api/projects/{id}/register/{docId}/metadata`
- **Current drawing set** (read only): Only the drawings in the project's current set, and the rule that defines it.
  - API: `GET /api/projects/{id}/drawings`; `GET /api/projects/{id}/currentSet`
- **Register fields and allowed values** (read only): Which fields the project uses and their allowed values. Claude uses this behind the scenes to search accurately.
  - API: `GET /api/projects/{id}/register/schema`; `GET …/projectfields/documenttype/{typeId}`
- **Search inside documents** (read only): Search the text inside files, not just titles and numbers.
  - API: `GET /api/projects/{id}/register?content_search=true`
- **Document event log** (read only): Who registered, viewed, downloaded or transmitted a document, and when.
  - API: `GET /api/projects/{id}/register/{docId}/eventlog`
- **Which transmittals a document went out on** (read only): The register's All Filters search, which can also show transmittal details.
  - API: `POST /api/projects/{id}/register/search (search only)`
- **Download a document** (read only): Get the file itself so Claude can read it or hand it to you. Each download is recorded in the document's event log.
  - API: `GET /api/projects/{id}/register/{docId}`
- **Choose which file (PDF, DWG…)** (read only): On projects with several files per document, pick a specific one.
  - API: `GET /api/projects/{id}/register/{docId}?fileName=…`
- **Use saved register searches** (read only): Run the saved searches people have set up in Aconex.
  - API: `GET /api/projects/{id}/documents/savedSearch`
- **What's changed since a date** (read only): Every document that changed since a given time, for summaries like "what's new this week".
  - API: `GET /api/projects/{id}/register/integrity`
- **See related documents** (read only): Documents linked to each other as related items, and the history of those links.
  - API: `GET …/document-relationships/…`; `GET …/document-relationships/projects/{id}/transactions`

**Later**

- **Download with markups** (read only): The document with its markups, as a PDF.
  - API: `GET /api/projects/{id}/register/{docId}/markedup`
- **Supplier documents status** (read only): Supplier documents with due and actual dates, days late, and submission and review status.
  - API: `GET /api/projects/{id}/supplierdocs`

**Don't need**

- **Register new documents** (changes things, permanent): Upload new documents into the register. Creates a permanent record; the API has no delete.
- **Upload a new revision** (changes things, permanent): Replace the current revision of a document with a new one.
- **Link or unlink related documents** (changes things): Create or remove related-item links between documents.


## Mail and transmittals

**Need now**

- **Search my mail** (read only): Find mail in the person's inbox, sent items or drafts, newest first.
  - API: `GET /api/projects/{id}/mail?mail_box=inbox|sentbox|draftbox`
- **Search all company mail, filtered to the person** (read only, admin permission): Needed for the service-account design: search everything (ALLBOX) and filter to mail the person is on. Needs the "search organisation mail" permission. Confidential mail stays hidden unless the account is on it.
  - API: `POST /api/projects/{id}/mail/search (mailBox=ALLBOX)`
- **Open a mail in full** (read only): Sender, To/Cc/Bcc, message, attachments and status. Doesn't mark it as read.
  - API: `GET /api/projects/{id}/mail/{mailId}`
- **See the whole conversation** (read only): The chain of replies and forwards a mail belongs to.
  - API: `GET /api/projects/{id}/mail/{threadId}/thread`
- **Mail types and fields** (read only): The project's mail types, reasons for issue and form fields. Claude uses these behind the scenes to search and draft correctly.
  - API: `GET …/mail/schema/search`; `GET …/mail/schema/creation`; `GET …/schema/reply`; `GET …/schema/forward`; `GET …/customfields/…/schema`; `GET …/restrictedfields/…/schema`
- **Download mail attachments** (read only): Get a file attached to a mail.
  - API: `GET /api/projects/{id}/mail/{mailId}/attachments/{attId}`
- **Download attachments with markups** (read only): The marked-up version of an attachment, as a PDF.
  - API: `GET …/attachments/{attId}/markedup`
- **Use saved mail searches** (read only): Run the saved mail searches people have set up in Aconex.
  - API: `GET /api/projects/{id}/mail/savedSearches`
- **What's new since a date** (read only): Mail that changed since a given time.
  - API: `GET /api/projects/{id}/mail/integrity`
- **Save a draft (new, reply or forward)** (changes things): Prepare mail as an unsent draft. A person opens it in Aconex and presses Send.
  - API: `POST /api/projects/{id}/mail?is_draft=true`; `POST …/mail/{mailId}/reply?is_draft=true`; `POST …/mail/{mailId}/forward?is_draft=true`
- **Update a saved draft** (changes things): Change a draft that's already saved, instead of making a new one.
  - API: `ExistingMailId on the draft calls above`

**Don't need**

- **Mark mail read or unread** (changes things): dropped 2 Nov 2026; only works on the service account's own mail.
- **Fax delivery log** (read only): Whether a mail sent by fax was delivered.
- **Delete drafts** (changes things, permanent): Permanently delete unsent drafts.
- **Send, reply or forward mail** (changes things, sends to others): Mail goes straight out to other companies. There's no recall in the API. The design rule so far is that Claude never sends.
- **Register mail on behalf of someone** (changes things, sends to others): Record a mail in Aconex as sent by another person in your company.


## Workflows and reviews

**Need now**

- **Find document review workflows** (read only): Workflows by status (current, overdue, complete…), started by you or others, assigned to you or others, or by number.
  - API: `GET /api/projects/{id}/workflows (+ status, initiated-by, assigned-to and number filters)`
- **Workflow supplementary files** (read only): List and download the extra files attached to a workflow.
  - API: `GET …/workflows/{wfId}/supplementary-files`; `…/download`; `…/bulk-download (ZIP)`
- **Deliverable reviews** (read only): Deliverables in review: who's reviewing, due dates, overdue steps and outcomes.
  - API: `POST /api/reviews/projects/{id}/deliverable/search`; `POST …/deliverable/reviewstep/search (search only)`
- **Review issues and comments** (read only): Issues raised during document review, with comments and responses.
  - API: `POST /api/reviews/projects/{id}/issue/search (search only)`; `GET …/issue-project-fields`
- **Package reviews** (read only): Package reviews and their steps: status, assignees, due dates, outcomes.
  - API: `POST …/package-reviews/search`; `POST …/package-reviews/reviewsteps/search`; `GET …/package-reviews/{id}/reviewsteps`

**Don't need**

- **Copy workflow templates to other projects** (changes things): Changes other projects' setup.


## My to-do list

**Don't need**

- **My to-do counts** (read only): Unread mail, overdue responses, mail awaiting approval, workflows awaiting review, supplier documents. With a service account these would be the service account's to-dos, not the person's.
- **My to-do list** (read only): The items behind those counts, 25 at a time.


## Packages

**Need now**

- **Look up packages** (read only): Packages, their versions, documents and status, linked mail and test plans, distribution list, schedule and transmittal history.
  - API: `GET /projects/{id}/packages (+ versions, mails, documents-status, distribution-list, transmittal-history, schedule, related-packages, test-plans)`; `POST /projects/{id}/packages/list (search only)`; `GET …/package-events`
- **Download package attachments** (read only): Get files attached to a package.
  - API: `GET …/packages/{pkgId}/attachments`; `GET …/attachments/{fileId}/file`

**Don't need**

- **Create or change packages** (changes things): Create and edit packages, close or reopen them, change collaborators and distribution lists, link mail and test plans, share attachments.
- **Send a package transmittal** (changes things, sends to others): Sends the package to its distribution list or chosen people.


## Field (site)

**Need now**

- **Read defects and issues** (read only): Issues by area, with counts, status, assignee, comments and photos.
  - API: `GET …/areas/{areaId}/issues (+ count, single issue, attachments)`; `GET …/issues/{issueId}/conversations`; `POST …/issues/filter (search only)`
- **Read inspection checklists** (read only): Checklists, their items, templates and PDF exports.
  - API: `GET …/areas/{areaId}/checklists (+ templates, attachments)`; `GET /api/checklists/{id}?format=pdf`; `GET …/templates`
- **Read daily reports** (read only): Daily site reports by date, company or status, and exports.
  - API: `GET …/daily-reports/filter`; `GET …/daily-reports/{id}`; `GET …/dailyreportbydate/{date}`; `GET …/daily-reports/{id}/export`
- **Read safety observations** (read only): Safety observations and their attachments.
  - API: `GET …/areas/{areaId}/observations`; `GET …/observations/meta-data`
- **Areas, issue types and subcontractors** (read only): The project's location tree, issue types, custom fields and subcontractor list.
  - API: `GET …/areas`; `GET …/issue_types`; `GET …/customfields`; `GET …/subcontractors`

**Don't need**

- **Raise or update issues** (changes things): Raise defects, change status or assignee (including closing them), attach photos.
- **Comment on an issue to another company** (changes things, sends to others): Posts in that company's thread on the issue.
- **Fill in or create checklists** (changes things): Create checklists, answer items, attach files.
- **Write and submit daily reports** (changes things): Create, edit and formally submit daily reports.
- **Record safety observations** (changes things): Create or edit safety observations.
- **Field setup** (changes things, admin permission): Subcontractors, Field directory invites, areas, issue types, templates and suggestion lists.


## Inspection and test plans

**Later**

- **Read test plans** (read only): ITPs, their activities, reviews, status history, linked documents and attachments, plus each person's to-do summary.
  - API: `GET /projects/{id}/test-plans (+ activities, reviews, eventlog, records/documents, attachments, homepage/summary)`
- **Plain-English ITP search** (read only): Aconex's own natural-language search over test plans, where enabled for the project.
  - API: `POST …/test-plans/natural-language-search (search only)`
- **Export ITPs as PDF** (read only): Export up to 5 test plans at a time.
  - API: `POST …/test-plans/export`
- **Progress and sign off ITPs** (changes things): Start or complete activities, submit, close or reopen plans, sign off hold and witness points.
  - API: `About 15 status-change and review calls`
- **ITP templates and settings** (changes things, admin permission): Templates, test plan types, reviewer actions, approval companies.
  - API: `About 30 setup calls`


## Models (BIM)

**Later**

- **Read design issues on models** (read only, unconfirmed): Design issues (BCF topics), comments, saved 3D views and linked documents.
  - API: `GET /bcf/{version}/projects/{id}/topics (+ comments, viewpoints, document_references, events)`
- **Raise or edit design issues** (changes things, unconfirmed): Create, edit or delete design issues, comments and saved views.
  - API: `POST/PUT/DELETE under /bcf/{version}/projects/{id}/topics`


## Cost

**Don't need**

- **Budgets and cost breakdown** (read only, Oracle must switch on): Cost lines, WBS, control accounts, spend over time and variance.
- **Contracts and pay items** (read only, Oracle must switch on): Contracts and their pay items.
- **Change events and variations** (read only, Oracle must switch on): Potential changes, budget changes and contract variations, including PDFs and history.
- **Progress claims and actual costs** (read only, Oracle must switch on, money): Payment applications with PDFs and history, and recorded actual costs.
- **Mail not yet reviewed for cost impact** (read only, Oracle must switch on): Mail flagged for cost review, and what it's linked to.
- **Create or edit changes and variations** (changes things, Oracle must switch on, money): Log change events and create or edit variations.
- **Submit, approve or share variations** (changes things, sends to others, Oracle must switch on, money): Formal variation steps, including sharing with the other contract party.
- **Create or edit claims and actuals** (changes things, Oracle must switch on, money): Draft and edit progress claims and actual costs.
- **Cost setup** (changes things, admin permission, Oracle must switch on, permanent): Users, security profiles, access rules, calendars, fields, templates, closing periods.


## Company setup and admin

**Don't need**

- **Create, invite or disable users** (changes things, sends to others, admin permission): Create Aconex or Lobby accounts, invite people to projects, switch logins on or off. Some of these send emails.
- **List everyone in our company** (read only, admin permission): All company users with login status and last login. Org admin only.
- **Change mailing groups** (changes things, permanent): Create, rename or delete mailing groups and change their members.
- **See roles and permissions** (read only, admin permission): Company and project roles, what each allows and who holds them. Needs the role-editing permission.
- **Change roles and permissions** (changes things, admin permission, permanent): Create, change, assign or delete roles. Changes access for everyone holding the role.
- **Change project custom fields** (changes things, admin permission): Create, edit, enable or disable project fields.
- **Copy a whole project** (changes things, admin permission, permanent): Creates a new project from an existing one. The API has no delete.


## Audit trail

**Need now**

- **Company-wide activity log** (read only, admin permission, Oracle must switch on): Logins, document changes, mail recipients and IP addresses across the company. Oracle must switch it on through a service request. Privacy-sensitive.
  - API: `GET /eventstream/events (+ single event, indexes, by duration)`
