# Stage 9: Reviews and packages

**Job:** read-only tools for document review workflows (and their files),
deliverable reviews, review issues, package reviews and packages.

## What the real Aconex showed (2 Nov 2026, read-only checks)

Every endpoint answers once called the right way, but **41 Warrs Road has
none of this data**:

| Endpoint | Result on Warrs Road | How to call it (confirmed) |
|---|---|---|
| `GET /projects/{id}/workflows` (+ status, assigned-to, initiated-by) | 0 workflows | `Accept: application/vnd.aconex.workflow.v1+xml`, XML `WorkflowSearch` with `TotalResults` |
| `POST /reviews/projects/{id}/issue/search` | 0 review issues | `application/json`, `{results, resultsSummary{total, totalPages}}` |
| `POST /reviews/projects/{id}/deliverable/search`, `.../reviewstep/search` | 0 | `Accept: application/vnd.aconex.reviews.v1+json` (406 with `application/json`) |
| `POST /reviews/projects/{id}/package-reviews/search`, `.../reviewsteps/search` | 0 | as above |
| `GET /package-management/projects/{id}/packages`, `.../package-types` | 0 | `Accept: application/vnd.aconex.packages.v1+json` (406 otherwise) |
| `POST /package-management/projects/{id}/packages/list` | 0 | body and `Content-Type` `application/vnd.aconex.packages.v1+json` (415 otherwise); `page`, `limit` (max 1000), `sort` in the query |

Field (stage 10) on the same project: **switched off** (`enabled: false`), one
empty area, 0 issues, checklists and safety observations. Field lives at
`https://api.aconex.com/field-management/api/projects/{id}`.

## Status

Parked (2 Nov 2026) until a project with workflows, reviews, packages or Field
data is available. Next up instead: testing on a Claude Enterprise account.
