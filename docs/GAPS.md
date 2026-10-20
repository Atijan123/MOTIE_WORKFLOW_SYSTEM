# Gaps: backend vs. the screen spec

An audit of the backend (as of commit `2d0bc42`, step 6l) against docs/SCREENS.md. Nothing here is built yet; this is the list to review before building.

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
| Every application goes to Records first | **Built** | Both workflows start with a Records move: facility letter `submitted → originals_received` (alembic/versions/0015), ETLS application `submitted → with_minister` (0005/0012). Will need re-checking when drafts are added (see A2): "Submit" must land with Records, never further. |
| Applicants see plain status labels, never internal step names or staff names | **Missing** | `workflow_statuses` has one `name` ("Originals received by Records", "Signed by the PS"), which is staff wording. There's no applicant label, no one-line explanation, and no mapping. `GET /cases/{id}` gives applicants the internal `status.code` and `name`. |
| Staff case page shows history, newest first, with "acting for [position]" and the absence/delegation relied on | **Partial** | `GET /cases/{id}/history` (core/workflow/router.py `case_history`) returns every audit row with `details.as_position`, `details.on_behalf_of`, `details.basis`, `details.delegation_id`, `details.absence_ids`. Missing: newest-first order (it's oldest first); the actor's **name and post title** (only `actor_user_id`); the absence/delegation **dates** (only ids, and there's no `GET /absences/{id}` or `GET /delegations/{id}` a screen could use to look them up). |
| Acting banner ("You are acting for the Director … (absent 20th–24th October)") | **Missing** | The data exists: absences (`core.absences`), delegations (`core.delegations`), succession (`core/workflow/succession.py acting_successor()`). But no endpoint answers "for which posts am I acting right now, on what basis, until when?" `GET /auth/me` lists only your own posts. |
| Disabled actions explain why | **Partial** | `GET /cases/{id}` lists `available_actions` (with `requires_comment`). The reasons only appear *after* a failed attempt: `POST /cases/{id}/status` answers 409 listing every check problem (`checks.problems()`) or the on-hold flags. Missing: a dry run, i.e. each action with `blocked_by: [...]` computed without moving the case. |
| Returning needs a written reason, shown to the applicant | **Partial** | `workflow_transitions.requires_comment` (0022) can force a reason, and the engine refuses without one (422). Missing: there are **no "return to applicant" moves** in any workflow, no "returned" status, and comments are internal (applicants can't read history). A reason meant for the applicant needs to be marked as applicant-visible. |
| Dates in the Ministry format ("16th October, 2026") | **Partial** | `long_date()` in modules/etls/letter.py, used on the facility letter. The API returns ISO dates everywhere else, which is right for an API; the frontend needs the same formatter (none exists yet). |
| Reference numbers per service (`MOTIE/ETLS/FL/…`, `/AP/…`, `/CO/…`) | **Partial** | FL only, and only *on the letter*: `file_reference()` in modules/etls/letter.py, from `FACILITY_LETTER_REFERENCE_FORMAT`, using the **signing year**. Missing: a reference stored on the case **from submission** (A1 and A3 show it before any letter exists); AP and CO formats. See conflict C6. |
| Uploads: PDF/PNG/JPEG, max 10 MB, type from content | **Built** | core/documents/storage.py `save()`, `POST /cases/{id}/documents/{type}`; `MAX_UPLOAD_BYTES`. |
| Notifications: email applicants at each status change and on return | **Missing** | No email or notification code at all. Needs a mail server `[CONFIRM]` and a way to send without slowing the request (an outbox table and a background sender). |
| Queues show how long each case has waited at its current step | **Missing** | There is **no list endpoint for cases at all**: no `GET /cases`, no queue. `core.cases.updated_at` is set on every status change, so "waiting since" can be derived, but nothing exposes it. |
| Walk-ins: Records can create any application on behalf of an applicant, recorded as such | **Missing** | Only users with the applicant role (`workflows.start_role_id`) can open cases, and `cases.created_by` is the only person field. Needs an "applicant" separate from "entered by", and a Records path to create one. |

---

## 2. Applicant screens

### A1. Services and my applications

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Three service cards | **Partial** | Static content. Only the facility letter has an application endpoint (`POST /etls/facility-letters`). ETLS approval has a workflow but no form; certificate of origin has nothing. |
| Notice for a returned case, with reason and "Fix and resubmit" | **Missing** | No return moves, no returned status, no resubmission (see global rules). |
| Table of my cases: reference, goods, submitted date, applicant status label | **Missing** | No `GET /cases` for "my cases". Goods come from the module (`GET /etls/facility-letters/{id}`), one case at a time. No stored reference; no applicant label. |
| Selected case: timeline of applicant labels with dates | **Missing** | Applicants can't read history (`case_history` is staff only, on purpose: it holds internal minutes). Needs an applicant-safe timeline: status changes only, applicant labels, dates, and return reasons, with no names or comments. |

### A2. Facility letter application

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Importer: business name, address | **Built** | `importer_name`, `importer_address` (modules/etls/schemas.py `FacilityLetterForm`). |
| Goods: product, quantity (number), unit, HS code (optional) | **Built** | `product`, `quantity` (NUMERIC), `unit`, `hs_code` optional since step 6k. |
| Exporter: name, country, ETLS approval number, one or more product approval numbers, one or more certificate numbers | **Built** | `exporter_name`, `exporter_country`, `exporter_etls_approval_number`, `product_approval_numbers[]`, `certificate_of_origin_numbers[]`. |
| Documents checklist (the six documents, with the note to bring the original certificate) | **Built** | `GET /cases/{id}/documents` (core/documents/router.py): `applies`, `missing`, `original_required` (true for the certificate of origin). Names from `core.document_types` (0017). |
| Receipt "not known yet" **until the HS code is confirmed** | **Partial** | Shown as `"applies": null` when there's **no** code (step 6k). But a code the applicant *declared* already decides it (`hs_heading()` in modules/etls/service.py uses the declared code until one is confirmed). The spec says only the confirmed code decides. See conflict C5. |
| Save draft | **Missing** | `POST /etls/facility-letters` opens the case straight at `submitted`. There's no draft status, and the form can't be edited after creation (the app has no `UPDATE` on `etls.facility_letters` except the HS confirmation columns). |
| Submit disabled until required documents are uploaded, with a count of what's missing | **Missing** | Today documents can only be uploaded **after** submission (uploads need a case), and the check runs at Records' move. The `missing` flags exist to count from, but submit-after-upload needs the draft flow: draft case → uploads → an applicant "Submit" move guarded by `known_documents_complete`. See conflict C4. |

### A3. Status on a phone

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Reference | **Missing** | No case reference before signing (C6). |
| Goods, exporter | **Built** | `GET /etls/facility-letters/{id}` (applicant can read their own; core `get_case()` visibility). |
| Current applicant status label + one-line explanation | **Missing** | As in global rules. |
| Timeline | **Missing** | As in A1. |

### A4. ETLS approval application (ECOWAS form)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Part I, identity of enterprise (12 fields) | **Missing** | No `etls` approval tables. The `etls_application` workflow is opened by the generic `POST /cases` with **no form at all**. |
| Part II, products (one or more): description, HS tariff item, brand, origin criterion, value added % | **Missing** | Needs a products child table. The HS code validation from step 6g (`normalize_hs_code()`) can be reused. |
| Part III, manufacturing process | **Missing** | |
| Documents (application letter, ECOWAS form parts I–IV with blank-form link, registration, statutes, amortisation schedule, preferential treatment text if listed, tariff classification optional) | **Partial** | The requirements mechanism is built and data-driven (core.document_requirements with conditions; "only if listed" is a condition on a fact). Missing: these document types and requirement rows for this workflow, and "optional" documents (today a requirement either applies or not; there's no "accepted but never required"). |
| Note: bring a sample of each product to Records | **Missing** | Static text, but S4 needs "samples received" recorded by Records (see S4). |

### A5. Approval progress and approved products

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Applicant labels: Submitted → Accepted → Technical review → Factory visit → NAC decision → Sent to ECOWAS → Approved by ECOWAS | **Missing** | The workflow has none of the NAC or ECOWAS steps (conflict C1), and no applicant labels. |
| Factory visit notice with date | **Missing** | No inspection data (S6). |
| My approved products, with ECOWAS enterprise/product approval numbers and "Request a certificate of origin" | **Missing** | No approved products register. |
| Products still in progress | **Missing** | Decisions are per product (S7), but the engine tracks one status per case. See conflict C2. |

### A6. Certificate of origin request

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Choose an approved product from the register | **Missing** | No register, no CO workflow, no CO tables. |
| Auto-filled boxes 1, 3, 5, 6 from the register | **Missing** | |
| Entered boxes 2, 4, 7, 8; commercial invoice upload | **Missing** | Upload mechanism is built; the CO document types and requirements aren't. |
| Box 9 declaration (name, place, checkbox; date = submission date) | **Missing** | |
| Applicant labels: Submitted → … → Collected | **Missing** | |

---

## 3. Staff screens: facility letters

Spec route: Records (originals seen) → ETLS desk (verify) → PS (sign) → sent to GRA → closed.
Built route (0015, 0018, 0020–0022): `submitted` →(Records: Confirm originals received)→ `originals_received` →(desk: Verify / Reject)→ `verified` / `rejected` →(PS: Sign)→ `signed` →(desk: Send to GRA)→ `sent_to_gra` →(desk: Close)→ `closed`; plus PS "Cancel the signed letter" from `signed`/`sent_to_gra` back to `originals_received`. **The main route matches the spec.** Differences are listed per screen and in section 4.

### S1. Records queue

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Queue of all services, oldest first, with service, applicant, goods, days waiting | **Missing** | No list/queue endpoint (global rules). "Goods" lives in each module's tables, so the queue needs each module to supply a one-line summary (the same pattern as `facts.register()`). |
| Documents list with view links | **Built** | `GET /cases/{id}/documents`, `GET /cases/{id}/documents/{document_id}/file`. |
| "Original seen in person" on the certificate of origin | **Built** | `POST /cases/{id}/documents/{document_id}/original-seen` (core/documents/service.py `mark_original_seen()`), audited with the scan's checksum. |
| Accept, disabled until originals seen | **Built** (backend) / **Partial** (the "why") | Records' move has checks `known_documents_complete` and `originals_seen` (0018, 0021); the 409 says what's missing. Disabled-with-reason needs the dry run (global rules). |
| Return to applicant with reason | **Missing** | No such move. |

### S2. ETLS desk verification

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Duplicate certificate flag: which earlier case used the number, **its status and date** | **Partial** | `GET /cases/{id}/flags`: the flag's `details` has `numbers` and `earlier_case_ids` (modules/etls/service.py `_earlier_uses()`). The earlier cases' status and date aren't included; the screen would have to call `GET /cases/{id}` once per earlier case. |
| Finding (required) to clear | **Built** | `POST /cases/{id}/flags/{flag_id}/resolve` with a required `resolution`, desk post only (core/workflow/flags.py). |
| Or reject | **Partial** | `originals_received → rejected` exists, but **an open blocking flag stops every move, rejecting included** (step 6b decision). So the desk must clear the flag before rejecting. See conflict C7. Rejecting doesn't require a reason (`requires_comment` false). |
| Application summary | **Built** | `GET /etls/facility-letters/{id}`. |
| HS code: enter or confirm; whether the cement receipt applies | **Built** | `POST /etls/facility-letters/{id}/hs-code`; `applies` on the receipt in `GET /cases/{id}/documents`. |
| ECOWAS ETLS list checks as recorded ticks (exporter approval listed; product approval covers the goods; certificates within six months) | **Missing** | No "recorded tick" concept. Needs a generic case checklist (who ticked, when, audited) plus a transition check on Verify. The FL form has no certificate issue dates, so "within six months" can only be a tick, not a computed check `[CONFIRM]`. |
| Verify, disabled until flag cleared, HS confirmed, checks ticked, documents complete | **Partial** | Built: blocking flag, `hs_code_confirmed`, `documents_complete` on Verify (0020, 0021). Missing: the ECOWAS ticks, and the reasons-before-clicking dry run. |
| Return to applicant | **Missing** | |
| History panel | **Partial** | As in global rules. |

### S3. PS signs the letter

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Letters awaiting signature | **Missing** | No queue endpoint. |
| Summary of checks done (originals seen, ECOWAS list checked, no duplicates) | **Partial** | Available piecemeal: `original_seen_at` on the documents, flags (resolved/open). ECOWAS ticks don't exist. No single summary endpoint. |
| Letter preview in the Ministry's wording | **Missing** | The letter is only rendered at signing (`issue_letter()` effect). A preview needs `render_pdf()` without storing, clearly marked as a draft so it can't pass for the signed letter. The template and wording are built (step 6i). |
| Sign (stores the letter) | **Built** | PS move `verified → signed` with effect `issue_facility_letter` (0019); stored with checksum and template version (core/documents/issued.py). Acting for the PS works through delegation and succession. |
| Return to desk | **Missing** | No `verified → originals_received` move for the PS before signing. (The post-signing cancel does go back to the desk.) |
| Cancel and reissue for signed letters | **Built** | "Cancel the signed letter" with required reason (0022), `GET /etls/facility-letters/{id}/letters`, `.../letters/{letter_id}/file`, current letter at `.../letter.pdf`. |

---

## 4. Staff screens: ETLS approval

Spec route: Records (samples received) → Minister → PS → Director of Industry & Investment (signs and assigns; DPS Admin & Finance when absent) → officer (technical review and inspection) → NAC → ECOWAS submission → ECOWAS outcome → approved register.
Built route (`etls_application`, 0005 + 0012): `submitted` →(Records: Register and forward to the Minister)→ `with_minister` →(Minister: Minute to the PS)→ `with_ps` →(PS: Minute to the Director)→ `with_director` →(Director: Sign and assign to an officer)→ `with_officer` →(officer: Approve / Reject / Return to the Director)→ `approved` / `rejected` / `with_director`. **Matches the spec up to the officer; everything after is missing**, and the officer's three moves are placeholders that conflict with it (C1).

### S4. Minute a file (Minister, PS)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Summary: products with tariff items, criteria, value added; documents complete; samples received | **Missing** | No approval form (A4). No "samples received" record. Documents mechanism is built but not configured for this workflow. |
| Minute text | **Built** | The move's `comment` (up to 2000 characters), stored in the audit row. Visible to staff in history. |
| Minute to the next position (Minister → PS, PS → Director) | **Built** | Transitions in 0012; acting for an absent Minister or PS via succession (step 5d). |
| Return to Records | **Missing** | No `with_minister → submitted` or `with_ps → …` return moves. |

### S5. Sign and assign (Director, or DPS Admin & Finance acting)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Minutes so far | **Partial** | Comments in history (staff only, oldest first, actor ids only). |
| Choose officer; minute to officer | **Missing** | The move goes to *any* holder of the `industry_officer` post. Choosing **a person** needs a case assignment (e.g. `core.case_assignments`), and the officer's moves then limited to the assignee. |
| Sign and assign | **Built** | `with_director → with_officer`, `director_of_industry`; DPS Admin & Finance acts when the Director is absent (succession, ETLS only; see section 6). |
| Return to PS | **Missing** | |

### S6. Technical review (assigned officer)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Per-product finding (meets / query applicant / does not meet) | **Missing** | No products, no findings. |
| Cost price limits from part IV: four amounts entered, each shown as % of ex-factory cost against 20% / 10% / 3%, over-limit flagged | **Missing** | The four limits as data, not code `[CONFIRM]` which item has which limit. |
| Factory inspection: date (shown to applicant), team, report upload | **Missing** | Upload mechanism is built. `[CONFIRM]` inspections are by the NAC. |
| Recommendation; send to NAC (disabled until report uploaded); ask applicant for information | **Missing** | No NAC status, no "ask for information" (a return-to-applicant variant). The "disabled until report uploaded" part fits the existing `documents_complete` check once the report is a document type. |

### S7. NAC decisions (secretary)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Meeting date; downloadable meeting pack (PDF) | **Missing** | PDF generation exists (fpdf2, step 6e); no meeting entity, no pack. Also no NAC secretary post. |
| Decision per product: approve / not approve / defer, reason for not approve or defer | **Missing** | Per-product outcomes (C2). |
| Signed minutes upload; record decisions; approved products go to the portal holder; applicants told of other decisions | **Missing** | No portal holder post; no notifications. |

### S8. ECOWAS submission and outcome (portal holder)

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| NAC-approved products: download submission pack; mark as sent (date) | **Missing** | |
| ECOWAS decision per product: approved / not, enterprise and product approval numbers, notification date, letter upload | **Missing** | |
| Saving adds approved products to the register and notifies the applicant | **Missing** | No register; no notifications. CLAUDE.md says the ECOWAS portal goes through an adapter; this screen is manual entry, which needs no adapter yet. |

---

## 5. Staff screens: certificates of origin

Spec route: Records (complete) → ETLS desk (verify) → authorised officer certifies box 10 `[CONFIRM: Director]` → Customs certification recorded (box 11) → collected. **Nothing is built:** no workflow, tables, documents or register.

### S9. Certificate verification

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Comparison table (boxes 6, 5, 3, 4, 8) against register and invoice, each matching or flagged | **Missing** | Needs the register (S8) and the CO request (A6). The flag mechanism (core/workflow/flags.py) can carry mismatches. |
| Note for the exporter; verified (send for certification) or return to exporter | **Missing** | |

### S10. Certify, Customs and collection

| Item | Status | Backed by / what's missing |
| --- | --- | --- |
| Box 10 certified by the authorised officer, with date; certificate number `[CONFIRM: pre-printed]`; reprint only as "Duplicate" | **Missing** | The issue-once / never-re-render pattern (core/documents/issued.py) fits "reprint only as Duplicate" if the certificate is printed by the system. If it's a pre-printed form, the system records the number instead. |
| Box 11: export document model number, dated, Customs place, date certified by Customs | **Missing** | |
| Collection: who collected the single original and when | **Missing** | |
| Certificate details panel; valid until six months from issue | **Missing** | |
| One certificate covers one product | **Missing** | A rule for the CO form (one product per request). |

---

## 6. Stand-in rules and "acting for" in history

| Check | Status | Where |
| --- | --- | --- |
| Minister → PS → DPS (Admin & Finance) | **Built** | `core.succession_orders` seeded in alembic/versions/0013_succession_orders.py: `minister` rank 1 `permanent_secretary`, rank 2 `dps_admin_finance` (all workflows). Used by `acting_successor()` in core/workflow/succession.py. Tested in tests/core/test_acting_for.py (`test_minister_absent_ps_does_the_ministers_step`, and the Minister-and-PS-absent case). |
| PS → DPS Admin & Finance | **Built** | Same migration: `permanent_secretary` rank 1 `dps_admin_finance`. This also covers the facility letter: when the PS is away the DPS signs "For: Permanent Secretary" (tests/modules/etls/test_letter.py) and can cancel (test_letter_corrections.py). |
| ETLS: Director of Industry & Investment → DPS Admin & Finance | **Built**, with a caveat | Seeded **only for workflow `etls_application`**. Tested in tests/core/test_acting_for.py. Caveat: if the approval workflow is replaced by a new one (C1), or the Director certifies certificates of origin (S10), each new workflow needs its own succession row, or the DPS won't stand in there. |
| A delegation overrides succession | **Built** | `_permitted()` in core/workflow/service.py; tested. |
| History can be fetched with "acting for" | **Built** (data) / **Partial** (display) | `GET /cases/{id}/history` returns, per status change, `as_position`, `on_behalf_of` (the "acting for" post), `basis` (`own`/`delegation`/`succession`), `delegation_id` and `absence_ids`. Tested (step 5d). For the spec's display it still needs newest-first, names and titles, and absence/delegation dates inline (global rules). |

---

## 7. Built but unused by the screens, or conflicting with them

### Conflicts (the backend does something the spec doesn't, or differently)

- **C1. ETLS approval route stops at the officer.** `with_officer → approved | rejected | with_director` (officer moves) are placeholders from step 3b. The spec continues to NAC, ECOWAS submission, ECOWAS outcome and the register. The workflow is also called `etls_application` (spec: "ETLS approval"), isn't `opened_by_module`, and has no form. **Proposal:** a new module workflow `etls_approval` with the spec's statuses, retiring `etls_application`. It's only in dev, so it can be removed, but deleting is your call.
- **C2. Decisions are per product; the engine has one status per case.** NAC and ECOWAS decide each product separately, and a case can end with some products approved and others not. **Proposal:** the case status tracks the *file* (with NAC, with ECOWAS, done), and each product carries its own outcome in the module's tables. Applicant labels (A5) follow the file, and the product list shows each product's outcome.
- **C3. No return-to-applicant anywhere.** The spec returns from Records (S1), the desk (S2) and the officer (S6 "ask for information"), with the reason shown to the applicant (A1). Needs a `returned` status per workflow, transitions requiring a reason, a way to mark that reason applicant-visible, and an applicant "Resubmit" move.
- **C4. Documents are uploaded after submission, not before.** The spec's A2 needs drafts. **Proposal:** a `draft` initial status, the applicant's "Submit" as a move to `submitted` guarded by `known_documents_complete`, and the form editable only while in draft (or returned).
- **C5. Receipt decided by the declared HS code.** Built: the applicant's code decides until the desk confirms one. Spec: "not known yet until the HS code is confirmed". Following the spec is a one-line change in `hs_heading()`, and Records' check is already lenient about undecided documents.
- **C6. The reference is made at signing, from the signing year.** Spec screens show it from submission (A1, A3) and need AP and CO too. **Proposal:** `core.cases.reference`, assigned when the case is submitted, from a per-workflow format. The letter then prints the case's reference instead of making its own. `[CONFIRM]` whether numbers run per service per year (…/FL/2026/0001) or use the case id. **Watch:** letters already issued keep the reference printed on them.
- **C7. A blocking flag stops rejecting.** Spec S2 offers "clear the flag, or reject". Built: the desk must resolve the flag before rejecting. Either allow specific moves while on hold (a per-transition "allowed while on hold" column), or treat the resolution as the rejection reason. `[CONFIRM]` with the desk.
- **C8. History is oldest first** (spec: newest first). Trivial, but the frontend should rely on one order.

### Built but not used by any screen

- **`POST /cases`** (generic case opening): no screen uses it, and every service will open through a module form.
- **"Send to GRA" and "Close the file" moves** (desk): the spec's route names them, but no screen shows them. `[CONFIRM]` which screen, and who does them.
- **Recording absences and delegations** (`POST /absences`, `POST /delegations`, revoke/cancel): the spec relies on them (the acting banner, history) but has no screen for recording them. Without one, the stand-in rules can only be used through the API.
- **Assigning posts** (CLI `assign-position`): no screen; fine while ICT does it.
- **Placeholder posts and roles:** `director_of_trade`, `trade_officer` and the Directorate of Trade (0008, unused since 0012); the role list (`director`, `officer`, `absence_recorder`, ...) predates positions and isn't shown anywhere.
- **Letter field `$hs_code`**: available to the template, not in the Ministry's wording.
- **Facts `product`, `unit`, `exporter_country`**: supplied for document conditions; no rule uses them since step 6g.
- **Desk "Reject" without a reason**: built, but the spec's global "written reason" rule suggests `requires_comment` should be on.

---

## 8. Proposed build order

Each chunk is a few small steps, with tests and a LEARNING.md entry each, as usual. Chunks 1 and 2 finish the facility letter screens end to end; the rest follow the spec's order.

### Chunk 1: shared foundations the facility letter screens need (backend)
1. **Applicant status labels**: `applicant_label` and `applicant_explanation` on `workflow_statuses`, seeded for the facility letter `[CONFIRM wording]`; applicants get labels, never internal names.
2. **Case reference at submission**: `core.cases.reference`, per-workflow format; the letter prints it (C6).
3. **Lists and queues**: `GET /cases` for "my cases" (applicant), and a staff queue of cases where I can make a move (own post, delegation or succession), oldest first, with days waiting and a module-supplied one-line summary (goods).
4. **Actions with reasons**: `available_actions` gains `blocked_by` (checks and on-hold flags run as a dry run).
5. **History for screens**: newest first, actor name and post title, and acting-for with the absence or delegation dates. Plus an applicant-safe timeline: labels, dates, return reasons only.
6. **"Am I acting?"**: `GET /auth/me/acting` for the banner (post, basis, absence or delegation dates).

### Chunk 2: facility letter screens end to end
1. **Drafts and submit** (A2, C4): `draft` status, editable form, applicant "Submit" with the missing-documents count.
2. **Return to applicant and resubmit** (C3): `returned` status, reason required and applicant-visible; from Records (S1) and the desk (S2). A1's notice.
3. **ECOWAS list ticks** (S2): a generic recorded checklist per case, plus a transition check on Verify.
4. **Desk details** (S2): earlier cases' status and date in the duplicate flag; reject while flagged and reject reason (C7, after confirming); HS rule follows the spec (C5).
5. **PS screen support** (S3): the checks summary, the letter preview (marked as a draft, never stored), and "Return to desk".
6. **Walk-ins**: Records opens an application for an applicant; the case records both who it's for and who entered it.
7. **Notifications**: email on every status change and on return, through an outbox table and a background sender. Needs the Ministry's mail server `[CONFIRM]`; tested with a fake sender.
8. **Frontend**: Next.js set-up, login, the Ministry date formatter, the acting banner; then A1 (facility letter part), A2, A3, S1, S2, S3, each against the API above.
9. **Send to GRA / close**: once you confirm where they belong on screen.

### Chunk 3: ETLS approval (A4, A5, S4–S8)
1. New `etls_approval` workflow with the spec's statuses and labels (C1), succession row for the Director moved to it, returns to Records and the PS.
2. Approval form: enterprise (part I), products (part II), process (part III); documents and conditional ones; "samples received" recorded by Records.
3. Assigning a named officer (S5).
4. Technical review per product, cost price limits as data, inspection and report (S6).
5. NAC meetings, per-product decisions, meeting pack and signed minutes (S7, C2).
6. ECOWAS submission and outcomes, the approved products register (S8), applicant's approved products (A5).
7. Frontend screens A4, A5, S4–S8.

### Chunk 4: certificates of origin (A6, S9, S10)
1. CO workflow (one product per certificate), labels, reference `MOTIE/ETLS/CO/…`, succession for the certifying officer.
2. Request form from the register (boxes 1–9), invoice upload.
3. Verification comparison and flags (S9).
4. Certification (box 10, numbering, duplicate reprints), Customs (box 11), collection, six-month validity (S10).
5. Frontend screens A6, S9, S10.

---

## Questions this audit raised

These are new; I'll copy them into LEARNING.md's Open questions when we build the chunk that needs them.

1. **Applicant labels for the facility letter**: the spec lists them for approvals (A5) and certificates (A6), not for facility letters. What should applicants see at each step?
2. **Returning:** which reason text is shown to the applicant? Is it the whole comment, or a separate "message to applicant" next to an internal minute?
3. **Reject while a duplicate flag is open** (C7): allowed?
4. **Send to GRA and Close:** which screen, and which post?
5. **Reference numbers:** a sequence per service per year, or the case id? Assigned at submission or when Records accepts?
6. **Certificates "within six months of issue"** (S2): a tick by the desk, or should the form ask for each certificate's issue date so the system can check it?
7. **Absences and delegations:** who records them, and on which screen? The spec has none.
8. **Retiring `etls_application`** (C1): OK to replace it with a new `etls_approval` workflow? Dev data only.
