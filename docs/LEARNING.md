# Learning doc — MOTIE Workflow Platform

Kept up to date by Claude Code after every build step. Read the newest build log entry, then work through its concepts and "Check yourself" questions.

## Contents

1. Build log
2. Concepts
3. Decisions
4. Open questions
5. Check yourself

---

## 1. Build log

Newest first. Each entry: what was built, the files involved, how to run and test it.

### Step 8e — Records sends letters to GRA; "Sent to GRA" is final (2026-10-25)
Chunk 2, step 5.

**Built:**
- **Records' "Mark sent to GRA".** The move `signed → sent_to_gra` now belongs to the Records post (it was the desk's), and needs the dispatch date. **`POST /etls/facility-letters/{id}/sent-to-gra`** with `{"dispatched_on": "2026-10-25"}` does both in one transaction:
  - it records the date in the new table `etls.facility_letter_dispatches`, against the exact issued letter (audit row `case.letter_dispatched` with its checksum);
  - it makes the move.

  The date can't be in the future or before the letter was signed. Permission and readiness are asked first, using the engine's own rules. The generic `POST /cases/{id}/status` can't make the move without a date, because the check `etls_dispatch_recorded` finds no dispatch.
- **Records' Outgoing tab** is `GET /cases/queue?status=signed` as Records. The letters listing (`GET /etls/facility-letters/{id}/letters`) shows each letter's `sent_to_gra_on`.
- **"Sent to GRA" is final; "Close the file" and `closed` are gone** (migration 0030 refuses to run if a case is still in `closed`).
- **Correction moves** (`workflow_transitions.is_correction`): cancelling a signed letter may leave a final status, and doesn't count as work in anybody's queue. Before, every signed letter also sat in the PS's queue, because the PS *could* cancel it. The workflow shape test now allows only corrections out of a final status.
- **Checks the dry run can't judge** (`transition_checks.in_dry_run = false`): the dispatch-date check is about something sent with the click, so `blocked_by` leaves it out (otherwise the button would always look disabled). The move itself still runs it.
- **"Corrected letter issued" (C11).** `workflow_statuses.applicant_label_corrected` is the timeline's wording when a case comes back to a status that a hidden move had taken it away from. A letter cancelled *after* it reached GRA, then corrected and sent, reads "Corrected letter issued". One cancelled before it was sent reads "Letter sent to GRA" as normal.
- **The registry reference.** The setting `FACILITY_LETTER_REFERENCE_FORMAT` is now documented as the Ministry's registry file reference, defaulting to `ADM 151/420/01/PART IV` `[CONFIRM]`. Download names use the case reference instead (`facility-letter-MOTIE-ETLS-FL-2026-0001.pdf`), because the registry reference is the same on every letter.

**Files:** backend/alembic/versions/0030_dispatch_to_gra.py, backend/app/modules/etls/letter.py (`mark_sent_to_gra()`, `_check_dispatch_recorded()`, `download_name()`), backend/app/modules/etls/models.py (`FacilityLetterDispatch`), backend/app/modules/etls/router.py, backend/app/modules/etls/schemas.py, backend/app/core/workflow/queues.py, backend/app/core/workflow/history.py (`applicant_timeline()`), backend/app/core/workflow/checks.py, backend/app/core/workflow/models.py, backend/app/core/workflow/router.py (`case_out()`), backend/app/core/config.py, backend/tests/modules/etls/test_dispatch.py, backend/tests/core/test_workflow_definitions.py, backend/tests/support.py (`send_to_gra()`)
**Try it:**
- Sign a letter. As `records@motie.test`, `GET /cases/queue?status=signed` lists it; as `ps@motie.test`, `GET /cases/queue` doesn't.
- `POST /etls/facility-letters/{id}/sent-to-gra` with today's date: the case is "Sent to GRA", final, with no actions left.
- As the PS, cancel it with a reason, verify and sign again, send it again. The applicant's `GET /cases/{id}/timeline` ends "Corrected letter issued".
- If `alembic upgrade head` refuses because of `closed` cases on your dev database, run `bash scripts/reset-dev.sh`.
- `docker compose run --rm tools pytest tests/modules/etls/test_dispatch.py -v`
**New concepts:** none new; it reuses checks, effects and the timeline rules.

### Step 8d — The desk's checks: ECOWAS ticks, the confirmed HS code, duplicates, rejecting while held (2026-10-24)
Chunk 2, step 4.

**Built:**
- **Recorded ticks** (core, backend/app/core/workflow/checklist.py). `core.checklist_items` lists what an officer ticks at a step. For the facility letter that's the two ECOWAS ETLS list checks at the desk: the exporter's approval is listed, and the product approval covers the goods. `core.case_ticks` records who ticked each one and when.
  - **`GET /cases/{id}/checklist`** (staff) lists the items with their ticks.
  - **`PUT /cases/{id}/checklist/{code}`** with `{"ticked": true}` or `false` ticks or unticks. Both are audited (`case.ticked`, `case.unticked`).
  - Only whoever may make the step's move may tick (the desk, or someone acting for it), and only items of the case's current step.
  - The desk's Verify has the new check `checklist_complete`; `blocked_by` names any unticked item.
  - The returns have the effect `clear_checklist`, so a resubmitted application is checked from scratch.
- **Only the confirmed HS code decides the receipt (C5).** `hs_heading()` ignores the applicant's declared code. Until the desk confirms, the cement receipt is "not known yet" (`applies: null`). So neither Submit nor Records waits for it, and the desk's strict documents check on Verify asks for it once a 2523 code is confirmed.
- **`GET /etls/facility-letters/{id}/duplicates`** (staff): for each certificate number on this case that another submitted case also used, those cases' reference, current status, submission date and importer. Read live, so the desk sees e.g. that the earlier case was since rejected.
- **A flag holds the case at its own post's step.** The duplicate flag is for the desk, so it now stops only the desk's moves. Records can still receive the originals, and the case reaches the desk. Before, it blocked every move, so a flagged case could never get to the desk.
- **Reject while held (C7).** The new column `workflow_transitions.allowed_on_hold` lets a move go ahead despite its post's open flags. The engine then resolves those flags with the move's reason: the internal minute, or else the message to the applicant. The resolution is recorded as "Reject: ..." with `by_move` in the audit row. It's set on the desk's Reject only; Return to applicant is still held.

**Files:** backend/alembic/versions/0029_desk_checks.py, backend/app/core/workflow/checklist.py, backend/app/core/workflow/flags.py (`holding()`, `resolve_by_move()`), backend/app/core/workflow/service.py (`what_blocks()`, `change_status()`), backend/app/core/workflow/models.py (`ChecklistItem`, `CaseTick`), backend/app/core/workflow/router.py, backend/app/core/workflow/schemas.py, backend/app/modules/etls/service.py (`hs_heading()`, `other_uses()`), backend/app/modules/etls/router.py, backend/app/modules/etls/schemas.py, backend/tests/modules/etls/test_desk_checks.py, backend/tests/support.py (`ready_to_verify()`), and the tests that verify a letter
**Try it:**
- Take a case to the desk. `GET /cases/{id}/checklist` as `desk@motie.test`: two unticked items. The Verify action's `blocked_by` names them. `PUT /cases/{id}/checklist/ecowas_exporter_listed` with `{"ticked": true}`, and the other one, and they go.
- Submit two applications with the same certificate number. The second reaches the desk; `GET /etls/facility-letters/{id}/duplicates` shows the first. Reject it with a minute: `GET /cases/{id}/flags` shows the flag resolved as "Reject: ...".
- `docker compose run --rm tools pytest tests/modules/etls/test_desk_checks.py -v`
**New concepts:** Recorded ticks (attestations)

### Step 8c — Certificate issue dates, and the six-month rule (2026-10-24)
Chunk 2, step 3.

**Built:**
- **Each certificate of origin has an issue date.** The form's `certificate_of_origin_numbers` (a list of strings) became **`certificates_of_origin`**: a list of `{"number", "issued_on"}`. The date is required and can't be in the future. Responses add **`expires_on`**, six calendar months after `issued_on`. It's stored in the new column `etls.facility_letter_certificates.issued_on`; it's empty only on applications from before this step.
- **Verify is blocked by an expired certificate.** The new check `etls_certificates_valid` on the desk's Verify fails while any certificate is past its expiry date (or has no date). The desk's `blocked_by` says which one, e.g. "certificate of origin SN-CO-1 expired on 16th April, 2026 (issued 16th October, 2025)". On the expiry day itself it's still valid.
- **Warning-only checks.** `core.transition_checks.warn_only` turns a check's findings into **warnings**: listed on the action as `warnings` (next to `blocked_by`), recorded in the move's audit row as `"warnings"`, but never stopping the move. The first one, `etls_certificates_expiring` on Submit and Resubmit, warns when a certificate expires within 30 days, or already has.
- **`app/core/dates.py`**: `long_date()` moved here from the letter code (`letter.long_date` still works), plus `add_months()`, which handles month ends: 31st August + 6 months = 28th February.

**Files:** backend/alembic/versions/0028_certificate_validity.py, backend/app/core/dates.py, backend/app/core/workflow/checks.py (`problems()`, `warnings()`), backend/app/core/workflow/service.py (`what_warns()`, `change_status()`), backend/app/core/workflow/router.py, backend/app/core/workflow/schemas.py, backend/app/core/workflow/models.py, backend/app/modules/etls/schemas.py (`CertificateOfOrigin`, `CertificateOut`), backend/app/modules/etls/service.py (`certificate_expiry()`, `_check_certificates_valid()`, `_check_certificates_expiring()`), backend/app/modules/etls/models.py, backend/app/modules/etls/router.py, backend/app/modules/etls/letter.py, backend/tests/modules/etls/test_certificate_validity.py, backend/tests/support.py (`certificate()`)
**Try it:**
- Start a draft whose certificate was issued five and a half months ago: `"certificates_of_origin": [{"number": "SN-CO-1", "issued_on": "2026-05-10"}]`. Upload the documents. `GET /cases/{id}`: the Submit action has an empty `blocked_by` and one entry in `warnings`.
- Submit, take it through Records, and once the date has passed, the desk's Verify is blocked with the expiry date.
- `docker compose run --rm tools pytest tests/modules/etls/test_certificate_validity.py -v`
**New concepts:** Blocking checks and warnings

### Step 8b — Returning an application, and resubmitting it (2026-10-24)
Chunk 2, step 2.

**Built:**
- **Two texts on a move.** `POST /cases/{id}/status` takes `applicant_message` (what the applicant is told) next to `comment` (the internal minute, staff only). Both go in the move's audit row. A move with the new column `requires_applicant_message` refuses to go without the message (422). A message sent on a move that doesn't take one is also refused (422, `MessageNotExpected`), so text written for the applicant can't silently disappear. Each action in `available_actions` says `requires_applicant_message`, so the screen knows to show the message box.
- **A `returned` status** for facility letters (label "Returned: action needed"), editable by the applicant like a draft.
- **"Return to applicant"** for Records (from `submitted`) and the ETLS desk (from `originals_received`). The minute is optional, the message required.
- **The applicant's "Resubmit"** (`returned → submitted`, timeline wording "Resubmitted"). It has the same check and effects as Submit: the reference stays, and the duplicate check runs again for any newly typed numbers. A resubmitted case goes back to Records first, like every application.
- **"Reject" needs a message too**: the applicant is told why.
- **The applicant sees the message** in three places:
  - `applicant_message` on `GET /cases/{id}`;
  - on their row in `GET /cases` (the "Fix and resubmit" notice);
  - on the timeline entry, which gained a `message` field.

  It's the message of the move that put the case where it is now (`current_message()` in backend/app/core/workflow/history.py), so the notice goes away once they resubmit. The minute is never in any of these.
- **Changing the goods after a return clears the desk's confirmed HS code** (recorded as `hs_code_confirmation_cleared` in the form's audit row), because it was confirmed for the goods as they were.

**Files:** backend/alembic/versions/0027_returns.py, backend/app/core/workflow/service.py (`change_status()`), backend/app/core/workflow/errors.py, backend/app/core/workflow/history.py (`current_message()`, `applicant_timeline()`), backend/app/core/workflow/queues.py, backend/app/core/workflow/router.py, backend/app/core/workflow/schemas.py, backend/app/modules/etls/service.py (`update_form()`), backend/tests/modules/etls/test_returns.py, backend/tests/support.py (`move()` takes `applicant_message`)
**Try it:**
- Submit a facility letter as the applicant. As `records@motie.test`: `POST /cases/{id}/status` with `{"to_status": "returned", "applicant_message": "The invoice is unreadable.", "comment": "Third time"}`.
- As the applicant: `GET /cases` shows the message on that row; `GET /cases/{id}/timeline` ends with "Returned: action needed" and the message, but no minute.
- Fix the form (`PUT /etls/facility-letters/{id}`), then `{"to_status": "submitted"}`: same reference, and it's back in Records' queue.
- `docker compose run --rm tools pytest tests/modules/etls/test_returns.py -v`
**New concepts:** none. It's the same "what applicants see is separate data" idea as the labels (step 7a).

### Step 8a — Drafts, and the applicant's "Submit" (2026-10-24)
Chunk 2, step 1.

**Built:**
- **Every facility letter starts as a draft.** `POST /etls/facility-letters` now opens the case at the new initial status `draft` (applicant label "Draft"), with **no reference yet**. The applicant uploads documents to it as before.
- **`PUT /etls/facility-letters/{id}`** replaces the whole form while the case is a draft. Only the applicant may do it (others get 403, or 404 if it isn't their case), and only in a status marked `applicant_editable` (409 otherwise). The audit row `case.form_updated` lists each changed field, before and after. Saving an unchanged form writes nothing.
- **"Submit" is a workflow move** (`draft → submitted`), made through the usual `POST /cases/{id}/status` with `{"to_status": "submitted"}`. It's the first move that belongs to **the applicant rather than a post**:
  - a new column `workflow_transitions.by_applicant`, with `required_position_id` left empty (a database check keeps the two in step);
  - `_permitted()` in backend/app/core/workflow/service.py lets only the case's applicant make such moves (`acts_as_applicant()`), never by delegation or succession;
  - the audit row says `"basis": "applicant"` and has no `as_position`.
- **Submit is disabled until the documents are in.** The move carries the `known_documents_complete` check, so the Submit action's `blocked_by` lists what's missing (the screen shows the count).
- **The reference is given at submission**, by a new core effect `assign_reference` on the Submit move (audit row `case.reference_assigned`). Drafts are numbered in the order they're *submitted*. A resubmitted case (step 8b) keeps its number.
- **The duplicate certificate check moved to Submit** (effect `etls_check_duplicate_certificates`). A draft's numbers don't count as used, and a resubmission only flags numbers no open flag covers yet.
- **`status.editable`** in every status view tells the screen whether the form can still be changed.

**Files:** backend/alembic/versions/0026_drafts.py, backend/app/core/workflow/models.py, backend/app/core/workflow/service.py (`acts_as_applicant()`, `_permitted()`, `open_case()`, `_assign_reference()`), backend/app/core/workflow/schemas.py, backend/app/modules/etls/service.py (`create_draft()`, `update_form()`, `check_duplicates()`), backend/app/modules/etls/router.py, backend/tests/support.py (`create_draft()`, `upload_required()`, `submit()`, `submitted_case()`), and the facility letter tests in tests/core and tests/modules/etls
**Try it:**
- As `applicant@motie.test`, `POST /etls/facility-letters`: `status_label` is "Draft" and `reference` is null.
- `GET /cases/{id}`: the "Submit" action's `blocked_by` lists the five missing documents. Upload them (`POST /cases/{id}/documents/{type}`) and it's empty.
- `PUT /etls/facility-letters/{id}` with a different quantity, then as `desk@motie.test` `GET /cases/{id}/history`: a `case.form_updated` row with `{"quantity": {"from": "1200.5", "to": "900"}}`.
- `POST /cases/{id}/status` with `{"to_status": "submitted"}`: the case now has `MOTIE/ETLS/FL/2026/000n`, and appears in Records' queue.
- `docker compose run --rm tools pytest tests/modules/etls/test_facility_letter.py tests/core/test_case_references.py -v`
**New concepts:** Drafts and submission

### Step 7f — The acting banner and the absences screen views (2026-10-20)
Chunk 1, step 6 (the last).

**Built** (backend/app/core/workflow/acting.py):
- **`GET /acting`**, the banner on every staff screen: the posts I'm acting for *today*. Each entry has the post and title, the basis (`delegation` or `succession`), the workflows it covers (`null` = all), and either the absences it rests on (whose, from when to when) or the delegation's dates. Empty when I'm acting for nobody. It asks the engine's own rules per workflow (`acting_successor()`, `is_delegated_away()`), so the banner and the buttons agree. E.g. the DPS covers an absent Director for ETLS approvals only.
- **`GET /acting/for-me`** (S11, "who acts for me"): for each of my posts, my current and upcoming delegations (with their ids, for "revoke") and the succession line per workflow, with the names of the people holding each post.
- **`GET /absences/current`** (S11, the list): everyone away now or later, with their posts, soonest first, for all staff. The **reason** is shown only to the person themselves, whoever recorded it, and recorders: reasons can be personal. Applicants get 403.

Recording, cancelling, delegating and revoking already existed (steps 4d and 5c). `_may_record_for_others()` in backend/app/core/workflow/absence.py became public (`may_record_for_others()`), because the new list uses it too.

**Files:** backend/app/core/workflow/acting.py, backend/app/core/workflow/acting_router.py, backend/app/core/workflow/absence_router.py (`/absences/current`), backend/app/core/workflow/absence.py, backend/app/core/workflow/schemas.py, backend/app/main.py, backend/tests/core/test_acting_views.py
**Try it:**
- As `ps@motie.test`, `POST /absences` for today; then as `dps@motie.test`, `GET /acting` shows the Permanent Secretary, by succession, with the PS's dates.
- As `director@motie.test`, `GET /acting/for-me`: one line, for `etls_application`, with the DPS.
- As `desk@motie.test`, `GET /absences/current`: the PS's absence, without the reason.
- `docker compose run --rm tools pytest tests/core/test_acting_views.py -v`
**New concepts:** none.

**Chunk 1 is done.** Next is chunk 2 in docs/GAPS.md: the facility letter screens end to end.

### Step 7e — History for screens, and the applicant's timeline (2026-10-20)
Chunk 1, step 5.

**Built** (backend/app/core/workflow/history.py):
- **`GET /cases/{id}/history`** (staff) is now **newest first**. Each entry adds:
  - `actor_name`;
  - `actor_title`: the post they acted from;
  - `acting_for` when they made another post's move: the post and its title ("acting for the Permanent Secretary"), the basis (`succession` or `delegation`), and either the **absences** relied on (whose, and from when to when) or the **delegation** (from which post to which, with its dates).

  The raw `details` are still there.
- **`GET /cases/{id}/timeline`** (anyone who can see the case): the applicant's view, oldest first, **labels and dates only**:
  - each status change shows its move's applicant wording ("Originals checked") or the new status's label (step 7a);
  - hidden moves (cancelling a letter) are left out;
  - a label repeating the one before it is shown once, so three internal minutes read "Accepted by the Ministry" once;
  - uploads, flags and letters aren't on it.

Nothing new is stored: both are read from the audit log, looking up names, titles, absences and delegations in a few batch queries. Several older tests read the history by position; they now say whether they read it newest or oldest first.

**Files:** backend/app/core/workflow/history.py, backend/app/core/workflow/schemas.py (`AuditEventOut`, `ActingForOut`, `TimelineEntryOut`), backend/app/core/workflow/router.py (`case_history`, `case_timeline`), backend/tests/core/test_history.py, and older tests in tests/core and tests/modules/etls that index the history
**Try it:**
- Mark `ps@motie.test` absent, have `dps@motie.test` sign a letter, then `GET /cases/{id}/history` as the desk: the signing row has `"acting_for": {"title": "Permanent Secretary", "basis": "succession", "absences": [{"person": "Dev Permanent Secretary", "starts_on": ..., "ends_on": ...}]}`.
- As the applicant, `GET /cases/{id}/timeline`: `Submitted`, `Originals checked`, `Awaiting signature`, `Letter signed`.
- `docker compose run --rm tools pytest tests/core/test_history.py -v`
**New concepts:** none (the audit log from step 3a, read two ways).

### Step 7d — Disabled actions explain why (2026-10-20)
Chunk 1, step 4.

**Built:** on `GET /cases/{id}`, every available action now has `blocked_by`: the reasons it can't be pressed right now, or `[]` when it can. Examples: `["Invoice is missing", "the original certificate of origin hasn't been marked as seen"]`, or `["On hold: Certificate of origin number(s) already used ..."]`.

It's a **dry run** of what `change_status()` would refuse with, in the same order: open blocking flags, then the move's checks (`what_blocks()` in backend/app/core/workflow/service.py). Nothing changes: no status, no audit row. That's safe because checks only read, a rule now written into backend/app/core/workflow/checks.py.

Two things aren't in it: a missing reason for moves that need one (that's a field to fill, shown by `requires_comment`), and effects (they only run on a real move). In queues `blocked_by` is `null`: running every check for every row would make the queue slow, and the case page is where the button is.

**Files:** backend/app/core/workflow/service.py (`what_blocks()`), backend/app/core/workflow/checks.py (the read-only rule), backend/app/core/workflow/schemas.py (`ActionOut.blocked_by`), backend/app/core/workflow/router.py, backend/tests/core/test_blocked_actions.py, and three tests that compare actions exactly
**Try it:**
- Submit a facility letter, then as `records@motie.test` `GET /cases/{id}`: the accept action lists every missing document. Upload them and look again: only the original certificate remains.
- `docker compose run --rm tools pytest tests/core/test_blocked_actions.py -v`
**New concepts:** none. It reuses A registry of named checks; a check is now also run as a preview.

### Step 7c — Lists and queues (2026-10-20)
Chunk 1, step 3.

**Built:**
- **`GET /cases`**, the applicant's "my applications" (A1): the cases I applied for, newest first.
- **`GET /cases/queue`**, a staff member's queue (S1, S2, S3): every open case where I can make a move *right now*, by my own post, a delegation or the succession order, longest-waiting first. `?status=signed` (or `?workflow=...`) narrows it, e.g. for Records' Outgoing tab in chunk 2. Applicants get 403.
- Each row has the reference, service name, status (labels for applicants, as in step 7a), submitted date, `status_since` and **`days_waiting`**, the applicant's name (staff only), a one-line `summary` and, in a queue, the moves I can make (with `on_behalf_of` when acting for someone).
- **`core.cases.status_changed_at`** (migration `0025`): when the case reached its current step, set only by the engine. `updated_at` would have been reset by editing a draft (chunk 2).
- **Summaries from modules:** backend/app/core/workflow/summaries.py, the same plug-in pattern as facts and checks. ETLS registers "Roofing sheets, 1200.5 tonnes" (`facility_letter_summaries()` in backend/app/modules/etls/service.py). It takes many case ids at once, so a queue costs one query per module.

**How the queue decides** (backend/app/core/workflow/queues.py `queue()`):
1. SQL narrows to open cases whose next step belongs to a post I *might* act as: mine, any delegated to me today, any whose succession line names one of mine.
2. For each, the engine's own `available_transitions()` gives the final answer.

So the queue and the case page's buttons can never disagree.

**Files:** backend/alembic/versions/0025_status_changed_at.py, backend/app/core/workflow/queues.py, backend/app/core/workflow/summaries.py, backend/app/core/workflow/models.py (`status_changed_at`, index), backend/app/core/workflow/service.py, backend/app/core/workflow/schemas.py (`CaseSummaryOut`), backend/app/core/workflow/router.py (`my_cases`, `my_queue`, `_action_out()`), backend/app/modules/etls/service.py, backend/tests/core/test_queues.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- As `applicant@motie.test`, submit two facility letters and `GET /cases`. As `records@motie.test`, `GET /cases/queue`: both, with `days_waiting: 0`. Accept one: it leaves Records' queue and appears in `desk@motie.test`'s.
- Mark the PS absent (`POST /absences` as `ps@motie.test`), and the DPS's queue picks up letters awaiting signature, each action marked `"on_behalf_of": "permanent_secretary"`.
- `docker compose run --rm tools pytest tests/core/test_queues.py -v`
**New concepts:** Narrow in SQL, decide in code

### Step 7b — Case reference numbers (2026-10-20)
Chunk 1, step 2.

**Built:** every case gets a tracking number when it's submitted: `MOTIE/ETLS/FL/2026/0001` for facility letters, `MOTIE/ETLS/AP/2026/0001` for approvals, a sequence per service per year (migration `0024`):
- `core.workflows.reference_prefix` (required, unique) says how a workflow's cases are numbered `[CONFIRM]` format.
- `core.reference_counters` holds the last number used per workflow per year. `next_reference()` in backend/app/core/workflow/service.py takes the next one with a single upsert (`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`).
- `core.cases.reference` and `submitted_at`: set together (a check constraint says so). Today that's in `open_case()`, because opening a case *is* submitting it; with drafts (chunk 2) it moves to "Submit".
- `GET /cases/{id}` and `GET /etls/facility-letters/{id}` show `reference`; the `case.created` audit row records it.
- Existing dev cases got numbers in the order they were opened.

This is **not** the reference printed on the letter: that's the Ministry's registry file reference, still the `FACILITY_LETTER_REFERENCE_FORMAT` setting (SCREENS.md, global rules).

