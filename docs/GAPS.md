# Gaps: backend vs. the screen spec

An audit of the backend (as of commit `2d0bc42`, step 6l) against docs/SCREENS.md. Updated 2026-10-20 for the revised SCREENS.md, which answers the questions from the first audit. Chunk 1 (section 8) is being built against this list; the marks below are as of the audit, before chunk 1.

**How to read it.** Each item is marked:
- **Built**: the backend supports it as the spec describes, with the file or endpoint.
- **Partial**: some of it exists; what's missing is said.
- **Missing**: nothing supports it yet.

Two things apply to every screen and aren't repeated below:
- **There is no frontend yet.** No Next.js code exists, so every screen is Missing on the frontend side. The marks below are about the **backend**: can the API supply the data and actions the screen needs?
- **Endpoints** are relative to the API root, e.g. `GET /cases/{id}`. Code paths are under `backend/app/`.

---

## 1. Global rules

| Rule | Status | Backed by / what's missing |
| --- | --- | --- |
| Every application goes to Records first | **Built** | Both workflows start with a Records move: facility letter `submitted → originals_received` (alembic/versions/0015), ETLS application `submitted → with_minister` (0005/0012). Re-check when drafts arrive: "Submit" must land with Records, never further. |
| Applicants see plain status labels, never internal step names or staff names | **Missing** | `workflow_statuses` has one `name` ("Originals received by Records"), which is staff wording. No applicant label, no one-line explanation, no mapping. `GET /cases/{id}` gives applicants the internal `status.code` and `name`. The facility letter labels are now in the spec (A2). |
| Staff case history: newest first, actor's name and post title, "acting for", absence or delegation dates | **Partial** | `GET /cases/{id}/history` (core/workflow/router.py `case_history`) returns each audit row with `details.as_position`, `on_behalf_of`, `basis`, `delegation_id`, `absence_ids`. Missing: newest-first order; the actor's name and post title (only `actor_user_id`); the absence or delegation dates (only ids, and no endpoint to look them up by id). |
| Acting banner | **Missing** | The data exists (`core.absences`, `core.delegations`, `acting_successor()` in core/workflow/succession.py), but no endpoint answers "for which posts am I acting right now, on what basis, until when?" `GET /auth/me` lists only your own posts. |
| Disabled actions explain why | **Partial** | `GET /cases/{id}` lists `available_actions` (with `requires_comment`). The reasons only appear after a failed attempt (409 from `POST /cases/{id}/status`). Missing: a dry run, i.e. each action with what blocks it, computed without moving the case. |
| Returning: a written reason, as a **message to the applicant** plus an optional **internal minute**; rejecting also needs a reason | **Partial** | `workflow_transitions.requires_comment` (0022) forces a written comment. Missing: return moves, a `returned` status, a separate applicant message (today there's one internal `comment`), and the reason requirement on "Reject" (`requires_comment` is false there). |
| Drafts: every application starts as an editable draft; "Submit" goes to Records; a returned case becomes editable and is resubmitted with the same reference and history | **Missing** | `POST /etls/facility-letters` opens the case straight at `submitted`; documents can only be uploaded after that; the form can never be edited. |
| Dates in the Ministry format | **Partial** | `long_date()` in modules/etls/letter.py, used on the letter. The API returns ISO dates elsewhere (right for an API); the frontend needs the same formatter. |
| Case reference numbers: a sequence per service per year, assigned at submission (`MOTIE/ETLS/FL/2026/0001`, `/AP/`, `/CO/`), shown to applicants and staff | **Missing** | No reference on the case. The `FACILITY_LETTER_REFERENCE_FORMAT` setting builds a reference only on the letter, at signing, from the case id. |
| The Ministry's **registry file reference** (e.g. `ADM 151/420/01/PART IV`) is separate: printed at the top of the letter; a setting until the desk explains it `[CONFIRM]` | **Partial** | The letter already prints a setting (`FACILITY_LETTER_REFERENCE_FORMAT`, core/config.py). Its default (`MOTIE/ETLS/FL/{year}/{case_id:05d}`) looks like the new case reference but isn't one; it should become the registry reference, with the case reference kept apart (chunk 2). |
| Uploads: PDF/PNG/JPEG, max 10 MB, type from content | **Built** | core/documents/storage.py `save()`, `POST /cases/{id}/documents/{type}`, `MAX_UPLOAD_BYTES`. |
| Notifications: email at each status change and on return | **Missing** | No email code. Needs the Ministry's mail server `[CONFIRM]`, an outbox table and a background sender. |
| Queues show how long each case has waited at its current step | **Missing** | No list endpoint for cases at all. `core.cases.updated_at` is set on each status change, but nothing exposes it as "waiting since". |
| Walk-ins: Records creates any application for an applicant, recorded as such | **Missing** | Only the applicant role can open cases; `cases.created_by` is the only person field. |

---

## 2. Applicant screens

### A1. Services and my applications

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Three service cards | **Partial** | Static content. Only the facility letter has an application endpoint. |
| Notice for a returned case, with the message and "Fix and resubmit" | **Missing** | Needs returns and drafts (global rules). |
| Table of my cases: reference, goods, submitted date, applicant label | **Missing** | No `GET /cases` for "my cases"; no reference; no labels. Goods live in each module's tables. |
| Selected case: timeline of applicant labels with dates | **Missing** | Applicants can't read history (it holds internal minutes, so that's right). Needs an applicant-safe timeline: labels and dates only, plus return messages. |

