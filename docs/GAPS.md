# Gaps: backend vs. the screen spec

An audit of the backend against docs/SCREENS.md. First written at commit `2d0bc42` (step 6l), revised 2026-10-20 for the updated SCREENS.md.
**Chunk 1 (shared foundations, steps 7a–7f) is done**, and the marks below include it (2026-10-24). Chunk 2 is done too: its backend in steps 8a–8m (2026-10-25) and its frontend in steps 9a–9h (2026-10-26). Each step updated the marks it changed.

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
| Every application goes to Records first | **Built** | Facility letter: the applicant's Submit lands at `submitted`, whose only move is Records' `submitted → originals_received` (0015, 0026). ETLS application: `submitted → with_minister` (0005/0012). |
| Applicants see plain status labels, never internal step names or staff names | **Built** | `applicant_label` and `applicant_explanation` on every status (0023); `status_view()` in core/workflow/service.py gives applicants `null` for the internal code and name. Draft and Returned labels come with those statuses (chunk 2). |
| Staff case history: newest first, actor's name and post title, "acting for", absence or delegation dates | **Built** | `GET /cases/{id}/history` (core/workflow/history.py `staff_history()`). |
| Acting banner | **Built** | `GET /acting` (core/workflow/acting.py). |
| Disabled actions explain why | **Built** | `available_actions[].blocked_by` on `GET /cases/{id}`: a dry run of on-hold flags and the move's checks (`what_blocks()` in core/workflow/service.py). |
| Returning: a written reason, as a **message to the applicant** plus an optional **internal minute**; rejecting also needs a reason | **Built** | 8b (0027): `applicant_message` next to the internal `comment` on `POST /cases/{id}/status`, required by `requires_applicant_message` on the return moves and on Reject. |
| Drafts: every application starts as an editable draft; "Submit" goes to Records; a returned case becomes editable and is resubmitted with the same reference and history | **Built** | 8a: `POST /etls/facility-letters` opens a `draft`; `PUT /etls/facility-letters/{id}` edits it while the status is `applicant_editable`; Submit is the applicant's move `draft → submitted` (`by_applicant`, 0026). 8b: `returned` is editable too, and "Resubmit" (`returned → submitted`) keeps the reference (0027). |
| Dates in the Ministry format | **Partial** | `long_date()` in modules/etls/letter.py, used on the letter. The API returns ISO dates elsewhere (right for an API); the frontend needs the same formatter. |
| Case reference numbers: a sequence per service per year, assigned at submission (`MOTIE/ETLS/FL/2026/0001`, `/AP/`, `/CO/`), shown to applicants and staff | **Built** | `core.reference_counters`, `next_reference()` in core/workflow/service.py (0024); given by the `assign_reference` effect on Submit (8a), kept on resubmission. |
| The Ministry's **registry file reference** (e.g. `ADM 151/420/01/PART IV`) is separate: printed at the top of the letter; a setting until the desk explains it `[CONFIRM]` | **Built** | 8e: `FACILITY_LETTER_REFERENCE_FORMAT` (core/config.py); download names use the case reference. 8k: it defaults to `ADM 151/420/01/PART IV` only with `APP_ENV=development`; on a production server the PS's Sign is blocked (`etls_registry_reference_set`) until it's set. |
| Uploads: PDF/PNG/JPEG, max 10 MB, type from content | **Built** | core/documents/storage.py `save()`, `POST /cases/{id}/documents/{type}`, `MAX_UPLOAD_BYTES`. |
| Notifications: email at each status change and on return | **Built** (fake sender) | 8h: `core.notifications` outbox written with each applicant-visible move (core/notifications/service.py); the `notifier` worker sends it. Only a fake sender (logs) until the mail server is known `[CONFIRM]`. |
| Queues show how long each case has waited at its current step | **Built** | `GET /cases/queue`: `status_since`, `days_waiting` (core/workflow/queues.py, `cases.status_changed_at` from 0025). |
| Walk-ins: Records creates any application for an applicant, recorded as such | **Built** (facility letters) | 8g: `POST /etls/facility-letters/walk-in`; `cases.entered_by`, `workflows.walk_in_position_id` (0032); Records may make the walk-in's applicant moves. 8j: a new account has no password and is emailed a single-use, expiring "set your password" link (`core.password_links`, `POST /auth/set-password`); with no email the account can't log in or be emailed and Records tells the applicant (`applicant_emailed: false`). Approvals and COs get the same when they're built. Frontend: a `/set-password` page that reads `#token=`. |