**Files:** backend/alembic/versions/0024_case_references.py, backend/app/core/workflow/models.py (`Workflow.reference_prefix`, `Case.reference`, `Case.submitted_at`, `ReferenceCounter`), backend/app/core/workflow/service.py (`next_reference()`, `open_case()`), backend/app/core/workflow/schemas.py, backend/app/core/workflow/router.py, backend/app/modules/etls/router.py, backend/app/modules/etls/schemas.py, backend/tests/core/test_case_references.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`, then `docker compose exec db psql -U motie -d motie -c "SELECT id, reference, submitted_at FROM core.cases ORDER BY id"`.
- Submit two facility letters: `0001`, `0002` (or the next numbers this year).
- `docker compose run --rm tools pytest tests/core/test_case_references.py -v`. The last test opens two real connections and shows the second submission *waiting* for the first.
**New concepts:** Gapless numbering (a counter row, not a sequence)

### Step 7a — Applicant status labels (2026-10-20)
Chunk 1 of docs/GAPS.md (shared foundations), step 1.

**Built:** applicants now see plain labels, never the internal step code or staff wording (migration `0023`):
- every status has a required `applicant_label` and an optional `applicant_explanation`, e.g. "Submitted" / "Bring the original certificate of origin to Records.";
- a move can have its own timeline wording, `applicant_event`: Records' accept reads "Originals checked", although the case then shows "Being verified";
- a move can be hidden from applicants, `applicant_visible = false`: the PS's "Cancel the signed letter", so the case simply shows "Being verified" again.

In the API, `status` in `GET /cases/{id}` now has `label` and `explanation`. For applicants, `code` and `name` are `null` (`status_view()` in backend/app/core/workflow/service.py). `GET /etls/facility-letters/{id}` gains `status_label`, and its `status` (the code) is `null` for applicants.

The facility letter labels are SCREENS.md A2's. "Draft" and "Returned: action needed" come with those statuses in chunk 2. The explanations are my placeholders `[CONFIRM]`. The retiring `etls_application` got labels from A5 as far as its steps go.

**Files:** backend/alembic/versions/0023_applicant_labels.py, backend/app/core/workflow/models.py, backend/app/core/workflow/schemas.py (`StatusOut`), backend/app/core/workflow/service.py (`status_view()`), backend/app/core/workflow/router.py, backend/app/modules/etls/router.py, backend/app/modules/etls/schemas.py, backend/tests/core/test_applicant_labels.py, and four older tests that read the applicant's status code
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- As `applicant@motie.test`, `GET /cases/{id}`: `"status": {"code": null, "name": null, "label": "Submitted", ...}`. As `desk@motie.test`, the same case shows the code too.
- `docker compose run --rm tools pytest tests/core/test_applicant_labels.py -v`
**New concepts:** none. It's the same separation as the letter template: *what* people see is data, not code.

### Docs — Answers on certificate validity and the timeline (2026-10-24)
**Built:** nothing; the docs catch up with two answers from you, before chunk 2.
- **Six-month check:** the desk's Verify is blocked if any certificate of origin is more than six months past its issue date. At submission the applicant is only *warned* if one expires within 30 days. GRA needing it valid at clearance is confirmed.
- **Timeline after a cancelled letter:** only the cancel move stays hidden. If the cancelled letter had already gone to GRA, the corrected letter's "sent to GRA" reads "Corrected letter issued".

docs/GAPS.md now says chunk 1 is done, and its marks include what chunk 1 built (labels, references, queues, `blocked_by`, history, timeline, the acting and absence views). Chunk 2's backend is steps 8a–8h.
**Files:** docs/GAPS.md, docs/SCREENS.md (A2, S2), docs/LEARNING.md
**Try it:** read docs/GAPS.md, C10, C11 and section 8.
**New concepts:** none.

### Audit — The backend against the screen spec (2026-10-20)
**Built:** nothing; this is a review step. docs/SCREENS.md is now the agreed spec, and docs/GAPS.md lists, for every global rule and screen (A1–A6, S1–S10), what the backend already supports (with the file or endpoint), what's partial and what's missing. It also covers the conflicts with what's built, a check of the stand-in rules and of "acting for" in the history, and a proposed build order that finishes the facility letter screens first.
**Files:** docs/SCREENS.md, docs/GAPS.md
**Try it:** read docs/GAPS.md, sections 7 (conflicts) and 8 (build order) first, then the questions at the end.
**New concepts:** none.

### Step 6l — Correcting a signed letter (2026-10-20)
**Built:** the PS, or someone acting for the PS, can cancel a signed letter with a written reason, and a corrected letter is then issued. Both files stay stored (migration `0022`).

**Cancelling is a workflow move**, "Cancel the signed letter", from "Signed" or "Sent to GRA" back to "Originals received" `[CONFIRM]`:
- **Who:** it needs the PS post, so delegation and succession (steps 4d and 5d) work as for signing. The desk, Records and the Minister get 403.
- **Reason:** a new column `core.workflow_transitions.requires_comment` makes the engine refuse the move (422) without a written reason in the comment. `available_actions` now shows `requires_comment`, so the frontend can ask for one.
- **What it does:** its effect `cancel_facility_letter` marks the current letter cancelled (`cancelled_at`, `cancelled_by`, `cancellation_reason`) and writes an audit row `case.document_cancelled` with the letter's checksum and the reason. The move's own audit row also has the reason as its comment.
- **Then:** the case is back with the desk, who can correct the HS code, verify again, and send it to the PS. Signing again issues the corrected letter through the existing effect. It records `replaces_id` (the cancelled letter), its audit row says `replaces_issued_document_id`, and its file name ends `-2.pdf` (`-3` for a second correction).

**Downloads:**
- `GET /etls/facility-letters/{id}/letter.pdf` serves the **current** letter. Between cancelling and re-signing it gives 409 "The letter was cancelled and a corrected one hasn't been signed yet."
- `GET /etls/facility-letters/{id}/letters` lists every letter, oldest first: status (`current`/`cancelled`), who issued it and when, the checksum, template version, `replaces_id`, the cancellation details and a `download_url`.
- `GET /etls/facility-letters/{id}/letters/{letter_id}/file` downloads any one of them, byte for byte as issued. The header `X-Letter-Status` says `current` or `cancelled`. The PDF itself can't be stamped "cancelled": that would change its checksum.

**The database enforces it too:**
- **One current letter:** "one per case" became "one *current* per case", a partial unique index (`issued_documents_one_current`).
- **A trigger** (`core.issued_documents_guard`) refuses deleting any row, changing anything but the cancellation columns, and changing a row once it's cancelled. It applies even to the table owner, like the audit log's triggers.

**Found while testing:** a corrected letter can be **byte-identical** to the cancelled one, when what changed isn't printed (the HS code) and both are signed within the same second. Two letters with one checksum would make "which copy is this?" unanswerable. So each PDF now carries its issue number ("Issue 1", "Issue 2") in its information block, and no two issues are ever the same file.

**Files:** backend/alembic/versions/0022_letter_corrections.py, backend/app/core/workflow/models.py (`requires_comment`), backend/app/core/workflow/service.py (the reason check in `change_status()`), backend/app/core/workflow/errors.py (`CommentRequired`), backend/app/core/workflow/router.py, backend/app/core/workflow/schemas.py, backend/app/core/documents/models.py, backend/app/core/documents/issued.py (`all_issued()`, `get_current()`, `cancel()`), backend/app/modules/etls/letter.py (`cancel_letter()`, `current_letter()`, `letters()`, `letter_by_id()`, `render_pdf(issue=...)`), backend/app/modules/etls/router.py, backend/app/modules/etls/schemas.py (`IssuedLetterOut`), backend/tests/modules/etls/test_letter_corrections.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Sign a letter. As `ps@motie.test`, `POST /cases/{id}/status` with `{"to_status": "originals_received"}` gives 422. Add `"comment": "Wrong HS code"` and it works.
- `GET /etls/facility-letters/{id}/letters`: one letter, `cancelled`, with your reason. `letter.pdf` gives 409.
- As the desk, re-confirm the HS code and verify; as the PS, sign. The listing now shows two, and `letter.pdf` serves the new one.
- Try to undo it: `docker compose exec db psql -U motie -d motie -c "UPDATE core.issued_documents SET cancelled_at = NULL"` fails with "a cancelled document can't be changed", even as the superuser.
- `docker compose run --rm tools pytest tests/modules/etls/test_letter_corrections.py -v`
**New concepts:** Cancel and replace (never delete)

### Step 6k — The HS code is optional for the applicant (2026-10-20)
**Built:** an applicant may now leave `hs_code` out of the form. The ETLS desk must still enter or confirm it before "Verify", exactly as in step 6g: `POST /etls/facility-letters/{id}/hs-code`.

The interesting part is the receipt rule. Without a code, nobody can say whether the cement receipt is needed. Before this step, a missing fact made the rule *fail closed* (receipt required), so every applicant who skipped the code would have been asked for a cement receipt. Now a condition has **three answers** (backend/app/core/documents/conditions.py `holds()`):
- `True`: the document is needed;
- `False`: it isn't;
- `None`: **not known yet**. The module supplies the fact, but it has no value yet. ETLS now always supplies `hs_heading`, as `None` until there's a code.

A fact the module *doesn't supply at all* (e.g. a typo in a rule) still fails closed. That safety net is unchanged.

The checklist (`GET /cases/{id}/documents`) shows `"applies": null` for an undecided document, with `"missing": false`. Two checks now use this (backend/app/core/documents/service.py):
- `known_documents_complete` (new, on Records' "Confirm originals received", migration `0021`): every document *known* to be needed is in. Undecided ones wait.
- `documents_complete` (on the desk's "Verify"): now strict. An undecided document with nothing uploaded is a problem: "it isn't known yet whether receipt (cement imports) is needed". Together with `hs_code_confirmed`, nothing undecided can reach the PS.

**Files:** backend/alembic/versions/0021_optional_hs_code.py, backend/app/core/documents/conditions.py, backend/app/core/documents/service.py (`RequirementStatus.applies`/`undecided`, the two checks), backend/app/core/documents/router.py, backend/app/modules/etls/schemas.py, backend/app/modules/etls/service.py (`facility_letter_facts()`), backend/tests/modules/etls/test_hs_code.py, backend/tests/modules/etls/test_documents.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Submit a facility letter without `hs_code`. `GET /cases/{id}/documents`: the receipt has `"applies": null`. Records can confirm the originals without it.
- As the desk, try "Verify": 409, listing both the missing HS code and the undecided receipt. Enter `{"hs_code": "2523.29"}`: now the receipt is required. Upload it, and Verify works.
- `docker compose run --rm tools pytest tests/modules/etls/test_hs_code.py -v`
**New concepts:** Three answers: yes, no, not known yet

### Step 6j — The letter date, the Ministry's way (2026-10-20)
**Built:** the date on the facility letter now reads like the Ministry's letters: **"16th September, 2026"**, with an ordinal day and a comma before the year. `long_date()` and `_ordinal()` in backend/app/modules/etls/letter.py do it, including the awkward ones: 1st, 2nd, 3rd, but 11th, 12th, 13th, then 21st, 22nd, 23rd.

The template file didn't change (it still just says `$date`), so its version stays `2`. The template version records the *wording*; the code that fills it in is recorded by the git commit. Letters already issued keep the date as it was printed: they're stored files.

**Files:** backend/app/modules/etls/letter.py (`long_date()`, `_ordinal()`), backend/tests/modules/etls/test_letter.py
**Try it:**
- `docker compose run --rm tools pytest tests/modules/etls/test_letter.py -k date -v` runs one case per tricky day.
- Sign a letter and download it: the top right says e.g. "20th October, 2026".
**New concepts:** none.

### Step 6i — The Ministry's wording for the facility letter (2026-10-20)
**Built:** backend/app/modules/etls/templates/facility_letter.txt now holds the Ministry's wording, word for word (including "benefitting" and "Liberalization"), as template version `2`. Each `[placeholder]` became a `$field`:

| Ministry's placeholder | Field |
| --- | --- |
| [File reference], [Date] | `$file_reference`, `$date` |
| [IMPORTER NAME] in the subject | `$importer_name_upper` (new) |
| [IMPORTER NAME] / [Importer name] elsewhere | `$importer_name` |
| [quantity] [unit] | `$quantity` (now the number only) and `$unit` (new) |
| [product], [exporter], [exporter country] | `$product`, `$exporter_name`, `$exporter_country` |
| [approval number], [product approval numbers] | `$exporter_approval_number`, `$product_approval_numbers` |
| [certificate numbers] | `$certificate_numbers` |
| [Importer address] | `$importer_address` |
| "Permanent Secretary" under "Sincerely," | `$signature_title` (new): "Permanent Secretary", or "For: Permanent Secretary" when someone acted for the PS `[CONFIRM]` |

Two small additions to the template's layout rules, in `render_pdf()` in backend/app/modules/etls/letter.py:
- **` >> ` puts the rest of a line at the right margin.** The first line is `$file_reference >> $date`, so the reference sits on the left and the date on the right, as in the Ministry's layout.
- **Layout marks are read from the template, not from the data.** The template is now filled line by line, after `**` and ` >> ` have been read. An importer called "A >> B" or "\*\*X\*\*" is printed exactly as typed.

The subject line is bold. The Ministry's text didn't say; I chose bold because the old template had it and it matches the capitals `[CONFIRM]`. The old Ministry address line at the top is gone, because the Ministry's wording doesn't have it (letterhead `[CONFIRM]`). Letters already issued keep version 1: they're stored files (step 6f).

**Files:** backend/app/modules/etls/templates/facility_letter.txt, backend/app/modules/etls/letter.py (`LetterFields`, `build_fields()`, `render_pdf()`), backend/tests/modules/etls/test_letter.py
**Try it:**
- `bash scripts/reset-dev.sh`, then walk a facility letter to "Signed by the PS" as the seeded users (step 6h) and download it as `desk@motie.test`.
- `docker compose exec db psql -U motie -d motie -c "SELECT case_id, template_version FROM core.issued_documents"` shows `2 (Ministry wording, 2026-10-20)`.
- To change a word, edit the template and change its `## version:` line. The `## Fields:` note at the top lists every field you can use. A misspelt field stops the signing with an error rather than printing it, and `test_the_template_only_uses_fields_the_letter_has` catches it first.
- `docker compose run --rm tools pytest tests/modules/etls/test_letter.py -v`
**New concepts:** none. See Generating documents from a template.

### Step 6h — Resetting the dev database (2026-10-20)
**Built:** `scripts/reset-dev.sh` gives you a clean dev environment in one command:
1. stops the API;
2. drops and recreates the dev database (`POSTGRES_DB` from `.env`), and re-runs db/init/10-db-users.sh;
3. deletes the `documents` volume (uploads and issued letters);
4. runs the migrations, then the new seed, backend/app/dev_seed.py: one user per post in the ETLS chain, plus an applicant, a recorder and an admin, all `...@motie.test`;
5. starts the API again.

**Safety:**
- It only runs when `.env` says `APP_ENV=development`, and asks you to type `reset` (unless `--yes`). The seed refuses too unless `APP_ENV=development`, because its accounts share a known password.
- `APP_ENV` is a new setting (backend/app/core/config.py). It defaults to `production`, and `.env.example` says `production`, so a server that copies it, or forgets it, is safe. I added `APP_ENV=development` to your local `.env`.
- CLAUDE.md now says: smoke tests run only against dev, never a shared or production database.

**How I tested the script:** the guard (no `.env`, `APP_ENV` missing, `APP_ENV=production`) from a scratch copy; then two full runs in a throwaway Compose project (`COMPOSE_PROJECT_NAME=motie_resettest`), with a stray user and file left in between to check both were wiped, the 10 seed users created, migrations at `0020`, and `/health/db` ok. Then I deleted that project. **I did not run it on your dev database**: it still has the smoke-test data from step 6c and the pre-6f/6g cases. Run it when you're ready.

**Files:** scripts/reset-dev.sh, backend/app/dev_seed.py, backend/app/core/config.py (`app_env`), .env.example, CLAUDE.md, backend/tests/test_dev_seed.py
**Try it:**
- `bash scripts/reset-dev.sh` from the repo root (Git Bash). Then log in at `localhost:8000/docs` as `desk@motie.test` with `dev password 123`.
- A different password for the seeded users: add `DEV_SEED_PASSWORD=...` to `.env` (at least 12 characters).
- `docker compose run --rm tools pytest tests/test_dev_seed.py -v`
**New concepts:** Disposable dev environments (reset and seed)

### Step 6g — The HS code decides the receipt rule (2026-10-20)
**Built:** the placeholder rule "product text contains *cement*" is gone. The receipt now depends on the **HS code** (migration `0020`):
- **The applicant declares it** on the form: new field `hs_code` (required here; optional since step 6k). Dots and spaces are ignored (`2523.29`, `2523 29` and `252329` are the same), and it's stored as 6, 8 or 10 digits. Anything else gives 422.
- **An officer confirms it**, or corrects it: `POST /etls/facility-letters/{case_id}/hs-code` with `{"hs_code": "2523.29"}`. Who may do it is the engine's rule, as for "original seen" in step 6d: whoever may make the move that needs the check `hs_code_confirmed`. That's the desk's "Verify" move, so the ETLS desk (or someone acting for it), and only while the case waits for verification. Each confirmation is audited (`case.hs_code_confirmed`, with the declared, confirmed and previous codes). The declared code is kept as the applicant gave it; the app can't change it (column-level grant).
- **The rule is still a row:** `{"field": "hs_heading", "op": "equals", "value": "2523"}` `[CONFIRM]`. The ETLS module supplies the fact `hs_heading`: the first 4 digits of the confirmed code, or of the declared code until an officer confirms. A case with no code at all (from before this step) has no `hs_heading`, so the rule fails closed: the receipt counts as required.
- **The desk's "Verify" move now has two checks:** `hs_code_confirmed`, and `documents_complete` again. So if the officer corrects the code to 2523, the case can't be verified until the receipt is uploaded. Records' earlier check uses the declared code.
- The confirmed code is available to the letter template as `$hs_code`, printed as `2523.29`. The current template doesn't use it yet.

**Files:** backend/alembic/versions/0020_facility_letter_hs_code.py, backend/app/modules/etls/models.py, backend/app/modules/etls/schemas.py (`normalize_hs_code()`, `HsCode`, `HsCodeConfirmation`), backend/app/modules/etls/service.py (`confirm_hs_code()`, `hs_heading()`, `facility_letter_facts()`, the `hs_code_confirmed` check), backend/app/modules/etls/router.py, backend/app/modules/etls/letter.py (`hs_code` field), backend/tests/modules/etls/test_hs_code.py, backend/tests/modules/etls/test_documents.py, backend/tests/modules/etls/test_originals.py, backend/tests/support.py (`confirm_hs_code()`, `hs_code` in the form), backend/tests/core/test_db_privileges.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Submit a facility letter with `"hs_code": "7210.49"`: `GET /cases/{id}/documents` shows `cement_receipt` with `applies: false`. Submit another with `"product": "Grey clinker", "hs_code": "2523.10"`: `applies: true`, although the product text never says "cement".
- Walk one to "Originals received", then as the desk `POST /etls/facility-letters/{id}/hs-code` with `{"hs_code": "2523.29"}`. Try "Verify": 409, the receipt is missing. Upload it, and Verify works.
- `docker compose run --rm tools pytest tests/modules/etls/test_hs_code.py -v`
**New concepts:** HS codes

### Step 6f — Issued letters are stored, never re-rendered (2026-10-20)
**Built:** the facility letter is now made **once**, at the moment it's signed, and stored. Every download serves that stored file.
- **Transition effects (core, migration `0019`):** the twin of step 6d's checks. A check runs *before* a move and can stop it; an *effect* runs *after* the status change, in the same transaction. Which move sets off which effect is a row in `core.transition_effects`; the code is registered by name in backend/app/core/workflow/effects.py. The PS's "Sign" move has the effect `issue_facility_letter`.
- **What the effect does** (`issue_letter()` in backend/app/modules/etls/letter.py): builds the fields from the signing audit row, renders the PDF, and stores it through the new core service backend/app/core/documents/issued.py:
  - the file goes in the `documents` volume, under a random name, like uploads;
  - a row in `core.issued_documents` records its SHA-256 checksum, size, the **template version** and the template file's own checksum, who issued it and when;
  - an audit row `case.document_issued` records the same checksum and template version.
- **All or nothing:** if rendering or storing fails, the signing fails too and the case stays "Verified". If the file was already written, it's deleted again (the effect hands the engine an "undo").
- **Served, not re-made:** `GET /etls/facility-letters/{case_id}/letter.pdf` reads the stored file, checks it against the recorded checksum (a file changed on disk gives a 500 and a log line, never the letter), and sends it with an `X-Checksum-SHA256` header.
- **Once per case:** a unique constraint on (case, kind), and the app may only `SELECT` and `INSERT` the table. (Since step 6l: one *current* letter per case, and a cancelled one is kept.)
- **Template version:** the template file now starts with `## version: 1 (...)`. Lines starting with `##` are notes, never printed. A template without a version line can't issue letters.
- An unknown effect name in the database blocks the move (409), like an unknown check.

**Files:** backend/alembic/versions/0019_issued_documents.py, backend/app/core/workflow/effects.py, backend/app/core/workflow/models.py (`TransitionEffect`), backend/app/core/workflow/service.py (`change_status()` runs effects and undoes them if the commit fails), backend/app/core/documents/issued.py, backend/app/core/documents/models.py (`IssuedDocument`), backend/app/core/documents/storage.py (`save_bytes()`, `read_verified()`), backend/app/modules/etls/letter.py (`load_template()`, `build_fields()`, `issue_letter()`, `issued_letter()`), backend/app/modules/etls/router.py, backend/app/modules/etls/templates/facility_letter.txt, backend/tests/modules/etls/test_letter.py, backend/tests/core/test_db_privileges.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Walk a facility letter to "Signed by the PS", then: `docker compose exec db psql -U motie -d motie -c "SELECT case_id, sha256, template_version, issued_at FROM core.issued_documents"` and `... -c "SELECT details FROM core.audit_log WHERE action = 'case.document_issued'"`. Same checksum in both.
- Download the letter twice: identical bytes, and the `X-Checksum-SHA256` header matches. Edit the template wording and download again: still the same file.
- Check a downloaded copy yourself: `sha256sum facility-letter-....pdf` (Git Bash) or `Get-FileHash` (PowerShell) gives the checksum in the audit log.
- **Your dev database:** cases signed before this step have no stored letter, so their download gives 404. We don't make one now, because nobody signed it.
- `docker compose run --rm tools pytest tests/modules/etls/test_letter.py -v`
**New concepts:** Issue once, store with a checksum. (Effects reuse the idea in A registry of named checks.)

### Step 6e — The facility letter PDF (2026-10-19)
**Built:** `GET /etls/facility-letters/{case_id}/letter.pdf` returns the letter to GRA once the case is signed (409 before that; staff only). It's built in two halves, in backend/app/modules/etls/letter.py:
- `letter_fields()` gathers the fields from the database:
  - file reference, date, importer, product, quantity and unit, exporter and country, the exporter's ETLS approval number, product approval numbers, certificate numbers;
  - the **signature block from the audit row of the "Sign" move**: the signer's name and post. If they signed acting for the PS (by delegation or succession), it adds "for the Permanent Secretary".