### A2. Facility letter application

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Importer: business name, address | **Built** | `importer_name`, `importer_address` (modules/etls/schemas.py `FacilityLetterForm`). |
| Goods: product, quantity, unit, HS code (optional) | **Built** | HS code optional since step 6k. |
| Exporter: name, country, ETLS approval number, product approval numbers | **Built** | |
| Certificates of origin, **each with number and issue date** | **Partial** | Numbers are built (`etls.facility_letter_certificates`, duplicate check from step 6b). **Issue dates are missing**: a new column, required on the form, used by the computed six-month check (S2). |
| Documents checklist, with the note to bring the original certificate | **Built** | `GET /cases/{id}/documents`: `applies`, `missing`, `original_required`. |
| Receipt "not known yet" until the **desk confirms** the HS code; a declared code doesn't decide it | **Partial** | `"applies": null` without any code (step 6k). But `hs_heading()` in modules/etls/service.py still lets the applicant's declared code decide until the desk confirms. Change to confirmed-only (C5). |
| Save draft; Submit disabled until required documents are uploaded, with a count | **Missing** | Needs drafts (global rules, C4). The per-document `missing` flags exist to count from. |
| Applicant labels: Draft → Submitted ("Bring the original certificate of origin to Records") → Originals checked → Being verified → Awaiting signature → Letter signed → Letter sent to GRA; Returned: action needed; Rejected; a cancelled letter is invisible (shows "Being verified" again) | **Missing** | No labels. Draft and Returned statuses don't exist yet. "Originals checked" and "Being verified" are two labels for one internal status (`originals_received`): one says what happened, the other where the case is now. |

### A3. Status on a phone

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Reference | **Missing** | No case reference. |
| Goods, exporter | **Built** | `GET /etls/facility-letters/{id}`. |
| Current applicant label + one-line explanation | **Missing** | |
| Timeline | **Missing** | As in A1. |

### A4. ETLS approval application (ECOWAS form)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Part I, identity of enterprise | **Missing** | No approval tables; the old `etls_application` workflow has no form and is being retired (chunk 3). |
| Part II, products: description, HS tariff item, brand, origin criterion, value added % | **Missing** | Products child table needed; `normalize_hs_code()` can be reused. |
| Part III, manufacturing process | **Missing** | |
| Documents (incl. conditional and optional ones) | **Partial** | The data-driven requirements mechanism is built. Missing: these document types and rows, and "optional" documents (accepted but never required). |
| Note: bring a sample of each product to Records | **Missing** | Records must record "samples received" (S4). |