---

## 2. Applicant screens

### A1. Services and my applications

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Three service cards | **Partial** | Static content. Only the facility letter has an application endpoint. |
| Notice for a returned case, with the message and "Fix and resubmit" | **Built** | 8b: `applicant_message` on each row of `GET /cases` (and on `GET /cases/{id}`): the message of the move into the current status. |
| Table of my cases: reference, goods, submitted date, applicant label | **Built** | `GET /cases` (core/workflow/queues.py `my_cases()`), goods from the module's summary. |
| Selected case: timeline of applicant labels with dates | **Built** | `GET /cases/{id}/timeline` (core/workflow/history.py `applicant_timeline()`); each entry has the move's `message` to the applicant, if any (8b). |

### A2. Facility letter application

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Importer: business name, address | **Built** | `importer_name`, `importer_address` (modules/etls/schemas.py `FacilityLetterForm`). |
| Goods: product, quantity, unit, HS code (optional) | **Built** | HS code optional since step 6k. |
| Exporter: name, country, ETLS approval number, product approval numbers | **Built** | |
| Certificates of origin, **each with number and issue date** | **Built** | 8c: `certificates_of_origin: [{number, issued_on}]` on the form, `expires_on` in responses (`etls.facility_letter_certificates.issued_on`, 0028). |
| Documents checklist, with the note to bring the original certificate | **Built** | `GET /cases/{id}/documents`: `applies`, `missing`, `original_required`. |
| Receipt "not known yet" until the **desk confirms** the HS code; a declared code doesn't decide it | **Built** | 8d: `hs_heading()` in modules/etls/service.py uses only the confirmed code (C5). |
| Save draft; Submit disabled until required documents are uploaded, with a count | **Built** | 8a: the draft is saved with `POST`/`PUT /etls/facility-letters`; the Submit action carries `known_documents_complete`, so its `blocked_by` lists what's missing. 8i: a draft may be saved half-filled; the check `etls_form_complete` on Submit and Resubmit adds each empty field to the same `blocked_by` list. |
| **Warning at submission** when a certificate expires within 30 days (doesn't block) | **Built** | 8c: the warning-only check `etls_certificates_expiring` on Submit and Resubmit; shown in the action's `warnings`, recorded with the move. |
| Applicant labels: Draft → Submitted ("Bring the original certificate of origin to Records") → Originals checked → Being verified → Awaiting signature → Letter signed → Letter sent to GRA; Returned: action needed; Rejected; a cancelled letter is invisible (shows "Being verified" again); a corrected letter that replaces one already sent to GRA shows "Corrected letter issued" | **Built** | 0023, 0026, 0027: every label; the cancel move is hidden. 8e: `applicant_label_corrected` gives "Corrected letter issued" (0030). |

### A3. Status on a phone

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Reference | **Built** | `reference` on `GET /cases/{id}` and `GET /etls/facility-letters/{id}`. |
| Goods, exporter | **Built** | `GET /etls/facility-letters/{id}`. |
| Current applicant label + one-line explanation | **Built** | `status.label`, `status.explanation` on `GET /cases/{id}`. |
| Timeline | **Built** | As in A1. |

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
| Products still in progress | **Missing** | Per-product outcomes (decided, C2). |

### A6. Certificate of origin request

Everything is **Missing**: no register, no CO workflow, no CO tables (boxes 1–9, invoice upload, declaration, labels).

---

## 3. Staff screens: facility letters

Spec route: Records (originals seen) → ETLS desk (verify) → PS (sign) → **Records dispatches the letter** → `Sent to GRA` (final; no manual Close unless GRA reports back `[CONFIRM]`).
Built route (0015–0030): `draft` →(applicant: Submit)→ `submitted` →(Records: Confirm originals received / Return)→ `originals_received` →(desk: Verify / Return / Reject)→ `verified` / `returned` / `rejected` →(PS: Sign)→ `signed` →(**Records**: Mark sent to GRA, with the dispatch date)→ `sent_to_gra` (final); `returned` →(applicant: Resubmit)→ `submitted`; plus the PS's correction "Cancel the signed letter" from `signed`/`sent_to_gra` back to `originals_received`. Matches the spec since 8e.

### S1. Records queue

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Queue of all services, oldest first: service, applicant, goods, days waiting | **Built** | `GET /cases/queue` (core/workflow/queues.py). |
| Documents list with view links | **Built** | `GET /cases/{id}/documents`, `.../documents/{document_id}/file`. |
| "Original seen in person" | **Built** | `POST /cases/{id}/documents/{document_id}/original-seen`. |
| Accept, disabled until originals seen | **Built** | Records' move has `known_documents_complete` and `originals_seen`; `blocked_by` says which is missing. |
| Return to applicant with message (and internal minute) | **Built** | 8b: "Return to applicant" (`submitted → returned`). |
| **Outgoing tab**: signed letters to dispatch; download the stored letter; "Mark sent to GRA" with the dispatch date | **Built** | 8e: `GET /cases/queue?status=signed` (Records), `GET /etls/facility-letters/{id}/letter.pdf`, `POST /etls/facility-letters/{id}/sent-to-gra` with `dispatched_on` (`etls.facility_letter_dispatches`). |

### S2. ETLS desk verification

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Duplicate flag: earlier case, its status and date | **Built** | 8d: `GET /etls/facility-letters/{id}/duplicates`: every other submitted case with the number, its reference, current status and date. The flag (for the desk) holds only the desk's moves, so the case reaches the desk. |
| Finding (required) to clear | **Built** | `POST /cases/{id}/flags/{flag_id}/resolve`. |
| **Or reject (or return) directly while the flag is open; the reason resolves the flag** `[CONFIRM]` | **Built** | 8d: `allowed_on_hold` on the desk's Reject; the engine resolves the flag with the minute (or the applicant message). 8l: the desk's Return to applicant too (0037); resubmitting runs the duplicate check again. |
| Application summary | **Built** | `GET /etls/facility-letters/{id}`. |
| HS code: enter or confirm; whether the receipt applies | **Built** | `POST /etls/facility-letters/{id}/hs-code`; `applies` in the documents checklist, from the confirmed code only (8d). |
| ECOWAS ETLS list ticks (exporter approval listed; product approval covers the goods), each recorded | **Built** | 8d: `GET /cases/{id}/checklist`, `PUT /cases/{id}/checklist/{code}` (core/workflow/checklist.py); check `checklist_complete` on Verify. Wording `[CONFIRM]`. |
| **Certificate validity computed** from the form's issue dates; Verify blocked if any certificate is more than six months past its issue date | **Built** | 8c: check `etls_certificates_valid` on Verify (`_check_certificates_valid()` in modules/etls/service.py). |
| Verify, disabled until flag cleared, HS confirmed, ticks done, documents complete, certificates valid | **Built** | Blocking flag, `hs_code_confirmed`, `documents_complete`, certificate validity (8c), ECOWAS ticks (8d), all shown in `blocked_by`. |
| Return to applicant | **Built** | 8b: "Return to applicant" (`originals_received → returned`). The resubmitted case goes to Records first. |
| History panel | **Built** | As in global rules. |

### S3. PS signs the letter

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Letters awaiting signature | **Built** | `GET /cases/queue` for the PS (`?status=verified` narrows it). |
| Summary of checks done | **Built** | 8f: `GET /etls/facility-letters/{id}/checks` (originals seen, ECOWAS ticks, duplicate flags, HS code, certificate validity, missing documents). |
| Letter preview in the Ministry's wording | **Built** | 8f: `GET /etls/facility-letters/{id}/letter-preview.pdf`: rendered on request, never stored, marked "DRAFT FOR CHECKING - NOT SIGNED". |
| Sign (stores the letter) | **Built** | `verified → signed`, effect `issue_facility_letter` (core/documents/issued.py). |
| Return to desk | **Built** | 8f: "Return to the desk" (`verified → originals_received`, PS, minute required; 0031). |
| Cancel and reissue | **Built** | "Cancel the signed letter" (0022); `.../letters`, `.../letters/{letter_id}/file`. The timeline hides the cancel move (7e). Since 8e it's a correction move (`is_correction`), so it puts no letter in the PS's queue. |

### S11. Absences and delegations (all staff)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| My absences: record my own (dates, optional reason) | **Built** | `POST /absences` without `user_id` (core/workflow/absence.py `record_absence()`); `POST /absences/{id}/cancel`. |
| Delegate to another post (dates, all workflows or one) | **Built** | `POST /delegations` (core/workflow/delegation.py); revoke with `POST /delegations/{id}/revoke`. |
| **Shows who will act for me** under the succession order | **Built** | `GET /acting/for-me` (core/workflow/acting.py). |
| Record for someone else (`absence_recorder` role `[CONFIRM: PS's office, HR]`), audited as "recorded by" | **Built** | `POST /absences` with `user_id`; the audit row records `recorded_by` and `on_behalf` (step 5c). |
| **List of current and upcoming absences**, with revoke for delegations | **Built** | `GET /absences/current` (everyone away now or later, for all staff, with `may_cancel`, 9g); revoke ids in `GET /acting/for-me`. The form's choices (posts with holders, workflows): `GET /acting/options` (9g). Screen: frontend/app/staff/absences/page.tsx. |
| (Banner, all screens) "You are acting for …" | **Built** | `GET /acting`. |

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
| History fetched with "acting for" | **Built** | `GET /cases/{id}/history`: names, post titles, and `acting_for` with the absence or delegation dates (step 7e). |

---

## 7. Conflicts, and built things the screens don't use

### Conflicts and how the spec decides them

- **C1. ETLS approval route.** *Decided:* new `etls_approval` workflow; `etls_application` retired in chunk 3.
- **C2. Per-product decisions.** *Decided:* the case status tracks the file (with NAC, with ECOWAS, done); each product carries its own NAC and ECOWAS decisions in the module's tables.
- **C3. Return to applicant.** *Decided and built (8b):* a return has a **message to the applicant** (shown to them) and an optional **internal minute** (staff only); the case becomes editable and is resubmitted with the same reference and history. Rejecting needs a reason too. Build: a `returned` status, an applicant-visible message stored apart from the internal comment, return moves from Records and the desk (and later the officer), an applicant "Resubmit".
- **C4. Documents after submission.** *Decided and built (8a):* every application starts as a draft; "Submit" goes to Records and is disabled until the required documents are uploaded.
- **C5. Which HS code decides the receipt.** *Decided and built (8d):* only the desk-confirmed code. A one-line change in `hs_heading()`.
- **C6. References.** *Decided:* two different numbers. The **case reference** (`MOTIE/ETLS/FL/2026/0001`) is a sequence per service per year, assigned at submission, shown to everyone. The **registry file reference** printed on the letter stays a setting `[CONFIRM]`. So the letter does *not* switch to the case reference; the setting's default should change to a registry-style value.
- **C7. Reject while a duplicate flag is open.** *Decided* `[CONFIRM]` *and built (8d)*: allowed, and the rejection reason resolves the flag (`allowed_on_hold`). Since 8l the desk may also return while held `[CONFIRM]`; the return's reason resolves the flag, and resubmitting checks the numbers again. Found while building: the flag used to hold every move, so a flagged case never reached the desk; a flag now holds only its own post's moves.
- **C8. History order.** *Decided and built (7e):* newest first, with name, post title and acting-for dates.
- **C9. Dispatch to GRA.** *Decided and built (8e):* Records dispatches signed letters (an "Outgoing" tab) and marks them sent with the dispatch date; `sent_to_gra` is the final status; the manual "Close" goes, unless GRA reports back `[CONFIRM]`. Build: the `signed → sent_to_gra` move changes from the desk to the Records post, with a required dispatch date; `sent_to_gra` becomes final; the "Close the file" move and `closed` status are removed (dev only; the migration must refuse if a case is in `closed`). The PS's "Cancel the signed letter" from `sent_to_gra` stays, so a final status needs a way to allow that one correction move.
- **C10. Certificate issue dates and validity.** *Decided (2026-10-24) and built (8c):* each certificate on the form has an issue date. At the desk's **Verify**, any certificate more than six months past its issue date **blocks** the move. At **submission**, a certificate that expires within 30 days gives the applicant a **warning** but doesn't block. Whether GRA also needs the certificate still valid at clearance is **not confirmed** `[CONFIRM]`; nothing is built for it. Build: a date column on `etls.facility_letter_certificates`, required on new forms; a blocking check on Verify; a warning-only check on Submit.
- **C11. Timeline after a cancelled letter.** *Decided (2026-10-24) and built (8e):* keep hiding only the cancel move. If the cancelled letter had already been sent to GRA, the next "sent to GRA" shows to the applicant as **"Corrected letter issued"**.

### Built but not used by any screen

- **`POST /cases`** (generic case opening): unused; retires with `etls_application`.
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
**Done.** Backend steps 8a–8h (2026-10-25), with fixes in 8i–8m (half-filled drafts, set-password links for walk-ins, the registry reference on a real server, returning while held, scrubbing sent links); the frontend in steps 9a–9h (2026-10-26), with Playwright walk-throughs in frontend/e2e/. See the build log in LEARNING.md.
1. **Drafts and submit** (C4): `draft` status, editable form, submit with the missing-documents list; the reference is assigned on submit.
2. **Returns** (C3): `returned` status, applicant message + internal minute, from Records (S1) and the desk (S2); resubmit. Reason required on Reject.
3. **Certificate dates and validity** (C10): issue dates on the form; Verify blocked by a certificate over six months old; a warning (not a block) at submission for one expiring within 30 days.
4. **Desk checks**: ECOWAS list ticks; HS rule confirmed-only (C5); earlier cases' reference, status and date for the duplicate flag; reject while flagged (C7).
5. **Dispatch** (C9, C11): Records' Outgoing queue and "Mark sent to GRA" with the dispatch date; `sent_to_gra` final; Close removed; "Corrected letter issued" on the timeline; the registry reference setting.
6. **PS support** (S3): checks summary, letter preview (never stored, marked as draft), return to desk.
7. **Walk-ins**: Records opens an application for an applicant; both are recorded.
8. **Notifications**: email on every applicant-visible status change and on return, through an outbox and a background sender. A fake sender for now `[CONFIRM: mail server]`.
9. **Frontend**: Next.js, login, a set-password page (reads `#token=`, 8j), date formatter, acting banner; A1 (facility letter part), A2, A3, S1 (with Outgoing), S2, S3, S11.

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
3. **Reject while a duplicate flag is open**: decided, still `[CONFIRM]`: allowed; the rejection reason resolves the flag. Returning while held is allowed too since 8l `[CONFIRM]`.
4. **Send to GRA and Close**: decided: Records dispatches and marks sent, with the dispatch date; no manual Close `[CONFIRM: unless GRA reports back]`.
5. **Reference numbers**: decided: a sequence per service per year, assigned at submission. The registry file reference on the letter is separate and stays a setting `[CONFIRM]`.
6. **Certificates within six months**: decided: computed from issue dates on the form.
7. **Absences and delegations**: decided: screen S11; recording for others by the `absence_recorder` role `[CONFIRM: PS's office, HR]`.
8. **Retiring `etls_application`**: approved, for chunk 3.

Questions from chunk 1, answered 2026-10-24:
- **Six months counted to which date?** Verify is blocked if any certificate is more than six months past its issue date (so: to the verification date). At submission the applicant is warned, not blocked, if one expires within 30 days. Whether GRA needs it still valid at clearance is not confirmed `[CONFIRM]` (C10).
- **The timeline after a cancelled letter?** Keep hiding only the cancel move. A corrected letter replacing one already sent to GRA shows "Corrected letter issued" when it is sent (C11).