- `render_pdf()` fills the text template backend/app/modules/etls/templates/facility_letter.txt (Python's built-in `string.Template`, `$name` placeholders, `**bold line**`) and lays it out on A4 with **fpdf2** (your choice; new library, `fpdf2==2.8.9`).

The addressee (Commissioner General, GRA), the subject "Request for ETLS facility: [importer]" and "cc: [importer]" are in the template. The **file reference** comes from the setting `FACILITY_LETTER_REFERENCE_FORMAT` `[CONFIRM]`, default `MOTIE/ETLS/FL/{year}/{case_id:05d}` (e.g. `MOTIE/ETLS/FL/2026/00042`). Only `{year}` and `{case_id}` are allowed, checked when the app starts.

**Files:** backend/app/modules/etls/letter.py, backend/app/modules/etls/templates/facility_letter.txt, backend/app/modules/etls/router.py, backend/app/core/config.py, backend/requirements.txt, backend/tests/modules/etls/test_letter.py
**Try it:**
- `docker compose build` (new library), `docker compose up -d`.
- Walk a facility letter to "Signed by the PS" (step 6d shows how to get past Records), then as the desk open `localhost:8000/etls/facility-letters/<id>/letter.pdf` with your token (in `/docs`, use "Download file").
- To change the reference format, add `FACILITY_LETTER_REFERENCE_FORMAT: "MOTIE/ETLS/{year}/{case_id}"` under the `api` service's `environment` in docker-compose.yml. A bad placeholder stops the API at startup with a clear message.
- To change the wording, edit the template file; no Python changes.
- `docker compose run --rm tools pytest tests/modules/etls/test_letter.py -v`
- **Changed in step 6f:** the letter is no longer made on each download; it's made once at signing and stored. `letter_fields()` became `build_fields()`.
**New concepts:** Generating documents from a template

### Step 6d — Transition checks, and originals seen in person (2026-10-19)
**Built:** a move can now require named **checks** before it's allowed (migration `0018`):
- **Which** move needs which check is data: `core.transition_checks` (transition id + check name).
- **What** a check does is a Python function, registered under its name in backend/app/core/workflow/checks.py. The documents service registers two:
  - `documents_complete`: every document that applies is uploaded, including the cement receipt when it applies.
  - `originals_seen`: every document whose paper original is required (`document_requirements.original_required`, set for the certificate of origin) has its *newest* upload marked as seen.
- On a facility letter, Records' "Confirm originals received" carries both. If either fails, `change_status()` answers **409** "Not ready: ...", listing every problem.
- `POST /cases/{id}/documents/{document_id}/original-seen` records that a person has seen the paper original. Who may do it is decided by the engine itself: whoever may make the move that needs the check (`may_make_move_with_check()`). That's the Records Officer, or anyone acting for Records by delegation or succession; no post is named in code. It is audited with the checksum of the scan it was compared with. A newer scan must be seen again.
- A check name in the database with no function behind it **blocks** the move (fail closed), and a test makes sure every name has one.

**Files:** backend/alembic/versions/0018_transition_checks.py, backend/app/core/workflow/checks.py, backend/app/core/workflow/models.py (`TransitionCheck`), backend/app/core/workflow/service.py (checks in `change_status()`, `may_make_move_with_check()`), backend/app/core/workflow/errors.py (`NotReady`), backend/app/core/documents/models.py, backend/app/core/documents/service.py (`mark_original_seen()`, `original_pending`, the two checks), backend/app/core/documents/router.py, backend/tests/modules/etls/test_originals.py, backend/tests/support.py (`ready_for_records()`, `FACILITY_LETTER_DOCUMENTS`)
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- On a facility letter case, try Records' move with documents missing: the 409 lists them. Upload them, try again: "the original certificate of origin hasn't been marked as seen". As Records, `POST /cases/{id}/documents/{certificate document id}/original-seen`, then the move succeeds.
- `docker compose run --rm tools pytest tests/modules/etls/test_originals.py -v`
**New concepts:** A registry of named checks (plug-ins)

### Step 6c — Documents and data-driven requirements (2026-10-19)
**Built:** a shared core service, backend/app/core/documents/, with three tables (migration `0017`):
- `document_types`: the kinds of document.
- `document_requirements`: which documents a workflow needs, each with an optional **condition**.
- `case_documents`: one row per uploaded file. The bytes are on disk, in the new `documents` volume.

**The cement rule is a row, not code:** `{"field": "product", "op": "contains", "value": "cement"}`. The core tests it against *facts* the module supplies, because the core can't read ETLS tables:
- The ETLS module registers `facility_letter_facts()` (product, unit, exporter country) with `facts.register(...)`.
- Only `equals` and `contains` exist (text compared ignoring case). A `CHECK` constraint refuses any other shape, and nothing is ever `eval()`-ed.
- A rule naming a fact the module doesn't supply fails closed: the document counts as required.

**Facility letter documents:** business registration, annual returns certificate, certificate of origin, invoice and export declaration are always required. A receipt is required when the product contains "cement" `[CONFIRM]` which receipt.

**Uploads, safely:**
- `POST /cases/{id}/documents/{type}?filename=...` takes the file as the raw request body, so no new library (your choice).
- It streams to disk while counting and hashing (SHA-256). More than 10 MB (`MAX_UPLOAD_BYTES`) gives 413, and the partial file is deleted.
- The file type is decided by the file's first bytes (PDF, PNG, JPEG only, otherwise 415), never by the name or the `Content-Type` the browser claims.
- On disk the file gets a random name, so the user's filename can't point anywhere (`../../etc/passwd` is stored for display as `passwd`).
- Only the case's applicant and staff can upload or download (others get 404). Nothing can be added to a closed case.
- Downloads are sent as `attachment` with `nosniff`.
- `GET /cases/{id}/documents` is the checklist: what applies, what's missing, and every upload (re-uploads add a newer version; old ones are kept).

**Files:** backend/alembic/versions/0017_documents.py, backend/app/core/documents/ (`models.py`, `conditions.py`, `facts.py`, `storage.py`, `service.py`, `router.py`), backend/app/core/config.py (`DOCUMENT_STORAGE_DIR`, `MAX_UPLOAD_BYTES`), backend/app/modules/etls/service.py (`facility_letter_facts()`), docker-compose.yml (`documents` volume), backend/tests/modules/etls/test_documents.py, backend/tests/conftest.py (`document_storage`: each test gets a temporary folder), backend/tests/support.py (`upload()`, sample `PDF`/`PNG`/`JPEG` bytes)
**Try it:**
- `docker compose up -d` (adds the volume to the API), then `docker compose run --rm tools alembic upgrade head`.
- Submit a facility letter with `"product": "Portland cement"`, then `GET /cases/{id}/documents`: `cement_receipt` has `applies: true`. (Since step 6g the HS code decides, not the product text: use `"hs_code": "2523.29"`.)
- Upload with curl: `curl -X POST "localhost:8000/cases/1/documents/invoice?filename=invoice.pdf" -H "Authorization: Bearer <token>" --data-binary @invoice.pdf`. Then try a `.txt` file renamed to `.pdf`: 415.
- `docker compose run --rm tools pytest tests/modules/etls/test_documents.py -v`
- **Note:** while testing this step I made a real user (`smoke-applicant@test.gm`), case 1 and one file in your *dev* database. They can't be deleted cleanly because the case has audit rows. `scripts/reset-dev.sh` (step 6h) clears them.
**New concepts:** Rules as data (a small condition language), Safe file uploads

### Step 6b — Case flags and the duplicate certificate check (2026-10-19)
**Built:**
- **Case flags (core):** `core.case_flags`. A flag is addressed to a post. While a *blocking* flag is open, `change_status()` refuses every move with **409** "This case is on hold until these are resolved: ...". A holder of the flag's post resolves it with a written reason. Raising and resolving are both written to the case's audit history. Staff see `on_hold` on `GET /cases/{id}` (it's `null` for applicants), and `GET /cases/{id}/flags` lists the flags.
- **Duplicate certificates (ETLS):** when a facility letter is submitted, each certificate of origin number (normalised: upper case, no spaces) is checked against every other case. A number used before doesn't refuse the submission. Instead, the case is flagged for the ETLS desk (`etls.duplicate_certificate_of_origin`), with the repeated numbers and the earlier case ids. Records can't confirm the originals until the desk resolves it.
- **Two submissions at the same moment:** the check first takes a Postgres advisory lock on each number, so the second submission waits for the first to commit and then sees it. The test proves it: with the lock removed, it fails.

The downgrade test now uses its own empty database (`empty_database_config`). Migration 0015's `downgrade()` rightly refuses to remove facility-letter statuses while cases still use them, and race tests leave committed cases behind.

**Files:** backend/alembic/versions/0016_case_flags.py, backend/app/core/workflow/models.py (`CaseFlag`), backend/app/core/workflow/flags.py, backend/app/core/workflow/service.py (the on-hold check in `change_status()`), backend/app/core/workflow/router.py (`/flags` endpoints, `on_hold`), backend/app/core/workflow/schemas.py, backend/app/core/workflow/errors.py, backend/app/modules/etls/service.py (`_earlier_uses()`), backend/tests/modules/etls/test_duplicate_certificates.py, backend/tests/conftest.py, backend/tests/test_migrations.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Submit two facility letters with the same certificate number (try `"SN-CO-1"` and `"sn-co 1"`). On the second: `GET /cases/{id}/flags` as staff shows the flag. Records' `POST /cases/{id}/status` gives 409. As the ETLS desk, `POST /cases/{id}/flags/{flag_id}/resolve` with `{"resolution": "..."}`, and Records can move it.
- `docker compose run --rm tools pytest tests/modules/etls/test_duplicate_certificates.py -v`
**New concepts:** Advisory locks

### Step 6a — ETLS facility letter: the module, the workflow and the form (2026-10-19)
**Built:** the first *module*: backend/app/modules/etls/, with its own Postgres schema `etls`. Migration `0015` adds:
- workflow `etls_facility_letter`;
- an ETLS Desk Officer post `[CONFIRM]`;
- three form tables: `etls.facility_letters` (one row per case) and child tables for the product approval numbers and the certificate of origin numbers ("one or more" of each).

`POST /etls/facility-letters` (applicants) checks the form and opens the case *and* saves the form in one transaction. `GET /etls/facility-letters/{case_id}` reads it back, using the core's visibility rule.
```
submitted          --(records_officer: Confirm originals received)--> originals_received
originals_received --(etls_desk_officer: Verify)--------------------> verified
                   --(etls_desk_officer: Reject)--------------------> rejected      [CONFIRM]
verified           --(permanent_secretary: Sign the facility letter)-> signed        [CONFIRM reviewer before the PS]
signed             --(etls_desk_officer: Send to GRA)----------------> sent_to_gra   [CONFIRM who]
sent_to_gra        --(etls_desk_officer: Close the file)-------------> closed        [CONFIRM who]
```
Core changes:
- `workflows.opened_by_module`: the generic `POST /cases` refuses module workflows, which would open a case with no form.
- `start_case()` is split, so a module can call `open_case()` (no commit), add its rows, then commit once.

The `people`/`act` fixtures moved to backend/tests/conftest.py, and `STAFF` (now with `desk`) to backend/tests/support.py, so module tests can use them too.

**Files:** backend/alembic/versions/0015_etls_facility_letter.py, backend/app/modules/etls/ (`models.py`, `schemas.py`, `service.py`, `router.py`), backend/app/models.py, backend/app/main.py, backend/app/core/workflow/models.py (`opened_by_module`), backend/app/core/workflow/service.py (`open_case()`), backend/tests/modules/etls/test_facility_letter.py, backend/tests/conftest.py, backend/tests/support.py (`STAFF`, `facility_letter_form()`), backend/tests/core/test_db_privileges.py (now checks `etls` too)
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Log in as an applicant and `POST /etls/facility-letters` with the example body from `facility_letter_form()` in backend/tests/support.py. Then try a quantity of `0`, or the same certificate written twice (`"CO 1"` and `"co1"`): both give 422.
- `docker compose exec db psql -U motie -d motie -c "SELECT * FROM etls.facility_letters"`
- `docker compose run --rm tools pytest tests/modules/etls -v`
**New concepts:** Modules on a shared core, `NUMERIC` vs floating point

### Step 5d — Acting for an absent post (2026-10-19)
**Built:** the engine now uses absences and the succession order. For each move, `_permitted()` in backend/app/core/workflow/service.py tries three bases, in this order:
1. **Own:** you hold the post the move needs. This works even while you're marked absent (you might be working remotely).
2. **Delegation:** the post has delegated to one of yours (step 4d).
3. **Succession:** every holder of the needed post is absent today, *and* the post hasn't delegated to anyone (a personal delegation takes priority). `acting_successor()` in backend/app/core/workflow/succession.py walks the post's succession order and picks the **first post with a holder at work**. Only that post may act; posts further down may not.

The audit row now records:
- `as_position`: the post you acted from;
- `on_behalf_of`: whose step it was, or `null` if it was your own. This is the "acting for" field;
- `basis`: `own`, `delegation` or `succession`;
- `delegation_id`;
- `absence_ids`: the absences that justified a succession, including those of successors who were skipped because they were away too.

`GET /cases/{id}` shows succession moves with `on_behalf_of` set, like delegated ones.

**What this gives, with the confirmed rules:**
| Situation | Who may do the Minister's step | Who may sign and assign (Director's step) |
| --- | --- | --- |
| Nobody away | Minister | Director of Industry and Investment |
| Minister away | PS | Director |
| Minister and PS away | DPS Admin & Finance `[CONFIRM]` | Director |
| Director away | Minister | DPS Admin & Finance |
| Minister away, but delegated to someone | that delegate only | Director |

**Files:** backend/app/core/workflow/service.py (`PermittedMove.basis`, `.on_behalf_of`, `_permitted()`, `change_status()`), backend/app/core/workflow/succession.py (`Succession`, `acting_successor()`), backend/app/core/workflow/delegation.py (`is_delegated_away()`), backend/app/core/workflow/router.py, backend/app/core/workflow/schemas.py, backend/tests/core/test_acting_for.py
**Try it:**
1. Set up the ETLS users with their posts (steps 3c and 4b), including someone holding `dps_admin_finance`. Walk a case to "With the Minister".
2. Log in as the Minister and `POST /absences` with today's dates.
3. As the PS: `GET /cases/1` offers "Minute to the Permanent Secretary" with `"on_behalf_of": "minister"`. Make the move.
4. `GET /cases/1/history`: the last row has `"basis": "succession"` and the Minister's absence id.
- `docker compose run --rm tools pytest tests/core/test_acting_for.py -v`. Each Ministry scenario is one test, named after it.
**New concepts:** Succession (acting for an absent post)

### Step 5c — Absence records (2026-10-19)
**Built:** `core.absences`: a person who holds a post is away from one date to another, both days included. Who may record one:
- the person themselves;
- someone with the new `absence_recorder` role, on their behalf. That role is the `[CONFIRM]` placeholder for "an authorised officer".

The audit row's actor is whoever recorded it. Its details hold `absent_user_id`, `recorded_by`, `on_behalf`, and the posts the person held at the time. Other rules:
- No back-dating.
- Only post holders can be marked absent.
- An absence is ended early by *cancelling* it (the absent person or a recorder may). The app can't change its dates (a column-level grant, as for delegations).

Endpoints:
- `POST /absences` records one; leave out `user_id` for yourself.
- `GET /absences` lists your own, or everyone's if you're a recorder.
- `POST /absences/{id}/cancel` ends one.

Absences don't change who may act yet; that's step 5d.

**Files:** backend/alembic/versions/0014_absences.py, backend/app/core/workflow/models.py (`Absence`), backend/app/core/workflow/absence.py, backend/app/core/workflow/absence_router.py, backend/app/core/workflow/errors.py (`InvalidAbsence`, `AlreadyCancelled`), backend/app/core/workflow/schemas.py, backend/app/core/workflow/router.py, backend/app/main.py, backend/tests/core/test_absences.py, backend/tests/core/test_db_privileges.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Create a recorder: `docker compose exec api python -m app.core.identity.cli create-user --email ps.secretary@motie.gov.gm --name "Private Secretary" --role officer --role absence_recorder`
- Log in as the recorder and `POST /absences` with `{"user_id": <the Minister's user id>, "starts_on": "<today>", "ends_on": "<today + 4 days>", "reason": "ECOWAS summit"}`. Then look at the audit row: `docker compose exec db psql -U motie -d motie -c "SELECT actor_user_id, action, details FROM core.audit_log WHERE entity_type = 'absence'"`.
- `docker compose run --rm tools pytest tests/core/test_absences.py -v`
**New concepts:** none. The pattern (dated record, cancel instead of delete, column-level grant) is the one from Delegation (acting on behalf of) and Column-level privileges.

### Step 5b — Succession orders (2026-10-19)
**Built:** `core.succession_orders`, the Ministry's standing rule for who is next in line when a post's holder is away. Each row says "when *post* is absent, *successor* is next, at *rank*", for every workflow or for one. Migration `0013` seeds:

| Post | Workflow | 1st in line | 2nd in line |
| --- | --- | --- | --- |
| Minister | all | Permanent Secretary | DPS Admin & Finance `[CONFIRM]` |
| Permanent Secretary | all | DPS Admin & Finance | |
| Director of Industry and Investment | ETLS only | DPS Admin & Finance | |

`succession_order()` in backend/app/core/workflow/succession.py returns the line for a post and a workflow. If a post has rows for that workflow, they *replace* its general rows. Nothing uses the table yet: step 5c records absences, and step 5d lets the engine act on them.

**Files:** backend/alembic/versions/0013_succession_orders.py, backend/app/core/workflow/models.py (`SuccessionStep`), backend/app/core/workflow/succession.py, backend/tests/core/test_succession.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- `docker compose exec db psql -U motie -d motie -c "SELECT p.code AS post, w.code AS workflow, s.rank, n.code AS next_in_line FROM core.succession_orders s JOIN core.positions p ON p.id = s.position_id JOIN core.positions n ON n.id = s.successor_position_id LEFT JOIN core.workflows w ON w.id = s.workflow_id ORDER BY p.code, s.rank"`
- `docker compose run --rm tools pytest tests/core/test_succession.py -v`
**New concepts:** NULL in unique constraints (`NULLS NOT DISTINCT`)

### Step 5a — The confirmed ETLS route (2026-10-19)
**Built:** migration `0012` turns the placeholder ETLS workflow into the route the Ministry confirmed:
- New posts: Director of Industry and Investment (`director_of_industry`), an Industry and Investment Officer (`industry_officer`) and the Deputy PS, Administration and Finance (`dps_admin_finance`), with their departments.
- The ETLS route now goes through the PS. The Director's single step, "Sign and assign to an officer", covers both signing and minuting the file to an officer.
- The Trade posts stay in the org chart, but ETLS no longer uses them.

```
submitted     --(records_officer: Register and forward to the Minister)--> with_minister
with_minister --(minister: Minute to the Permanent Secretary)-----------> with_ps
with_ps       --(permanent_secretary: Minute to the Director)-----------> with_director
with_director --(director_of_industry: Sign and assign to an officer)----> with_officer
with_officer  --(industry_officer)--> approved | rejected | back to with_director   [CONFIRM]
```
The old "With the Directorate" status was *renamed* to `with_director`, not replaced, so a case already in it keeps a valid status. The officer's three moves are still placeholders: the Ministry hasn't said what the officer does after the Director signs, or who may reject.

The race test now gives its posts back when it ends (`release_posts`). It commits for real, and from step 5d a leftover "race" Minister would count as present in other tests.

**Files:** backend/alembic/versions/0012_confirmed_etls_route.py, backend/tests/core/conftest.py (`STAFF` replaces `POSITION_FOR`, and adds the DPS), backend/tests/core/test_cases.py, backend/tests/core/test_case_race.py, backend/tests/core/test_delegations.py, backend/tests/core/test_workflow_definitions.py (`test_etls_route_is_the_one_the_ministry_confirmed`), backend/tests/core/test_positions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`, then the transitions query from step 4c: 7 rows, matching the diagram.
- `docker compose run --rm tools pytest tests/core/test_workflow_definitions.py tests/core/test_cases.py -v`
**New concepts:** none. See Data migrations, and Changing a column with existing data (expand, backfill, contract).

### Step 4e — The PS acts for the Minister through delegation (2026-10-19)
**Built:** migration `0011` removes the placeholder transition from step 3b that let the Permanent Secretary *always* make the Minister's move. Now the PS can only do it while the Minister's post has delegated to the PS post (step 4d). The audit row then says `"as_position": "permanent_secretary", "on_behalf_of": "minister"`. Without a delegation, the PS gets 403 and sees no button.

**The ETLS moves now (6, down from 7):**
```
submitted --(records_officer: Register and forward)--> with_minister
with_minister --(minister: Minute to the Directorate)--> with_directorate
with_directorate --(director_of_trade: Assign to an officer)--> with_officer
with_officer --(trade_officer)--> approved | rejected | back to with_directorate
Any of these can also be made by a post the required post has delegated to.
```
**Tests changed, and why:**
- `test_permanent_secretary_can_act_for_the_minister` now first has the Minister delegate for a week (`_minister_is_away`). Its original assertions are unchanged and still pass, and it also checks `on_behalf_of`.
- `test_etls_workflow_is_seeded` now expects 6 transitions, not 7, because the row really is gone.
- New: `test_permanent_secretary_cannot_act_for_the_minister_without_a_delegation`.

**Files:** backend/alembic/versions/0011_remove_ps_placeholder_move.py, backend/tests/core/test_cases.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`, then rerun the transitions query from step 4c: 6 rows, no `permanent_secretary`.
- Walk a case to "With the Minister". As the PS, `GET /cases/1` shows no actions. As the Minister, `POST /delegations` with `{"from_position": "minister", "to_position": "permanent_secretary", "starts_on": "<today>", "ends_on": "<today + 6 days>"}`. As the PS, the "Minute to the Directorate" button appears with `"on_behalf_of": "minister"`.
- `docker compose run --rm tools pytest tests/core/test_cases.py -v`
**New concepts:** none. This step uses Delegation (acting on behalf of) from step 4d.

### Step 4d — Delegation (2026-10-19)
**Built:** `core.delegations`. A holder of a post can let another post act for it from one date to another, both days included, either for every workflow or for one. Example: the Director of Trade is on leave from 3 to 10 March and delegates to the Trade Officer post.
- The engine now tries the actor's own posts first, then any delegation active *today* to a post they hold. `change_status()` records three keys in the audit row: `as_position` (the post the actor acted from), `on_behalf_of` (whose authority they used, or `null`) and `delegation_id`.
- `GET /cases/{id}` marks borrowed moves: `"on_behalf_of": "director_of_trade"`.
- Rules (backend/app/core/workflow/delegation.py): only a holder of the post may delegate or revoke it. No delegating to yourself, no back-dating, at most 90 days `[CONFIRM]`. Delegations aren't passed on: a delegate can't hand the borrowed powers to someone else. The delegating post keeps its own powers.
- A delegation is ended early by *revoking* it. It's never deleted or edited: the app may only set `revoked_at`/`revoked_by` (a column-level grant), so nobody can stretch the dates afterwards to cover an earlier action.

Endpoints:
- `POST /delegations` creates one.
- `GET /delegations` lists current and upcoming ones given by, or to, your posts.
- `POST /delegations/{id}/revoke` ends one.

The workflow engine's errors moved to backend/app/core/workflow/errors.py, so the delegation code can use them too. A broken delegation rule returns **422**; revoking twice returns **409**.

**Files:** backend/alembic/versions/0010_delegations.py, backend/app/core/workflow/models.py (`Delegation`), backend/app/core/workflow/delegation.py, backend/app/core/workflow/delegation_router.py, backend/app/core/workflow/errors.py, backend/app/core/workflow/service.py (`PermittedMove`, `_permitted()`, `change_status()`), backend/app/core/workflow/router.py, backend/app/core/workflow/schemas.py, backend/app/main.py, backend/tests/core/test_delegations.py, backend/tests/core/conftest.py (`people`, `act`, moved from test_cases.py), backend/tests/support.py (`open_case`, `move`), backend/tests/core/test_db_privileges.py
**Try it:**
1. `docker compose run --rm tools alembic upgrade head`
2. Set up the step 4c users with their posts and walk a case to "With the Directorate".
3. Log in as the Trade Officer: `GET /cases/1` shows no actions, and moving to `with_officer` gives 403.
4. Log in as the Director and `POST /delegations` with `{"from_position": "director_of_trade", "to_position": "trade_officer", "starts_on": "<today>", "ends_on": "<today + 6 days>", "workflow": "etls_application", "reason": "Annual leave"}`.
5. As the Trade Officer again: `GET /cases/1` now offers "Assign to an officer" with `"on_behalf_of": "director_of_trade"`. Make the move, then look at the last row of `GET /cases/1/history`.
6. As the Director, `POST /delegations/1/revoke`. The officer loses the button.
- `docker compose run --rm tools pytest tests/core/test_delegations.py -v`
**New concepts:** Delegation (acting on behalf of), Column-level privileges, Testing with a fake "today" (monkeypatch)

### Step 4c — Approvals belong to positions (2026-10-19)
**Built:** each workflow transition now names the *position* that may make it (`required_position_id`), not a role. Migration `0009` converted the existing ETLS moves with a fixed role-to-post mapping `[CONFIRM]`, then dropped `required_role_id`. The engine (backend/app/core/workflow/service.py) now checks the posts you hold:
- `available_transitions()` lists moves for any post you hold.
- `change_status()` refuses with **403** "None of your positions can make this move" otherwise.
- The audit row records `as_position` (older rows keep their `as_role`; the log is append-only).

Roles still decide what *kind* of user you are: who may open an ETLS case (applicants) and who may see case history (staff). Holding the `director` role without the Director of Trade post no longer lets you assign files.

**The ETLS moves now:**
```
submitted --(records_officer: Register and forward)--> with_minister
with_minister --(minister, or permanent_secretary)--> with_directorate
with_directorate --(director_of_trade: Assign to an officer)--> with_officer
with_officer --(trade_officer)--> approved | rejected | back to with_directorate
```
**Files:** backend/alembic/versions/0009_transitions_require_positions.py, backend/app/core/workflow/models.py (`WorkflowTransition.required_position`), backend/app/core/workflow/service.py, backend/app/core/identity/service.py (`create_user` now loads `positions`), backend/tests/core/test_cases.py (`POSITION_FOR`, two new tests), backend/tests/core/test_case_race.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- See which post makes each move:
  ```
  docker compose exec db psql -U motie -d motie -c "SELECT f.code AS from_status, t.code AS to_status, p.code AS position, x.name FROM core.workflow_transitions x JOIN core.workflow_statuses f ON f.id = x.from_status_id JOIN core.workflow_statuses t ON t.id = x.to_status_id JOIN core.positions p ON p.id = x.required_position_id ORDER BY x.id"
  ```
- Create staff users as in step 3c, then give each a post with `assign-position` (step 4b): `records_officer`, `minister`, `director_of_trade`, `trade_officer`. Without the post, the same user gets 403.
- `docker compose run --rm tools pytest tests/core/test_cases.py -v`. Read `test_the_position_decides_not_the_role` and `test_a_new_post_holder_takes_over_at_once`.
**New concepts:** Changing a column with existing data (expand, backfill, contract)

### Step 4b — Departments, positions and who holds them (2026-10-19)
**Built:** three tables in `core`:
- `departments`: the Ministry's units.
- `positions`: posts such as "Director of Trade". Each belongs to a department and has a `reports_to_id` pointing at the post above it.
- `position_holders`: which user holds which post.

A user can hold several posts (an officer acting as Director), and a post can have several holders (several Trade Officers). Migration `0008` seeds a placeholder org chart `[CONFIRM]`. `assign_position()` and `remove_position()` change holders and write an audit row (`position.assigned` / `position.removed`) for each real change. `/auth/me` now lists your positions. Nothing uses positions for approvals yet; that's step 4c.

**The placeholder org chart:**
```
Minister (Office of the Minister)
└── Permanent Secretary (Office of the PS)
    ├── Records Officer (Registry)
    └── Director of Trade (Directorate of Trade)
        └── Trade Officer (Directorate of Trade)
```
**Files:** backend/alembic/versions/0008_positions.py, backend/app/core/identity/models.py (`Department`, `Position`, `position_holders`, `User.positions`), backend/app/core/identity/service.py (`assign_position`, `remove_position`), backend/app/core/identity/cli.py, backend/app/core/identity/schemas.py, backend/app/core/identity/router.py, backend/tests/conftest.py (`make_user(..., positions=[...])`), backend/tests/core/test_positions.py, backend/tests/core/test_auth.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- Give a user a post: `docker compose exec api python -m app.core.identity.cli assign-position --email you@motie.gov.gm --position director_of_trade`. Run it twice: the second time it says "Nothing to do". Take it away with `remove-position`.
- Log in and call `GET /auth/me`: `positions` lists your posts.
- See who holds what: `docker compose exec db psql -U motie -d motie -c "SELECT p.title, u.email, h.assigned_at FROM core.position_holders h JOIN core.positions p ON p.id = h.position_id JOIN core.users u ON u.id = h.user_id"`
- `docker compose run --rm tools pytest tests/core/test_positions.py -v`
**New concepts:** Positions vs roles, Self-referencing foreign key, `ON CONFLICT DO NOTHING ... RETURNING`

### Step 4a — Separate database users (2026-10-19)
**Built:** the API no longer logs in to Postgres as the superuser. There are now three database users, each with one job:
- `motie` (`POSTGRES_USER`, the superuser): only used by db/init/10-db-users.sh and to create the test database.
- `motie_owner`: owns the database, the schemas and every table. Migrations run as it.
- `motie_app`: what the API logs in as. It owns nothing, so it can't `ALTER` or `DROP` tables or disable the audit triggers. Migration `0007` grants it only what the API needs, table by table: read-only on roles and workflow definitions, no `DELETE` on users and cases, and only `SELECT` and `INSERT` on the audit log.

Migrations and tests now run in a new one-off `tools` container, which has the owner's password. The long-running `api` container only gets `motie_app`'s.

**Files:** db/init/10-db-users.sh, backend/alembic/versions/0007_app_privileges.py, docker-compose.yml, .env.example, backend/alembic/env.py, backend/app/core/config.py, backend/tests/conftest.py (`owner_session`), backend/tests/core/test_db_privileges.py, backend/tests/core/test_audit.py, backend/tests/core/test_workflow_definitions.py, CLAUDE.md (commands)
**Try it:**
- **Your `.env` needs two new passwords:** `MIGRATION_DB_PASSWORD` and `APP_DB_PASSWORD`. I added generated ones to your local `.env`. On any other machine, copy them from `.env.example` and change them.
- **Commands changed.** Migrations: `docker compose run --rm tools alembic upgrade head`. Tests: `docker compose run --rm tools pytest -v`. `docker compose exec api alembic ...` now stops with "MIGRATION_DATABASE_URL is not set". That's on purpose: the API container doesn't have the owner's password.
- A database created before this step (your dev one, or a server) needs the users script once, then the migration. I've already done both on your dev database:
  ```
  docker compose up -d
  docker compose exec db bash /docker-entrypoint-initdb.d/10-db-users.sh
  docker compose run --rm tools alembic upgrade head
  ```
  On a brand-new volume, Postgres runs the script by itself the first time it starts.
- Try to switch off the audit protection as the app: `docker compose exec db psql -U motie_app -d motie -c "ALTER TABLE core.audit_log DISABLE TRIGGER ALL"` gives `ERROR: must be owner of table audit_log`. The same with `-c "DELETE FROM core.audit_log"` gives `permission denied`.
- `docker compose run --rm tools pytest tests/core/test_db_privileges.py tests/core/test_audit.py -v`
**New concepts:** Least privilege (database users), GRANT and table ownership, One-off containers (Compose profiles)

### Step 3c — Cases moving through the workflow (2026-10-18)
**Built:** `core.cases` (one row per file, holding its current status) and the workflow engine in backend/app/core/workflow/service.py, the only code that creates cases or changes their status. `change_status()` does five things:
1. Locks the case row.
2. Checks that the move exists from the current status (otherwise **409**).
3. Checks that the caller has the role for it (otherwise **403**).
4. Updates the status.
5. Writes the audit row and commits both together.

Four endpoints:
- `POST /cases` opens a case.
- `GET /cases/{id}` returns the case plus the actions *you* may take next.
- `POST /cases/{id}/status` makes a move.
- `GET /cases/{id}/history` returns the audit trail (staff only).

Applicants see only their own cases. Someone else's case returns the same 404 as a case that doesn't exist.

**Files:** backend/alembic/versions/0006_cases.py, backend/app/core/workflow/models.py (`Case`), backend/app/core/workflow/service.py, backend/app/core/workflow/schemas.py, backend/app/core/workflow/router.py, backend/app/main.py, backend/tests/core/test_cases.py, backend/tests/core/test_case_race.py
**Try it:**
1. `docker compose run --rm tools alembic upgrade head`
2. Create one user per role with the CLI (step 2b): `applicant`, `records_officer`, `minister`, `director`, `officer`.
3. In `localhost:8000/docs`, log in as the applicant and `POST /cases` with `{"workflow": "etls_application"}`.
4. Log in as the records officer, `GET /cases/1`, and look at `available_actions`. Then `POST /cases/1/status` with `{"to_status": "with_minister", "comment": "Registered"}`.
5. Try something illegal, such as the officer approving straight away, and watch it get a 409 or 403.
6. `GET /cases/1/history` as staff shows every step, with who and when.
- `docker compose run --rm tools pytest tests/core/test_cases.py tests/core/test_case_race.py -v`
**New concepts:** Row locking (`SELECT ... FOR UPDATE`), Hiding existence with 404

### Step 3b — Workflow definitions as data (2026-10-18)
**Built:** three tables that *describe* a workflow. `workflows` holds the process and the role that may start one. `workflow_statuses` holds its steps, with one marked initial and some marked final. `workflow_transitions` holds the allowed moves, each with the role that may make it. The database refuses a second initial status and refuses a move that points into another workflow's status. Migration `0005` seeds a placeholder ETLS workflow `[CONFIRM]`. Tests check that every workflow has exactly one start, no dead ends, no moves out of final statuses, and no unreachable statuses.
**Files:** backend/alembic/versions/0004_workflow_definitions.py, backend/alembic/versions/0005_seed_etls_workflow.py, backend/app/core/workflow/models.py, backend/tests/core/test_workflow_definitions.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- See the ETLS moves as a table (this query is the step 4c version, with positions):
  ```
  docker compose exec db psql -U motie -d motie -c "SELECT f.code AS from_status, t.code AS to_status, p.code AS position, x.name FROM core.workflow_transitions x JOIN core.workflow_statuses f ON f.id = x.from_status_id JOIN core.workflow_statuses t ON t.id = x.to_status_id JOIN core.positions p ON p.id = x.required_position_id ORDER BY x.id"
  ```
- `docker compose run --rm tools pytest tests/core/test_workflow_definitions.py -v`
**The placeholder ETLS workflow:**
```
submitted --(records_officer: Register and forward)--> with_minister
with_minister --(minister, or permanent_secretary)--> with_directorate
with_directorate --(director: Assign to an officer)--> with_officer
with_officer --(officer)--> approved | rejected | back to with_directorate
```
**New concepts:** State machine, Composite foreign keys, Partial unique index, Data migrations

### Step 3a — Append-only audit log (2026-10-18)
**Built:** `core.audit_log`, one row per event: who, what action, which record, when, and details as JSON. Postgres triggers reject every `UPDATE`, `DELETE` and `TRUNCATE` on it, so history can't be rewritten even with raw SQL. `record_event()` adds a row to the *current* transaction without committing, so the change and its audit row are saved together. `history()` lists a record's events, oldest first.
**Files:** backend/alembic/versions/0003_audit_log.py, backend/app/core/audit/models.py, backend/app/core/audit/service.py, backend/app/models.py, backend/tests/core/test_audit.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head`
- See the protection yourself: `docker compose exec db psql -U motie -d motie -c "DELETE FROM core.audit_log"` gives `ERROR: core.audit_log is append-only: DELETE is not allowed`.
- `docker compose run --rm tools pytest tests/core/test_audit.py -v`
**New concepts:** Append-only audit log, Database triggers, Transactions (all-or-nothing)

### Step 2c — Login with tokens (2026-10-18)
**Built:** `POST /auth/login` checks email and password and returns a signed token (JWT) valid for 60 minutes. `GET /auth/me` returns who the token belongs to. `get_current_user` and `require_role(...)` are the dependencies every protected endpoint will use. Login failures all look identical (same status, same message, same timing), so nobody can probe which emails have accounts.
**Files:** backend/app/core/identity/security.py (tokens), backend/app/core/identity/service.py (`authenticate`), backend/app/core/identity/deps.py, backend/app/core/identity/schemas.py, backend/app/core/identity/router.py, backend/app/core/config.py, backend/app/main.py, docker-compose.yml, .env.example, backend/tests/core/test_auth.py, backend/tests/conftest.py (`make_user`, `auth_headers`)
**Try it:**
- **Your `.env` now needs `JWT_SECRET`.** I added a generated one to your local `.env`. On any other machine, generate one as `.env.example` shows. Compose refuses to start without it.
- `docker compose up --build`, create a user with the CLI (step 2b), then open `localhost:8000/docs`. Run `POST /auth/login`, copy the `access_token`, click **Authorize**, paste it, and run `GET /auth/me`.
- Or with curl: `curl -X POST localhost:8000/auth/login -H "Content-Type: application/json" -d '{"email":"you@motie.gov.gm","password":"..."}'`
- `docker compose run --rm tools pytest tests/core/test_auth.py -v`
**New concepts:** JWT access tokens, Authentication vs authorization (401 vs 403), User enumeration

### Step 2b — Roles and users (2026-10-18)
**Built:** three tables in `core`. `roles` comes pre-filled with placeholder Ministry roles `[CONFIRM]`. `users` holds email, name, an Argon2 password hash, an active flag and a creation time. `user_roles` links them, because one person can hold several roles. A service function `create_user` enforces the rules: lowercase unique email, known roles only, password at least 12 characters. A CLI creates users from the terminal. A new test fails if the Python table classes and the migrations ever disagree.
**Files:** backend/alembic/versions/0002_roles_and_users.py, backend/app/core/identity/models.py, backend/app/core/identity/security.py, backend/app/core/identity/service.py, backend/app/core/identity/cli.py, backend/app/models.py, backend/tests/core/test_users.py, backend/tests/test_migrations.py
**Try it:**
- `docker compose up --build` (new library: pwdlib), then `docker compose run --rm tools alembic upgrade head`.
- Create your own admin: `docker compose exec api python -m app.core.identity.cli create-user --email you@motie.gov.gm --name "Your Name" --role admin`
- Look at the result in psql: `docker compose exec db psql -U motie -d motie -c "SELECT id, email, left(password_hash, 30) FROM core.users"`. The hash starts with `$argon2id$`.
- `docker compose run --rm tools pytest -v`
**New concepts:** Password hashing, ORM models vs migrations

### Step 2a — Alembic and the core schema (2026-10-18)
**Built:** Alembic migrations, set up for our async engine. Migration `0001` creates the `core` schema, where all shared tables will live. The test suite now rebuilds `motie_test` from the migrations on every run, and one test downgrades everything and upgrades again to prove every migration can be rolled back.
**Files:** backend/alembic.ini, backend/alembic/env.py, backend/alembic/versions/0001_core_schema.py, backend/app/db/base.py, backend/app/models.py, backend/tests/conftest.py, backend/tests/test_migrations.py
**Try it:**
- `docker compose run --rm tools alembic upgrade head` applies migrations to your dev database. Run this after pulling new migrations.
- `docker compose run --rm tools alembic current` shows which migration the database is at.
- `docker compose run --rm tools alembic upgrade head --sql` prints the SQL without running it.
- `docker compose run --rm tools pytest -v`
**New concepts:** Database migrations, Postgres schemas

### Step 1 — FastAPI skeleton connected to Postgres (2026-10-18)
**Built:** two Docker Compose services: Postgres 16 (with pgvector available) and the FastAPI app. The app reads `DATABASE_URL`, keeps one connection pool, and exposes `/health` (the process is alive) and `/health/db` (Postgres answers a query). If the database is down, `/health/db` returns 503 with a plain message and logs the full error on the server. Tests run against a separate `motie_test` database.
**Files:** docker-compose.yml, .env.example, backend/Dockerfile, backend/requirements.txt, backend/requirements-dev.txt, backend/app/main.py, backend/app/core/config.py, backend/app/db/session.py, backend/app/api/health.py, backend/tests/conftest.py, backend/tests/test_health.py
**Try it:**
- `docker compose up --build`, then `curl localhost:8000/health` and `curl localhost:8000/health/db`.
- `docker compose run --rm tools pytest -v` runs the tests (since step 4a, in the tools container).
- `docker compose stop db`, then `curl -i localhost:8000/health/db` should give 503 with no hostnames or usernames in the body. Bring it back with `docker compose start db`.
- From your own machine, a database tool connects to `localhost:5433` (not 5432).
**New concepts:** Docker Compose networking, Connection pool, Liveness vs readiness, Lifespan and `yield` dependencies, Test database with rollback

## 2. Concepts

One short explanation per concept, where it lives in this codebase, and one free resource.

### Docker Compose networking
**What:** Compose puts all services on one private network and gives each one a hostname equal to its service name. Every container has its *own* `localhost`, so the API must reach Postgres as `db`, not `localhost`. `ports:` only matters for reaching a container from your own machine.
**Here:** docker-compose.yml: `DATABASE_URL` uses host `db`, and the db service publishes `127.0.0.1:5433:5432` (host port 5433 → container port 5432).
**Learn more:** [Networking in Compose](https://docs.docker.com/compose/how-tos/networking/)

### Connection pool
**What:** opening a Postgres connection is slow (network handshake + login). A pool keeps a few connections open and lends them out to requests, then takes them back. SQLAlchemy's *engine* owns the pool; a *session* borrows a connection for the length of one request.
**Here:** backend/app/db/session.py: `engine` (one per process) and `get_session()` (one per request).
**Learn more:** [SQLAlchemy: Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)

### Liveness vs readiness
**What:** two different health questions. *Liveness*: is the process running? *Readiness*: can it actually do its job (here: reach the database)? Keeping them apart tells an operator *which* part is broken.
**Here:** backend/app/api/health.py: `health()` never touches the database, while `health_db()` runs `SELECT 1`.
**Learn more:** [Kubernetes: liveness and readiness probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/). The same idea applies outside Kubernetes.

### Lifespan and `yield` dependencies
**What:** in both, code before `yield` is setup and code after `yield` is cleanup. They differ in *how often* that happens. `lifespan` runs once for the whole server (startup and shutdown). A `yield` dependency runs once per request.
**Here:** backend/app/main.py `lifespan()` closes the pool on shutdown. backend/app/db/session.py `get_session()` closes each request's session.
**Learn more:** [FastAPI: Lifespan events](https://fastapi.tiangolo.com/advanced/events/), [FastAPI: Dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)

### Test database with rollback
**What:** tests use a separate database so they never damage dev data. Each test runs inside one big transaction that is rolled back at the end, so tests can't leave data behind for each other. Code under test can still call `commit()`: in tests that only commits a *savepoint* inside the outer transaction.
**Here:** backend/tests/conftest.py: `_create_test_database()`, `db_session` and `client` fixtures. The `client` fixture swaps the real `get_session` for the test one with `app.dependency_overrides`.
**Learn more:** [SQLAlchemy: Joining a Session into an External Transaction](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)

### Database migrations
**What:** numbered scripts that change the database structure step by step. Each has an `upgrade()` (apply the change) and a `downgrade()` (undo it). Alembic records the current number in a small `alembic_version` table, so `alembic upgrade head` runs only the scripts a database hasn't had yet. Every copy of the database (yours, the test one, the Ministry server) ends up identical.
**Here:** backend/alembic/versions/: one file per change, named `NNNN_description.py`. backend/alembic/env.py connects Alembic to our database.
**Learn more:** [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)

### Postgres schemas
**What:** a schema is a named folder for tables inside one database. `core.users` and `etls.users` would be two different tables. We use one schema per module so modules can't collide, and so permissions can later be granted per module.
**Here:** backend/alembic/versions/0001_core_schema.py creates `core`. Table classes will set `__table_args__ = {"schema": "core"}`.
**Learn more:** [PostgreSQL docs: Schemas](https://www.postgresql.org/docs/16/ddl-schemas.html)

### Password hashing
**What:** we never store passwords. We store a *hash*, a one-way scramble that can check a password but can't be turned back into it. Argon2 is built to be slow and to need a lot of memory, so an attacker who steals the users table can only try a few guesses per second per machine. Each hash includes a random *salt*, so identical passwords give different hashes.
**Here:** backend/app/core/identity/security.py: `hash_password()` and `verify_password()`.
**Learn more:** [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

### ORM models vs migrations
**What:** two descriptions of the same tables. *Migrations* actually build the tables in Postgres, step by step. *Models* (Python classes like `User`) let the code read and write rows without hand-written SQL. They must agree, so `test_models_match_migrations` asks Alembic to compare them and fails on any difference.
**Here:** backend/app/core/identity/models.py (models), backend/alembic/versions/0002_roles_and_users.py (migration), backend/tests/test_migrations.py (the check).
**Learn more:** [SQLAlchemy ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)

### JWT access tokens
**What:** a JWT is a small piece of text with three parts: header, payload (here: user id and expiry time) and a *signature*. The server makes the signature with `JWT_SECRET`, so if anyone changes the payload, or makes a token without the secret, the signature check fails. The payload is only encoded, **not encrypted**: never put secrets in it. Paste a token into jwt.io to see.
**Here:** backend/app/core/identity/security.py: `create_access_token()` and `decode_access_token()`. backend/app/core/identity/deps.py: `get_current_user()` checks the token on each request.
**Learn more:** [Introduction to JSON Web Tokens (jwt.io)](https://jwt.io/introduction)

### Authentication vs authorization (401 vs 403)
**What:** *authentication* asks "who are you?". If we can't tell (no token, bad token), the answer is **401 Unauthorized**. *Authorization* asks "are you allowed to do this?". If we know who you are but the answer is no, it's **403 Forbidden**.
**Here:** backend/app/core/identity/deps.py: `get_current_user()` raises 401, `require_role()` raises 403.
**Learn more:** [MDN: 401](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401), [MDN: 403](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403)

### User enumeration
**What:** if a login form says "no such email" for one email and "wrong password" for another, an attacker learns which emails have accounts and can target them. Response *time* can leak the same thing: checking a password hash is slow, and skipping it for unknown emails is fast. So we return one message and always do a hash check.
**Here:** backend/app/core/identity/service.py: `authenticate()` and `_dummy_hash()`. backend/app/core/identity/router.py: `login()`.
**Learn more:** [OWASP Authentication Cheat Sheet: authentication responses](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html#authentication-and-error-messages)

### Append-only audit log
**What:** a record of everything that happened, where rows are only ever added, never changed or deleted. If someone could edit it, it would prove nothing. For a Ministry, the log answers "who approved this, and when?" years later.
**Here:** backend/app/core/audit/service.py: `record_event()` and `history()`. The rule is enforced in backend/alembic/versions/0003_audit_log.py.
**Learn more:** [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

### Database triggers
**What:** a function that Postgres runs automatically before or after certain statements on a table. Ours runs *before* any UPDATE, DELETE or TRUNCATE on `core.audit_log` and raises an error, which cancels the statement. Because it lives in the database, it protects the table from every client: our API, psql, a future reporting tool.
**Here:** backend/alembic/versions/0003_audit_log.py: `core.audit_log_block_changes()` and the two `CREATE TRIGGER` statements.
**Learn more:** [PostgreSQL docs: Triggers](https://www.postgresql.org/docs/16/plpgsql-trigger.html)

### Transactions (all-or-nothing)
**What:** a group of SQL statements that Postgres saves together at `COMMIT`, or not at all if anything fails (`ROLLBACK`). That's why `record_event()` doesn't commit: the caller changes the record, adds the audit row, then commits once. A crash in between leaves neither change behind.
**Here:** backend/app/core/audit/service.py `record_event()` (adds, never commits). Step 3c's `change_status()` uses it.
**Learn more:** [PostgreSQL tutorial: Transactions](https://www.postgresql.org/docs/16/tutorial-transactions.html)

### State machine
**What:** a model with a fixed set of *states* (our statuses) and a fixed set of allowed *transitions* between them. Anything not on the list is impossible. A file can't jump from "Submitted" to "Approved" just because someone sent that request. Storing the states and transitions in tables ("workflows are data") means a new Ministry process is new rows, not new code.
**Here:** the tables are in backend/alembic/versions/0004_workflow_definitions.py and the classes in backend/app/core/workflow/models.py. Step 3c's `change_status()` enforces them.
**Learn more:** [Wikipedia: Finite-state machine](https://en.wikipedia.org/wiki/Finite-state_machine). Read the turnstile example.

### Composite foreign keys
**What:** a foreign key over *two* columns together. `workflow_transitions(workflow_id, to_status_id)` must match a row in `workflow_statuses(workflow_id, id)`. A plain key on `to_status_id` alone would accept *any* status, even one from a different workflow. The pair forces both to agree.
**Here:** `workflow_transitions_from_fkey` and `workflow_transitions_to_fkey` in backend/alembic/versions/0004_workflow_definitions.py. They need the matching `UNIQUE (workflow_id, id)` on `workflow_statuses`.
**Learn more:** [PostgreSQL docs: Foreign keys](https://www.postgresql.org/docs/16/ddl-constraints.html#DDL-CONSTRAINTS-FK)

### Partial unique index
**What:** a unique rule that applies only to rows matching a condition. `UNIQUE (workflow_id) WHERE is_initial` means a workflow can have many statuses, but only one of them with `is_initial = true`.
**Here:** `workflow_statuses_one_initial` in backend/alembic/versions/0004_workflow_definitions.py.
**Learn more:** [PostgreSQL docs: Partial indexes](https://www.postgresql.org/docs/16/indexes-partial.html)

### Data migrations
**What:** a migration that inserts or changes *rows* rather than table structure. We use one to load the ETLS workflow, so every database gets exactly the same definition. Rows are looked up by `code`, never by `id`, because ids can differ between databases.
**Here:** backend/alembic/versions/0005_seed_etls_workflow.py. Also the role list at the end of 0002.
**Learn more:** [Alembic cookbook: data migrations](https://alembic.sqlalchemy.org/en/latest/cookbook.html#data-migrations-general-techniques)

### Row locking (`SELECT ... FOR UPDATE`)
**What:** two officers press "Approve" and "Reject" on the same file in the same second. Without care, both requests read "With the officer", both decide their move is allowed, and both save: the file is approved *and* rejected. `FOR UPDATE` locks the row when it's read. The second request waits until the first commits, then reads the *new* status (final) and is refused.
**Here:** backend/app/core/workflow/service.py: `get_case(..., for_update=True)`, used by `change_status()`. Proven by backend/tests/core/test_case_race.py, which fails if you remove the lock (we tried it: 3 out of 3 failures).
**Learn more:** [PostgreSQL docs: Row-level locks](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)

### Hiding existence with 404
**What:** if `/cases/41` said "403 not yours" and `/cases/9999` said "404 not found", an applicant could count how many cases exist, or test which ids are real. Returning the same 404 for both reveals nothing. We use 403 only when the user is allowed to *see* the thing but not to *do* the action.
**Here:** backend/app/core/workflow/service.py `get_case()`. Tested by `test_applicants_only_see_their_own_cases`.
**Learn more:** [OWASP: Insecure Direct Object Reference](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html)

### Least privilege (database users)
**What:** give each program only the rights it needs. If someone breaks into the API, they get whatever the API's database login can do. If that login owns the tables, they can switch off the audit trigger and rewrite history. As `motie_app`, they can only do what the API itself does. So there are three logins with three jobs: the superuser creates logins, the owner changes the structure (migrations), and the app reads and writes rows.
**Here:** db/init/10-db-users.sh creates the users. docker-compose.yml gives the `api` container only `motie_app`'s password. backend/tests/core/test_db_privileges.py checks what `motie_app` can't do.
**Learn more:** [OWASP Database Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Database_Security_Cheat_Sheet.html)

### GRANT and table ownership
**What:** in Postgres, whoever creates a table owns it. Only the owner (or a superuser) can `ALTER` or `DROP` it or touch its triggers. Everyone else needs a `GRANT` for each action: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`. Postgres checks privileges *before* it runs triggers, so the app's `DELETE FROM core.audit_log` fails with "permission denied" and never reaches the trigger. The trigger is now a second wall, and it holds even against the owner.
**Here:** backend/alembic/versions/0007_app_privileges.py. Every future migration that adds a table must add its own `GRANT`. If one forgets, `test_every_table_is_owned_by_motie_owner_and_readable_by_the_app` names the table.
**Learn more:** [PostgreSQL docs: Privileges](https://www.postgresql.org/docs/16/ddl-priv.html)

### One-off containers (Compose profiles)
**What:** `docker compose run --rm tools <command>` starts a fresh container from the `tools` service, runs one command, then deletes the container (`--rm`). `profiles: ["tools"]` stops `docker compose up` from starting it. We use it for jobs that need the owner's password, so that password never sits in a server that runs all day.
**Here:** the `tools` service in docker-compose.yml.
**Learn more:** [Docker docs: docker compose run](https://docs.docker.com/reference/cli/docker/compose/run/), [Using profiles with Compose](https://docs.docker.com/compose/how-tos/profiles/)

### Positions vs roles
**What:** a *role* says what kind of user someone is: an applicant, Ministry staff, a system admin. A *position* is a post in the organisation chart, like "Director of Trade", that a person holds for a while and then hands over. Approvals belong to posts. When a new Director arrives, they take over the post, and every workflow that names the post works for them at once, without editing any workflow.
**Here:** `Role` and `Position` in backend/app/core/identity/models.py. `User.role_codes` and `User.position_codes` give each one as a set of codes.
**Learn more:** [Wikipedia: Role-based access control](https://en.wikipedia.org/wiki/Role-based_access_control). Our positions are close to what it calls roles; we keep "role" for the kind of user.

### Self-referencing foreign key
**What:** a column that points at another row of the *same* table. `positions.reports_to_id` holds the id of the post above, so the whole org chart (a tree) fits in one table. The top post has no boss, so its `reports_to_id` is empty. The danger is a loop (A reports to B, B reports to A), which would make "walk up the chain" run forever.
**Here:** `positions.reports_to_id` in backend/alembic/versions/0008_positions.py. The `positions_not_own_boss` check stops the shortest loop. `test_every_chain_of_command_ends_at_one_top_post` walks up from every post to catch longer ones.
**Learn more:** [PostgreSQL docs: recursive queries (WITH RECURSIVE)](https://www.postgresql.org/docs/16/queries-with.html#QUERIES-WITH-RECURSIVE), the usual way to walk such a tree in SQL.

### `ON CONFLICT DO NOTHING ... RETURNING`
**What:** "insert this row, unless one with the same key already exists; then tell me what you inserted". If nothing was inserted, nothing comes back. Checking first ("does the row exist?") and inserting second has a gap: two admins clicking at the same moment both see "no", and the second insert crashes. Doing it in one statement has no gap.
**Here:** `assign_position()` in backend/app/core/identity/service.py. It writes an audit row only when the insert returned something, so the log never records a change that didn't happen. `remove_position()` does the same with `DELETE ... RETURNING`.
**Learn more:** [PostgreSQL docs: INSERT ... ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html#SQL-ON-CONFLICT)

### Changing a column with existing data (expand, backfill, contract)
**What:** you can't swap one column for another in one go when rows already use it. Do it in three moves inside one migration. *Expand*: add the new column, allowing empty values. *Backfill*: fill it from the old column for every existing row. *Contract*: make it `NOT NULL`, then drop the old column. The `NOT NULL` step is also a safety check: if any row couldn't be converted, the migration fails and rolls back instead of leaving a move with no approver.
**Here:** backend/alembic/versions/0009_transitions_require_positions.py: `add_column` (expand), the `UPDATE ... FROM (VALUES ...)` (backfill), `alter_column(..., nullable=False)` and `drop_column` (contract). `downgrade()` does the same in reverse.
**Learn more:** [Martin Fowler: Parallel Change (expand and contract)](https://martinfowler.com/bliki/ParallelChange.html)

### Delegation (acting on behalf of)
**What:** letting someone use another person's authority for a limited time, while every action still records *who* acted and *whose* authority they used. In a ministry this is everyday work: "the PS, for the Minister". Three things make it safe: it's limited (dates, optionally one workflow), it's visible (both sides see it, and every use is logged) and it can be ended early (revoked).
**Here:** backend/app/core/workflow/delegation.py: `create_delegation()` checks the rules, and `active_delegations_to()` answers "which posts may this user act for today?". backend/app/core/workflow/service.py: `_permitted()` combines own posts and delegations, and `change_status()` writes `on_behalf_of` and `delegation_id` into the audit row.
**Learn more:** [Wikipedia: Delegation of authority](https://en.wikipedia.org/wiki/Delegation)

### Column-level privileges
**What:** a `GRANT` (see GRANT and table ownership) can name single columns: `GRANT UPDATE (revoked_at, revoked_by) ON core.delegations`. The app can then change those columns and nothing else in the row. Any `UPDATE` that touches another column fails with "permission denied". SQLAlchemy only sends the columns that actually changed, so ordinary code works.
**Here:** backend/alembic/versions/0010_delegations.py. Tested by the `stretch-delegation` case in backend/tests/core/test_db_privileges.py.
**Learn more:** [PostgreSQL docs: GRANT, column privileges](https://www.postgresql.org/docs/16/sql-grant.html)

### Testing with a fake "today" (monkeypatch)
**What:** code that asks "what's the date?" is hard to test: you can't wait until next week. So all delegation code gets the date from one function, `today()`. A test swaps that function for one returning any date it likes. pytest's `monkeypatch` fixture does the swap and puts the real function back when the test ends, even if it fails.
**Here:** `today()` in backend/app/core/workflow/delegation.py. `test_a_delegation_only_works_between_its_dates` in backend/tests/core/test_delegations.py moves "today" to the day before, the day after and the last day.
**Learn more:** [pytest docs: monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)

### NULL in unique constraints (`NULLS NOT DISTINCT`)
**What:** in SQL, `NULL` means "unknown", so two NULLs are never equal. Usually that's harmless, but it means a `UNIQUE (position_id, workflow_id, rank)` would let two general rules (workflow empty) share rank 1: Postgres doesn't see them as duplicates. Postgres 15 added `NULLS NOT DISTINCT`, which makes the constraint treat every NULL as the same value.
**Here:** `succession_orders_rank_key` and `succession_orders_successor_key` in backend/alembic/versions/0013_succession_orders.py. The `same-rank` case in backend/tests/core/test_succession.py only passes because of it.
**Learn more:** [PostgreSQL docs: Unique constraints](https://www.postgresql.org/docs/16/ddl-constraints.html#DDL-CONSTRAINTS-UNIQUE-CONSTRAINTS)

### Succession (acting for an absent post)
**What:** a standing rule for who takes over a post's work while its holder is away, so files don't stop moving. It differs from delegation in who decides. With delegation, the holder decides, each time. With succession, the Ministry decided once, in advance, and it applies by itself once an absence is recorded. To stay safe, it only applies when *every* holder is recorded as away; only the first person in line who is at work may act; and the audit row lists the absences that justified it.
**Here:** the order is `core.succession_orders` (0013), absences are `core.absences` (0014), and `acting_successor()` in backend/app/core/workflow/succession.py combines them. `_permitted()` in backend/app/core/workflow/service.py decides between own post, delegation and succession.
**Learn more:** [Wikipedia: Order of succession](https://en.wikipedia.org/wiki/Order_of_succession). The same idea, applied to heads of state.

### Modules on a shared core
**What:** the core (users, posts, workflow engine, audit) knows nothing about ETLS. A module adds its own tables in its own schema and calls core functions; the core never imports the module or reads its tables. So the next Ministry process can be added without touching ETLS, and the core stays one tested piece.
**Here:** backend/app/modules/etls/service.py `submit_facility_letter()` calls `workflow.open_case()` from the core, adds `etls.*` rows, and commits once. The tables are in the `etls` schema (backend/alembic/versions/0015_etls_facility_letter.py). `workflows.opened_by_module` tells the core "don't open these yourself".
**Learn more:** [Martin Fowler: Monolith First](https://martinfowler.com/bliki/MonolithFirst.html), on starting with one well-divided app.

### `NUMERIC` vs floating point
**What:** a float stores numbers in binary, so most decimals are only approximated: in Python, `0.1 + 0.2 == 0.30000000000000004`. `NUMERIC(14, 3)` stores decimal digits exactly (up to 14 digits, 3 after the point), and Python's `Decimal` keeps them exact. Use it for anything copied onto an official document or added up as money.
**Here:** `quantity` in `etls.facility_letters`, `Decimal` with `max_digits=14, decimal_places=3` in backend/app/modules/etls/schemas.py. `test_applicant_submits_the_form_and_a_case_opens` checks `1200.5` comes back as exactly `1200.500`.
**Learn more:** [Python docs: decimal](https://docs.python.org/3/library/decimal.html)

### Advisory locks
**What:** a lock on a *number you choose*, not on a table row. `pg_advisory_xact_lock(n)` waits until nobody else holds lock `n`, then holds it until your transaction ends. It's for "only one at a time" rules that no row can carry. Here, a certificate number that may not exist in any row yet: `FOR UPDATE` can't lock a row that isn't there. We turn the text "etls.coo:<number>" into a lock number with `hashtextextended()`. We lock several numbers in sorted order, so two transactions can never each hold one lock and wait for the other's (a deadlock).
**Here:** `_earlier_uses()` in backend/app/modules/etls/service.py. `test_two_submissions_at_the_same_moment_cannot_both_slip_through` holds each transaction open after the check. Without the lock, both submissions go through unflagged; we checked by removing it.
**Learn more:** [PostgreSQL docs: Advisory locks](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS)

### Rules as data (a small condition language)
**What:** instead of `if product == "cement": require receipt` in Python, the rule is a row: which document, and a condition. A new rule is a migration, not a code change, and anyone can read the rules from the table. The danger is letting data run arbitrary code, so the "language" is tiny on purpose: one field, one of two operators, one value. The database refuses anything else. The core gets the facts to test from the module through a registered function, so it never needs to know what a facility letter is (this is called *dependency inversion*: the core defines the hook, the module plugs into it).
**Here:** backend/app/core/documents/conditions.py `holds()`, backend/app/core/documents/facts.py `register()`/`facts_for()`, the `document_requirements_condition_shape` check in backend/alembic/versions/0017_documents.py, and `facility_letter_facts()` in backend/app/modules/etls/service.py.
**Learn more:** [Martin Fowler: Rules Engine](https://martinfowler.com/bliki/RulesEngine.html). It's also a warning about letting these grow too big.

### Safe file uploads
**What:** an upload is the easiest way to get something nasty onto a server. The rules we follow:
- Limit the size while reading, not after.
- Decide the type from the file's own first bytes ("magic numbers"), never from its name or the browser's claim.
- Never use the user's filename in a path: store under a random name, and keep the cleaned-up name for display only.
- Keep a checksum, to prove later that the file hasn't changed.
- Serve files back as downloads (`attachment`, `nosniff`), so a browser never runs them as part of our site.
**Here:** backend/app/core/documents/storage.py `save()` and `path_for()`, `clean_filename()` in backend/app/core/documents/service.py, `download_document()` in backend/app/core/documents/router.py.
**Learn more:** [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)

### A registry of named checks (plug-ins)
Since step 6f, the same pattern also covers **effects**: things a move sets off once it's made (backend/app/core/workflow/effects.py, table `core.transition_effects`).

**What:** the engine shouldn't know about documents, payments or GRA, but some moves must wait for them. So the engine only knows *names*: "this move needs `documents_complete`". Each part of the system registers a function under a name it owns, and the engine calls whatever is registered. It's the same idea as `facts.register()` in step 6c. Two safety rules: a name with nothing registered blocks the move instead of being skipped, and a test compares the names in the database with the registered functions.
**Here:** backend/app/core/workflow/checks.py `register()` and `problems()`, called from `change_status()`. Registrations at the bottom of backend/app/core/documents/service.py.
**Learn more:** [Python Packaging Guide: creating and discovering plugins](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/), the same idea at package scale.

### Generating documents from a template
**What:** keep *what* a letter says (a text file with placeholders) apart from *how* it's printed (code that lays text out on a page), and apart from *where the facts come from* (database queries). Each part can then change without the others: the Ministry rewords the letter, ICT changes the layout, or a field moves to another table. Testing is easier too. The fields are a plain object you can check, and the PDF can be written uncompressed so tests can find the printed text in its bytes.
**Here:** `build_fields()` (facts), templates/facility_letter.txt (words) and `render_pdf()` (layout) in backend/app/modules/etls/. `string.Template` only replaces `$names`; unlike `str.format()` it can't reach into objects, which is why we use it for text people may edit. Since step 6i the template is filled one line at a time, *after* its layout marks (`**` bold, ` >> ` right-aligned) are read, so data can never change the layout. That's the same idea as keeping SQL and its parameters apart.
**Learn more:** [Python docs: Template strings](https://docs.python.org/3/library/string.html#template-strings), [fpdf2 tutorial](https://py-pdf.github.io/fpdf2/Tutorial.html)

### Disposable dev environments (reset and seed)
**What:** your dev database should be something you can throw away and rebuild in a minute: migrations make the tables and reference data, a *seed* adds the fake people you need to click through the app. Then trying something by hand ("smoke testing") never leaves you with a database you're afraid to touch, and nobody is tempted to try things on the real one. The danger is the reverse: a reset script run against real data. So it checks a setting that says "this is a dev machine" (`APP_ENV`), defaults to the safe answer when it's missing, and asks before deleting.
**Here:** scripts/reset-dev.sh, `seed()` and `main()` in backend/app/dev_seed.py, `app_env` in backend/app/core/config.py.
**Learn more:** [The Twelve-Factor App: Dev/prod parity](https://12factor.net/dev-prod-parity) and [Config](https://12factor.net/config)

### Cancel and replace (never delete)
**What:** an official record that turns out to be wrong isn't edited or deleted; it's *cancelled*, with who, when and why, and a new record *replaces* it, pointing back at the old one. Anyone can then answer "what did GRA receive on the 3rd?" and "why is there a second letter?". It's how paper registries already work (a cancelled letter stays on file, stamped). Three pieces make it safe here:
- a status on the row, not a delete;
- a link from the new record to the old one (`replaces_id`);
- a database rule saying only one record is current at a time (a *partial* unique index: unique only among rows where `cancelled_at IS NULL`).

A trigger stops anyone from quietly un-cancelling or deleting.
**Here:** `cancel()` and `issue()` in backend/app/core/documents/issued.py, `cancel_letter()` in backend/app/modules/etls/letter.py, the index and trigger in backend/alembic/versions/0022_letter_corrections.py.
**Learn more:** [PostgreSQL docs: Partial indexes](https://www.postgresql.org/docs/16/indexes-partial.html). Example 11.3 there is exactly "only one current row".

### Narrow in SQL, decide in code
**What:** "which cases can I act on?" depends on rules that live in Python: own post, delegation, succession with absences, the order between them. Writing all of that again in SQL would give two versions of the rules that could drift apart. Running the Python on every open case would be slow once there are thousands. So we do both in turn. A cheap SQL query keeps only cases that *could* concern me (a generous superset, never missing one). Then the real rule decides for each of the few left. The superset may let through a case I can't act on, but the second step drops it; it must never leave out one I can, which is why it's generous.
**Here:** `_positions_i_might_act_as()` and `queue()` in backend/app/core/workflow/queues.py; the final word is `available_transitions()` in backend/app/core/workflow/service.py.
**Learn more:** [Martin Fowler: Specification pattern (PDF, with Eric Evans)](https://martinfowler.com/apsupp/spec.pdf), on keeping one definition of a rule and using it for both selecting and checking.

### Gapless numbering (a counter row, not a sequence)
**What:** Postgres has `SEQUENCE`s for numbering, and our ids use them. But a sequence never gives a number back: if a transaction takes 42 and then fails, 42 is gone, and the registry sees 41, 43 and wonders where 42 went. For official numbers people track, we keep the last number in an ordinary row instead, and take the next one with `UPDATE ... SET last_number = last_number + 1 RETURNING last_number` (as an upsert, so the first case of a year creates the row). That `UPDATE` locks the row until the transaction ends. A second submission at the same moment waits, then gets the next number. And if the first one rolls back, its `+ 1` rolls back too. The price is that submissions queue for a moment, which is fine at the Ministry's volume.
**Here:** `next_reference()` in backend/app/core/workflow/service.py; `core.reference_counters` in backend/alembic/versions/0024_case_references.py. `test_two_submissions_at_the_same_moment_get_different_numbers` and `test_a_submission_that_fails_gives_its_number_back` in backend/tests/core/test_case_references.py.
**Learn more:** [PostgreSQL docs: INSERT ... ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html#SQL-ON-CONFLICT) and the note on sequences not being transactional in [Sequence Manipulation Functions](https://www.postgresql.org/docs/16/functions-sequence.html)

### Three answers: yes, no, not known yet
**What:** "does this case need a cement receipt?" can't always be answered yet. Squeezing "don't know" into yes or no is a classic bug: say *yes* and you ask honest applicants for papers they don't need; say *no* and the requirement quietly disappears. So the answer has a third value, `None`, and each place that uses it decides what "not known yet" means *for it*. The early check (Records) lets it wait; the late check (Verify) refuses to go on until it's known. SQL works the same way: `NULL = 'x'` is neither true nor false but unknown, which is why `WHERE` needs `IS NULL`.
**Here:** `holds()` in backend/app/core/documents/conditions.py, `RequirementStatus.undecided` and the checks `known_documents_complete`/`documents_complete` in backend/app/core/documents/service.py.
**Learn more:** [Wikipedia: Three-valued logic (in SQL)](https://en.wikipedia.org/wiki/Null_(SQL)#Comparisons_with_NULL_and_the_three-valued_logic_(3VL))

### HS codes
**What:** the Harmonized System is the world's shared numbering of goods, kept by the World Customs Organization and used by GRA and ECOWAS tariffs. The first 2 digits are the chapter (25: salt, earths and stone, cement), the first 4 the *heading* (2523: cement), the first 6 the subheading (2523.29: other Portland cement). Countries add digits for their own tariff lines (8 or 10). Because everyone uses the same numbers, "is this cement?" becomes "does the code start with 2523?", which free text like "cement mixer" can't fool.
**Here:** `normalize_hs_code()` in backend/app/modules/etls/schemas.py, `hs_heading()` and `facility_letter_facts()` in backend/app/modules/etls/service.py, the rule row in backend/alembic/versions/0020_facility_letter_hs_code.py.
**Learn more:** [WCO: What is the Harmonized System?](https://www.wcoomd.org/en/topics/nomenclature/overview/what-is-the-harmonized-system.aspx)

### Issue once, store with a checksum
**What:** a signed letter is a record, not a report. A report is made fresh from the data each time you ask; a record must say tomorrow exactly what it said when it was signed. So the letter is rendered once, at signing, and the bytes are kept. A *checksum* (SHA-256) is a 64-character fingerprint of those bytes: change one byte and it's completely different. Writing it in the append-only audit log means anyone can later prove a copy is the one issued, by hashing it again and comparing. We also record the *template version*, so you can tell which wording a letter used without opening it.
Two more ideas here:
- **The database can't roll back a file.** So the effect returns an "undo" (delete the file), and the engine calls it if the commit fails.
- **Verify on read.** Each download re-hashes the stored file before sending it. A file damaged or edited on disk is refused, never served as the letter.
**Here:** `issue()` and `read()` in backend/app/core/documents/issued.py; `run()` and `undo_all()` in backend/app/core/workflow/effects.py, called from `change_status()`; `issue_letter()` in backend/app/modules/etls/letter.py.
**Learn more:** [Wikipedia: Cryptographic hash function](https://en.wikipedia.org/wiki/Cryptographic_hash_function) (the "Verifying the integrity of messages and files" section)

### Drafts and submission
**What:** an application has two lives. While it's a **draft**, it belongs only to the applicant: they can change it, add documents, and nothing official has happened. **Submitting** is the moment it becomes the Ministry's business: it gets its tracking number, other people's checks start (the duplicate check), and it lands in a queue. After that the applicant can't quietly change what was submitted; they can only change it if the Ministry hands it back (a return, step 8b). Here both lives are statuses of the same case, so the history runs unbroken from the first draft to the letter. Whether the form may be changed is a property of the status (`applicant_editable`), not a rule in code.
**Here:** `draft` and the Submit move in backend/alembic/versions/0026_drafts.py; `update_form()` in backend/app/modules/etls/service.py; `_assign_reference()` in backend/app/core/workflow/service.py.
**Learn more:** [GOV.UK Service Manual: Structuring forms](https://www.gov.uk/service-manual/design/form-structure) (how public services split "fill in" from "check and send")

### Blocking checks and warnings
**What:** a rule can do two different things to a move. A **blocking check** says "not yet": the move is refused until it passes, and the button shows why (`blocked_by`). A **warning** says "are you sure?": the person is told before they press, the move goes ahead, and the warning is recorded with it, so nobody can later say they weren't told. The same rule can be either at different steps. Here a nearly expired certificate is only a warning when the applicant submits (it's their risk), but an expired one blocks the desk's Verify (the Ministry mustn't approve it). Which one applies is a column on the link between the move and the check (`warn_only`), not code.
**Here:** `problems()` and `warnings()` in backend/app/core/workflow/checks.py; `what_blocks()` and `what_warns()` in backend/app/core/workflow/service.py; the two certificate checks in backend/app/modules/etls/service.py.
**Learn more:** [Nielsen Norman Group: Confirmation dialogs](https://www.nngroup.com/articles/confirmation-dialog/) (when to warn and when to prevent)

### Recorded ticks (attestations)
**What:** some checks can't be done by the computer: here, looking up the exporter on the ECOWAS ETLS list, which isn't connected yet. The officer looks, then *says* they looked, by ticking. A tick that's just a checkbox on the screen proves nothing later. A **recorded tick** is a small statement, "I, this officer, confirmed this, at this time", kept in the database and the audit log, and the move checks it's there. If the item list is data, a new check is a new row, and the same mechanism will serve the certificate of origin desk (S9) and the technical review (S6). When the application changes (a return), the ticks are cleared, because they were statements about the old version.
**Here:** `checklist()`, `set_tick()`, `_check_complete()` and `_clear()` in backend/app/core/workflow/checklist.py; the items in backend/alembic/versions/0029_desk_checks.py.
**Learn more:** [Wikipedia: Non-repudiation](https://en.wikipedia.org/wiki/Non-repudiation) (why a record of *who* confirmed something matters later)

## 3. Decisions

### Confirmed by the Ministry

These were open questions; the Ministry has answered them. The code follows them and no longer marks them `[CONFIRM]`.

- **Chain of command (2026-10-19):** Minister → Permanent Secretary → Deputy PS.
- **ETLS route (2026-10-19):** Records → Minister → PS → Director of Industry and Investment. The Director signs the file and assigns it to an officer. See backend/alembic/versions/0012_confirmed_etls_route.py.
- **Who signs ETLS files (2026-10-19):** the Director of Industry and Investment.
- **"Assign" means minuting the file to an officer (2026-10-19).** It doesn't pass on the Director's signing power, so delegations still can't be passed on (step 4d).
- **Delegations aren't passed on (2026-10-19).** The step 4d rule stays.
- **When the Minister is away, the PS acts; when the PS is away too, a DPS acts (2026-10-19).** This follows the general chain of command, through the succession order (steps 5b and 5d), not a standing transition. (Which DPS is still open.)
- **When the Director of Industry and Investment is away, the DPS Administration and Finance may sign and assign ETLS files (2026-10-19).**
- **A position holder, or an authorised officer on their behalf, records absences (2026-10-19).** The audit log shows who recorded it. (Who counts as "authorised" is still open.)
- **Certificate of origin validity (2026-10-24):** the desk can't verify while any certificate is more than six months past its issue date; at submission the applicant is warned, not stopped, if one expires within 30 days. GRA needs the certificate valid at clearance.
- **The applicant's timeline after a cancelled letter (2026-10-24):** only the cancel move is hidden. A corrected letter replacing one already sent to GRA reads "Corrected letter issued" when it is sent.

### Choices made while building

| Date | Decision | Alternatives considered | Why |
| --- | --- | --- | --- |
| 2026-10-18 | SQLAlchemy 2.0 async + asyncpg | raw asyncpg; SQLModel | Chosen by you. Widely used, works with Alembic, async fits FastAPI. |
| 2026-10-18 | API and db both in Compose; source bind-mounted with `--reload` | only Postgres in Docker | Chosen by you. One command starts everything; edits reload without rebuilding. |
| 2026-10-18 | `pgvector/pgvector:pg16` image | plain `postgres:16` and install pgvector later | The stack needs pgvector. This image has it ready; we enable it with a migration when AI work starts. |
| 2026-10-18 | Ports bound to 127.0.0.1 only | `5432:5432` (all interfaces) | An exposed Postgres port on a server is a common way in for attackers. |
| 2026-10-18 | Postgres published on host port 5433 | 5432 | A Postgres installed on your Windows machine already uses 5432. Containers are unaffected. |
| 2026-10-18 | `/health/db` returns 503 with a fixed body and logs the real error | 500; returning the error text | 503 means "temporarily unavailable", which is right for monitoring. The error text can leak the DB host and username. |
| 2026-10-18 | Test tools in `requirements-dev.txt`, chosen by a Docker build argument | one requirements file | Production images shouldn't carry test tools. |
| 2026-10-18 | Async tests use anyio's pytest plugin | pytest-asyncio | anyio already comes with FastAPI, so no extra library. |
| 2026-10-18 | Tests use httpx `AsyncClient` in-process | running a real server in tests | Faster, and the test and the app share one database transaction. |
| 2026-10-18 | Migrations written by hand, with short numbered IDs (`0001`, `0002`, ...) | `alembic revision --autogenerate` with random IDs | You can read each migration top to bottom and know exactly what SQL runs. Numbers show the order at a glance. Autogenerate is still available as a starting point. |
| 2026-10-18 | Migrations run by a manual command, not on API startup | auto-migrate when the API starts | On the Ministry server, a schema change should be a deliberate step someone watches, ideally after a backup. |
| 2026-10-18 | Test database dropped and rebuilt every test run | keep it between runs | It always matches the current migrations, even after you edit one. Costs about a second. |
| 2026-10-18 | `alembic_version` table stays in the `public` schema | put it in `core` | Alembic creates that table *before* running migration 0001, so `core` wouldn't exist yet. |
| 2026-10-18 | Users log in with email | a separate username | Applicants need an email for notifications anyway, so one identifier works for staff and applicants alike. |
| 2026-10-18 | A user can hold several roles (`user_roles` link table) | one role column on `users` | A Director may also act as an officer. Adding a role is then a row, not a schema change. |
| 2026-10-18 | Roles hold permissions; positions and delegation come later with the workflow | positions now | Step 2 is "users and roles". Approvals will attach to positions, as CLAUDE.md requires, when we build that. |
| 2026-10-18 | Numeric IDs (`BIGINT` identity) | UUIDs | Simpler to read and debug. IDs in URLs can be guessed, so every endpoint must check permissions anyway, which it would need to with UUIDs too. |
| 2026-10-18 | Users are deactivated, never deleted | allow delete | The audit log must always be able to say who did what. |
| 2026-10-18 | Minimum password length 12, no complexity rules | 8 characters plus symbols | Follows NIST SP 800-63B: length matters more than symbols. |
| 2026-10-18 | Service functions own the transaction (they call `commit()`) | endpoints commit | One place decides what is saved together. Matters most for "status change + audit row" in step 3. |
| 2026-10-18 | Users created by a CLI with a password prompt | seed an admin from `.env`; an admin API endpoint | No password ever sits in a file or shell history. An admin UI can come later. |
| 2026-10-18 | JWT access tokens (PyJWT, HS256), 60-minute lifetime | server-side sessions in a table | Approved by you. No session table to clean up. The weakness is that a token can't be "taken back" before it expires, which the next row works around. |
| 2026-10-18 | The token holds only the user id; user and roles are reloaded from the database on every request | put roles in the token | Deactivating a user or removing a role works immediately, not after up to 60 minutes. The cost is one small query per request. |
| 2026-10-18 | No refresh tokens yet | short access token + long refresh token | Keeps step 2 small. Users log in again after 60 minutes. Revisit with the frontend. |
| 2026-10-18 | Login takes a JSON body | OAuth2 password form (`OAuth2PasswordRequestForm`) | The form version needs another library (`python-multipart`). JSON is all the Next.js frontend needs. |
| 2026-10-18 | `JWT_SECRET` must be at least 32 characters, or the app won't start | accept anything | A short secret can be brute-forced, which would let someone forge logins as anyone. |
| 2026-10-18 | Append-only enforced by a database trigger | only "be careful in Python"; `REVOKE UPDATE, DELETE` permissions | A trigger protects against every client, even the table owner. Since step 4a the app also has no `UPDATE`/`DELETE` rights on it, so there are two walls. |
| 2026-10-18 | One generic audit table (`entity_type` + `entity_id` + JSON `details`) | a separate history table per record type | Every module can log to it, and "show everything user X did" is one query. |
| 2026-10-18 | `record_event()` never commits | commit inside it | So a change and its audit row are always saved in the same transaction. |
| 2026-10-18 | Transitions name a required *role* for now | name a *position* (e.g. "Director of Trade") | CLAUDE.md says approvals attach to positions, with delegation for absences. Positions need their own tables. Until then, roles keep the engine working, and switching the column later is one migration. **Done in step 4c (migration 0009).** |
| 2026-10-18 | The PS gets the Minister's move as a second transition row | delegation | Placeholder for "PS when the Minister is away". With real delegation, the PS row goes and the Minister delegates when absent. **Done in step 4e (migration 0011).** |
| 2026-10-18 | One role may start a workflow (`workflows.start_role_id`) | a link table allowing several roles | Enough for ETLS. Becomes a table if Records also needs to open cases for walk-in applicants (see Open questions). |
| 2026-10-18 | The ETLS definition is seeded in the shared migration chain | a separate `etls` module migration | There's only one Alembic chain so far. When the `etls` schema arrives, its data can move with it. |
| 2026-10-18 | Database constraints guard the workflow's structure; tests guard its logic | everything in Python | Constraints (one initial status, statuses from the same workflow) protect against any client. Rules like "no dead ends" need a whole-graph check, which is easier as a test. |
| 2026-10-18 | The generic table is called `cases` | `files`, `requests`, `applications` | "File" collides with uploaded documents, which come later. "Application" is ETLS-specific. Module tables (e.g. `etls.applications`) will point at `core.cases.id`. |
| 2026-10-18 | The case's history lives only in `core.audit_log` | a separate `case_status_history` table | One source of truth. A second table could disagree with the audit log. |
| 2026-10-18 | Pessimistic locking (`FOR UPDATE`) | optimistic locking (a version number, retry on conflict) | Simpler to read, and contention is tiny (a handful of officers per file). No retry logic needed. |
| 2026-10-18 | 409 for "move not possible from here", 403 for "move exists but not for your role" | 400 for both | The frontend can show "this file has already moved on" (409) differently from "you can't do this" (403). |
| 2026-10-18 | Engine errors are Python exceptions, turned into HTTP codes in one handler | raise `HTTPException` inside the service | The service stays usable from the CLI, background jobs and tests, without knowing about HTTP. |
| 2026-10-18 | Applicants can't read the history | show applicants everything | History holds internal minutes and comments. Applicants see the current status only, until the Ministry decides otherwise. |
| 2026-10-19 | Three database users: the superuser only for setup, `motie_owner` for migrations, `motie_app` for the API | app connects as owner and we `REVOKE` some rights; migrations run as the superuser | The owner can always disable its own table's triggers, so the app must not be the owner. Migrations as the superuser would give migration code unlimited rights over the whole server; `motie_owner` can change our tables and nothing else. |
| 2026-10-19 | Database users created by a shell script in `docker-entrypoint-initdb.d`, safe to run again by hand | create them in a migration | Creating logins needs the superuser, and migrations deliberately don't have it. The passwords also stay in `.env`, out of committed files. |
| 2026-10-19 | Fixed user names (`motie_owner`, `motie_app`), passwords from `.env` | names set in `.env` too | Migration 0007 needs the name to `GRANT` to. One server runs one copy of the platform, so there's nothing to configure. |
| 2026-10-19 | Grants written out table by table in each migration | `ALTER DEFAULT PRIVILEGES` (new tables granted automatically) | Automatic grants fail *open*: a new append-only table would quietly get `DELETE`. Explicit grants fail *closed*: forget one and the API gets "permission denied", which a test catches straight away. |
| 2026-10-19 | The app gets no `DELETE` on users and cases, and only `SELECT` on roles and workflow definitions | read and write everything | These were already our rules ("users are deactivated, never deleted"; "workflows are loaded by migrations"). Now the database enforces them too. |
| 2026-10-19 | Migrations and tests run in a one-off `tools` container; the `api` container only has `motie_app`'s password | give the API container the owner's URL too, so `docker compose exec api alembic` keeps working | A dev Compose file tends to get copied to production. Keeping the owner's password out of the server that runs all day costs a few seconds per command. |
| 2026-10-19 | Tests run the code as `motie_app` | run tests as the owner | A missing grant then fails a test, not the Ministry server. The few tests that write workflow rows use `owner_session`. |
| 2026-10-19 | A database from before step 4a is handed over to `motie_owner` by the same script | wipe the volume and start again | No data is lost, and a Ministry server set up the old way would need the same handover. |
| 2026-10-19 | Roles stay, next to positions | turn roles into positions | Roles answer "what kind of user?" (applicant, staff, admin); positions answer "which post?". An applicant holds no post. |
| 2026-10-19 | A post can have several holders; a user can hold several posts | exactly one holder per post | There are several Trade Officers, and an officer may act as Director while keeping their own post. Whether top posts must have a single holder is an open question. |
| 2026-10-19 | When someone leaves a post, their holder row is deleted; the history is in the audit log | keep rows with start and end dates | One source of history, the same choice as for cases (step 3c). |
| 2026-10-19 | The org chart is loaded by migrations; the app may only read it (and change who holds posts) | an admin screen to edit the chart | Same rule as workflows. Changes to the chart are rare, and they then go through review like code. |
| 2026-10-19 | Positions live in the identity module, next to `User` | a separate `org` module | `User.positions` needs the `Position` class; two modules importing each other would be a circular import. Split it out if it grows. |
| 2026-10-19 | `Position` has no `department` or `reports_to` relationship objects, only the id columns | `lazy="selectin"` relationships | Positions are loaded with every user, on every request. Eager relationships would add a query per level of the chain each time. |
| 2026-10-19 | Reports-to loops are caught by a test, not a database trigger | a trigger running a recursive query on every change | Only migrations write the chart, and the tests check every migration. Add the trigger if an admin screen ever edits the chart. |
| 2026-10-19 | Posts are assigned with the CLI for now; the audit row has no actor | an admin API endpoint | Only someone with server access can assign posts, which suits a power this strong. An admin screen can come later. |
| 2026-10-19 | Old transitions converted by a fixed role-to-post mapping in migration 0009 | re-seed the ETLS workflow from scratch | Keeps the transition ids (and so the audit trail's meaning) unchanged. A role missing from the mapping makes the migration fail rather than drop a move. |
| 2026-10-19 | Who may *start* a workflow is still a role (`workflows.start_role_id`) | a position | Applicants hold no post. "Who may open a case" is about the kind of user, not a post. |
| 2026-10-19 | Seeing cases and history still depends on roles (`is_staff()`) | positions | Visibility rules aren't decided yet (see Open questions). Moves were the part CLAUDE.md said must follow posts. |
| 2026-10-19 | The audit key `as_role` became `as_position` | keep writing `as_role` | It says what was actually checked. Old rows keep `as_role`; the log is append-only, so code reading history must accept both. |
| 2026-10-19 | Delegation goes from post to post | from person to person | It matches "approvals attach to positions". If the PS changes while the Minister is away, the new PS can act at once. |
| 2026-10-19 | The delegating post keeps its own powers | suspend the delegator while delegated | If the Minister comes back early, they can act without first revoking. Both sides' actions are logged either way. |
| 2026-10-19 | Delegations aren't passed on (Minister → PS → Director doesn't let the Director act for the Minister) | follow chains | "Who could act for the Minister on 5 March?" stays one simple query, and nobody hands on powers they only borrowed. |
| 2026-10-19 | The engine finds the delegation by itself; own posts are tried first | the caller says "I'm acting for X" | Fewer ways to get it wrong. The button shows `on_behalf_of` before the click, and the audit row records it after. Using your own post first means the log shows the strongest basis for the action. |
| 2026-10-19 | Dates are whole days, both included, in UTC | start and end timestamps | People say "away from 3 to 10 March". The Gambia keeps GMT all year with no daylight saving, so the UTC date is the local date. |
| 2026-10-19 | No back-dating; at most 90 days `[CONFIRM]` | allow both | A back-dated delegation could make an earlier action look authorised. A delegation with no limit would hand a post's powers over for good. |
| 2026-10-19 | Revoke, never delete or edit; enforced by a column-level grant | let the app update or delete delegations | Audit rows point at `delegation_id`, so the delegation must stay as it was when it was used. |
| 2026-10-19 | If several delegations cover the same post, the oldest is recorded | the newest; refuse overlaps | Any of them gives the same right. Refusing overlaps would block a sensible fix ("I set the wrong end date, here's a second one"). |
| 2026-10-19 | Errors moved to `errors.py`; `service.py` still re-exports them | keep them in `service.py` | `delegation.py` needs them and `service.py` needs `delegation.py`. Importing each other would be a circular import. |
| 2026-10-19 | `available_actions` always includes `on_behalf_of` (`null` for your own moves) | leave it out when empty | A fixed shape is easier for the frontend. One existing test assertion gained `"on_behalf_of": None`. |
| 2026-10-19 | The PS placeholder row is deleted by a new migration (0011) | edit migration 0005 so the row was never seeded | Databases that already ran 0005 (yours, and any server) would never lose the row. Migrations that have run are never edited. |
| 2026-10-19 | The Minister records each absence as a delegation | a standing Minister → PS delegation with no end date | A standing delegation would recreate the placeholder under another name. A dated one shows *when* the PS was entitled to act. |
| 2026-10-19 | "With the Directorate" renamed to `with_director` in place | delete it and add a new status | Cases point at the status id. Renaming keeps every existing case valid; deleting would fail, or strand them. |
| 2026-10-19 | The Trade posts stay in the org chart; ETLS moves to the Industry and Investment posts | delete the Trade posts | The Directorate of Trade exists and will have its own work. Deleting posts loses the audit trail's meaning for anyone who held them. |
| 2026-10-19 | The officer's moves (approve, reject, return) are kept as they were | remove them, or make the Director's signature final | Without them, a case could never finish (the well-formedness test would fail). What the officer really does after signing is still an open question. |
| 2026-10-19 | The DPS gets the `director` role in tests | add a `deputy_permanent_secretary` role | Roles only say "staff or applicant" now; the post is what counts. A new role waits for the role list question. |
| 2026-10-19 | A test pins the whole ETLS route, row by row | only count the rows | The route is confirmed now. Any later change to it should be deliberate and show up as a failing test. |
| 2026-10-19 | Succession is its own table, not a kind of delegation | standing delegations with no end date | A delegation is a person's choice for their own absence; succession is the Ministry's rule. Keeping them apart lets the audit log say which one was used, and lets the engine give delegations priority. |
| 2026-10-19 | One line of succession per post, with ranks; no following of chains | look up each successor's own successor | The confirmed rule lists the whole chain (Minister → PS → DPS), so one list says it all and is easy to read. |
| 2026-10-19 | A workflow-specific line replaces the post's general line for that workflow | add the two together | "For ETLS the Director is covered by DPS Admin & Finance" is a complete answer. Adding lists together would make the order hard to predict. |
| 2026-10-19 | The PS's line (PS → DPS) is seeded too | seed only the Minister's line | It follows from the confirmed general chain. Without it, files would stop at "With the PS" whenever the PS is away. |
| 2026-10-19 | Succession rules are loaded by migrations; the app only reads them | an admin screen | Same rule as workflows and the org chart: rare changes, reviewed like code. |
| 2026-10-19 | An absence belongs to a person, not to a post | record "the Minister's post is unattended" | People go on leave, not posts. A person with two posts is away from both, and the one record shows it. |
| 2026-10-19 | "Authorised officer" is anyone with an `absence_recorder` role | the Minister's office staff only; any staff member; admins | Marking someone absent can hand their step to someone else, so it must be a deliberate, named right. A role is easy to give the right people once the Ministry says who. |
| 2026-10-19 | The audit actor is the person who recorded the absence, with `recorded_by` and `absent_user_id` in the details | the absent person as actor | The log must show who actually did it. If the PS could mark the Minister absent unnoticed, they could take the Minister's step. |
| 2026-10-19 | No back-dating, no maximum length | a maximum like delegations' 90 days | Back-dating could make an earlier action look covered. Absences such as sick or maternity leave can be long, and they are only facts, not a handing-over of power. |
| 2026-10-19 | Only people who hold a post can be marked absent | anyone | Absence only matters for who may act for a post. Refusing others catches mistakes such as picking the wrong user. |
| 2026-10-19 | Order of precedence: own post, then delegation, then succession | succession before delegation | The Ministry said delegations take priority. Your own post comes first so the log shows the strongest basis. |
| 2026-10-19 | A delegation from the needed post blocks succession entirely, even for its first in line | let both the delegate and the successor act | The holder chose who covers for them; the standing order is the fallback for when they didn't. Two people both able to act would blur responsibility. |
| 2026-10-19 | A post counts as absent only when it has holders and *all* of them are recorded absent | absent if *any* holder is away; vacant counts as absent | One Trade Officer on leave shouldn't hand the others' work to someone else. Treating a vacancy as absence is an open question. |
| 2026-10-19 | Only the first present post in the succession order may act | any present post in the line | That's what "the next present position" means, and it keeps one person responsible at a time. |
| 2026-10-19 | The audit row keeps the key `on_behalf_of` for "acting for", and adds `basis` and `absence_ids` | a new `acting_for` key | Rows from step 4d already use `on_behalf_of`. One key for one meaning, however the right arose, keeps history queries simple. |
| 2026-10-19 | `absence_ids` lists the skipped successors' absences too | only the needed post's absence | "Why did the DPS sign for the Minister?" needs both answers: the Minister was away, and so was the PS. |
| 2026-10-19 | `available_actions` shows `on_behalf_of` for succession moves; no `basis` field there | add `basis` to the API | The button only needs "for whom". The response shape stays the same, so no existing test or client changes. |
| 2026-10-19 | The facility letter is a module (backend/app/modules/etls/, schema `etls`) | put its tables in `core` | CLAUDE.md: one schema per module, and modules never touch each other's tables. ETLS fields don't belong in the shared core. |
| 2026-10-19 | Module migrations stay in the one Alembic chain | a separate chain per module | One chain keeps the order of core and module changes obvious (0015 needs core tables from 0014). Split it when a second module arrives, if needed. |
| 2026-10-19 | The case and its form are saved in one transaction (`open_case()` doesn't commit) | open the case, then save the form in a second request | A case without its form would be a half-filed application nobody can process. |
| 2026-10-19 | The generic `POST /cases` refuses workflows with `opened_by_module` set | trust callers to use the right endpoint | Workflows are data: the rule is a column, not code that knows about ETLS. |
| 2026-10-19 | "One or more" numbers are child tables, not arrays or JSON | `TEXT[]` or JSONB columns | Each certificate number needs its own row for the duplicate check (step 6b) and an index to find earlier uses. |
| 2026-10-19 | No review step between the desk and the PS yet | a placeholder reviewer | We don't know who reviews; a guessed gate would block files. Adding one later is a status and two transitions in a migration. |
| 2026-10-19 | The desk sends to GRA, closes and rejects (placeholders) | Records; the PS | The desk follows the file from verification on. All three are `[CONFIRM]`. GRA is sent to by hand until the GRA adapter exists. **Replaced in step 8e (SCREENS.md): Records sends, there's no Close; the desk still rejects.** |
| 2026-10-19 | Form fields are plain checked text (country, unit, product) | fixed lists (ECOWAS countries, units, product codes) | We don't have the lists yet. Lists would make the cement rule (step 6c) much more reliable. |
| 2026-10-19 | A reused certificate number holds the case for the desk instead of refusing the submission | refuse it with an error; a `UNIQUE` constraint | You asked for "block and flag". It also lets the desk judge real cases (a split shipment) and keeps a record of the attempt, which a refused form wouldn't. |
| 2026-10-19 | Flags are a core feature; the ETLS module only decides *when* to raise one | an ETLS-only "duplicate" column | Other modules will need "hold this for someone to look at" (missing payment, failed GRA check). Holding a case is the engine's job. |
| 2026-10-19 | A blocking flag stops *every* move, even rejecting | let some moves through | Simple and safe. The desk records its reason when resolving ("confirmed duplicate, rejecting") and then rejects, so the log explains both. **Replaced in step 8d: a flag holds only its own post's moves, and Reject may go ahead while held.** |
| 2026-10-19 | The on-hold check runs after the permission check | before it | Someone who may not act at all gets 403, not a glimpse of why the case is held. |
| 2026-10-19 | Only a holder of the flag's post may resolve it; no delegation or succession yet | let acting officers resolve too | Keeps the first version strict. Easy to extend with the same `_permitted()` rules if the Ministry wants it. |
| 2026-10-19 | Numbers compared normalised (upper case, spaces removed) | exact text | "SN-CO 42" and "sn-co42" are the same paper certificate; exact matching would miss the easiest way round the check. |
| 2026-10-19 | Advisory lock per number for the duplicate check | a separate registry table with a unique key; `SERIALIZABLE` transactions | No second copy of the numbers to keep in step, and no retry logic. The lock lasts only while one submission is saved. |
| 2026-10-19 | The downgrade test uses its own empty database | clean up every race test's committed rows | Downgrades that refuse to delete statuses still in use are correct behaviour. The test should prove the migrations reverse, not depend on what other tests left behind. |
| 2026-10-19 | Uploads are the raw request body, one file per request | `python-multipart` form uploads | Chosen by you. No new library; a Next.js `fetch()` sends a file body directly. |
| 2026-10-19 | Documents are a core service; requirements, conditions and facts are generic | ETLS-only document tables | Every Ministry process has required documents. The module only supplies facts. |
| 2026-10-19 | Conditions are a tiny JSON language (`equals`, `contains`) checked by a database constraint | Python expressions in the database; one hard-coded `if` for cement | Data-driven, as you asked, without letting data run code. Add operators only when a real rule needs them. |
| 2026-10-19 | The cement rule matches "cement" anywhere in the product text | an exact product name | The product is free text for now. It's a placeholder: it would also match "cement mixer". A product list would make it exact. **Replaced in step 6g by the HS heading.** |
| 2026-10-19 | Files on a local Docker volume (`/data/documents`), random names, SHA-256 kept | store files in Postgres; object storage (S3-like) | Simple on one Ministry server, and it keeps the database small. `storage.py` is the only code touching the disk, so moving to object storage later changes one file. |
| 2026-10-19 | Accept only PDF, PNG and JPEG, detected from the first bytes; 10 MB limit | accept anything; trust `Content-Type` | Scans of official papers come as these. Anything else (Office files, scripts) is a risk we don't need yet. |
| 2026-10-19 | Re-uploading adds a newer version; nothing is deleted | replace the old file | Same rule as the audit log: what someone submitted stays on record. |
| 2026-10-19 | The applicant and staff may upload, until the case is closed | applicant only; only while "Submitted" | Records may need to add a scan of an original. Tighten when the Ministry says. |
| 2026-10-19 | Checks are named per transition in a table; their code is registered by name | hard-code "documents complete" in `change_status()`; a check per workflow | The engine stays generic, and a new rule like "fee paid before signing" is a function plus a row. |
| 2026-10-19 | An unknown check name blocks the move | skip it with a warning | Skipping would quietly remove a safeguard. |
| 2026-10-19 | All of a move's problems are reported at once | stop at the first | Records can tell the applicant everything that's missing in one go. |
| 2026-10-19 | Checks run after the permission and on-hold checks | before | Someone who may not make the move gets 403 without learning the case's details. |
| 2026-10-19 | "Original seen" may be marked by whoever may make the move that needs it | name the Records post in code; any staff member | No post in code, and delegation and succession apply automatically. |
| 2026-10-19 | "Seen" belongs to one upload; a newer scan must be seen again | mark the document *type* as seen | The audit row records which scan (by checksum) was compared with the original. A later scan could differ. |
| 2026-10-19 | Moves that aren't ready still appear in `available_actions` | hide them | The officer sees the button and gets a clear list of what's missing. Hiding it would leave them guessing. `GET /cases/{id}/documents` shows the checklist beforehand. |
| 2026-10-19 | fpdf2 with a plain-text template | WeasyPrint + HTML; ReportLab | Chosen by you. Pure Python, no system libraries, small. |
| 2026-10-19 | The letter is made fresh from the case's data on each download | store the PDF as a document when it's signed | The data it's made from can't change (the form is insert-only, the signature is an audit row). The catch: a later template change would also change old letters. **Replaced in step 6f: you asked for it to be stored at signing.** |
| 2026-10-19 | The signature block comes from the audit row of the "Sign" move | a separate "signed_by" column | One source of truth for who acted and for whom (step 5d). The letter can never disagree with the history. |
| 2026-10-19 | The letter date is the day it was signed, not the day it's downloaded | today | A reprint next month must say the same thing. |
| 2026-10-19 | The reference format allows only `{year}` and `{case_id}`, checked at startup | any `str.format()` string | `str.format()` can read object attributes (`{case_id.__class__}`). A bad setting should stop the server at startup, not break the first letter. |
| 2026-10-19 | Built-in PDF fonts (Latin-1); other characters print as "?" | ship a Unicode font file | Covers English and French names. A font file (e.g. DejaVu Sans) can be added later without other changes. |
| 2026-10-19 | Only staff can download the letter | the applicant too (they're copied) | The importer gets the copy the Ministry sends. Opening it to applicants is one line, once confirmed. |
| 2026-10-20 | The letter is issued by a *transition effect* (a named row plus registered code) | call the letter code from the ETLS router after the move; a database trigger | The engine stays generic, and which move issues what is data. Calling it from an ETLS endpoint would let the generic `POST /cases/{id}/status` sign without a letter. |
| 2026-10-20 | Effects run inside the move's transaction, before the commit | after the commit; in a background job | If the letter can't be made, the case shouldn't say "Signed". A background job would leave a window where it's signed with no letter. Rendering one page takes milliseconds. |
| 2026-10-20 | Issued documents are a core table (`core.issued_documents`) with a `kind` | an `etls.issued_letters` table; reuse `core.case_documents` | Other modules will issue certificates too. Uploads are what applicants *gave*; issued documents are what the Ministry *produced*. Mixing them would apply the upload rules (applicants may download uploads) to signed letters. |
| 2026-10-20 | Template version = a `## version:` label in the file, plus the file's own SHA-256 | only a label; only the hash; a version table | The label is readable; the hash catches an edit where someone forgot to change the label. |
| 2026-10-20 | Re-hash the stored file on every download | trust the disk | The letter is small, so it costs nothing, and a damaged or edited file is caught before it reaches GRA. |
| 2026-10-20 | The Ministry's wording is kept word for word, spelling included | correct "benefitting"/"Liberalization" | It's the Ministry's official text. Spelling is theirs to change. |
| 2026-10-20 | `[IMPORTER NAME]` in capitals only in the subject line; normal case in the body | capitals wherever the placeholder was in capitals | The subject line is all capitals; in the body, a name in capitals mid-sentence would look odd. Easy to change in the template. |
| 2026-10-20 | Quantity and unit are separate fields | keep "1200.5 tonnes" as one field | The Ministry's wording names them separately. |
| 2026-10-20 | The signature line is the signing post's title, "For: ..." when acting; no name printed | print the signer's name and title too | Follows the Ministry's wording, which shows only "Permanent Secretary". Who actually signed is in the audit log and `issued_by`. `[CONFIRM]` |
| 2026-10-20 | A ` >> ` mark for the reference and date line | a tab character; two template files | A tab is invisible and editors often turn it into spaces. ` >> ` is visible and explained in the template's notes. |
| 2026-10-20 | Template version `2`, with a date and a short label | a date only; a number only | Numbers sort and compare easily; the label says what changed. |
| 2026-10-20 | The banner works out "acting for" with the engine's own functions, per workflow | a separate query of absences and succession rows | One set of rules. A line can differ per workflow (the Director's), and a delegation blocks succession; only the engine knows both. |
| 2026-10-20 | Absence reasons are hidden from other staff | show them to all staff | Reasons like sick leave are personal. Who and when is all a colleague needs. `[CONFIRM]` |
| 2026-10-20 | New routes `/acting` and `/acting/for-me` in the workflow package | `/auth/me/acting` | The identity module mustn't depend on the workflow module (workflow already imports identity). |
| 2026-10-20 | History and timeline are computed from the audit log on each request | store a separate timeline table | One source of truth (as in step 3c). A case has tens of rows, so it's cheap. |
| 2026-10-20 | The timeline finds each move by its from-status, to-status and name, as recorded in the audit row | store the transition id in the audit row | Old rows don't have an id; the three together identify the move. New rows could also record the id, if moves are ever renamed. |
| 2026-10-20 | Repeated labels on the timeline are shown once | show every move | To the applicant, three internal minutes are one step. |
| 2026-10-20 | Staff may read the applicant's timeline too | applicants only | Records can see exactly what the applicant sees when they phone. |
| 2026-10-20 | `blocked_by` is a dry run of the real checks, via one function shared in spirit with `change_status()` | separate "is it ready?" rules for the screens | The reason shown is exactly the reason the move would be refused. |
| 2026-10-20 | Not worked out in queues (`null`) | run it for every row | A queue row only needs to say there's work; the case page explains. Keeps the queue fast. |
| 2026-10-20 | The queue is filtered by the engine's own permission check, after a SQL pre-filter | the same rules again in SQL; ask the engine about every open case | One definition of "who may act" (no drift), and the SQL step keeps it fast. |
| 2026-10-20 | A separate `status_changed_at` column | use `updated_at` | Editing a draft (chunk 2) updates the case without moving it; "days waiting" mustn't reset. |
| 2026-10-20 | `GET /cases` is "cases I applied for", for anyone; staff use `/cases/queue` | one endpoint that behaves differently for staff | Two clear questions, two endpoints. Walk-ins (chunk 2) will decide whether "applied for" means the applicant or whoever typed it in. |
| 2026-10-20 | Days waiting counts whole calendar days | working days | Simple and honest for now. Working days need the Ministry's holiday calendar `[CONFIRM]` if deadlines use them. |
| 2026-10-20 | Case references come from a counter row per workflow per year | a Postgres `SEQUENCE`; the case id | A sequence leaves gaps on rollback and doesn't restart yearly; the case id runs across all services. The spec wants a sequence per service per year. |
| 2026-10-20 | The prefix is a column on `workflows` | a format setting per module | Workflows are data; a new service gets its numbering with its migration. |
| 2026-10-20 | The year is today's date (UTC = Gambian time), via the same `today()` as delegations | `submitted_at`'s year | One clock the tests can move. They can't differ except across midnight on 31st December. |
| 2026-10-20 | The app may in principle update `cases.reference` (its `UPDATE` grant on `core.cases` is table-wide) | narrow the grant to named columns now | No code changes it, and narrowing the grant touches every column the engine writes. Worth doing in a hardening step. |
| 2026-10-20 | Applicant labels live on statuses (required), with optional timeline wording and a "hidden" flag on moves | a label per move only; a mapping in the frontend | Labels are data, like the rest of the workflow, and the database refuses a status without one. "Originals checked" vs "Being verified" needs both: one for what happened, one for where the case is. |
| 2026-10-20 | Applicants get `null` for the internal code and name, rather than those fields being removed | separate response models for applicants and staff | One shape for the frontend; the rule is in one function, `status_view()`. |
| 2026-10-20 | The cancel move is hidden, but earlier "Letter signed" timeline entries stay | rewrite the applicant's timeline to drop everything about the cancelled letter | The applicant may already have seen "Letter signed"; hiding history they saw would be confusing and dishonest. Confirmed 2026-10-24. |
| 2026-10-20 | Cancelling a letter is a workflow move with an effect | a separate `POST .../cancel` endpoint | Who may cancel then follows the post rules for free, delegation and succession included, and it's a status change in the audit log like every other. Which statuses it's allowed from is data. |
| 2026-10-20 | Cancel goes back to "Originals received" (the desk), not to "Verified" (the PS) | straight back to the PS to re-sign | Most corrections need the desk: the HS code can only be changed before Verify. Going back to the PS would only allow re-signing the same data. `[CONFIRM]` |
| 2026-10-20 | Allowed from "Signed" and "Sent to GRA", not from "Closed" | from "Signed" only; from any status | A mistake is often found after the letter reached GRA. A closed file stays closed. `[CONFIRM]` **Since step 8e there's no "Closed"; cancelling is a correction move out of the final "Sent to GRA".** |
| 2026-10-20 | `requires_comment` is a column on transitions, checked by the engine | check the comment inside the cancel effect | It's a property of the move, useful elsewhere (e.g. rejecting), and the frontend can see it in `available_actions` before the click. |
| 2026-10-20 | A cancelled letter's PDF isn't stamped; the response header and listing say "cancelled" | re-render it with a "CANCELLED" watermark | The stored bytes must keep matching the checksum in the audit log. A watermarked copy could be added later as a separate, derived file. |
| 2026-10-20 | Each PDF carries its issue number in its metadata | accept identical files; print "Issue 2" on the letter | Two issues with the same checksum couldn't be told apart. Printing it would change the Ministry's wording. |
| 2026-10-20 | A corrected letter keeps the file reference, with a new date and file name `-2` | a new reference (e.g. `/R1`) | We don't know the Ministry's practice; changing the reference format is one line. `[CONFIRM]` |
| 2026-10-20 | A trigger guards `core.issued_documents` against deletes and edits, even by the owner | rely on the app's grants only | Same reasoning as the audit log (step 3a): an issued letter is evidence. |
| 2026-10-20 | A condition can answer "not known yet" (`None`) when a supplied fact has no value | keep failing closed (receipt required); treat unknown as "not needed" | Failing closed would ask every applicant without a code for a cement receipt; "not needed" would let the receipt vanish. A fact the module doesn't supply at all still fails closed, so a typo in a rule is still caught. |
| 2026-10-20 | Records gets a lenient check (`known_documents_complete`); `documents_complete` became strict | one check that's lenient everywhere; make the applicant answer before submitting | The desk decides the code after Records, so Records can't wait for it. The strict check plus `hs_code_confirmed` on Verify guarantees it's settled before signing. The default (`documents_complete`) is the safe one. |
| 2026-10-20 | The date change in step 6j didn't bump the template version | bump it anyway | You asked to bump it only when the template file changes. `template_version` describes the wording; the commit describes the code. |
| 2026-10-20 | The reset script is bash, run from the host with `docker compose` | a Python script; a Makefile | It drives Docker from outside the containers, which is what shell is for, and Git Bash is already how you run the other commands. No new tool. |
| 2026-10-20 | Reset drops the database rather than downgrading every migration | `alembic downgrade base` | Faster, and it also clears anything a migration doesn't know about. The test suite already proves the downgrades work. |
| 2026-10-20 | The seed is Python using the normal `create_user()`/`assign_position()` | SQL inserts | Passwords get hashed the same way as real ones, and the seed breaks loudly if those rules change. |
| 2026-10-20 | `APP_ENV` defaults to `production`; `.env.example` says `production` | default `development` | Fail safe: forgetting the setting on a server must not enable a delete-everything script. |
| 2026-10-20 | Seed users share one known password, overridable with `DEV_SEED_PASSWORD` | random passwords printed once | You need to log in as several people quickly. The `APP_ENV` guard keeps these accounts off real servers. |
| 2026-10-20 | The applicant declares the HS code; an officer confirms or corrects it; both are kept | only the officer enters it; the officer overwrites the applicant's | Records' documents check comes before the desk, so it needs a code to work with. Keeping both shows when, and by whom, a declared code was corrected. |
| 2026-10-20 | The receipt fact is the *heading* (4 digits) tested with `equals` | a new `starts_with` operator on the full code | No change to the condition language or its database constraint. Headings are how tariff rules are usually written. |
| 2026-10-20 | Facts use the confirmed code once there is one, the declared code before | only the confirmed code | Records can then ask for the receipt early. The desk's Verify move re-checks documents with the confirmed code, so a correction can't slip through. |
| 2026-10-20 | Confirmation happens during the desk's verification, by whoever may make that move | a named post; any staff member; at any status | No post in code (same pattern as "original seen"), and the code can't change after the file is verified and the letter is on its way to the PS. |
| 2026-10-20 | The HS code is stored as digits only, 6, 8 or 10 of them | keep it as typed | "2523.29" and "252329" must compare equal. Printed back with dots on the letter. |
| 2026-10-20 | `hs_code` is nullable in the database but required on new forms | `NOT NULL` with a made-up value for old rows | Old dev cases have no code, and inventing one would be false data. Their receipt rule fails closed. **Changed in step 6k: optional on the form; a missing code makes the rule "not known yet".** |
| 2026-10-20 | Cases signed before step 6f get 404, not a freshly made letter | render one now for old cases | A letter made today isn't the one that was signed. Only your dev database has such cases. |
| 2026-10-24 | The applicant's own moves are transitions with `by_applicant` and no post | an "applicant" position every applicant holds; a separate `POST /submit` endpoint outside the workflow | Submit stays data, with checks, effects and an audit row like every other move. A pretend post would let delegation or succession hand an applicant's case to someone else. |
| 2026-10-24 | A draft needs a complete, valid form; editing replaces the whole form | allow half-filled drafts (every column nullable, a "form complete" check on Submit) | Documents attach to an existing case, so the case must exist early; requiring the fields keeps every database constraint (`NOT NULL`, quantity > 0) as it is. The screen keeps unsaved typing itself and shows the 422's field errors. Easy to loosen later. |
| 2026-10-24 | Whether the form can be changed is a status column (`applicant_editable`) | check for the status code `draft` in the module | "Returned" (8b) is editable too; a column covers both without code knowing status names. |
| 2026-10-24 | The reference comes from an effect on Submit (`assign_reference`) | the engine numbers any case that leaves its initial status | Which move counts as submitting is then data. `open_case()` still numbers cases at once for a workflow with no editable first status (the old `etls_application`). |
| 2026-10-24 | The duplicate check runs at Submit, and a draft's numbers don't count | at opening, as before; count drafts too | A draft isn't an application yet: someone's abandoned draft mustn't put a real submission on hold. Checking at Submit also catches a number typed in while editing. |
| 2026-10-24 | Child rows (approvals, certificates) are deleted and re-added on each save | edit them in place | They have no identity of their own beyond the number. The audit row's before/after keeps the history. The app got `DELETE` on these two tables only. |
| 2026-10-24 | Submit goes through the generic `POST /cases/{id}/status` | an ETLS `POST .../submit` endpoint | Every move uses one endpoint, so `available_actions` and `blocked_by` work for Submit with no new code. |
| 2026-10-24 | Staff can still see drafts (`can_view()` unchanged) | hide drafts from staff | It's the existing placeholder rule ("any staff member sees every case"). Drafts are in no queue, so nobody stumbles on them. `[CONFIRM]` with the visibility question. |
| 2026-10-24 | The applicant's timeline starts with "Draft" | start at "Submitted" | It's true, and shows when they began. Easy to hide with `applicant_visible`-style data if the Ministry prefers. |
| 2026-10-24 | The applicant's message is a second field on the move (`applicant_message`), next to the internal `comment` | one text with a "show the applicant" tick; a separate messages table | Two fields make it impossible to show the minute by mistake: applicant views only ever read `applicant_message`. Both live in the move's audit row, so nothing is stored twice. |
| 2026-10-24 | A message on a move that doesn't send one is refused (422) | ignore it | An officer who typed something for the applicant must find out it wouldn't have been sent. |
| 2026-10-24 | A returned case goes back to `submitted` (Records), even when the desk returned it | back to wherever it was returned from | "Every application goes to Records first" (SCREENS.md). A fixed application may have new papers whose originals Records must see. One move instead of one per returning post. |
| 2026-10-24 | The notice shows the message of the move into the *current* status | the newest message ever sent | Once resubmitted, an old "please fix" message would be misleading on the list. The timeline keeps every message. |
| 2026-10-24 | Editing the product or HS code clears the desk's confirmed code | keep it | It was confirmed for different goods. The desk's Verify needs a confirmed code, so it must be looked at again; the cleared value stays in the audit row. |
| 2026-10-24 | Reject needs a message to the applicant; the minute stays optional | require the minute too | The spec says the applicant sees the reason. A minute can be added when the desk wants one. |
| 2026-10-24 | Timeline entries with a message are always shown, even if the label repeats | dedupe by label as before | Two returns in a row each carry a different message the applicant must see. |
| 2026-10-24 | The form field became a list of `{number, issued_on}` (`certificates_of_origin`) | keep `certificate_of_origin_numbers` and add a parallel list of dates | A date belongs to one certificate; two lists can fall out of step. There's no frontend yet, so changing the API costs nothing now. |
| 2026-10-24 | Six months = the same day six calendar months later, the month's last day if there's no such day; valid through that day | 182 days; valid until the day before | It's how people read "six months" on a certificate. Counting days would drift by a day or two. `[CONFIRM]` the exact convention with the desk if a boundary case matters. |
| 2026-10-24 | Verify is measured against today (the day the desk verifies) | the submission date | The Ministry's answer: blocked if more than six months past issue *at Verify*. |
| 2026-10-24 | The submission warning also covers certificates that have already expired | warn only for "within 30 days, not yet expired" | An expired certificate is the strongest reason to warn; the applicant may still submit and replace it after a return. |
| 2026-10-24 | Warnings are a property of the link between move and check (`warn_only`) | a separate warnings table; a flag on the check's code | The same check could warn at one step and block at another. Everything else about checks (registry, dry run) is reused. |
| 2026-10-24 | Warnings go in the move's audit row only when there are some | always write `"warnings": []` | Old rows and moves without warnings stay as they were. |
| 2026-10-24 | Old applications with no issue date can't be verified ("isn't recorded") | treat them as valid | Failing closed, as with other checks. Only dev data is affected. |
| 2026-10-24 | `long_date()` moved to `app/core/dates.py` | import it from the letter module | Check messages in `service.py` need it, and `letter.py` imports `service.py`: importing back would be circular. The frontend formatter should follow the same rules. |
| 2026-10-24 | Ticks are a core feature (`checklist_items`, `case_ticks`) with a `checklist_complete` check | ETLS-only boolean columns on the form | The CO desk (S9) and the officer's review (S6) need the same thing. Items are data, like workflows. |
| 2026-10-24 | Unticking deletes the tick row; the audit log keeps both events | keep every tick with an "unticked at" column | The current state is one row per item, simple to check; the history is already in the audit log. The app got `DELETE` on `case_ticks` only. |
| 2026-10-24 | A return clears a case's ticks (effect `clear_checklist`) | keep them | They were statements about the application before the applicant changed it. Clearing on the return move (data) rather than on every form edit keeps the rule in one visible place. |
| 2026-10-24 | Who may tick follows the move that needs the checklist (`may_make_move_with_check()`) | name the desk post | Same pattern as "original seen" and the HS code: no post in code, acting rules for free. |
| 2026-10-24 | A blocking flag holds only the moves of the post it's for | hold every move, as before | The duplicate flag was raised at Submit and then stopped Records too, so a flagged case could never reach the desk that must judge it, nor be rejected there. Records receiving papers doesn't depend on the duplicate question. A future flag that must stop everything can be given to the first post in line. |
| 2026-10-24 | A move allowed on hold resolves its post's open flags, with the minute (or else the applicant message) as the reason | leave the flags open; require a separate resolve first | The spec: "the rejection reason also resolves the flag". Leaving a flag open on a rejected case would show it as still needing attention. |
| 2026-10-24 | Only Reject is allowed on hold; Return is not | allow Return too | The spec names Reject only. The desk can resolve the flag with a finding and then return, which records both. `[CONFIRM]` with C7. |
| 2026-10-24 | The duplicates endpoint lists every *other* submitted case with the number, earlier or later | earlier cases only; the ids saved in the flag | The desk wants to know where the number was used now; a later case using the same number matters too. Read live, so the status is current. |
| 2026-10-24 | Tick labels are my wording `[CONFIRM]` | wait for the desk | Placeholders that read sensibly; changing them is an `UPDATE` in a migration. |
| 2026-10-25 | The dispatch date has its own table, one row per issued letter | a date column on the case or the form; the date in the move's audit row only | A corrected letter is sent again on another day; each issued letter needs its own date, and the row ties the date to the exact file (checksum) that went. |
| 2026-10-25 | One ETLS endpoint records the date and makes the move | two calls (save the date, then move); generic "data" on every move | One click, as the screen has it, and one transaction. The engine stays unaware of dates. The check stops the generic endpoint skipping the date. |
| 2026-10-25 | `mark_sent_to_gra()` asks permission and readiness first, and rolls back only on the unexpected | add the row, try the move, roll back on any refusal | A rollback expires everything loaded in the session. Asking first means the normal "not allowed" path changes nothing. |
| 2026-10-25 | Checks can be left out of the dry run (`in_dry_run`) | always run them; hide the dispatch move's `blocked_by` in code | It's a property of the check-on-move link, like `warn_only`; no special case in the engine. |
| 2026-10-25 | "Correction" is a property of a move (`is_correction`): may leave a final status, never in a queue | keep `sent_to_gra` non-final; a separate "reopen" mechanism | Final means "nobody needs to act". A correction is the exception that proves it, and it shouldn't fill queues with every signed letter. |
| 2026-10-25 | The corrected wording is a status column (`applicant_label_corrected`), used after any hidden move away from that status | hard-code "Corrected letter issued" for sent_to_gra in the timeline | Workflows are data; the CO workflow will have the same "reissued" case. |
| 2026-10-25 | Migration 0030 refuses when a case is in `closed` | move those cases to `sent_to_gra` | Rewriting a case's status without an audit row would break the history. Only dev data can be there; `scripts/reset-dev.sh` clears it. (As planned in GAPS.md C9.) |
| 2026-10-25 | The registry reference default is the example from the spec, `ADM 151/420/01/PART IV`, the same on every letter | keep the old case-reference-like default | The case reference is the tracking number (C6); printing a look-alike would confuse. `[CONFIRM]` with the desk what the parts mean. The setting keeps its name, so `.env` files keep working. |
| 2026-10-25 | Download names use the case reference | the registry reference | That's the same on every letter, so every download would have the same name. |

## 4. Open questions

Items marked `[CONFIRM]` in the code, to check with the Ministry.

- [ ] **Role list:** is `applicant, records_officer, minister, permanent_secretary, director, officer, admin` right? Are there other roles (e.g. Deputy PS, Registrar)? See backend/alembic/versions/0002_roles_and_users.py.
- [ ] **Staff password policy:** does the Government of The Gambia have an ICT policy we must follow (length, expiry, two-factor)?
- [ ] **Session length:** is 60 minutes before re-login acceptable for officers? (`ACCESS_TOKEN_MINUTES` in settings.)
- [ ] **Security to-do before going live (not a Ministry question):** rate-limit `/auth/login` against password guessing, and serve the API only over HTTPS. Tokens sent over plain HTTP can be stolen.
- [ ] **Rest of the org chart:** the chain Minister → PS → DPS is confirmed. Still to check: the exact titles of the DPS and the ETLS officer post, which department the DPS sits in, whether there are other DPS posts, and where the Registry and the Directorate of Trade fit. See 0008 and 0012 in backend/alembic/versions/.
- [ ] **Single-holder posts:** should the database refuse a second Minister, PS or Director at the same time? Right now any post can have several holders.
- [ ] **Who may assign posts:** right now only someone with server access, through the CLI. Should an HR or admin officer do it from a screen?
- [ ] **Who may record a delegation:** only the post holder, or also e.g. the Minister's private secretary or a system admin on their behalf? See `create_delegation()` in backend/app/core/workflow/delegation.py.
- [ ] **Delegation limits:** is 90 days the right maximum (`MAX_DELEGATION_DAYS`)? Is back-dating ever needed, e.g. after an emergency?
- [ ] **Delegation rules:** should the delegating post be blocked from acting while it is delegated? (Whether delegations can be passed on is confirmed: they can't.)
- [ ] **Vacant posts:** if a post has no holder at all, should the succession order apply, as if it were absent? Right now it doesn't: nobody acts until someone is appointed or an absence is recorded. See `acting_successor()` in backend/app/core/workflow/succession.py.
- [ ] **A delegate who is away:** if the Minister delegated to the DPS and the DPS is also away, nobody covers the Minister's step (the delegation blocks succession). Should succession apply then?
- [ ] **An absent holder acting:** a Minister marked absent can still act in their own right (e.g. working remotely). Should being absent block that?
- [ ] **Which DPS covers the Minister's step when both the Minister and the PS are away?** Placeholder: DPS Administration and Finance, the only DPS post we know of. See backend/alembic/versions/0013_succession_orders.py.
- [ ] **The PS's own line:** we assumed the general chain means DPS Admin & Finance also covers the PS. Confirm.
- [ ] **Who may record an absence on someone's behalf?** Placeholder: anyone with the `absence_recorder` role (e.g. the Minister's private secretary, HR). Should it instead be tied to posts, e.g. "the Minister's office may record the Minister's absences"? See backend/app/core/workflow/absence.py.
- [ ] **Audit retention:** how long must audit records be kept under Gambian public records rules?
- [ ] **ETLS after the Director signs:** what does the officer do with the file (issue the certificate, notify the applicant)? Who may reject an application, and at which step? Are there steps such as "returned to applicant for more documents", a fee payment or an inspection? See the officer's moves in backend/alembic/versions/0012_confirmed_etls_route.py.
- [ ] **Facility letter route:** who reviews between the ETLS desk and the PS? Who sends the letter to GRA, who closes the file, and who may reject (and at which steps)? The placeholder is the ETLS desk for all three. See backend/alembic/versions/0015_etls_facility_letter.py.
- [ ] **The ETLS desk post:** its real title and department (placeholder: "ETLS Desk Officer", Directorate of Industry and Investment).
- [ ] **Facility letter form lists:** are there fixed lists for exporter country (ECOWAS members), unit and product? They would make checks such as the cement rule exact.
- [ ] **Duplicate certificates:** does a number from a *rejected* case count as used? (Right now every earlier use counts.) May anyone besides the ETLS desk clear the flag?
- [ ] **Originals:** besides the certificate of origin, must any other paper original be seen in person (e.g. the invoice)? It's one column per document (`original_required`).
- [ ] **Facility letter layout:** the wording is in (step 6i). Still to check: the letterhead (printed paper, or a logo and address we should add?); whether the subject line is bold; and what the signature line says when someone acts for the PS (now "For: Permanent Secretary", no name). See backend/app/modules/etls/templates/facility_letter.txt.
- [ ] **File reference format:** what is the Ministry's real format? Placeholder `MOTIE/ETLS/FL/{year}/{case_id:05d}` (`FACILITY_LETTER_REFERENCE_FORMAT`).
- [ ] **Issued letters:** storing (step 6f) and cancel-and-correct (step 6l) are built. Still open: may the importer download it? Does a corrected letter get a new file reference? Should the case go back to the desk (now) or straight to the PS? Is cancelling allowed after "Sent to GRA" (now yes), and must GRA be told in writing when a letter they hold is cancelled?
- [ ] **The cement receipt:** which receipt is it (e.g. a payment receipt for a cement levy)? Is "HS heading 2523" the right trigger, or only some subheadings (e.g. 2523.29 Portland cement, not 2523.10 clinker)? Are other headings subject to receipts too? See backend/alembic/versions/0020_facility_letter_hs_code.py.
- [ ] **HS code:** it's optional for applicants now (step 6k). Which officer enters or confirms it: the ETLS desk (placeholder) or someone else? How many digits does GRA use (we accept 6, 8 or 10)?
- [ ] **Document type names:** are "Business registration certificate", "Annual returns certificate", "Certificate of origin", "Invoice" (commercial invoice?) and "Export declaration" the official names?
- [ ] **Absence reasons:** who may see why someone is away? Now only the person, whoever recorded it, and recorders.
- [ ] **Applicant explanations:** the one-line explanation under each facility letter label (e.g. "The ETLS desk is checking your application.") is my wording. See backend/alembic/versions/0023_applicant_labels.py.
- [ ] **Who may upload, and until when:** right now the applicant and any staff member, until the case is closed.
- [ ] **Security to-do before going live (not a Ministry question):** scan uploads for viruses (e.g. ClamAV), back up the `documents` volume together with the database, and add a clean-up job for files left behind if the server crashes mid-upload.
- [ ] **Who may open an ETLS case:** only the applicant online, or can Records register walk-in applications too?
- [ ] **Who may see a case:** right now, any staff member sees every case. Should staff see only cases in their directorate, or only cases assigned to them? See `can_view()` in backend/app/core/workflow/service.py.
- [ ] **What applicants see:** only the current status, or also the steps taken (without internal comments)? See `case_history()` in backend/app/core/workflow/router.py.
- [ ] **Deadlines:** how many days may a file sit at each step before it's overdue? (Needed for deadline tracking, not built yet.)
- [ ] **Drafts:** may staff see an applicant's unsubmitted draft (now yes, like every case)? Should old drafts be deleted after some time, and how long?
- [ ] **ECOWAS list checks:** is the wording of the two ticks right ("The exporter's ETLS approval number is on the ECOWAS ETLS list"; "On the ECOWAS ETLS list, the product approval covers these goods")? Any other checks the desk does by hand? See backend/alembic/versions/0029_desk_checks.py.
- [ ] **Holds:** may the desk also *return* (not only reject) while a duplicate flag is open? Now it must resolve the flag first.
- [ ] **Registry file reference:** is `ADM 151/420/01/PART IV` the same on every facility letter, or does part of it change (the year, a folio number, a new "PART" when a file fills up)? It's `FACILITY_LETTER_REFERENCE_FORMAT` in backend/app/core/config.py.
- [ ] **GRA:** does GRA ever report back about a letter (received, used at clearance)? If so, a step after "Sent to GRA" may be needed again (C9).

## 5. Check yourself

Questions per step. Try to answer before reading the answers.

### Step 8e
1. Why does the "Mark sent to GRA" action show `blocked_by: []` even though the date hasn't been entered, and what stops someone making the move without one?
2. A letter went to GRA on Monday, was cancelled on Tuesday and a corrected one went on Thursday. How many rows are in `etls.facility_letter_dispatches`, and what does the applicant's timeline end with?
3. "Sent to GRA" is final, yet the PS can still cancel from it. Why doesn't that put every sent letter in the PS's queue?

#### Show answers
1. The `etls_dispatch_recorded` check is linked with `in_dry_run = false`, so `what_blocks()` leaves it out: the date comes with the click. The move itself runs every check, so the generic `POST /cases/{id}/status` gets 409 ("the dispatch date hasn't been entered"); only `POST /etls/facility-letters/{id}/sent-to-gra` adds the dispatch row first.
2. Two: one per issued letter (each `issued_document_id` once). The timeline ends "Letter sent to GRA", then (cancel hidden) "Awaiting signature", "Letter signed", "Corrected letter issued", because the hidden cancel took the case away from `sent_to_gra`, which has `applicant_label_corrected`.
3. The cancel move has `is_correction = true`. `queue()` in backend/app/core/workflow/queues.py ignores correction moves, both in the SQL pre-filter and in the per-case check, and final statuses are left out anyway.

### Step 8d
1. Two applications use the same certificate number. The second is submitted. Can Records accept its originals? Can the desk verify it? Why the difference?
2. The desk rejects the flagged case with the minute "exporter confirmed one shipment only" and a message to the applicant. What does the flag's `resolution` say, and why that text and not the message?
3. An applicant declares HS code 2523.29 (cement). Is the cement receipt required at Submit? When does it become required, and which function decides?

#### Show answers
1. Records: yes. The flag is for the desk post, and `holding()` in backend/app/core/workflow/flags.py only returns flags for the post whose move it is. The desk: no; Verify is the desk's move, so the flag holds it until resolved (or the case is rejected).
2. "Reject: exporter confirmed one shipment only". `change_status()` resolves the flags with the minute when there is one, because it's the officer's finding; the message to the applicant is only used when there's no minute.
3. No: `applies` is null ("not known yet"), because `hs_heading()` in backend/app/modules/etls/service.py uses only `hs_code_confirmed`. It becomes required when the desk confirms a 2523 code, and the desk's Verify (strict `documents_complete`) then waits for the upload.

### Step 8c
1. A certificate was issued on 31st August 2026. On which date does Verify start being blocked, and which function decides?
2. Why can the applicant submit with an expired certificate, but the desk can't verify it? Where in the database is that difference?
3. Months later someone asks "was the applicant told the certificate was about to expire?" Where do you look?

#### Show answers
1. On 1st March 2027. `certificate_expiry()` uses `add_months()`, which gives 28th February 2027 (February has no 31st); the certificate is valid through that day, and `_check_certificates_valid()` fails once `today() > expiry`.
2. The expiring check is linked to Submit with `warn_only = true`, so it only produces `warnings`. The valid check is linked to Verify as a normal (blocking) check. Both links are rows in `core.transition_checks` (migration 0028).
3. In the Submit move's audit row (`GET /cases/{id}/history`, the `case.status_changed` row to `submitted`): `details.warnings` holds the exact text they were shown.

### Step 8b
1. The desk returns a case with a message and a minute. Name every place the applicant could see the minute, and explain why it can't appear in any of them.
2. After the applicant resubmits, why does the notice on their list disappear, while the timeline still shows the message?
3. A returned applicant changes the product from "Roofing sheets" to "Cement". What happens to the HS code the desk confirmed, and what stops the desk verifying without looking again?

#### Show answers
1. `GET /cases/{id}`, `GET /cases` and `GET /cases/{id}/timeline`. All three read only `applicant_message` from the audit row; the minute is `comment`, which only the staff history (`GET /cases/{id}/history`, staff only) returns.
2. The notice is `current_message()`: the message of the move into the case's *current* status. After resubmitting, that move is "Resubmit", which has none. The timeline lists every move, each with its own message.
3. `update_form()` clears `hs_code_confirmed` (and records the old value as `hs_code_confirmation_cleared`). The desk's Verify move has the `hs_code_confirmed` check, which fails until someone confirms a code again.

### Step 8a
1. Why can't the DPS submit an applicant's draft, even when acting for everyone above them?
2. Two applicants start drafts on Monday and submit on Tuesday in the opposite order. Which one gets `/0001`, and which code decides that?
3. An applicant's draft uses a certificate number that's already on a submitted case. When is the flag raised, and why not when the draft is saved?

#### Show answers
1. The Submit move has `by_applicant = true` and no post. `_permitted()` gives such moves only to the case's applicant (`acts_as_applicant()`), before any delegation or succession is looked at, so there's no post for anyone to act for.
2. The one who submits first. The number comes from the `assign_reference` effect on the Submit move (`_assign_reference()` in backend/app/core/workflow/service.py), not from opening the case.
3. When they submit, by the `etls_check_duplicate_certificates` effect. A draft isn't an application yet; checking on save would put cases on hold over forms nobody has sent, and the numbers can still change.

### Step 7f
1. The Director is on leave. The DPS opens any screen. What does the banner say, and why does it mention ETLS approvals only?
2. Why does `GET /absences/current` hide the reason from a desk officer but show it to the absent person?

#### Show answers
1. "Acting for the Director of Industry and Investment" by succession, with `workflows: ["etls_application"]` and the Director's absence dates. The Director's succession row exists only for that workflow (migration 0013), and `acting_now()` asks `acting_successor()` per workflow.
2. Reasons can be personal (e.g. medical). `current_absences()` in backend/app/core/workflow/acting.py returns the reason only to the person, whoever recorded it, and `absence_recorder`s.

### Step 7e
1. The DPS signs while the PS is on leave. Where in the history response is the PS's absence, and where does that come from?
2. Why doesn't the applicant's timeline show the PS cancelling a letter, and what does it show as the current status?

#### Show answers
1. In the signing row's `acting_for.absences`: the PS's name with `starts_on` and `ends_on`. The audit row only stores `absence_ids` (step 5d); `staff_history()` loads those absences and the absent person's name.
2. The cancel move has `applicant_visible = false` (migration 0023), so `applicant_timeline()` skips it. The current status comes from `GET /cases/{id}`: `originals_received`, whose applicant label is "Being verified".

### Step 7d
1. Why is it safe to run every check on every `GET /cases/{id}`, and what would break if someone wrote a check that saves something?
2. An action's `blocked_by` is `[]`, but the move still fails. What could cause that?

#### Show answers
1. Checks only read data, so a dry run changes nothing. A check that wrote something would write it each time anyone *looked* at the case, possibly without it ever being committed, or commit it unintentionally. That's why the rule is written in backend/app/core/workflow/checks.py.
2. Things the dry run deliberately leaves out: a missing reason on a move with `requires_comment`, an effect failing (e.g. the letter can't be stored), or the case changing between the look and the click (another officer moved it first, giving 409).

### Step 7c
1. The PS is on leave and the DPS opens their queue. Which facility letters do they see, and how does the queue know?
2. Why does the queue still call `available_transitions()` for each case, after the SQL query has already filtered?
3. A desk officer edits nothing, but someone uploads a new invoice to a case. Does its `days_waiting` change?

#### Show answers
1. Letters in "Verified" (the PS's step). The SQL step includes posts whose succession line names one of the DPS's posts (the PS's line does). Then `available_transitions()` checks the PS's holders really are all absent today and nobody holds a delegation, and marks the move `on_behalf_of: permanent_secretary`.
2. The SQL is a deliberately generous superset: it doesn't know who is absent today or which delegations block succession. The engine's check is the real rule, so the queue and the case page always agree.
3. No. Only the engine sets `status_changed_at`, when the status changes. Uploads don't touch it.

### Step 7b
1. Two applicants press Submit in the same second. Why can't they get the same number?
2. A submission takes `MOTIE/ETLS/FL/2026/0007`, then fails while saving the form. What number does the next submission get, and why would a `SEQUENCE` give a different answer?

#### Show answers
1. `next_reference()` updates the year's counter row, which locks it until the first transaction ends. The second waits, then reads the new value and adds one.
2. `0007` again: the counter's `+ 1` was part of the failed transaction and rolled back with it. A sequence's `nextval()` is never rolled back, so the next one would be `0008` and `0007` would be missing.

### Step 7a
1. Where does the applicant's "Being verified" come from, and why don't they see "originals_received"?
2. Records accepts a case. What does the applicant's timeline say happened, and what does the case page say it is now?

#### Show answers
1. From `workflow_statuses.applicant_label` of the `originals_received` status (migration 0023). `status_view()` in backend/app/core/workflow/service.py returns `null` for `code` and `name` when the user isn't staff.
2. "Originals checked" (the move's `applicant_event`) on the timeline, and "Being verified" (the new status's label) as the current status.

### Step 6l
1. The PS is away and the DPS cancels a letter. Which records show that, and what do they say?
2. Why can't the desk download "the letter" between the cancellation and the new signature, and how would they get the old one?
3. Someone with psql access runs `DELETE FROM core.issued_documents WHERE id = 7`. What stops them, and would it stop the superuser?

#### Show answers
1. The status-change audit row (`basis: succession`, `on_behalf_of: permanent_secretary`, the reason as `comment`); the `case.document_cancelled` audit row (the letter's id, checksum and the reason); and the letter's own row (`cancelled_by` = the DPS, `cancellation_reason`).
2. `letter.pdf` serves only the *current* letter, and there's none until the PS signs again, so it answers 409. The old one is in `GET .../letters`; its `download_url` serves it with `X-Letter-Status: cancelled`.
3. The `issued_documents_guard` trigger raises "issued documents are never deleted". The app user has no `DELETE` grant either. Triggers also fire for the owner and the superuser; only someone who deliberately drops or disables the trigger could get past it, and that takes the owner's rights.

### Step 6k
1. An applicant gives no HS code. What does the checklist say about the cement receipt, and can Records confirm the originals?
2. Someone writes a rule `{"field": "hs_haeding", ...}` (typo). Does the document become "not known yet"? Why not?
3. Why is `documents_complete` (the strict one) the check on Verify, and not on Records?

#### Show answers
1. `"applies": null`, `"missing": false`. Yes: Records' move uses `known_documents_complete`, which waits on undecided documents.
2. No. `holds()` only returns `None` when the module supplies the fact with no value. A fact name the module never supplies fails closed (`True`, required) and logs a warning, so the typo shows up as a document everyone is asked for.
3. The desk enters the HS code during verification, after Records' step. By Verify the answer must be known, so the strict check (with `hs_code_confirmed`) makes sure nothing undecided goes to the PS. On Records it would block every case without a code.

### Step 6j
1. What does `long_date()` give for 12 March 2027 and for 22 March 2027, and which line makes them different?
2. A letter was signed on 1 October with the old format "1 October 2026". After this step, what does its download show?

#### Show answers
1. "12th March, 2027" and "22nd March, 2027". In `_ordinal()`, `11 <= n % 100 <= 13` sends 11, 12 and 13 to "th"; otherwise the last digit decides (2 gives "nd").
2. Still "1 October 2026". Downloads serve the file stored at signing (step 6f); nothing is rendered again.

### Step 6i
1. The Ministry wants "Kindly" instead of "We hereby write to your good office to kindly". What do you change, and what happens to letters already issued?
2. An importer registers as "ACME >> Trading". Where does the date end up on their letter, and why?
3. The DPS signs while the PS is on leave. What does the line under "Sincerely," say, and where does that come from?

#### Show answers
1. Edit the sentence in templates/facility_letter.txt and change the `## version:` line (e.g. to `3`). Letters already issued don't change: they're the stored files from step 6f, and they keep `template_version` 2.
2. At the right of the first line, as usual. `render_pdf()` looks for ` >> ` in the template line *before* filling in fields, so the importer's name is just text.
3. "For: Permanent Secretary". `build_fields()` reads the signing audit row: `on_behalf_of` is `permanent_secretary`, so `signature_title` is "For: " plus that post's title.

### Step 6h
1. Someone copies `.env.example` to `.env` on the Ministry server and runs `scripts/reset-dev.sh`. What happens?
2. Why does the script stop the API before dropping the database?
3. Why does `app_env` default to `production` instead of `development`?

#### Show answers
1. Nothing is deleted: `.env.example` says `APP_ENV=production`, so the script prints "Refusing: APP_ENV in .env is 'production'..." and exits before touching Docker.
2. The API holds open database connections and has the documents volume mounted. Docker won't delete a volume a container is using, and while `WITH (FORCE)` would close the connections, the API could open new ones and write to the half-built database during the migration.
3. To fail safe. If someone forgets to set it, the dangerous tools (reset, seed with a known password) stay off. Forgetting it on your own machine only means the script refuses until you add `APP_ENV=development`.

### Step 6g
1. An importer declares `7210.49` (steel) but the goods are really cement. Where in the process is that caught, and what stops the file going to the PS without the receipt?
2. Why does `facility_letter_facts()` leave out `hs_heading` entirely for a case with no HS code, rather than returning an empty string?
3. The Ministry says the receipt is also needed for heading 6810 (cement blocks). What do you change?

#### Show answers
1. When the desk confirms the code as `2523.29` (`confirm_hs_code()`). From then on `hs_heading` is `2523`, the receipt applies, and the desk's Verify move fails its `documents_complete` check until it's uploaded. Verify also needs `hs_code_confirmed`, so the desk can't skip confirming.
2. A missing fact makes `holds()` fail closed and require the document. An empty string would compare as "not 2523" and quietly drop the receipt.
3. Only data: a new migration. The condition language has one condition per requirement and only `equals`/`contains`, so either add a second requirement row with its own document type, or add an `in` operator to `conditions.py` and to the `document_requirements_condition_shape` constraint, then change the row to `{"field": "hs_heading", "op": "in", "value": ["2523", "6810"]}`. No change to the ETLS module.

### Step 6f
1. The PS signs a letter, then the Ministry rewords the template. What does GRA get when the desk downloads the letter next week, and how could you prove it?
2. Rendering works but writing the audit row fails during signing. What state are the case and the documents folder in afterwards, and which code makes that so?
3. Someone deletes the `issue_facility_letter` function but leaves the row in `core.transition_effects`. What happens when the PS tries to sign?

#### Show answers
1. The same bytes that were stored at signing: downloads read the stored file and never call `render_pdf()` again. Hash the download (`sha256sum`) and compare it with `sha256` in `core.issued_documents` and in the `case.document_issued` audit row. `template_version` says which wording it used.
2. The case is still "Verified" (nothing was committed) and no new file is left behind. `issue()` in backend/app/core/documents/issued.py deletes the file if anything after the write fails; if the commit itself fails, `change_status()` calls the undo the effect returned.
3. The move is refused with 409 ("The step 'issue_facility_letter' isn't available...") and the server log says why: `run()` in backend/app/core/workflow/effects.py fails closed. `test_every_effect_named_in_the_database_has_code_behind_it` would fail too.

### Step 6e
1. The PS is on leave and the DPS signs. What does the signature block say, and where does that information come from?
2. Someone sets `FACILITY_LETTER_REFERENCE_FORMAT` to `MOTIE/{case_id.__class__}`. What happens, and when?
3. Why does the test call `render_pdf(fields, compress=False)` before searching the PDF for text?

#### Show answers
1. The DPS's name, "Deputy Permanent Secretary, Administration and Finance", then "for the Permanent Secretary". `letter_fields()` (`build_fields()` since step 6f) reads the audit row of the move to `signed`: the actor, `as_position` and `on_behalf_of` (recorded by the engine in step 5d).
2. The API refuses to start: `_only_known_placeholders()` in backend/app/core/config.py finds the placeholder `case_id.__class__`, which isn't `year` or `case_id`, and pydantic raises a validation error. Better at startup than on the day a letter is needed.
3. PDFs normally compress each page's contents, so the words aren't readable in the raw bytes. Without compression, every printed line appears as text in the file, so the test can check what the letter actually says.

### Step 6d
1. Records tries to confirm "originals received" with the invoice missing *and* the original certificate not yet seen. What do they get?
2. The Ministry wants the PS's "Sign" move to require that a fee is paid. Which parts change?
3. The Records Officer marks the original certificate as seen, then the applicant uploads a new scan of it. Can Records confirm? Why is that the right behaviour?

#### Show answers
1. **409** with both problems in one message: "Not ready: Invoice is missing; the original certificate of origin hasn't been marked as seen". `checks.problems()` runs every check on the move and collects all their problems.
2. A function, e.g. `_check_fee_paid()`, registered with `checks.register("fee_paid", ...)` by whatever code knows about fees, and a migration adding a `core.transition_checks` row for the Sign move. `change_status()` doesn't change.
3. No: `original_pending` looks at the *newest* upload, which hasn't been seen. The original was compared with the earlier scan (its checksum is in the audit row), and the new scan could show something different. Records must compare it again.

### Step 6c
1. The Ministry decides that rice imports need a phytosanitary certificate. What do you change?
2. Someone uploads `invoice.pdf` that is really a Windows program. What happens, and which line decides?
3. A requirement row says `{"field": "origin", "op": "equals", "value": "Mali"}`, but the facility letter module supplies no `origin` fact. Is the document required? Why that choice?

#### Show answers
1. A migration that adds a document type (`phytosanitary_certificate`) and a requirement row for `etls_facility_letter` with `{"field": "product", "op": "contains", "value": "rice"}`. No Python changes.
2. **415**, and the partial file is deleted. `storage.save()` compares the file's first bytes with the PDF, PNG and JPEG signatures. A Windows program starts with `MZ`, so `content_type` is `None` and it raises `UnsupportedFileType`. The name and the browser's `Content-Type` are never trusted.
3. Yes. `holds()` treats an unknown fact as "applies" and logs a warning. A typo in a rule then asks for one document too many, which someone will notice and fix. The other choice would quietly drop a required document.

### Step 6b
1. A facility letter is submitted with certificate "gm-co 15", and an earlier case used "GM-CO15". What does the importer see, and what does the desk see?
2. Why does `_earlier_uses()` need an advisory lock? Why not `SELECT ... FOR UPDATE`, as in `get_case()`?
3. The case is flagged. A Trade Officer (not the ETLS desk) tries to resolve the flag, and then Records tries to confirm the originals. What do they get?

#### Show answers
1. The importer gets **201**: the submission is accepted and the case opens. On `GET /cases/{id}` they see no flag (`on_hold` is `null` for applicants). The desk sees `on_hold: true` and a flag `etls.duplicate_certificate_of_origin` listing `GM-CO15` and the earlier case id. Both numbers normalise to `GM-CO15`.
2. Two submissions at the same moment would each check, find no earlier use (the other isn't committed yet), and both go through. `FOR UPDATE` locks rows that exist, and here the row that matters is the one the other transaction is *about to* insert. An advisory lock on the number itself makes the second submission wait until the first commits.
3. The Trade Officer gets **403** "Only the ETLS Desk Officer can resolve this flag." Records gets **409**: the case is on hold until the flag is resolved.

### Step 6a
1. An applicant sends `POST /cases` with `{"workflow": "etls_facility_letter"}`. What happens, and why is that the right answer?
2. Saving the certificate numbers fails halfway through `submit_facility_letter()`. Is there a case without a form left behind? Why not?
3. Why is `quantity` a `NUMERIC(14, 3)` and not a `float`?

#### Show answers
1. **403**: "Cases of 'etls_facility_letter' are opened through the etls module." `open_case()` compares the workflow's `opened_by_module` (`etls`) with the caller's `module` (none). Otherwise the case would have no form, and nobody could process it.
2. No. `open_case()` only adds the case and its audit row to the transaction. `submit_facility_letter()` commits once, after adding the form rows. If anything fails before that, the whole transaction is rolled back: no case, no audit row, no form.
3. Floats approximate decimals in binary. A quantity typed as `1200.5` must appear exactly on an official letter to GRA. `NUMERIC` stores decimal digits exactly, and the schema refuses more than 3 decimal places instead of silently rounding.

### Step 5d
1. The Minister is recorded absent and has *not* delegated. The DPS (who is at work) tries the Minister's step while the PS is also at work. What happens, and why?
2. The Minister is absent and has delegated to the DPS for the week. Can the PS do the Minister's step? Which function decides?
3. Both the Minister and the PS are away, and the DPS minutes a file to the PS desk. What does the audit row's `details` contain, and why are there two absence ids?

#### Show answers
1. **403.** `acting_successor()` walks the Minister's order (PS, then DPS) and stops at the first post with a holder at work: the PS. Only the PS may act, so the DPS gets "None of your positions can make this move."
2. No. In `_permitted()`, `is_delegated_away()` sees the Minister's active delegation and skips succession for that step: the Minister's own choice takes priority. The DPS may act, with `"basis": "delegation"`.
3. `"as_position": "dps_admin_finance"`, `"on_behalf_of": "minister"`, `"basis": "succession"`, `"delegation_id": null`, `"absence_ids": [<Minister's>, <PS's>]`, plus `from`, `to`, `transition` and `comment`. Two ids, because the DPS acted only because the Minister was away *and* the PS, first in line, was away too. Both facts justify the move.

### Step 5c
1. The PS sends `POST /absences` with the Minister's `user_id`. What happens, and why does it matter?
2. The Minister's private secretary (role `absence_recorder`) marks the Minister absent. Who is `actor_user_id` in the audit row, and where does the Minister appear?
3. The Minister comes back two days early. What should happen to the absence, and why can't the app just change `ends_on`?

#### Show answers
1. **403** "You can only record your own absence." The PS has no `absence_recorder` role. It matters because marking the Minister absent would let the PS take the Minister's step through succession (step 5d).
2. `actor_user_id` is the private secretary: the log records who actually did it. The Minister appears as `absent_user_id` in `details`, with `on_behalf: true` and `recorded_by` set to the secretary's id.
3. Cancel it: `POST /absences/{id}/cancel`, by the Minister or a recorder. That sets `cancelled_at` and writes an audit row. The app may only update `cancelled_at` and `cancelled_by` (migration 0014), so dates stay as they were when the absence was used to justify a move.

### Step 5b
1. The Ministry adds a rule: for ETLS only, the Minister is covered by the DPS straight away. Which rows does `succession_order()` return for the Minister on an ETLS case, and on a case of another workflow?
2. Without `NULLS NOT DISTINCT`, what mistake could a migration make without the database noticing?
3. Why is the PS → DPS row in the seed, when the Ministry only spelled out the Minister's chain and the Director's ETLS rule?

#### Show answers
1. On ETLS: only the DPS, because the ETLS rows *replace* the Minister's general line. On any other workflow: the general line, PS then DPS. `test_a_workflow_rule_replaces_the_general_one` checks exactly this.
2. Insert two general rules for the same post with the same rank (or the same successor). Two NULLs are never equal, so the unique constraint wouldn't fire, and the order between the two rows would be a coin toss.
3. The confirmed general chain is Minister → PS → DPS, so we read it as "the DPS covers the PS" too. Without it, files would stop at "With the PS" whenever the PS is away. It's listed under Open questions so the Ministry can confirm.

### Step 5a
1. A case was "With the Directorate" when you ran migration 0012. Where is it afterwards, and why didn't the migration need to touch `core.cases`?
2. Why does the ETLS workflow still have an officer "Approve" move, when the Director now signs?
3. Why does the race test need `release_posts`, when other tests don't clean up after themselves?

#### Show answers
1. It's "With the Director of Industry and Investment". The case points at the status *id*, and 0012 renamed that status row (`code` and `name`) without changing its id. The next move is then the Director of Industry's "Sign and assign to an officer".
2. Because the Ministry hasn't said yet what the officer does after the signature, or who may reject. Removing the officer's moves would leave "With the officer" as a dead end, which `test_every_workflow_is_well_formed` refuses. It's an open question.
3. Other tests run inside a transaction that is rolled back (`db_session`). The race test commits for real on separate connections, so its post holders would stay for the rest of the run. Once absences matter (step 5d), a leftover Minister who isn't absent would make the Minister's post look present.

### Step 4e
1. The Minister is in Banjul (no delegation exists). The PS tries to minute an ETLS file to the Directorate. What happens? How would that answer have differed before step 4e?
2. Why did we write a new migration (0011) instead of deleting the PS line from migration 0005?
3. The Minister delegates to the PS for ETLS only. What does the audit row look like when the PS minutes a file?

#### Show answers
1. **403**, and `available_actions` is empty for the PS. Before 4e the PS had their own transition row for that move, so it would have succeeded at any time, with nothing in the log showing the Minister was away.
2. Migrations that have already run are never edited. Your dev database (and any server) ran 0005 and has the row. Alembic only runs migrations a database hasn't had yet, so an edited 0005 would never run there and the row would stay. A new migration removes it everywhere, and its `downgrade()` can put it back.
3. `"as_position": "permanent_secretary"`, `"on_behalf_of": "minister"`, `"delegation_id": <its id>`, together with `from`, `to`, `transition` and `comment` as before. `actor_user_id` is the PS's user id.

### Step 4d
1. The Director delegates to the Trade Officer post from 3 to 10 March. On 11 March a Trade Officer tries to assign a file. What happens, and which line decides it?
2. Why can the app set `revoked_at` on a delegation but not change `ends_on`? What could go wrong if it could?
3. The Director delegates to the Trade Officer post, and the Trade Officer post delegates to the Records Officer post. Can a Records Officer assign a file to an officer? Why?

#### Show answers
1. **403** "None of your positions can make this move." `active_delegations_to()` only returns delegations where `starts_on <= today` and `ends_on >= today`. On 11 March the delegation is no longer active, so `_permitted()` finds nothing.
2. Migration 0010 grants `UPDATE` on those two columns only. If `ends_on` could change, someone could later stretch a delegation to cover a move made after it ended, and the audit trail would look legitimate. Revoking only ever shortens a delegation, and it's logged.
3. No. `active_delegations_to()` only looks at delegations *to* posts the user holds. The Records Officer has one from the Trade Officer post, but the assign move needs the Director's post, and nothing delegates that to the Records Officer post. Delegations aren't passed on (`test_delegations_are_not_passed_on`).

### Step 4c
1. The Ministry decides that the PS, not the Minister, minutes ETLS files to the Directorate. What do you change?
2. A user has the `director` role but holds no post. They try to move a case from `with_directorate` to `with_officer`. What do they get, and which line decides it?
3. Why does migration 0009 add `required_position_id` as nullable first and only make it `NOT NULL` after the `UPDATE`?

#### Show answers
1. A new migration that updates (or deletes) the `with_minister` → `with_directorate` row for the `minister` post. No Python changes, and no change to who holds which post.
2. **403** "None of your positions can make this move." In `change_status()`, `held` is empty, so `next(...)` finds no matching move and raises `NotPermitted`. Roles no longer grant moves.
3. Existing rows have no value for the new column when it's added, so `NOT NULL` would fail straight away. The `UPDATE` fills it in from the old role. Then `NOT NULL` both locks the rule in and checks that every row was converted: if one wasn't, the migration fails and rolls back.

### Step 4b
1. A new Director of Trade replaces the old one. What changes in the database, and what stays the same?
2. Why does `assign_position()` use `ON CONFLICT DO NOTHING ... RETURNING` instead of first checking whether the user already holds the post?
3. Why does `Position` have a `reports_to_id` column but no `reports_to` relationship?

#### Show answers
1. One row in `core.position_holders` is deleted (old Director) and one is inserted (new Director), and each change adds an audit row. The positions table and, from step 4c, the workflow transitions stay the same, because they name the *post*, not the person.
2. Check-then-insert has a gap: two admins at the same moment both see "not held", and the second insert fails on the primary key. A single statement has no gap. And since nothing comes back when the row already existed, no audit row is written for a change that didn't happen.
3. Positions are loaded with every user on every request (`User.positions` is `selectin`). A self-referencing relationship would also load each boss, then each boss's boss, adding queries to every request. The id is enough; code that needs the chain can look it up.

### Step 4a
1. Someone takes full control of the API process and runs `ALTER TABLE core.audit_log DISABLE TRIGGER ALL`. What happens, and why? What about `DELETE FROM core.audit_log`?
2. You write migration `0012` that creates `core.documents` and forget the `GRANT`. What breaks, and what tells you?
3. Why does `docker compose exec api alembic upgrade head` no longer work, and why is that good?

#### Show answers
1. `ERROR: must be owner of table audit_log`. The API logs in as `motie_app`, and only a table's owner (`motie_owner`) or a superuser may alter it or its triggers. The `DELETE` gives `permission denied`: `motie_app` was never granted `DELETE` on that table (see 0007), and Postgres checks that before the trigger even runs.
2. The API gets "permission denied for table documents" the first time it touches the table, so it fails closed, never open. `test_every_table_is_owned_by_motie_owner_and_readable_by_the_app` fails and names `core.documents`. Any test using the table through `db_session` fails too, because tests run as `motie_app`.
3. The `api` container has no `MIGRATION_DATABASE_URL`, so `get_url()` in backend/alembic/env.py stops with a clear message. That's good: the server that runs all day, and could be attacked, never holds the password that can change tables. Use `docker compose run --rm tools alembic upgrade head`.

### Step 3c
1. An officer sends `{"to_status": "approved"}` for a case that is still "Submitted". Which status code comes back, and which line decides it? Does anything get written to the audit log?
2. Why does `get_case()` use `populate_existing=True` together with `with_for_update()`?
3. An applicant asks for `GET /cases/57`, which belongs to another applicant. What do they get, and why not 403?

#### Show answers
1. **409 Conflict.** In `change_status()`, the query for moves from `submitted` to `approved` finds no rows, so it raises `TransitionNotAllowed`, which `_ERROR_STATUS` in router.py maps to 409. Nothing is written: the exception happens before `record_event()`, and nothing was committed.
2. The lock makes a second request wait. But if the session already had the case in memory, SQLAlchemy would hand back the old copy with the old status. `populate_existing` forces it to use the freshly read row, so the decision is based on the status *after* the other request committed.
3. **404 "Case not found."**, the same answer as for a case that doesn't exist. A 403 would confirm that case 57 exists, letting someone map out the Ministry's case ids.

### Step 3b
1. The Ministry says Directors may now reject a file directly from "With the Directorate". What do you change: Python code, or something else?
2. Why does `workflow_transitions` reference `(workflow_id, to_status_id)` together instead of just `to_status_id`?
3. In the seed migration, what happens if someone misspells `'with_officer'` as `'with_oficer'` in a transition row, and what catches it?

#### Show answers
1. Something else: a new migration that inserts one row into `core.workflow_transitions` (`with_directorate` → `rejected`, position `director_of_trade` since step 4c). No Python changes, because workflows are data.
2. So a transition can only point to a status in its *own* workflow. With `to_status_id` alone, a move could lead into another process's status, and a case would end up stuck in a workflow it doesn't belong to.
3. The `JOIN` on the status code finds no match, so that row is silently left out. `test_etls_workflow_is_seeded` expects exactly 7 transitions and fails. `test_every_workflow_is_well_formed` would probably also report a dead end.

### Step 3a
1. Why doesn't `record_event()` call `session.commit()`?
2. Someone with psql access runs `UPDATE core.audit_log SET actor_user_id = 3 WHERE id = 10`. What happens? Is there still a way around it?
3. Why is `entity_id` a text column and not a number?

#### Show answers
1. So the change and its audit row are committed together, in one transaction. If `record_event()` committed on its own, a crash between the two commits could leave an audit row for a change that never happened, or a change with no audit row.
2. The trigger `audit_log_no_update_delete` raises an error and the update is cancelled. The way around it is that the table owner or a superuser can disable the trigger. That's why, since step 4a, the app connects as `motie_app`, which is neither.
3. Different modules may use different kinds of keys (numbers, reference codes like `ETLS-2026-0001`). Text can hold any of them.

### Step 2c
1. An officer is dismissed at 10:00 and an admin sets `is_active = false`. Their token was issued at 9:30 and expires at 10:30. Can they still use the API at 10:05? Why?
2. Someone edits their token's payload to change `"sub": "7"` into `"sub": "1"` (the admin). What happens, and which line of code stops it?
3. Why does `authenticate()` hash a dummy password when the email doesn't exist?

#### Show answers
1. No. `get_current_user()` in backend/app/core/identity/deps.py loads the user from the database on every request and rejects inactive users with 401, even if the token itself is still valid.
2. The signature no longer matches the payload, so `jwt.decode(...)` in `decode_access_token()` raises `InvalidTokenError` and they get 401. Making a valid signature needs `JWT_SECRET`, which only the server has.
3. So the response takes the same time whether or not the email exists. Otherwise an attacker could time the responses to find out which emails have accounts (user enumeration).

### Step 2b
1. An attacker copies the whole `core.users` table. Why can't they just read the passwords, and why does Argon2 being slow matter?
2. You add a `phone` attribute to the `User` class but forget the migration. What catches it?
3. Why does `User.roles` use `lazy="selectin"`?

#### Show answers
1. The table only holds hashes, which can't be reversed. The attacker has to guess passwords and hash each guess. Argon2 makes each guess slow and memory-hungry, and the per-user salt means they must attack each user separately.
2. `test_models_match_migrations` in backend/tests/test_migrations.py. Alembic finds a column in the model that the database doesn't have, and the test fails.
3. With async SQLAlchemy, a relationship can't be fetched silently the first time you touch it (that would need hidden I/O). `selectin` loads the roles in one extra query right when the user is loaded.

### Step 2a
1. You pull new code that contains migration `0003`. Your database is at `0002`. What command do you run, and which migrations does it execute?
2. Why does `0001`'s `downgrade()` use `DROP SCHEMA core` without `CASCADE`?
3. Where does Alembic get the database password from, and why isn't it in `alembic.ini`?

#### Show answers
1. `docker compose run --rm tools alembic upgrade head`. It reads `alembic_version` (0002) and runs only `0003`.
2. `CASCADE` would silently delete every table inside `core`. Without it, Postgres refuses if tables still exist, which protects you from losing data with a mistaken downgrade.
3. From `DATABASE_URL`, read by `get_url()` in backend/alembic/env.py (via `settings`). `alembic.ini` is committed to git, and passwords must never be in committed files.

### Step 1
1. Why does `DATABASE_URL` use `db` as the host and not `localhost`?
2. If 10 requests hit `/health/db` at once, how many times does `get_session`'s cleanup run, and how many times does `lifespan`'s?
3. A test creates rows in the database. Why are they gone when the next test starts, even if the code under test called `commit()`?

#### Show answers
1. Each container has its own `localhost`. Inside the API container, `localhost` is the API container itself, where no Postgres runs. Compose gives each service a hostname on its private network, so `db` points to the Postgres container.
2. `get_session` cleanup: 10 times, once per request. `lifespan` cleanup: zero times. It only runs when the server shuts down.
3. The `db_session` fixture opens an outer transaction and rolls it back after each test. With `join_transaction_mode="create_savepoint"`, the code's `commit()` only commits a savepoint *inside* that outer transaction, so the rollback undoes it too.