### A5. Approval progress and approved products

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Applicant labels Submitted → … → Approved by ECOWAS | **Missing** | The new `etls_approval` workflow (chunk 3). |
| Factory visit notice with date | **Missing** | |
| My approved products with ECOWAS numbers, "Request a certificate of origin" | **Missing** | No register. |
| Products still in progress | **Missing** | Per-product outcomes (now decided, C2). |

### A6. Certificate of origin request

Everything is **Missing**: no register, no CO workflow, no CO tables (boxes 1–9, invoice upload, declaration, labels).

---

## 3. Staff screens: facility letters

Spec route: Records (originals seen) → ETLS desk (verify) → PS (sign) → **Records dispatches the letter** → `Sent to GRA` (final; no manual Close unless GRA reports back `[CONFIRM]`).
Built route (0015, 0018, 0020–0022): `submitted` →(Records: Confirm originals received)→ `originals_received` →(desk: Verify / Reject)→ `verified` / `rejected` →(PS: Sign)→ `signed` →(**desk**: Send to GRA)→ `sent_to_gra` →(**desk**: Close the file)→ `closed`; plus the PS's "Cancel the signed letter" from `signed`/`sent_to_gra` back to `originals_received`. Differences: "Send to GRA" belongs to Records, with a dispatch date; `sent_to_gra` must become final and "Close" goes (C9).

### S1. Records queue

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Queue of all services, oldest first: service, applicant, goods, days waiting | **Missing** | No queue endpoint. Each module needs to supply a one-line "goods" summary. |
| Documents list with view links | **Built** | `GET /cases/{id}/documents`, `.../documents/{document_id}/file`. |
| "Original seen in person" | **Built** | `POST /cases/{id}/documents/{document_id}/original-seen`. |
| Accept, disabled until originals seen | **Built** (move and checks) / **Partial** (the "why") | Records' move has `known_documents_complete` and `originals_seen`. The reason before clicking needs the dry run. |
| Return to applicant with message (and internal minute) | **Missing** | |
| **Outgoing tab**: signed letters to dispatch; download the stored letter; "Mark sent to GRA" with the dispatch date | **Partial** | The stored letter is built (`GET /etls/facility-letters/{id}/letter.pdf`). Missing: a queue filtered to `signed` cases for Records; the move belongs to the desk today (C9); no dispatch date (it would be today's date of the move, but the spec wants a date entered). |

### S2. ETLS desk verification

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Duplicate flag: earlier case, its status and date | **Partial** | `GET /cases/{id}/flags`: `details.numbers`, `details.earlier_case_ids`. Earlier cases' status and date aren't included. |
| Finding (required) to clear | **Built** | `POST /cases/{id}/flags/{flag_id}/resolve`. |
| **Or reject directly while the flag is open; the rejection reason resolves the flag** `[CONFIRM]` | **Missing** | Today an open blocking flag stops every move, rejecting included (C7). |
| Application summary | **Built** | `GET /etls/facility-letters/{id}`. |
| HS code: enter or confirm; whether the receipt applies | **Built** | `POST /etls/facility-letters/{id}/hs-code`; `applies` in the checklist (rule follows the declared code until C5 is fixed). |
| ECOWAS ETLS list ticks (exporter approval listed; product approval covers the goods), each recorded | **Missing** | Needs a recorded-tick checklist per case and a check on Verify. |
| **Certificate validity computed** from the form's issue dates; any certificate over six months old flagged | **Missing** | Needs the issue dates (A2). `[CONFIRM]` "six months" counted to the submission date or to the verification date. |
| Verify, disabled until flag cleared, HS confirmed, ticks done, documents complete | **Partial** | Built: blocking flag, `hs_code_confirmed`, `documents_complete`. Missing: ticks, certificate validity, and the dry run. |
| Return to applicant | **Missing** | |
| History panel | **Partial** | As in global rules. |

### S3. PS signs the letter

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Letters awaiting signature | **Missing** | No queue endpoint. |
| Summary of checks done | **Partial** | Available piecemeal (documents' `original_seen_at`, flags). No ticks; no summary endpoint. |
| Letter preview in the Ministry's wording | **Missing** | `render_pdf()` exists; a preview must never be stored and must be marked as a draft. |
| Sign (stores the letter) | **Built** | `verified → signed`, effect `issue_facility_letter` (core/documents/issued.py). |
| Return to desk | **Missing** | No `verified → originals_received` move for the PS. |
| Cancel and reissue | **Built** | "Cancel the signed letter" (0022); `.../letters`, `.../letters/{letter_id}/file`. The applicant must not see it (A2): a timeline rule. |

### S11. Absences and delegations (all staff)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| My absences: record my own (dates, optional reason) | **Built** | `POST /absences` without `user_id` (core/workflow/absence.py `record_absence()`); `POST /absences/{id}/cancel`. |
| Delegate to another post (dates, all workflows or one) | **Built** | `POST /delegations` (core/workflow/delegation.py); revoke with `POST /delegations/{id}/revoke`. |
| **Shows who will act for me** under the succession order | **Missing** | `succession_order()` and `acting_successor()` exist, but no endpoint returns "if you're away, these posts act for you, in this order, per workflow". |
| Record for someone else (`absence_recorder` role `[CONFIRM: PS's office, HR]`), audited as "recorded by" | **Built** | `POST /absences` with `user_id`; the audit row records `recorded_by` and `on_behalf` (step 5c). |
| **List of current and upcoming absences**, with revoke for delegations | **Partial** | `GET /absences` lists only your own (everyone's for a recorder) and includes past ones; `GET /delegations` lists those given by or to your posts. Missing: a current-and-upcoming list every staff member can see (who's away, and who acts). |
| (Banner, all screens) "You are acting for …" | **Missing** | As in global rules. |

---

## 4. Staff screens: ETLS approval

Decided: a new `etls_approval` workflow replaces `etls_application` (retiring it is approved for chunk 3), and outcomes are per product (C2).
Built today (`etls_application`, 0005 + 0012): Records → Minister → PS → Director (sign and assign) → officer → approve/reject placeholders. Everything from the NAC onwards is missing.

| Screen | Status | Notes |
| --- | --- | --- |
| S4. Minute a file | **Partial** | Built: minute text (the move's comment), Minister → PS → Director moves, acting via succession. Missing: the form summary, "samples received", return to Records. |
| S5. Sign and assign | **Partial** | Built: the sign-and-assign move; DPS Admin & Finance stands in (succession, `etls_application` only). Missing: choosing a named officer (case assignment), return to PS; the stand-in row must move to `etls_approval`. |
| S6. Technical review | **Missing** | Per-product findings, cost-price limits as data, inspection and report, send to NAC, ask the applicant. |
| S7. NAC decisions | **Missing** | Meetings, per-product decisions, meeting pack, signed minutes. |
| S8. ECOWAS submission and outcome | **Missing** | Submission pack, per-product outcomes, the approved products register. |

---

## 5. Staff screens: certificates of origin

Everything is **Missing** (S9 comparison table and flags; S10 box 10 certification and numbering, duplicate reprints, box 11 Customs, collection, six-month validity, one product per certificate). The issue-once pattern (core/documents/issued.py) and flags (core/workflow/flags.py) can be reused. The certifying officer is the Director `[CONFIRM]`, so the DPS stand-in needs a succession row for the CO workflow too.

---

## 6. Stand-in rules and "acting for" in history

| Check | Status | Where |
| --- | --- | --- |
| Minister → PS → DPS Admin & Finance | **Built** | alembic/versions/0013_succession_orders.py; `acting_successor()`; tests/core/test_acting_for.py. |
| PS → DPS Admin & Finance | **Built** | Same migration. Covers the facility letter: the DPS signs "For: Permanent Secretary" and can cancel. |
| ETLS: Director → DPS Admin & Finance | **Built**, with a caveat | Seeded only for `etls_application`. `etls_approval` (chunk 3) and the CO workflow (chunk 4) each need their own row. |
| A delegation overrides succession | **Built** | `_permitted()` in core/workflow/service.py. |
| History fetched with "acting for" | **Built** (data) / **Partial** (display) | `GET /cases/{id}/history`: `as_position`, `on_behalf_of`, `basis`, `delegation_id`, `absence_ids`. For the screens it needs newest first, names and titles, and the dates (chunk 1). |

---

## 7. Conflicts, and built things the screens don't use

### Conflicts and how the spec decides them

- **C1. ETLS approval route.** *Decided:* new `etls_approval` workflow; `etls_application` retired in chunk 3.
- **C2. Per-product decisions.** *Decided:* the case status tracks the file (with NAC, with ECOWAS, done); each product carries its own NAC and ECOWAS decisions in the module's tables.
- **C3. Return to applicant.** *Decided:* a return has a **message to the applicant** (shown to them) and an optional **internal minute** (staff only); the case becomes editable and is resubmitted with the same reference and history. Rejecting needs a reason too. Build: a `returned` status, an applicant-visible message stored apart from the internal comment, return moves from Records and the desk (and later the officer), an applicant "Resubmit".
- **C4. Documents after submission.** *Decided:* every application starts as a draft; "Submit" goes to Records and is disabled until the required documents are uploaded.
- **C5. Which HS code decides the receipt.** *Decided:* only the desk-confirmed code. A one-line change in `hs_heading()`.
- **C6. References.** *Decided:* two different numbers. The **case reference** (`MOTIE/ETLS/FL/2026/0001`) is a sequence per service per year, assigned at submission, shown to everyone. The **registry file reference** printed on the letter stays a setting `[CONFIRM]`. So the letter does *not* switch to the case reference; the setting's default should change to a registry-style value once the desk explains it.
- **C7. Reject while a duplicate flag is open.** *Decided* `[CONFIRM]`: allowed, and the rejection reason resolves the flag. Build: a per-transition "allowed while on hold" property, plus resolving the case's open flags with the reason.
- **C8. History order.** *Decided:* newest first, with name, post title and acting-for dates.
- **C9 (new). Dispatch to GRA.** *Decided:* Records dispatches signed letters (an "Outgoing" tab) and marks them sent with the dispatch date; `sent_to_gra` is the final status; the manual "Close" goes, unless GRA reports back `[CONFIRM]`. Build: the `signed → sent_to_gra` move changes from the desk to the Records post, with a required dispatch date; `sent_to_gra` becomes final; the "Close the file" move and `closed` status are removed (dev only; the migration must refuse if a case is in `closed`). The PS's "Cancel the signed letter" from `sent_to_gra` stays.
- **C10 (new). Certificate issue dates and the six-month check.** *Decided:* each certificate on the form has an issue date, and validity is computed (S2). Build: a date column on `etls.facility_letter_certificates`, required on new forms, and a check that flags certificates older than six months `[CONFIRM: counted to which date]`.

### Built but not used by any screen

- **`POST /cases`** (generic case opening): unused; retires with `etls_application`.
- **"Close the file"** and the `closed` status: dropped by the spec (C9).
- **Placeholder posts:** `director_of_trade`, `trade_officer`, the Directorate of Trade (0008).
- **Letter field `$hs_code`**: not in the Ministry's wording.
- **Facts `product`, `unit`, `exporter_country`**: no rule uses them since step 6g.
- **Assigning posts** (CLI): no screen; fine while ICT does it.

---

## 8. Build order

Each chunk is a few small steps, each with tests, a LEARNING.md entry and its own commit. Chunks 1 and 2 finish the facility letter screens end to end.

### Chunk 1: shared foundations (backend)
**Done** (steps 7a–7f, 2026-10-20). See the build log in LEARNING.md.
1. **Applicant status labels**: `applicant_label` and `applicant_explanation` on every status (required), plus an optional applicant wording per move, and moves the applicant never sees (the letter cancel). Applicants get labels, never internal codes or names.
2. **Case reference at submission**: a per-workflow prefix and a counter per workflow per year; `MOTIE/ETLS/FL/2026/0001`. The letter keeps printing the registry reference setting.
3. **Lists and queues**: `GET /cases` (my cases, for applicants) and `GET /cases/queue` (staff: cases where I can make a move now, by own post, delegation or succession), oldest first, with days waiting, service, applicant and a module-supplied "goods" line; filter by status (for Records' Outgoing tab).
4. **Actions with reasons**: each available action says what blocks it (dry run of on-hold flags and checks).
5. **History and timeline**: staff history newest first with names, post titles and acting-for with absence or delegation dates; an applicant timeline with labels and dates only.
6. **Acting and absences views** (banner, S11): "for which posts am I acting now, and until when", "who acts for my posts", and current and upcoming absences visible to all staff.

### Chunk 2: facility letter screens end to end
1. **Drafts and submit** (C4): `draft` status, editable form, submit with the missing-documents count; the reference is assigned on submit.
2. **Returns** (C3): `returned` status, applicant message + internal minute, from Records (S1) and the desk (S2); resubmit. Reason required on Reject.
3. **Form and desk checks**: certificate issue dates and the computed six-month check (C10); ECOWAS list ticks; HS rule confirmed-only (C5); earlier cases' status and date in the duplicate flag; reject while flagged (C7).
4. **Dispatch** (C9): Records' Outgoing queue and "Mark sent to GRA" with dispatch date; `sent_to_gra` final; Close removed; the registry reference setting.
5. **PS support** (S3): checks summary, letter preview (never stored, marked as draft), return to desk.
6. **Walk-ins**: Records opens an application for an applicant; both are recorded.
7. **Notifications**: email on every applicant-visible status change and on return, through an outbox and a background sender `[CONFIRM: mail server]`.
8. **Frontend**: Next.js, login, date formatter, acting banner; A1 (facility letter part), A2, A3, S1 (with Outgoing), S2, S3, S11.

### Chunk 3: ETLS approval (A4, A5, S4–S8)
1. Retire `etls_application`; new `etls_approval` workflow with the spec's statuses and labels; the Director's stand-in row moves to it; returns to Records and the PS.
2. Approval form (parts I–III), documents, "samples received".
3. Assigning a named officer (S5).
4. Technical review per product, cost-price limits as data, inspection (S6).
5. NAC meetings and per-product decisions (S7).
6. ECOWAS submission and outcomes, the approved products register (S8, A5).
7. Frontend screens.

### Chunk 4: certificates of origin (A6, S9, S10)
CO workflow and labels, reference `MOTIE/ETLS/CO/…`, the certifying officer's stand-in, request form from the register, verification comparison, certification and numbering, Customs, collection, frontend.

---

## Questions from the first audit: decided

1. **Facility letter applicant labels**: decided (SCREENS.md A2).
2. **Return reasons**: decided: a message to the applicant plus an optional internal minute; rejecting needs a reason too.
3. **Reject while a duplicate flag is open**: decided, still `[CONFIRM]`: allowed; the rejection reason resolves the flag.
4. **Send to GRA and Close**: decided: Records dispatches and marks sent, with the dispatch date; no manual Close `[CONFIRM: unless GRA reports back]`.
5. **Reference numbers**: decided: a sequence per service per year, assigned at submission. The registry file reference on the letter is separate and stays a setting `[CONFIRM]`.
6. **Certificates within six months**: decided: computed from issue dates on the form.
7. **Absences and delegations**: decided: screen S11; recording for others by the `absence_recorder` role `[CONFIRM: PS's office, HR]`.
8. **Retiring `etls_application`**: approved, for chunk 3.

Still open (new):
- Six months counted to which date: submission, or verification?
- Should the timeline hide everything about a cancelled letter, or only the cancellation itself? (Chunk 1 hides the cancel move; the earlier "Letter signed" entry stays, because the applicant may already have seen it.)
