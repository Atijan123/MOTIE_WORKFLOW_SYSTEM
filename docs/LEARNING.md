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

### Fix — An ended session goes to the login page, not a crash (2026-11-10)

**What happened:** the morning after signing in, opening the queue showed a Next.js error page: "Not authenticated", from `api()` in frontend/app/staff/page.tsx. The session cookie lasts 60 minutes, as the API's token does, so overnight the browser had dropped it. `apiFetch()` sent people to the login page on a 401 only when a cookie *was* there (the token had expired, but the cookie hadn't). With no cookie, the 401 was thrown as an error instead.

Why didn't `requireUser()` in the staff layout catch it? Next.js renders a layout and its page **at the same time**, not one after the other. The page's own API call failed before the layout's redirect could take effect.

**Built:** `signInAgainPath()` in frontend/lib/auth-redirect.ts decides: any 401 goes to the login page (`/login?expired=1` if a token was sent, `/login` if not), except a wrong password at `/auth/login`, which the login form shows. `apiFetch()` in frontend/lib/api.ts uses it.

**Files:** frontend/lib/auth-redirect.ts, auth-redirect.test.ts, api.ts; frontend/e2e/tests/session.spec.ts.
**Try it:** sign in, delete the `motie_session` cookie in the browser's dev tools, open http://localhost:3001/staff: you land on the login page. Tests: the web unit tests (above), and `docker compose run --rm e2e npx playwright test tests/session.spec.ts`, which only reads and needs no reset.

### Step 11b — The import says why it can't start (2026-11-09)

**What happened:** run from PowerShell, the import stopped with only a "Usage" line and never touched Docker. There, `bash` is `C:\WINDOWS\system32\bash.exe`, WSL's Ubuntu: it can't see a `C:/Users/...` path, and it can't reach Docker Desktop on this machine. That is the likely reason S13 showed 0 letters, and it corrects step 11a below, which blamed my reset as most likely. The reset guard from 11a is still worth having.

**Built:** `scripts/import-history.sh` now checks that Docker is reachable, then that the file exists, and says which failed, starting "Nothing was imported". The Docker message gives the Git Bash command.

**Files:** scripts/import-history.sh, CLAUDE.md.
**Try it:** from PowerShell, `& "C:\Program Files\Git\bin\bash.exe" scripts/import-history.sh "C:/path/to/register.xlsx"`.

### Step 11a — A reset can't silently discard an import; the import prints what the page will show (2026-11-09)

**What happened:** the import was run, and S13 showed 0 letters. The app and the import use the same database (`motie` on `db:5432`, as `motie_app` and `motie_owner`), nothing resets it on start-up, and the API's login has SELECT on the history tables. All three tables were empty, with no import row in the audit log. The API returned the right totals for a fictional import, so the page and API were fine. The database was last rebuilt at 09:52:54 by my own `reset-dev.sh` cleanup. A reset also deletes the audit log, so it leaves no sign of what it removed. I first named this reset as the most likely cause; step 11b found the import had most likely never started.

**Built:**
- `scripts/reset-dev.sh` counts imported letters first. With any present, `--yes` refuses unless `--discard-history` is added too; the typed prompt lists how many will go. `scripts/seed-demo.sh` passes the options through.
- The import now ends by reading back **as the API's own login** and printing the database name and the totals the Statistics page will show (`page_totals()` in backend/app/modules/etls/import_history.py). Counts only.

**Files:** scripts/reset-dev.sh, scripts/seed-demo.sh; backend/app/modules/etls/import_history.py, statistics.py (`all_letters()`); backend/tests/modules/etls/test_statistics.py; CLAUDE.md.
**Try it:** after an import, `bash scripts/reset-dev.sh --yes` should refuse and say how many letters it would delete.
`docker compose run --rm tools pytest tests/modules/etls/test_statistics.py -v`

### Step 11 — Historical facility letters imported from the Excel register; statistics page S13 (2026-11-05)
Also in this step: SCREENS.md A2 got back the half-filled draft rule (8i) and "Corrected letter issued".

**Built:**
- **New library: openpyxl** (you approved it), the standard Python reader for .xlsx files. One line in backend/requirements.txt; the images need rebuilding once (`docker compose build tools api`).
- **History is kept apart from live cases** (migration 0042, schema `etls`): `historical_letters` (one row per letter, 245 in the register, from the sheet "Facility letters"), `historical_goods_lines` ("Goods lines"), `historical_certificates` (each number from "Certificate of origin no(s).", split on ";"), and `historical_data_checks` with `historical_data_check_letters` ("Data checks", linked to the letters they mention). They are not cases and have no workflow.
- **Every column as written.** Every cell is stored as text, exactly as in the register. Where a figure needs a typed value, it gets a second column: `letter_date` (read from "Letter date": Excel dates, "16th October, 2025", "03/11/2025" day first…) and `quantity` (from "Quantity": "1,200.5" and so on). When a value can't be read, the typed column is empty and the text stays. Each letter also keeps where it came from: "PDF page(s)" as written ("File 2, p. 7"), read into `source_file` ("File 2") and `source_page` (7), plus its row in the sheet. Column V, "Also filed at (second copy of this letter)", says where a second paper copy sits ("File 5, p. 9 (folio 5)"). It is stored as text in `also_filed_at`, so a letter filed twice is still one letter and counts once without any special handling.
- **Why `historical_certificates` and the data-check tables exist:** the live duplicate check must find one certificate number among letters that list several, and the register's "Data checks" notes must show on the page of each letter they're about; neither works from a single text cell.
- **The import reports only counts, and problems by sheet and row.** It never quotes a cell (CLAUDE.md, Data rules). Any unexpected error shows only its type, because database errors and tracebacks can quote the row being written.
- **The import:** `bash scripts/import-history.sh /path/outside/the/repo/register.xlsx`. It mounts the file's folder **read-only** at `/data` in a one-off tools container and runs `python -m app.modules.etls.import_history /data/<file>` (the module lives with the rest of the ETLS module, at app/modules/etls/, not app/etls/ as in your example). It:
  - checks the sheets and headings first, then every row: "Letter no." a unique whole number, and the goods lines' "Letter no." pointing at real letters. **Any problem stops it, changes nothing, and lists every problem** with its sheet and row;
  - **replaces the previous import in one transaction**: delete everything, insert everything, commit once;
  - runs as the schema owner (`motie_owner`). **The API's database user can only read these tables**;
  - writes one audit row (`etls.history_imported`) with the file name, its SHA-256 and the counts, but no register content;
  - refuses a file inside the code folder, and `*.xlsx` is git-ignored and docker-ignored, so the register can't end up in the repository or an image;
  - prints what it imported: letters (how many were filed twice, how many have an unreadable scan file and page), goods lines, certificates, data checks (and how many it couldn't link), letters with no readable date, quantities it couldn't read.
- **Data checks are linked** to letters by folio: a check about folio 4 goes with the letter on folios 3-4, narrowed to the check's reference if that matches. With no folio, by reference, but only when the reference belongs to one letter. A registry reference shared by many letters says nothing. Checks it can't link are kept and listed on the statistics page. `[CONFIRM]` once you've seen how the real sheet links.
- **The live duplicate check (S2) searches history too.** A submitted case whose certificate number is on a historical letter is held for the desk: "Certificate of origin number(s) HX-1 used on historical letter ADM/…, 16th October, 2025, Kombo Feeds Ltd". The desk's panel links to the letter's page.
- **Statistics, S13** (`/staff/statistics`, for the Director's post and the new role `stats_viewer`):
  - live letters (a signed letter in force) and historical letters together;
  - letters by month and by year;
  - top 10 importers, exporters, exporter countries and products;
  - quantities by category **and unit**, never adding different units;
  - certificate numbers on more than one letter;
  - letters by signatory.

  Every table says **how many letters it is based on**, and what it leaves out (no readable date, no readable quantity). Filters: date range and part of the importer's name. "Download these letters (CSV)" gives exactly the letters behind the figures. Names written differently ("BANJUL TEST TRADERS", "Banjul Test Traders") count as one.
- **A page for each historical letter** (`/staff/history/{id}`, any staff member): every column as written, its goods lines, certificates and data check notes.
- **Seeds:** `stats@motie.test` (Dev Statistics Viewer). The demo seed also imports a small **fictional** register, so its Statistics page has history.

**Files:** backend/alembic/versions/0042_historical_facility_letters.py; backend/app/modules/etls/history_models.py, import_history.py (`read_register()`, `build_records()`, `letters_mentioned()`, `replace_history()`, `write_register()`, `main()`), statistics.py (`letters()`, `statistics()`, `to_csv()`, `historical_letter()`), history_router.py, service.py (`historical_uses()`, `describe_historical()`, `check_duplicates()`), router.py, schemas.py (`HistoricalUseOut`); backend/app/main.py, models.py, dev_seed.py, demo_seed.py (`write_demo_register()`); backend/requirements.txt, backend/.dockerignore, .gitignore; scripts/import-history.sh; tests: backend/tests/modules/etls/test_history_import.py, test_statistics.py, backend/tests/test_demo_seed.py, backend/tests/support.py (`made_up_register()`), backend/tests/conftest.py (`import_history`); frontend/app/staff/statistics/page.tsx, frontend/app/staff/history/[id]/page.tsx, frontend/app/staff/layout.tsx, frontend/app/files/[...path]/route.ts, frontend/components/staff/DeskChecks.tsx, frontend/lib/session.ts (`mayViewStatistics()`), frontend/lib/types.ts, frontend/e2e/tests/s13-statistics.spec.ts; docs/SCREENS.md (S2, S13), docs/GAPS.md, CLAUDE.md.
**Try it:**
- `bash scripts/seed-demo.sh --yes`, then log in as `stats@motie.test`: Statistics. Filter on "Kombo", download the CSV. Click through to a historical letter from the desk's duplicate panel, or open `/staff/history/1`.
- **The real register (you, not me):** first on the dev database: `bash scripts/import-history.sh "C:/Users/LENOVE/Downloads/ETLS_Facility_Letters_2025-2026 (2).xlsx"` (the 6 November version; older versions have a different column V and are refused). Read what it prints (or the list of problems), then look at Statistics. Running it again with a corrected file replaces the earlier import.
- `docker compose run --rm tools pytest tests/modules/etls/test_history_import.py tests/modules/etls/test_statistics.py -v`
- The S13 walk-through (frontend/e2e/tests/s13-statistics.spec.ts): `bash scripts/seed-demo.sh --yes`, `docker compose up -d web`, then `docker compose run --rm e2e`. The Director filters to the fictional Kombo Feeds letter and downloads the CSV.
**New concepts:** [Keeping what was written beside what was understood](#keeping-what-was-written-beside-what-was-understood), [An import that replaces everything, in one transaction](#an-import-that-replaces-everything-in-one-transaction), [CSV (formula) injection](#csv-formula-injection), [Saying what a figure is based on](#saying-what-a-figure-is-based-on).

### Step 10b — One signing flow for every letter; who may cancel; three copies of each letter (2026-11-05)
Follow-ups to step 10a.

**Built:**
- **No special rule for cement.** Cement letters go Records → ETLS officer → Director (or a signatory while the Director is away), like every other facility letter. Migration 0041 deletes the Minister's and the PS's cement rows from 0040, and the two columns only they used (`applies_when`, `own_post_only`), with the engine code behind them (`applicable()`) and the `not_equals` operator. **The cement receipt is unchanged:** a document requirement decided by the HS code the desk confirms (step 6g). The demo's cement case 9 is gone.
- **The printed signature block is just the name and "For: Permanent Secretary"** (template version 4), as the Ministry's letters are now. "In the Director's absence" is no longer printed. It is still in the signing's audit row (`in_absence`) and now also on the stored letter: the new column `core.issued_documents.signature_note` (the database trigger keeps it unchangeable like the rest of the row; letters signed under 10a were filled in from their audit rows).
- **Cancel and reissue: only the Director, or the officer who signed that letter** `[CONFIRM]`. New move setting `workflow_transitions.stand_in_must_be_issuer`, on "Cancel the signed letter": someone acting for the Director (a signatory, or a delegate) may make the move only if they issued the case's current letter. The Director, in their own right, may always. Any signatory may still **return** a letter nobody has signed yet. See `_permitted()` and `_issued_current_document()` in backend/app/core/workflow/service.py.
- **Three copies of each letter.** Signing still stores one PDF; it now also writes three rows in the new table `etls.facility_letter_copies`: **Records' file copy**, **GRA's copy** (dispatched from Outgoing, as before) and **the applicant's copy**. A corrected letter gets three of its own; a cancelled one's stay on record. The app can add copy rows, never change or delete them. `GET /etls/facility-letters/{id}/letters` lists each letter's copies and its `signature_note`.
- **The applicant downloads their copy** from A1 (the selected case) and A3 ("Download your copy of the facility letter (PDF)") once GRA's copy is marked sent: `GET /etls/facility-letters/{id}/my-copy.pdf`, for the applicant (or Records for a walk-in) only, the same stored file with its checksum. Before the dispatch, or while a corrected letter is awaited, it answers 409. How the applicant collects a paper copy is `[CONFIRM]`.
- **SCREENS.md is the master copy** and now matches what's built: the four built rules are written back (S2: return while the duplicate flag is open, a certificate over six months blocks Verify; Sign disabled until the registry reference is set; A2's 30-day expiry warning), the cement exception is gone from S12, and S3 and the route describe the copies and the cancel rule. The three-copies gap is removed from GAPS.md.

**Files:** backend/alembic/versions/0041_one_signing_flow_and_letter_copies.py; backend/app/core/workflow/service.py, models.py; backend/app/core/documents/conditions.py, issued.py (`issue(..., signature_note=)`), models.py; backend/app/modules/etls/letter.py (`COPIES`, `issue_letter()`, `copies()`, `applicant_copy_ready()`, `applicant_copy()`, `_signature()`), templates/facility_letter.txt, models.py (`FacilityLetterCopy`), router.py (`download_applicant_copy()`), schemas.py (`LetterCopyOut`, `letter_copy_url`); backend/app/demo_seed.py; tests: backend/tests/modules/etls/test_letter_copies.py (new), test_signing_rules.py, test_letter.py, test_letter_corrections.py, test_facility_letter.py, test_ps_support.py, backend/tests/core/test_applicant_labels.py, backend/tests/test_demo_seed.py; frontend/components/LetterCopy.tsx (new), frontend/app/applications/page.tsx, frontend/app/applications/[id]/page.tsx, frontend/app/files/[...path]/route.ts, frontend/lib/types.ts, frontend/e2e/tests/facility-letter.spec.ts; docs/SCREENS.md, docs/GAPS.md.
**Try it:**
- `bash scripts/seed-demo.sh --yes`, then log in as `fatou.jallow@demo.test`: case 0001 has been sent to GRA, so its panel offers "Download your copy of the facility letter". Case 0007 (not signed yet) doesn't.
- As `signer1@motie.test` (the Director is recorded away in the demo), sign 0003; as `signer2@motie.test` you may not cancel it, as `signer1@` you may.
- `docker compose run --rm tools pytest tests/modules/etls/test_letter_copies.py tests/modules/etls/test_signing_rules.py -v`
**New concepts:** [Copies as records, not files](#copies-as-records-not-files).

### Step 10a — Authorised signatories sign in the Director's absence (S12); cement letters need the Minister or the PS (2026-11-04)
*The cement rule and the printed "In the Director's absence" line were removed again in step 10b.*
The rule for signing in the Director's absence changed (SCREENS.md S3, S5, S12 and both routes).

**Built:**
- **The facility letter is now signed by the Director of Industry and Investment**, "For: Permanent Secretary" (it used to be the PS). The Director also returns it to the desk and cancels a signed letter.
- **Cement letters are the exception** (HS heading 2523, as the *desk* confirms it; the applicant's own code never decides). Only the Minister or the PS may sign, return or cancel them, each in their own right: no delegation, no succession, no signatory list. A cement letter isn't in the Director's queue at all.
- **The succession step "DPS Admin & Finance acts for the Director" is gone.** In its place is a list of **named people** (not posts): `core.authorised_signatories`, with date added, added by, date removed and removed by. While every Director is recorded absent, the Director's steps appear in the queue of **every officer on the list**, for facility letters (signing) and ETLS approvals (sign and assign).
- **First to act claims it.** Two signatories pressing Sign at the same moment: the engine already locks the case row (`SELECT ... FOR UPDATE` in `change_status()`), so the second waits, then finds the case signed and gets 409 "someone may have just acted on it: reload". One signing, one letter. Proven by backend/tests/core/test_signatory_race.py.
- **One list for both services, kept as a per-workflow setting** so it can be split later: `core.signatory_rules` says "in workflow W, while every holder of post P is away, the people on list L act for P". Two rows today, both pointing at the list `director_absence`. Splitting is a new list and an UPDATE of one row.
- **Who keeps the list:** the new role `signatory_admin` (the Director's office), on the new screen **S12, Signatories** (`/staff/signatories`, in the menu for that role only). Add an officer, remove one, see earlier signatories. Every change writes an audit row (`signatory.added`, `signatory.removed`). You can't add yourself, an applicant, or someone already on the list.
- **Nothing is forgotten.** The app's database user can't delete entries, can't change who was added or when, and a trigger refuses to undo a removal. Someone put back on the list gets a new row.
- **The record says who and why.** The audit row of a signatory's move has `basis: "signatory"`, `on_behalf_of: "director_of_industry"`, the signatory's name, their list entry, `in_absence: "in the Director's absence"`, and the Director's absences it relied on. The case history shows "Awa Bah, authorised signatory for the Director of Industry and Investment, in the Director's absence (… away …)".
- **The signature block** (template version 3) is now, as in SCREENS.md S3:

  ```
  [signer's name]
  In the Director's absence        (only for an authorised signatory)
  For: Permanent Secretary         (the PS or the Minister signing cement: their own title)
  ```
  A template line made only of fields that are all empty is left out, so the middle line disappears when nobody was absent. The preview shows the block as the person looking at it would sign.
- **Two small engine features** made this data, not code:
  - `workflow_transitions.applies_when`: a condition in the documents' condition language (`{"field": "hs_heading", "op": "equals", "value": "2523"}`, plus a new `not_equals`). A move whose condition doesn't hold isn't that case's move at all. Anything uncertain (no confirmed HS code) means "doesn't apply". See `applicable()` in backend/app/core/workflow/service.py.
  - `workflow_transitions.own_post_only`: only holders of the post itself, for the cement rule.
- **Everywhere else follows:** the acting banner ("You may sign for the Director …, as an authorised signatory"), S11 ("any officer on the authorised signatories list can sign (…)" for the Director; the list in "Who acts"), the queue, and the desk's button now reads "Verify and send for signature".
- **Seeds (fake names only):** `signatories@motie.test` (Dev Signatory Admin) keeps the list; `signer1@` and `signer2@motie.test` (Dev Signatory One, Two) are on it. The demo now has the Director sign case 1; case 2 is signed by Dev Signatory One while the Director is away; and case 9 is a verified cement letter waiting for the Minister or the PS.

**Files:** backend/alembic/versions/0040_authorised_signatories.py; backend/app/core/workflow/signatories.py (`acting_signatory()`, `add_signatory()`, `remove_signatory()`, `overview()`), signatory_router.py, service.py (`applicable()`, `_permitted()`, `change_status()`), queues.py, acting.py, history.py, models.py, schemas.py, succession.py (`presence()`); backend/app/core/documents/conditions.py (`not_equals`); backend/app/modules/etls/letter.py (`_signature()`, `build_fields()`, `preview_fields()`, `render_pdf()`), templates/facility_letter.txt; backend/app/dev_seed.py, demo_seed.py; backend/app/main.py; tests: backend/tests/core/test_signatories.py, test_signatory_race.py, backend/tests/modules/etls/test_signing_rules.py, plus the existing tests where the PS used to sign; frontend/app/staff/signatories/ (page.tsx, actions.ts), frontend/app/staff/layout.tsx, frontend/app/staff/absences/page.tsx, frontend/components/ActingBanner.tsx, frontend/components/staff/History.tsx, Actions.tsx, Signing.tsx, frontend/lib/types.ts, frontend/e2e/tests/s12-signatories.spec.ts, facility-letter.spec.ts.
**Try it:**
- `bash scripts/reset-dev.sh --yes` (migrates and seeds the new users), then http://localhost:3001 as `signatories@motie.test`: Signatories. Remove Dev Signatory Two and add them back; "Earlier signatories" keeps the removal.
- `bash scripts/seed-demo.sh --yes`, then log in as `signer1@motie.test`: the banner, and case 0003 in My queue. Sign it, then log in as `signer2@motie.test`: it's gone from their queue. As `ps@motie.test`: case 0008 (cement) is there; as `director@motie.test` it isn't.
- `docker compose run --rm tools pytest tests/core/test_signatories.py tests/core/test_signatory_race.py tests/modules/etls/test_signing_rules.py -v`
- `docker compose run --rm e2e npx playwright test tests/s12-signatories.spec.ts`
**New concepts:** [Named signatories instead of a successor post](#named-signatories-instead-of-a-successor-post), Moves that apply only to some cases (removed in 10b, with the cement rule), [Separation of duties](#separation-of-duties). Also see [Row locking](#row-locking-select--for-update) for "first to act claims it".

### Step 9k — Demo data: `scripts/seed-demo.sh` (2026-10-26)
For the Ministry demo. Development only.

**Built:**
- **`bash scripts/seed-demo.sh`** (add `--yes` to skip the prompt): refuses unless `.env` says `APP_ENV=development`; runs `scripts/reset-dev.sh` (a fresh database, documents volume and dev users); then runs `python -m app.demo_seed` in the `tools` container, which refuses too if `APP_ENV` isn't development.
- **Three fictional importers** (`fatou.jallow@`, `lamin.ceesay@`, `awa.touray@demo.test`, the dev password) and **eight fictional facility letter cases**, one per stage:

  | Reference | Stage |
  | --- | --- |
  | FL/2026/0001 | Sent to GRA (the whole route) |
  | FL/2026/0002 | Signed by the **DPS acting for the PS**, who is recorded as away for three days; waiting for Records to dispatch |
  | FL/2026/0003 | Verified, waiting for signature (the PS or, while the PS is away, the DPS) |
  | FL/2026/0004 | At the desk: cement, so the receipt question is open until the code is confirmed |
  | FL/2026/0005 | Returned by Records: "The invoice scan is unreadable…" |
  | FL/2026/0006 | At the desk, **on hold**: the same certificate number as 0001 |
  | FL/2026/0007 | Submitted, waiting for Records |
  | (no reference) | A half-filled draft |
- **Made through the API, as the real people.** The seed logs in as the applicant, Records, the desk, the PS and the DPS and makes each move, so references, histories ("acting for the Permanent Secretary"), audit rows and outbox emails are exactly what real use gives. Uploaded documents are one-page PDFs that say "DEMO DOCUMENT. Fictional".
- It prints the cases with their references and every demo login with the password.
- The PS's absence is left in place, so the demo can show the acting banner (log in as the DPS) and S11's "Who acts". End it from S11 as the PS ("End early") if you'd rather not.
- **Fixed while looking at the demo:** the applicant's "Action needed … Fix and resubmit" notice was squashed into the centre (frontend/app/globals.css, `.notice.spread`).

**Files:** scripts/seed-demo.sh, backend/app/demo_seed.py (`seed_users()`, `seed_cases()`, `Demo`), backend/tests/test_demo_seed.py, frontend/app/globals.css, CLAUDE.md (commands)
**Try it:**
- `bash scripts/seed-demo.sh --yes`, then http://localhost:3001: as `records@motie.test` (My queue and Outgoing), `desk@motie.test` (0004 and 0006), `dps@motie.test` (the banner; 0003 to sign), `awa.touray@demo.test` (the returned case).
- `docker compose run --rm tools pytest tests/test_demo_seed.py -v` runs the whole seed against the test database (rolled back afterwards) and checks each case's stage.
**New concepts:** none; see [Disposable dev environments (reset and seed)](#disposable-dev-environments-reset-and-seed).

### Step 9j — Exporter countries and units are fixed lists an admin keeps `[CONFIRM]` (2026-10-26)
A change to A2 (9c).

**Built:**
- **Two lists as data**, `etls.countries` and `etls.units` (migration 0039): a name, whether it's offered (`active`), and its place in the list. Seeded with:
  - countries: Benin, Cabo Verde, Côte d’Ivoire, Ghana, Guinea, Guinea-Bissau, Liberia, Nigeria, Senegal, Sierra Leone, Togo. How goods from Burkina Faso, Mali and Niger are treated is `[CONFIRM]`; they're not on the list for now.
  - units: bags, cartons, tonnes, kg, litres, pieces `[CONFIRM]`.
- **The form's Country and Unit are select boxes** fed by **`GET /etls/form-options`** (active entries, in order).
- **The API checks them** (backend/app/modules/etls/choices.py):
  - on every save (new draft, change, walk-in): a value that isn't an active entry is refused with 422, naming the field ("Exporter's country: 'Mali' isn't on the Ministry's list"). Case doesn't matter: "ghana" is stored as "Ghana". Empty is still fine on a draft.
  - on Submit: if an entry was switched off after the draft was saved, Submit is blocked: "Unit 'tonnes' is no longer on the Ministry's list: choose another". The form shows the old value as "(no longer on the list)" so it isn't silently lost.
- **Admins keep the lists** on the new **Lists** screen (`/staff/lists`, in the menu for the `admin` role only): rename, switch off or back on, add (at the end). The endpoints are `GET /etls/lists`, `POST /etls/lists/{countries|units}` and `PATCH /etls/lists/{kind}/{id}` (`name` and/or `active`). Each change writes an audit row (`etls.list_item_added`, `etls.list_item_changed`).
- **No deleting.** The app's database user has no DELETE on these tables; an entry is switched off instead. Applications keep the name as text, so renaming or switching off an entry never changes what an earlier applicant wrote.
- Names are unique ignoring case (a unique index on `lower(name)`), with no spaces at either end (a check constraint).
- New error type `InvalidValue` (422) in backend/app/core/workflow/errors.py.

**Files:** backend/alembic/versions/0039_etls_choice_lists.py, backend/app/modules/etls/choices.py (`clean_form()`, `list_gaps()`, `add_item()`, `change_item()`), backend/app/modules/etls/models.py (`Country`, `Unit`), backend/app/modules/etls/service.py (`create_draft()`, `update_form()`, `open_walk_in()`, `_check_form_complete()`), backend/app/modules/etls/router.py, backend/app/modules/etls/schemas.py, backend/app/core/workflow/errors.py, backend/app/core/workflow/router.py, backend/tests/modules/etls/test_choice_lists.py, frontend/app/applications/ApplicationForm.tsx (`Choice`), frontend/app/applications/new/page.tsx, frontend/app/applications/[id]/edit/page.tsx, frontend/app/staff/lists/ (page.tsx, actions.ts), frontend/app/staff/layout.tsx, frontend/e2e/tests/lists.spec.ts, frontend/e2e/tests/facility-letter.spec.ts
**Try it:**
- `docker compose run --rm tools alembic upgrade head`, then log in as `admin@motie.test` and open Lists. Add "drums" to Units.
- As `applicant@motie.test`, start an application: Unit offers "drums". Save a draft with it. Back as the admin, switch "drums" off: the applicant's Submit now says to choose another unit.
- `docker compose run --rm tools pytest tests/modules/etls/test_choice_lists.py -v` and `docker compose run --rm e2e npx playwright test tests/lists.spec.ts`
**New concepts:** Reference lists as data (switch off, never delete)

### Step 9i — S11: "Who acts" and "Recorded by" in the absences list (2026-10-26)
A follow-up to 9g, as in docs/design/Absences.dc.html.

**Built:**
- **Two new columns** in "Current and upcoming absences" (frontend/app/staff/absences/page.tsx):
  - **Who acts:** for each stand-in, the post, the people at work in it, and why: "Deputy Permanent Secretary, Administration and Finance (Dev Deputy PS), succession", or "Permanent Secretary (Dev Permanent Secretary), delegation, for ETLS application". When the answer differs by service, there's a line per stand-in naming the services. If nobody in the succession order is at work, it says so in orange.
  - **Recorded by:** "Themselves", or the name of the recorder who entered it.
- **`GET /absences/current`** gives each row `who_acts` (`position`, `title`, `holders`, `basis`, `workflows`), `recorded_by` and `recorded_by_self`.
- **Who acts follows the engine's rules,** worked out for the absence's **first day** (or today, if it has already started):
  1. if another holder of the same post is at work, they carry on ("same post");
  2. otherwise a delegation from the post in force that day, for that service, comes first;
  3. otherwise the first post in the succession order with a holder at work that day. A stand-in who is away too is skipped.
  The page says that it's the first day's answer: an absence or delegation recorded later can change who acts on the following days.

**Files:** backend/app/core/workflow/acting.py (`current_absences()`, `_who_acts()`, `_away_on()`, `WhoActs`), backend/app/core/workflow/schemas.py (`WhoActsOut`), backend/tests/core/test_acting_views.py, frontend/app/staff/absences/page.tsx (`WhoActs`), frontend/lib/types.ts, frontend/e2e/tests/s11-absences.spec.ts
**Try it:**
- As `ps@motie.test`, record an absence: the row says the DPS acts, by succession, and "Themselves".
- As `dps@motie.test`, record an absence for today only; then as the PS, one starting the day after tomorrow. The PS's row still names the DPS, who is back by then. Record the PS's absence for today instead: the DPS is skipped.
- `docker compose run --rm tools pytest tests/core/test_acting_views.py -v` and `docker compose run --rm e2e npx playwright test tests/s11-absences.spec.ts`
**New concepts:** none; see [Succession (acting for an absent post)](#succession-acting-for-an-absent-post).

### Step 9h — Browser walk-throughs with Playwright; chunk 2 is done (2026-10-26)
Chunk 2, step 9, part 8 of 8.

**Built:**
- **frontend/e2e/**, end-to-end tests that drive a real Chromium through the running app, the way people will:
  - **tests/facility-letter.spec.ts**: the applicant fills in the form, saves, sees Submit disabled with "Invoice is missing", uploads the five documents and submits. Records ticks the original certificate and accepts. The desk confirms the HS code, ticks the ECOWAS list and verifies. The PS reads the checks and the preview and signs. Records downloads the letter (checks it's a PDF) and marks it sent to GRA. The applicant sees **"Letter sent to GRA"** on A1 and on the phone page A3.
  - **tests/s11-absences.spec.ts**: the PS records an absence, the DPS sees the acting banner (and not the reason), the PS ends it early and the banner goes; the Minister delegates to the PS for one service and revokes it; the recorder records and cancels an absence for the Director. Each test ends what it started.
- **The Compose service `e2e`** (profile `tools`) runs them against `http://web:3000`. Its image (frontend/e2e/Dockerfile) holds only Chromium's headless shell, about a quarter of the size of Microsoft's image with every browser.
- **What the walk-through found, fixed in the steps above before committing:** the desk's checks and the PS's signing view were written but never shown in the case panel; two confirmations vanished with the button or row they were in (9d); the HS code showed as bare digits (9b); a select box's name included its chosen option (9g); and port 3000 was taken on this machine (9a).
- Each run makes new cases with a unique certificate number, so runs don't trip the duplicate flag. They pile up in the dev database; `bash scripts/reset-dev.sh` clears them.

**Files:** frontend/e2e/package.json (`@playwright/test` 1.64.0), frontend/e2e/Dockerfile, frontend/e2e/playwright.config.ts, frontend/e2e/tests/helpers.ts (`loginAs()`, `pdf()`), frontend/e2e/tests/facility-letter.spec.ts, frontend/e2e/tests/s11-absences.spec.ts, docker-compose.yml (`e2e`), docs/GAPS.md (chunk 2 done), CLAUDE.md (commands)
**Try it:**
- `docker compose up -d web`, then `docker compose run --rm e2e`. The first run takes a few minutes while `next dev` compiles each page.
- After a failure: screenshots and a trace are in frontend/e2e/test-results/. Open frontend/e2e/playwright-report/index.html in your browser, or drag a trace.zip onto https://trace.playwright.dev to replay the run step by step.
- One file only: `docker compose run --rm e2e npx playwright test tests/s11-absences.spec.ts`
**Chunk 2 is done:** the facility letter screens work end to end. Next is chunk 3 in docs/GAPS.md (ETLS approval: A4, A5, S4–S8).
**New concepts:** End-to-end tests in a real browser

### Step 9g — Staff screen S11: absences and delegations (2026-10-26)
Chunk 2, step 9, part 7 of 8.

**Built:**
- **`/staff/absences`** (docs/design/Absences.dc.html), "Absences" in the staff menu:
  - **I will be away** (for anyone holding a post): who acts for me under the succession order, per service, with the names of the people holding each post (`GET /acting/for-me`); my current and upcoming delegations, each with **Revoke**; and the form: from, to, reason (optional, seen only by me and the recorders), and **"Or delegate to a different post"** (default "No, use the succession order") for all services or one.
  - **Record for someone else** (only with the `absence_recorder` role `[CONFIRM]`): pick "post: person", dates and reason. The audit row records who entered it (step 5c).
  - **Current and upcoming absences** for all staff (`GET /absences/current`): who, post, dates, the reason where I may see it, and **Cancel** (not started yet) or **End early** (already started) where I may.
- **Two small backend additions:**
  - **`GET /acting/options`** (staff only): every post with its holders (`user_id`, name), sorted by title, and every workflow with its name. It's what the form's select boxes list. Applicants get 403, since it says who holds which post.
  - **`may_cancel`** on each row of `GET /absences/current`: true for my own absence and for recorders, the same rule as `cancel_absence()`. So the screen offers Cancel only where it will work.
- **Recording with a delegation makes two calls**, delegation first, then absence. If the delegation is refused (say, the dates are wrong), nothing is recorded and the form shows why.
- The select boxes have their own `<label for>`: wrapped in the label, browsers read the chosen option as part of the box's name ("For All services"), which confuses screen readers.

**Files:** frontend/app/staff/absences/page.tsx, frontend/app/staff/absences/actions.ts (`recordMyAbsence()`, `recordAbsenceFor()`, `cancelAbsence()`, `revokeDelegation()`), frontend/app/staff/layout.tsx, frontend/lib/types.ts, frontend/app/globals.css (`.visually-hidden`), backend/app/core/workflow/acting.py (`choices()`, `AbsenceView.may_cancel`), backend/app/core/workflow/acting_router.py, backend/app/core/workflow/schemas.py (`ChoicesOut`), backend/tests/core/test_acting_views.py
**Try it:**
- As `ps@motie.test`, Absences: record today to the day after tomorrow. Log in as `dps@motie.test`: the acting banner is on every page, and the PS's row has no Cancel for them. Back as the PS, "End early".
- As `minister@motie.test`, delegate to the Permanent Secretary for "ETLS application": the delegation shows with Revoke.
- As `recorder@motie.test` (no post of their own): only "Record for someone else" and the list.
- `docker compose run --rm tools pytest tests/core/test_acting_views.py -v`
**New concepts:** none; see [Succession (acting for an absent post)](#succession-acting-for-an-absent-post) and [Delegation (acting on behalf of)](#delegation-acting-on-behalf-of).

### Step 9f — Staff screen S3: the PS signs the letter (2026-10-26)
Chunk 2, step 9, part 6 of 8.

**Built** (frontend/components/staff/Signing.tsx, docs/design/PS.dc.html), in the case panel for whoever can Sign:
- **Checks done**, each with ✓ or ✗ (`GET /etls/facility-letters/{id}/checks`): originals seen (by whom, when), the ECOWAS ticks (by whom), duplicate flags and how they were cleared, the HS code and who confirmed it, each certificate's validity, and any missing documents.
- **The letter preview** in the Ministry's wording, in the page and as a link to open it alone (`/files/etls/facility-letters/{id}/letter-preview.pdf`). It's rendered on request and marked "DRAFT FOR CHECKING - NOT SIGNED"; nothing is stored until Sign.
- **"Sign letter"** stores the letter (8f). On a production server without the registry reference, Sign is disabled with the reason (8k). **"Return to desk"** needs a minute.
- After signing, the case leaves the PS's queue and appears on Records' Outgoing tab.

**Files:** frontend/components/staff/Signing.tsx, frontend/components/staff/CasePanel.tsx (`canSign`)
**Try it:**
- Take a case through the desk (9e) and log in as `ps@motie.test`: the checks, the preview, then "Sign letter". Log in as `records@motie.test`: Outgoing shows it with "Download PDF".
- Return one to the desk without a minute: the API's "a reason is required" appears above the buttons.
**New concepts:** none.

### Step 9e — Staff screen S2: the ETLS desk's checks (2026-10-26)
Chunk 2, step 9, part 5 of 8.

**Built** (frontend/components/staff/DeskChecks.tsx, docs/design/Desk.dc.html), in the case panel for whoever can Verify:
- **On hold:** an open duplicate-certificate flag shows its message and the earlier cases using the same number, each with its reference (a link to it), importer, status and date (`GET /etls/facility-letters/{id}/duplicates`). "Clear flag and continue" needs a written finding (`POST /cases/{id}/flags/{flag_id}/resolve`). Or the desk rejects or returns the application below, and that reason clears the flag (8d, 8l).
- **HS code:** the applicant's code (or "Applicant left this blank") in a box to confirm or correct (`POST /etls/facility-letters/{id}/hs-code`), and whether the cement receipt is needed for it: "decided once you confirm the code" until then.
- **The ECOWAS ETLS list ticks**, each a recorded statement with "Mark as checked" or "Undo" (`PUT /cases/{id}/checklist/{code}`).
- **"Verify and send to PS"** stays disabled, with the reasons under it, until the flag is cleared, the code confirmed, both ticks done, the documents complete and the certificates within six months (all from `blocked_by`). "Return to applicant" and "Reject application" (red) sit beside it.

**Files:** frontend/components/staff/DeskChecks.tsx, frontend/components/staff/CasePanel.tsx (`canVerify`), frontend/app/staff/actions.ts (`resolveFlag()`, `confirmHsCode()`, `setTick()`)
**Try it:**
- Take a case past Records (9d), log in as `desk@motie.test` and open it. Verify lists four reasons; confirm the code and tick both lines, and it's enabled.
- Submit two applications with the same certificate number and accept both at Records: the second opens at the desk "On hold" with a link to the first.
**New concepts:** none; see [Recorded ticks (attestations)](#recorded-ticks-attestations) and [Three answers: yes, no, not known yet](#three-answers-yes-no-not-known-yet).

### Step 9d — Staff screens: the queue, the case panel, and S1 (Records, with Outgoing) (2026-10-26)
Chunk 2, step 9, part 4 of 8.

**Built:**
- **The staff shell** (frontend/app/staff/layout.tsx): the header with my post ("Records Officer"), the **acting banner** on every staff page ("You are acting for the Permanent Secretary (Dev Permanent Secretary absent 26th–28th October)", from `GET /acting`), and the menu with counts.
- **My queue** (`/staff`, docs/design/Records.dc.html): every case where I can make a move now (`GET /cases/queue`), oldest first, with service, applicant, goods and days waiting (in orange from 2 days). The selected case opens beside it. The same screen serves Records, the desk and the PS: what the panel offers depends on what the API says this person may do.
- **The case panel** (frontend/components/staff/CasePanel.tsx): reference, importer, goods, exporter, the form summary, "this applicant has no email: tell them yourself" for walk-ins without one (8j), the documents with View links, the buttons, and the **history** (newest first, with names, posts and "acting for the ... (absent ...)").
- **The buttons** (frontend/components/staff/Actions.tsx) are the case's `available_actions`, one each. A blocked one is disabled and the reasons are written under it, starting "Accept: originals received isn’t possible yet: ...". One message box (to the applicant, for returns) and one minute box (staff only) serve all of them; the minute says which moves require it.
- **S1, Records:** "Original seen in person" next to each document whose original must be seen; once ticked, the button gives way to "✓ Original seen 26th October, 2026". Then "Accept: originals received" or "Return to applicant".
- **S1's Outgoing tab** (`/staff/outgoing`, RecordsOutgoing.dc.html): signed letters waiting to go to GRA (`GET /cases/queue?status=signed`), the signing date, "Download PDF" of the stored letter, and "Mark sent to GRA" with the dispatch date (today by default, never in the future). After marking, the page says "MOTIE/ETLS/FL/2026/0001 marked as sent to GRA on 26th October, 2026" and the row is gone. Signed letters are kept out of "My queue" so they aren't counted twice.
- **Downloads** go through `/files/...` (frontend/app/files/[...path]/route.ts), which adds the login and passes the file on. It only passes four exact path shapes (a document, the letter, the preview, an issued letter), so it can't be used to reach any other API endpoint.

**Files:** frontend/app/staff/layout.tsx, frontend/app/staff/page.tsx, frontend/app/staff/outgoing/page.tsx, frontend/app/staff/actions.ts (`moveCase()`, `markOriginalSeen()`, `markSentToGra()`), frontend/components/staff/CasePanel.tsx, frontend/components/staff/Actions.tsx, frontend/components/staff/Documents.tsx, frontend/components/staff/History.tsx, frontend/components/ActingBanner.tsx, frontend/components/NavLink.tsx, frontend/app/files/[...path]/route.ts
**Try it:**
- Submit an application as the applicant (9c), then log in as `records@motie.test`: it's in My queue. Accept is disabled and says why; tick "Original seen in person" and accept.
- As `ps@motie.test`, record an absence through the API (`POST /absences`); log in as `dps@motie.test` and the banner is on every page.
- In the browser, open `http://localhost:3001/files/auth/me`: 404, it's not one of the allowed paths.
**New concepts:** none; the screens show what [Blocking checks and warnings](#blocking-checks-and-warnings) and [Delegation (acting on behalf of)](#delegation-acting-on-behalf-of) already provide.

### Step 9c — Applicant screen A2: the facility letter form, uploads and submit (2026-10-26)
Chunk 2, step 9, part 3 of 8.

**Built:**
- **A2, the application** (`/applications/new`, then `/applications/{id}/edit`; docs/design/Apply.dc.html): 1. Importer, 2. Goods, 3. Exporter and approvals (with the certificates of origin and their issue dates), 4. Documents, then Submit.
- **Nothing is stored until "Save draft"**, so opening the form and leaving makes no empty application. Any box may be empty on a draft (step 8i); what *is* typed must have the right shape, and the API's 422 errors come back as one readable line next to the field's label ("Quantity: ..."), with what was typed put back in the boxes.
- **One spare row** for another product approval number or certificate. Fill it in and save, and a new spare row appears. No JavaScript is needed to add rows.
- "1,200" is accepted as a quantity (the commas are taken out before it goes to the API).
- **Documents:** one row per required document (`GET /cases/{id}/documents`), with Upload or Replace. The file goes through a server action to `POST /cases/{id}/documents/{type}`, which checks the type from the content (PDF, PNG or JPEG) and the size (10 MB). The receipt for cement imports shows as "needed only in some cases" until the Ministry confirms the HS code. The certificate of origin says "Bring the original to Records".
- **Submit** is disabled until nothing is missing, and lists what's still to do, straight from the Submit action's `blocked_by` ("Invoice is missing", "Quantity is missing"). The 30-day expiry warning (step 8c) shows as "Please note".
- A **returned** case opens in the same form with the Ministry's message on top, and the button reads "Resubmit application". Once submitted, the edit page sends the applicant to the status page.
- Country and unit boxes suggest values (Senegal, Ghana…; bags, tonnes…) but take any text, as the API does. `[CONFIRM]` whether these should become fixed lists.

**Files:** frontend/app/applications/ApplicationForm.tsx, frontend/app/applications/actions.ts (`saveDraft()`, `uploadDocument()`, `submitApplication()`), frontend/app/applications/new/page.tsx, frontend/app/applications/[id]/edit/page.tsx, frontend/lib/api.ts (`FIELD_LABELS`, `errorText()`)
**Try it:**
- As `applicant@motie.test`: "Apply for a facility letter", type a product only, "Save draft". The Submit box lists everything still missing.
- Type `abc` as the quantity and save: "Not saved. Quantity: ..." and your other boxes keep what you typed.
- Fill everything in, upload five small PDFs, and submit: A1 shows the new reference, `MOTIE/ETLS/FL/2026/....`
- Try uploading a .txt renamed to .pdf: the API refuses it.
**New concepts:** none; it's [Drafts and submission](#drafts-and-submission) and [Blocking checks and warnings](#blocking-checks-and-warnings) on a screen.

### Step 9b — Applicant screens A1 and A3: my applications and the status page (2026-10-26)
Chunk 2, step 9, part 2 of 8.

**Built:**
- **A1, "ETLS services"** (`/applications`, docs/design/Main.dc.html): the three services (only the facility letter is live; the other two say "Coming soon"), any case returned to me with the Ministry's message and "Fix and resubmit", the table of my cases (`GET /cases`), and the selected case's timeline beside it.
- **A3, one case on a phone** (`/applications/{id}`, Track.dc.html): the status in plain words with its explanation and any message, the timeline, and a link to continue a draft or fix a returned case.
- **The timeline** (frontend/components/Timeline.tsx) shows the steps taken with their dates (`GET /cases/{id}/timeline`), the current one, and the usual steps still ahead, greyed out. The API only knows what has happened; the steps ahead are a fixed list in frontend/lib/labels.ts (`FACILITY_LETTER_STEPS`). A returned or rejected case shows no steps ahead.
- Only applicant labels are shown: never the internal status names or staff names (the API gives applicants `null` for those anyway, step 7a).
- Staff who open `/applications` are sent to `/staff`, and applicants who open `/staff` to `/applications` (`requireUser()`); the API still checks every call.
- `hsCode()` in frontend/lib/labels.ts writes the API's digits the way people do ("230990" → "2309.90"), for the screens that follow.

**Files:** frontend/app/applications/layout.tsx, frontend/app/applications/page.tsx, frontend/app/applications/[id]/page.tsx, frontend/components/Timeline.tsx, frontend/lib/labels.ts (`stepsAhead()`, `pillClass()`, `goods()`, `hsCode()`), frontend/lib/labels.test.ts
**Try it:**
- Log in as `applicant@motie.test` at http://localhost:3001. With no cases yet, A1 says so. After step 9c you can make one; meanwhile, any case made through the API shows up.
- Make the window narrow (or use the browser's phone view) and open a case's "Open on its own page".
- `docker compose run --rm --no-deps web npm test` (the HS code formatter).
**New concepts:** none.

### Step 9a — The frontend starts: login, set-password, dates (2026-10-26)
Chunk 2, step 9 (the frontend), part 1 of 8.

**Built:**
- **A Next.js app in frontend/**, run by the new Compose service **`web`** at **http://localhost:3001**. That's port 3001 on your machine because 3000 is often taken by other Node projects (it was here). Inside Compose it's still `web:3000`, and it calls the API as `http://api:8000`.
- **The browser never talks to the API.** Pages and forms run on the Next.js server (server components and server actions), which calls the API with the login token. The token lives in an **httpOnly cookie** (`motie_session`) that page scripts can't read. To the API, Next.js is just another client.
- **Login** (`/login`): email and password go to `POST /auth/login`; the token goes in the cookie for 60 minutes, as long as the token lasts. When it runs out, the next page sends you back to `/login?expired=1` with "Your session ended".
- **Set your password** (`/set-password`): the page walk-in applicants reach from their email (step 8j). A script in the browser reads the token after `#`, takes it out of the address bar at once, and the form sends it to `POST /auth/set-password`.
- **`/`** sends applicants to their applications and staff to their queue (those screens come in 9b and 9d).
- **Dates the Ministry's way** in frontend/lib/dates.ts: `longDate()` ("16th October, 2026") follows the same rules as `long_date()` in backend/app/core/dates.py, with the same test cases. Also `dayRange()` for absences ("20th–24th October") and `shortDateTime()` for history lines.
- **`GET /auth/me` now gives `position_titles`** next to the position codes, for the header ("Records Officer").
- The look follows docs/design (navy bar, cream page, IBM Plex Sans and Source Serif 4, 44px touch targets), in frontend/app/globals.css. The fonts are downloaded at build time and served by this site, so browsers make no request to Google.
- Security headers on every page: no framing by other sites (`X-Frame-Options`), no MIME sniffing, no full URL in the referrer.

**Files:** frontend/package.json, frontend/Dockerfile, frontend/next.config.mjs, frontend/app/layout.tsx, frontend/app/globals.css, frontend/app/page.tsx, frontend/app/login/ (page.tsx, actions.ts), frontend/app/set-password/ (page.tsx, SetPasswordForm.tsx, actions.ts), frontend/lib/api.ts (`api()`, `apiFetch()`), frontend/lib/session.ts (`startSession()`, `requireUser()`), frontend/lib/forms.ts, frontend/lib/dates.ts, frontend/lib/dates.test.ts, frontend/components/TopBar.tsx, frontend/components/ActionForm.tsx, docker-compose.yml (`web`), .env.example (`PUBLIC_BASE_URL` is now port 3001), backend/app/core/identity/router.py, backend/app/core/identity/schemas.py, backend/tests/core/test_auth.py
**Try it:**
- `docker compose up -d web` and open http://localhost:3001. Log in as `records@motie.test` (password in backend/app/dev_seed.py).
- In the browser's developer tools, Application → Cookies: `motie_session` is marked HttpOnly. Type `document.cookie` in the console: it isn't there.
- Typecheck and unit tests: `docker compose run --rm --no-deps web sh -c "npm run typecheck && npm test"`
**New concepts:** Server components and server actions, A login cookie the browser can't read

### Step 8m — Sent emails lose their password link (2026-10-25)
A follow-up to 8j.

**Built:**
- **Once a "set your password" email is sent, its stored copy no longer has the link.** A database trigger on `core.notifications` (`notifications_scrub_link_on_send`) replaces the link with "[link removed after sending]" in the same UPDATE that marks the row sent. The applicant's email went out with the working link; only the database's copy changes.
- **Waiting or failed emails keep the link**, so a retry still sends one that works.
- **Unsent emails whose link has expired are scrubbed too** ("[link removed after it expired]"), by the function `core.scrub_expired_password_links()`. The worker calls it at the start of each round (`scrub_expired_links()`), and no longer sends such emails: an expired link is no use to anyone.
- `core.notifications.password_link_id` says which link an email carries, so the database knows which rows to scrub. Migration 0038 fills it in for links sent before, and scrubs those already sent.
- **The app still can't rewrite an email.** It has no UPDATE on `body`. The trigger and the function belong to the schema owner and can only remove a link.

**Files:** backend/alembic/versions/0038_scrub_sent_links.py, backend/app/core/notifications/worker.py (`scrub_expired_links()`, `send_pending()`), backend/app/core/notifications/models.py, backend/app/core/identity/password_links.py (`issue_link()`), backend/tests/core/test_password_links.py
**Try it:**
- Open a walk-in with a new email as `records@motie.test`. `SELECT body FROM core.notifications ORDER BY id DESC LIMIT 1;` shows the link.
- `docker compose run --rm tools python -m app.core.notifications.worker --once`; the log shows the email went (the fake sender), and the same SELECT now shows "[link removed after sending]".
- `docker compose run --rm tools pytest tests/core/test_password_links.py -v`
**New concepts:** SECURITY DEFINER functions

### Step 8l — The desk may return a flagged case, not only reject it (2026-10-25)
A change to chunk 2, step 4 (8d). `[CONFIRM]` with the ETLS desk.

**Built:**
- The desk's **"Return to applicant"** (`originals_received → returned`) is now allowed while a duplicate certificate flag holds the case, like Reject (`allowed_on_hold`, migration 0037). Its action's `blocked_by` no longer says "On hold".
- As with Reject, the engine **resolves the flag with the move's reason**: the internal minute, or else the message to the applicant. It's recorded as "Return to applicant: ...", with `by_move` in the audit row. The applicant sees only the message, as before.
- **When the applicant resubmits, the duplicate check runs again** (the Submit effect `etls_check_duplicate_certificates`, unchanged). If the number is still used on another case, a new flag holds the case at the desk again. If the applicant typed in a different, unused number, no flag is raised.
- Verify is still held by an open flag.
- No engine code changed: it's one column on one row. The engine already did the rest for Reject.

**Files:** backend/alembic/versions/0037_return_while_held.py, backend/tests/modules/etls/test_desk_checks.py
**Try it:**
- Submit two applications with the same certificate number, and take the second to the desk. As `desk@motie.test`, `GET /cases/{id}`: "Return to applicant" has an empty `blocked_by`; "Verify" says "On hold: ...".
- Return it with a message and a minute; `GET /cases/{id}/flags` shows it resolved as "Return to applicant: ...".
- Resubmit it unchanged as the applicant: `GET /cases/{id}/flags` has a new open flag.
- `docker compose run --rm tools pytest tests/modules/etls/test_desk_checks.py -v`
**New concepts:** none.

### Step 8k — A real server can't sign until the registry reference is set (2026-10-25)
A fix to chunk 2, step 5 (8e).

**Built:**
- **`FACILITY_LETTER_REFERENCE_FORMAT` has no default any more.** Read it through `settings.registry_reference_format()` in backend/app/core/config.py:
  - if it's set, that's it;
  - if not, and `APP_ENV=development`, the spec's example `ADM 151/420/01/PART IV` (`DEV_REGISTRY_REFERENCE`), as before;
  - if not, and `APP_ENV=production`, nothing.
  An empty value counts as not set.
- **Signing is blocked on a production server without it.** The new check `etls_registry_reference_set` on the PS's Sign move (migration 0036) shows in the Sign action's `blocked_by`: "the Ministry's registry file reference isn't set on this server (FACILITY_LETTER_REFERENCE_FORMAT); ask the system administrator". The move itself gets 409 with the same text. `file_reference()` refuses too, as a last guard.
- The **preview** still works, printing "[REGISTRY FILE REFERENCE NOT SET]" where the reference goes, so the PS can read the letter meanwhile.
- **Found while building, and fixed:** the `api` container never received `APP_ENV` from `.env`, so it always ran as "production". docker-compose.yml now passes `APP_ENV` and `FACILITY_LETTER_REFERENCE_FORMAT` to it. Check with `docker compose config api`.
- Tests no longer depend on your `.env`: an autouse fixture `registry_reference` in backend/tests/conftest.py sets the example reference, and backend/tests/modules/etls/test_registry_reference.py tests the production behaviour explicitly.

**Files:** backend/alembic/versions/0036_registry_reference_check.py, backend/app/core/config.py (`registry_reference_format()`, `DEV_REGISTRY_REFERENCE`), backend/app/modules/etls/letter.py (`file_reference()`, `_check_registry_reference_set()`), docker-compose.yml, .env.example, backend/tests/conftest.py, backend/tests/modules/etls/test_registry_reference.py
**Try it:**
- Set `APP_ENV=production` in `.env` (dev only, and put it back afterwards!), leave `FACILITY_LETTER_REFERENCE_FORMAT` empty, `docker compose up -d api`. Take a case to "Verified": as `ps@motie.test`, `GET /cases/{id}` shows the reason on Sign.
- Add `FACILITY_LETTER_REFERENCE_FORMAT=ADM 151/420/01/PART IV` to `.env`, `docker compose up -d api` again, and Sign works.
- `docker compose run --rm tools pytest tests/modules/etls/test_registry_reference.py -v`
**New concepts:** none; it's [Blocking checks and warnings](#blocking-checks-and-warnings) again, with a setting as what's checked.

### Step 8j — Walk-in applicants set their own password from an emailed link (2026-10-25)
A fix to chunk 2, step 7 (8g).

**Built:**
- **A walk-in account has no password at all** until the applicant sets one. Before, it got a random password nobody knew. Now `core.users.password_hash` is empty, so "can't log in" is a fact in the database, not a secret. Login refuses such an account, with the same 401 and the same timing as a wrong password. Migration 0035 empties the random passwords of walk-in accounts made before now (nobody ever knew them).
- **"Set your password" links** (backend/app/core/identity/password_links.py):
  - When Records opens a walk-in for an email with no account, or for an account that still has no password, `issue_link()` makes a random token. It stores only the token's **SHA-256 hash** in the new table `core.password_links`, and puts an email with the link in the outbox (`core.notifications`), in the same transaction as the case. The fake sender logs it as usual.
  - The link is `PUBLIC_BASE_URL/set-password#token=...`. The token goes after `#`, so browsers never send it to a server: it can't end up in a log.
  - **`POST /auth/set-password`** with `{"token", "password"}` (no login needed) sets the password; then the applicant logs in as usual. Returns 204.
  - A link works **once** (`used_at`). It **expires** after `PASSWORD_LINK_HOURS` (72 by default) `[CONFIRM]`. A newer link for the same account **ends the older ones** (`revoked_at`). Unknown, used, replaced and expired links all get the same 400 ("This link doesn't work any more. Ask the Ministry for a new one."). A too-short password is refused (422) *before* the link is used up.
  - Audit rows: `user.password_link_sent` (who sent it, where, until when; never the token) and `user.password_set`.
- **Walk-ins with no email.** `applicant_email` may be left out or empty. The account then has no email and no password: it can't log in, and the engine writes no emails for it. Records finishes the application and tells the applicant of each step. Staff see **`applicant_emailed: false`** on `GET /cases/{id}`, so the screen can say "Tell the applicant yourself". There's nothing to match such applicants by, so each walk-in without email makes a new account.
- `docker-compose.yml` now passes `PUBLIC_BASE_URL` and `PASSWORD_LINK_HOURS` to the API (see .env.example).

**Files:** backend/alembic/versions/0035_password_links.py, backend/app/core/identity/password_links.py (`issue_link()`, `set_password()`), backend/app/core/identity/models.py (`PasswordLink`), backend/app/core/identity/service.py (`create_user()`, `authenticate()`, `check_password_strength()`), backend/app/core/identity/router.py, backend/app/core/identity/schemas.py, backend/app/core/notifications/service.py, backend/app/core/workflow/router.py (`case_out()`), backend/app/core/workflow/schemas.py, backend/app/core/config.py, backend/app/modules/etls/service.py (`open_walk_in()`), backend/app/modules/etls/schemas.py, docker-compose.yml, .env.example, backend/tests/core/test_password_links.py, backend/tests/modules/etls/test_walk_ins.py
**Try it:**
- As `records@motie.test`, `POST /etls/facility-letters/walk-in` with a new email. Read the link from the database: `SELECT body FROM core.notifications ORDER BY id DESC LIMIT 1;`
- `POST /auth/set-password` with the part after `#token=` and a password of 12+ characters: 204. Log in with the email and that password. Try the same token again: 400.
- Open a walk-in with `"applicant_email": null`: `GET /cases/{id}` as Records shows `"applicant_emailed": false`.
- `docker compose run --rm tools pytest tests/core/test_password_links.py tests/modules/etls/test_walk_ins.py -v`
**New concepts:** Single-use, expiring links

### Step 8i — Drafts can be saved half-filled (2026-10-25)
A fix to chunk 2, step 1 (8a).

**Built:**
- **Any field may be empty on a draft.** `POST` and `PUT /etls/facility-letters` accept a form with gaps, even `{}`. An empty box (`""` or spaces) is saved as "not filled in" (`null`), not refused. What *is* given must still have the right shape: a quantity above 0 with at most 3 decimals, a real HS code, no number listed twice, no certificate dated in the future, no certificate date without its number. Those are still 422.
- A certificate of origin on a draft may have its number but no issue date yet.
- **Submit checks the form is complete.** The new check `etls_form_complete` on Submit and Resubmit lists every gap in the action's `blocked_by`, in the form's order, next to the missing documents: "Quantity is missing", "Issue date of certificate of origin CO-9 is missing", "Invoice is missing". The screen counts them, as before. Pressing Submit anyway gives 409 with the same list. The HS code is still not required: the applicant may leave it to the desk.
- So nothing after Submit has an empty field: Records, the desk and the letter read a whole form, as before.
- The goods line in lists says what there is ("Cement, tonnes"), or "Not filled in yet".
- The letter preview refuses (409, with the gaps) on a half-filled draft, instead of failing.

**Files:** backend/alembic/versions/0034_partial_drafts.py, backend/app/modules/etls/schemas.py (`FacilityLetterForm`, `Blank`), backend/app/modules/etls/service.py (`form_gaps()`, `_check_form_complete()`, `_goods()`), backend/app/modules/etls/models.py, backend/app/modules/etls/letter.py (`preview()`), backend/tests/modules/etls/test_partial_drafts.py, backend/tests/modules/etls/test_facility_letter.py, backend/tests/modules/etls/test_hs_code.py
**Try it:**
- As `applicant@motie.test`, `POST /etls/facility-letters` with `{"product": "Cement"}`: 201, a draft with mostly `null`s.
- `GET /cases/{id}`: the Submit action's `blocked_by` lists each empty field and each missing document.
- `PUT /etls/facility-letters/{id}` with the rest, upload the documents, and `blocked_by` is empty.
- `docker compose run --rm tools pytest tests/modules/etls/test_partial_drafts.py -v`
**New concepts:** none; it's [Drafts and submission](#drafts-and-submission) and [Blocking checks and warnings](#blocking-checks-and-warnings) used together.

### Docs — GRA and certificate validity at clearance is not confirmed (2026-10-25)
**Built:** nothing; a correction. The docs said the Ministry had confirmed that GRA needs the certificate of origin still valid on the day goods are cleared. It hadn't. What *is* decided stays as built: the desk's Verify is blocked once a certificate is more than six months past its issue date, and the applicant is warned at submission if one expires within 30 days. Whether GRA's own rule needs more (say, refusing a letter whose certificate expires before the goods arrive) is now an open question `[CONFIRM]`. Nothing in the code depended on it.
**Files:** docs/SCREENS.md (S2), docs/GAPS.md (C10, and the chunk 1 answers), docs/LEARNING.md (Decisions, Open questions)
**Try it:** read docs/GAPS.md C10.
**New concepts:** none.

### Step 8h — Emails to applicants, through an outbox (2026-10-25)
Chunk 2, step 8: the last backend step of chunk 2.

**Built** (backend/app/core/notifications/):
- **The outbox, `core.notifications`.** Every move calls `notify_applicant()` inside its own transaction. If the move added a line to the applicant's timeline, an email row is written: to the applicant's email, with the subject "MOTIE/ETLS/FL/2026/0001: Returned: action needed" and a body with the label, the status's explanation and any message to the applicant. Because the email is built from the timeline, it can only say what the timeline says. So hidden moves (cancelling a letter) and repeated labels send nothing, and internal minutes or staff names never appear. If the move fails, there's no email; if the email can't be written, there's no move.
- **The worker** (`python -m app.core.notifications.worker`, or the new Compose service **`notifier`**) sends due emails one at a time. Each row is locked while it's sent (`FOR UPDATE SKIP LOCKED`), then marked `sent_at`. A failure is recorded (`attempts`, `last_error`) and tried again after 1, 2, 4… minutes, up to 8 attempts.
- **Senders** (`sender.py`): one interface, and only a **fake sender** for now (`EMAIL_BACKEND=fake`, the default). It logs each email and sends nothing, until the Ministry's mail server is known `[CONFIRM]`.
- The app may add emails and record sending, but can't change an email's address or text (column grants; a test in test_db_privileges.py checks it).
- `TimelineEntry` gained `event_id` (internal only), so the engine can tell whether *this* move produced the timeline's newest line.
- **Found by the smoke test, and fixed:** run on its own, the worker only loaded the `Notification` model, so saving "sent" failed (`NoReferencedTableError`: its foreign keys point at tables it hadn't loaded). The tests import the whole app, which hid it. The worker now imports `app.models`, and `test_the_worker_starts_on_its_own` checks it in a fresh process.

**Files:** backend/alembic/versions/0033_notifications.py, backend/app/core/notifications/models.py, backend/app/core/notifications/service.py (`notify_applicant()`), backend/app/core/notifications/sender.py (`FakeSender`), backend/app/core/notifications/worker.py (`send_pending()`), backend/app/core/workflow/service.py (`change_status()`), backend/app/core/workflow/history.py, backend/app/core/config.py (`email_backend`, `notification_poll_seconds`), backend/app/models.py, docker-compose.yml (`notifier`), backend/tests/core/test_notifications.py
**Try it:**
- `docker compose up -d notifier`, submit an application, then `docker compose logs notifier`: "Email (not sent, fake sender) to applicant@motie.test: MOTIE/ETLS/FL/2026/0001: Submitted".
- In a database tool: `SELECT to_email, subject, sent_at, attempts FROM core.notifications ORDER BY id DESC;`
- Or once by hand: `docker compose run --rm tools python -m app.core.notifications.worker --once`
- `docker compose run --rm tools pytest tests/core/test_notifications.py -v`
**New concepts:** The outbox pattern, Background workers

**Chunk 2's backend is done.** Next is its frontend (GAPS.md chunk 2, step 9).

### Step 8g — Walk-in applicants (2026-10-25)
Chunk 2, step 7.

**Built:**
- **`POST /etls/facility-letters/walk-in`** with `{"applicant_email", "applicant_name", "form": {...}}`: Records starts a draft for someone who came in person.
  - The case belongs to the **applicant's account** (`created_by`): it's in their `GET /cases`, they'll be emailed (8h), and they can carry on online.
  - The new column **`cases.entered_by`** records the Records officer who typed it in. The `case.created` audit row has Records as its actor and `walk_in_for_user_id`.
  - If no account has that email, one is made with the applicant role and a random password nobody knows (audit row `user.created_for_walk_in`). *Since 8j: no password at all, and a "set your password" link is emailed.* An email belonging to staff, or to a deactivated account, is refused.
- **Who may open walk-ins is data:** `workflows.walk_in_position_id` (the Records post for facility letters). Others get 403, *before* any account is made.
- **Records can finish a walk-in.** `acts_as_applicant()` in backend/app/core/workflow/service.py now also lets holders of the walk-in post make the applicant's moves on a walk-in case (edit the draft, Submit, Resubmit), so a colleague can carry on. The move's audit row adds `for_applicant_user_id`. On an application the applicant started online, Records still can't edit or submit.
- `GET /cases` (my cases) also lists the walk-ins I entered.

**Files:** backend/alembic/versions/0032_walk_ins.py, backend/app/core/workflow/service.py (`acts_as_applicant()`, `may_open_walk_in()`, `open_case()`, `change_status()`), backend/app/core/workflow/models.py, backend/app/core/workflow/queues.py (`my_cases()`), backend/app/core/workflow/schemas.py, backend/app/core/workflow/router.py, backend/app/modules/etls/service.py (`open_walk_in()`, `create_draft()`), backend/app/modules/etls/schemas.py (`WalkInApplication`), backend/app/modules/etls/router.py, backend/tests/modules/etls/test_walk_ins.py
**Try it:**
- As `records@motie.test`, `POST /etls/facility-letters/walk-in` with a new email. `GET /cases/{id}`: `created_by` is the new applicant, `entered_by` is you.
- Upload the documents and submit it as Records; `GET /cases/{id}/history` shows Records as actor with `for_applicant_user_id`.
- As `applicant@motie.test`, a walk-in opened with your email appears in `GET /cases`.
- `docker compose run --rm tools pytest tests/modules/etls/test_walk_ins.py -v`
**New concepts:** none.

### Step 8f — What the PS needs before signing (2026-10-25)
Chunk 2, step 6.

**Built:**
- **`GET /etls/facility-letters/{id}/checks`** (staff): everything checked so far, read from the same records the moves check:
  - which originals were seen, by whom and when;
  - the ECOWAS list ticks, by whom;
  - the duplicate flags and their findings (empty when no number was used before);
  - the confirmed HS code and who confirmed it;
  - each certificate's expiry and whether it's valid today;
  - any document still missing.

  It's the "summary of checks done" on S3, and useful to the desk too.
- **`GET /etls/facility-letters/{id}/letter-preview.pdf`** (staff): the letter in the Ministry's wording as it would read if signed today. The signature line is the signing post (taken from the workflow's Sign move, not named in code) and no person's name. A boxed red line at the top says "DRAFT FOR CHECKING - NOT SIGNED - NOT VALID AS A FACILITY LETTER", and the PDF's subject says "Preview, not issued". It's made fresh on each request and **never stored**; the response says `Cache-Control: no-store` and `X-Letter-Status: preview`. Once a letter is signed, the preview refuses (409) and points to `letter.pdf`.
- **"Return to the desk"** (`verified → originals_received`) for the PS or whoever acts for the PS, with a required internal minute. Nothing is signed yet, so there's nothing to cancel. The desk's ticks stay, because the application didn't change.
- `build_fields()` in backend/app/modules/etls/letter.py was split so the signed letter and the preview share `_form_fields()`: a preview can never show different goods from what would be signed.

**Files:** backend/alembic/versions/0031_ps_return_to_desk.py, backend/app/modules/etls/letter.py (`preview()`, `preview_fields()`, `render_pdf(preview=True)`, `PREVIEW_MARK`), backend/app/modules/etls/service.py (`checks_summary()`), backend/app/modules/etls/router.py, backend/app/modules/etls/schemas.py (`ChecksSummaryOut`), backend/tests/modules/etls/test_ps_support.py
**Try it:**
- Take a case to "Verified". As `ps@motie.test`, `GET /etls/facility-letters/{id}/checks`, then open `/etls/facility-letters/{id}/letter-preview.pdf` in the browser (with your token): red box at the top.
- `POST /cases/{id}/status` with `{"to_status": "originals_received", "comment": "Check the quantity"}` returns it to the desk's queue.
- `docker compose run --rm tools pytest tests/modules/etls/test_ps_support.py -v`
**New concepts:** none.

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
- **Six-month check:** the desk's Verify is blocked if any certificate of origin is more than six months past its issue date. At submission the applicant is only *warned* if one expires within 30 days. (Corrected 2026-10-25: whether GRA needs it valid at clearance was *not* confirmed; it's an open question.)
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

### The outbox pattern
**What:** sending an email (or calling any outside system) can't be part of a database transaction. If you send first and the save then fails, the applicant was told about something that never happened. If you save first and the send fails, nobody is told. The **outbox** fixes this: the move writes "an email to send" as a row, *in the same transaction* as the status change, so both happen or neither does. Something else sends the rows afterwards and marks them sent. The email may go a few seconds late, or (after a crash) twice, but it's never lost and never about a move that didn't happen. It also keeps a slow mail server from slowing down the officer clicking "Return".
**Here:** `notify_applicant()` in backend/app/core/notifications/service.py, called from `change_status()` in backend/app/core/workflow/service.py; `send_pending()` in backend/app/core/notifications/worker.py.
**Learn more:** [microservices.io: Transactional outbox](https://microservices.io/patterns/data/transactional-outbox.html)

### Single-use, expiring links
**What:** a way to let someone prove "I can read this mailbox" without a password. You email them a link with a long random **token** in it; whoever brings the token back is treated as the owner of the email. Three habits make it safe:
- **Store only a hash of the token**, like a password. If someone copies the database, they can't use the links in it.
- **Make it work once and expire.** A link found later in an old email, a forwarded message or a shared computer is useless.
- **Keep it out of logs.** Put the token where browsers don't send it to servers (after `#`), and never write it in the audit log.

Because the token is 256 random bits, a plain SHA-256 hash is enough. Passwords need slow hashing (Argon2) because people choose guessable ones; nobody can guess a random token.
**Here:** `issue_link()` and `set_password()` in backend/app/core/identity/password_links.py; the table in backend/alembic/versions/0035_password_links.py; `POST /auth/set-password` in backend/app/core/identity/router.py.
**Learn more:** [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html) (the "URL tokens" part)

### SECURITY DEFINER functions
**What:** normally a database function runs with the rights of whoever calls it. A `SECURITY DEFINER` function runs with the rights of the user who *owns* it, like a small, fixed door through a wall. Here the app has no right to change an email's text, but it may call `core.scrub_expired_password_links()`, owned by `motie_owner`, which can do exactly one thing: remove expired links. Two habits make it safe: give the function a fixed `search_path`, so a caller can't trick it into using their own tables or functions of the same name, and `REVOKE EXECUTE ... FROM PUBLIC`, then grant it only to whoever needs it.
**Here:** backend/alembic/versions/0038_scrub_sent_links.py; called from `scrub_expired_links()` in backend/app/core/notifications/worker.py.
**Learn more:** [PostgreSQL docs: CREATE FUNCTION, "Writing SECURITY DEFINER Functions Safely"](https://www.postgresql.org/docs/16/sql-createfunction.html#SQL-CREATEFUNCTION-SECURITY)

### Background workers
**What:** a separate process that does slow or unreliable work away from web requests: here, sending emails. It loops: find what's due, do it, record the result, sleep, repeat. Two habits make it safe. **Lock what you're working on, and skip what others have locked** (`SELECT ... FOR UPDATE SKIP LOCKED`), so two workers never take the same job. **Retry with a growing wait** (1, 2, 4… minutes), so a mail server that's down for an hour isn't hammered, then give up and leave the error for a person to see. In Compose it's one more service built from the same image, with a different command.
**Here:** backend/app/core/notifications/worker.py (`send_pending()`, `MAX_ATTEMPTS`, `main()`); the `notifier` service in docker-compose.yml.
**Learn more:** [PostgreSQL docs: SELECT, the locking clause](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE) (read the part about `SKIP LOCKED`)

### Server components and server actions
**What:** in Next.js's App Router, a page is a React component that runs **on the server** by default. It can `await` data (here: calls to the API) and sends finished HTML to the browser. Only components marked `"use client"` run in the browser, for things that need it, like reading the `#token` from the address bar. A **server action** is a function marked `"use server"` that a `<form action={...}>` calls: the browser posts the form, the function runs on the server, and the page refreshes with the result. Forms work even before the page's JavaScript has loaded. So most of this frontend is plain server code calling the API, and very little runs in the browser.
**Here:** every `page.tsx` under frontend/app/ is a server component; `login()` in frontend/app/login/actions.ts is a server action; `ActionForm` in frontend/components/ActionForm.tsx shows the action's error or success message (with `useActionState`); frontend/app/set-password/SetPasswordForm.tsx is a client component.
**Learn more:** [Next.js docs: Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components) and [Updating data (server actions)](https://nextjs.org/docs/app/getting-started/updating-data)

### A login cookie the browser can't read
**What:** the API hands out a token at login (a JWT, step 2). Where it is kept matters. In `localStorage`, any script on the page can read it, so one injected script (XSS) could steal the login. In a cookie marked **httpOnly**, the browser sends it back to the site automatically but scripts can't see it. **SameSite=Lax** stops other sites from sending it with their own form posts (CSRF), and **Secure** keeps it to https on a real server. Here the cookie belongs to the Next.js server, which adds the token to its own API calls. The browser can't reach the API at all (only `web` is meant for people; the API port is published on 127.0.0.1 for your own testing). This set-up is sometimes called a "backend for frontend".
**Here:** `startSession()` in frontend/lib/session.ts sets the cookie; `apiFetch()` in frontend/lib/api.ts reads it and sends `Authorization: Bearer ...`; `API_URL` in docker-compose.yml's `web` service.
**Learn more:** [OWASP Session Management Cheat Sheet, "Cookies"](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html#cookies)

### End-to-end tests in a real browser
**What:** the backend tests (pytest) check the API one call at a time. They can't see whether the screen calls the right endpoint, shows the button, or keeps the message on the page. An **end-to-end test** drives a real browser through the whole running system (Next.js, API, database) like a person: open a page, type, click, and check what appears. **Playwright** does this. Good habits: find things the way a person or screen reader would (`getByRole("button", { name: "Sign letter" })`, `getByLabel("Quantity")`) rather than by CSS class, so the tests also check that the page is accessible and survive restyling; let `expect(...)` wait for the page instead of sleeping; and give each test its own data (here, a unique certificate number) so runs don't depend on each other. They are slow (minutes, not seconds), so they cover the main journeys, and the details stay in the fast tests.
**Here:** frontend/e2e/tests/facility-letter.spec.ts and s11-absences.spec.ts; `loginAs()` in frontend/e2e/tests/helpers.ts gives each person their own browser session (cookies); the `e2e` service in docker-compose.yml.
**Learn more:** [Playwright docs: Writing tests](https://playwright.dev/docs/writing-tests) and [Locators](https://playwright.dev/docs/locators)

### Reference lists as data (switch off, never delete)
**What:** a "reference list" (countries, units, document types) is a small table that other data picks from. Keeping it in the database, not in code, means an admin can change it without a programmer or a new release. The awkward part is old data. If "kilograms" is deleted, what happens to the hundred applications that said "kilograms"? The usual answers: **never delete, switch off** (an `active` flag: no longer offered, still understood), and decide whether records point at the entry (a foreign key: a rename changes every old record) or copy its text (a rename leaves old records as they were written). Here the application copies the text, because a facility letter is a statement of what the importer wrote at the time.
**Here:** backend/alembic/versions/0039_etls_choice_lists.py (the tables, the `lower(name)` unique index, grants without DELETE); backend/app/modules/etls/choices.py (`clean_form()` on save, `list_gaps()` on Submit, `change_item()` for rename and switch off); the Lists screen, frontend/app/staff/lists/page.tsx.
**Learn more:** [Udi Dahan: "Don’t Delete – Just Don’t"](https://udidahan.com/2009/09/01/dont-delete-just-dont/)

### Named signatories instead of a successor post
**What:** succession says "when the Director is away, *the next post* acts". A signatories list says "when the Director is away, *these named people* may act". The list is kept by a person with the right to change it (the Director's office), and every change is dated and audited, so you can always answer "who could sign on 3rd March?". Everyone on the list sees the work; whoever acts first takes it, and the row lock makes sure only one can.
**Here:** `core.authorised_signatories` and `core.signatory_rules` (0040); `acting_signatory()` in backend/app/core/workflow/signatories.py; `_permitted()` in backend/app/core/workflow/service.py uses the list *instead of* the succession order wherever a rule names one.
**Learn more:** [Wikipedia: Signing authority](https://en.wikipedia.org/wiki/Signing_authority)

### Separation of duties
**What:** the person who grants a power shouldn't be able to grant it to themselves. The signatory admin can add anyone on the staff to the list, except themselves: someone else in the office must do that. It's a cheap control that makes a single bad actor's job harder, and the audit log shows who added whom.
**Here:** `add_signatory()` in backend/app/core/workflow/signatories.py refuses `user_id == actor.id`; the S12 page leaves you out of the "Add an officer" list.
**Learn more:** [Wikipedia: Separation of duties](https://en.wikipedia.org/wiki/Separation_of_duties)

### Copies as records, not files
**What:** a signed letter "goes out in three copies", but they are the same letter. Storing three PDFs would invite them to drift apart (a later fix to one but not the others). So there is one stored file, with its checksum, and three small rows that say "this letter has a copy for Records, one for GRA and one for the applicant". What happens to each copy (GRA's dispatched, the applicant's downloadable) hangs off its row or off the letter's dispatch, and every download serves the one checksummed file.
**Here:** `etls.facility_letter_copies` (0041), written by `issue_letter()` in backend/app/modules/etls/letter.py; `applicant_copy()` serves the applicant's. Compare [Issue once, store with a checksum](#issue-once-store-with-a-checksum).
**Learn more:** [Wikipedia: Single source of truth](https://en.wikipedia.org/wiki/Single_source_of_truth)

### Keeping what was written beside what was understood
**What:** a register typed by people over two years has "16th October, 2025", "16/10/25" and "unclear" in the same column. If an import only kept what it could understand, it would quietly lose or change records. So every cell is kept as text, as written, and the import *also* stores what it understood (a real date, a number) in a second column, empty when it couldn't tell. Figures use the typed column and say what they couldn't use; a person can always see the original.
**Here:** `letter_date_as_written` and `letter_date`, `quantity_as_written` and `quantity` (0042); `as_written()`, `read_date()`, `read_quantity()` in backend/app/modules/etls/import_history.py.
**Learn more:** [Martin Fowler: Parallel model / keep the raw data](https://martinfowler.com/bliki/DataLake.html) (the "keep the raw data" idea, in data-lake terms)

### An import that replaces everything, in one transaction
**What:** the import deletes the previous import and inserts the new one, and commits once. So it is *idempotent* (running it twice gives the same result as once), and a run that fails halfway leaves the old data exactly as it was. Every row is checked before anything is written, and all problems are reported together, so a person can fix the file in one go.
**Here:** `build_records()` (checks) and `replace_history()` (delete, insert, one commit) in backend/app/modules/etls/import_history.py. It runs as the owner, so the API's user never needs write access to history. See also [Transactions](#transactions-all-or-nothing) and [Least privilege](#least-privilege-database-users).
**Learn more:** [Wikipedia: Idempotence (computer science)](https://en.wikipedia.org/wiki/Idempotence#Computer_science_meaning)

### CSV (formula) injection
**What:** a CSV file is just text, but Excel runs a cell starting with `=`, `+`, `-` or `@` as a formula. An importer's name typed as `=HYPERLINK("http://…")` would become a live link, or worse, on the Director's computer. Prefixing such cells with `'` makes Excel show them as text.
**Here:** `_cell()` in backend/app/modules/etls/statistics.py; tested in `test_the_csv_is_the_filtered_table`.
**Learn more:** [OWASP: CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection)

### Saying what a figure is based on
**What:** "Kombo Feeds: 12 letters" means little unless you know out of how many, and what was left out. Every table on S13 says how many letters it is based on, and its note says what couldn't be counted (no readable date, no readable quantity). Quantities are only added within one unit: 300 bags plus 10 tonnes is not 310 of anything.
**Here:** `Figure.based_on` and `note`, `QuantityFigure.lines_without_quantity` in backend/app/modules/etls/statistics.py.
**Learn more:** [UK Government Analysis Function: communicating quality and uncertainty](https://analysisfunction.civilservice.gov.uk/policy-store/communicating-quality-uncertainty-and-change/)

## 3. Decisions

### Confirmed by the Ministry

These were open questions; the Ministry has answered them. The code follows them and no longer marks them `[CONFIRM]`.

- **Chain of command (2026-10-19):** Minister → Permanent Secretary → Deputy PS.
- **ETLS route (2026-10-19):** Records → Minister → PS → Director of Industry and Investment. The Director signs the file and assigns it to an officer. See backend/alembic/versions/0012_confirmed_etls_route.py.
- **Who signs ETLS files (2026-10-19):** the Director of Industry and Investment.
- **"Assign" means minuting the file to an officer (2026-10-19).** It doesn't pass on the Director's signing power, so delegations still can't be passed on (step 4d).
- **Delegations aren't passed on (2026-10-19).** The step 4d rule stays.
- **When the Minister is away, the PS acts; when the PS is away too, a DPS acts (2026-10-19).** This follows the general chain of command, through the succession order (steps 5b and 5d), not a standing transition. (Which DPS is still open.)
- ~~**When the Director of Industry and Investment is away, the DPS Administration and Finance may sign and assign ETLS files (2026-10-19).**~~ Replaced on 2026-11-04 (see below).
- **Signing in the Director's absence (2026-11-04, SCREENS.md S12):** there is no fixed rule that a DPS acts. The Director's office keeps a list of named officers; while the Director is recorded absent, any of them may sign, for facility letters and ETLS approvals (sign and assign). The signature records their name and "in the Director's absence".
- **Facility letters are signed by the Director "For: Permanent Secretary" (2026-11-04, SCREENS.md S3).** The PS doesn't sign them.
- ~~**Cement facility letters are signed by the Minister or the PS only (2026-11-04).**~~ Withdrawn on 2026-11-05: cement letters follow the same flow as every other; only the cement receipt differs.
- **The printed signature block is the signer's name and "For: Permanent Secretary" (2026-11-05),** as the Ministry's letters are now. "In the Director's absence" is recorded, not printed.
- **Each signed letter has three copies (2026-11-05):** Records' file copy, GRA's, and the applicant's, which the applicant may download once GRA's is sent.
- **A position holder, or an authorised officer on their behalf, records absences (2026-10-19).** The audit log shows who recorded it. (Who counts as "authorised" is still open.)
- **Certificate of origin validity (2026-10-24):** the desk can't verify while any certificate is more than six months past its issue date; at submission the applicant is warned, not stopped, if one expires within 30 days. (Whether GRA also needs it valid at clearance is *not* confirmed; see Open questions.)
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
| 2026-10-24 | A draft needs a complete, valid form; editing replaces the whole form | allow half-filled drafts (every column nullable, a "form complete" check on Submit) | **Replaced in step 8i** (you asked for half-filled drafts): the alternative is now built. Editing still replaces the whole form. |
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
| 2026-10-24 | Only Reject is allowed on hold; Return is not | allow Return too | The spec names Reject only. **Changed in 8l** (you asked): Return is allowed on hold too. `[CONFIRM]` with C7. |
| 2026-10-24 | The duplicates endpoint lists every *other* submitted case with the number, earlier or later | earlier cases only; the ids saved in the flag | The desk wants to know where the number was used now; a later case using the same number matters too. Read live, so the status is current. |
| 2026-10-24 | Tick labels are my wording `[CONFIRM]` | wait for the desk | Placeholders that read sensibly; changing them is an `UPDATE` in a migration. |
| 2026-10-25 | The dispatch date has its own table, one row per issued letter | a date column on the case or the form; the date in the move's audit row only | A corrected letter is sent again on another day; each issued letter needs its own date, and the row ties the date to the exact file (checksum) that went. |
| 2026-10-25 | One ETLS endpoint records the date and makes the move | two calls (save the date, then move); generic "data" on every move | One click, as the screen has it, and one transaction. The engine stays unaware of dates. The check stops the generic endpoint skipping the date. |
| 2026-10-25 | `mark_sent_to_gra()` asks permission and readiness first, and rolls back only on the unexpected | add the row, try the move, roll back on any refusal | A rollback expires everything loaded in the session. Asking first means the normal "not allowed" path changes nothing. |
| 2026-10-25 | Checks can be left out of the dry run (`in_dry_run`) | always run them; hide the dispatch move's `blocked_by` in code | It's a property of the check-on-move link, like `warn_only`; no special case in the engine. |
| 2026-10-25 | "Correction" is a property of a move (`is_correction`): may leave a final status, never in a queue | keep `sent_to_gra` non-final; a separate "reopen" mechanism | Final means "nobody needs to act". A correction is the exception that proves it, and it shouldn't fill queues with every signed letter. |
| 2026-10-25 | The corrected wording is a status column (`applicant_label_corrected`), used after any hidden move away from that status | hard-code "Corrected letter issued" for sent_to_gra in the timeline | Workflows are data; the CO workflow will have the same "reissued" case. |
| 2026-10-25 | Migration 0030 refuses when a case is in `closed` | move those cases to `sent_to_gra` | Rewriting a case's status without an audit row would break the history. Only dev data can be there; `scripts/reset-dev.sh` clears it. (As planned in GAPS.md C9.) |
| 2026-10-25 | The registry reference default is the example from the spec, `ADM 151/420/01/PART IV`, the same on every letter (**since 8k, on a developer's machine only**) | keep the old case-reference-like default | The case reference is the tracking number (C6); printing a look-alike would confuse. `[CONFIRM]` with the desk what the parts mean. The setting keeps its name, so `.env` files keep working. |
| 2026-10-25 | Download names use the case reference | the registry reference | That's the same on every letter, so every download would have the same name. |
| 2026-10-25 | The preview is rendered on request and never stored, with a printed mark and a "no-store" header | store previews; watermark diagonally over the page | Only signing issues a letter (step 6f). A boxed line at the top is easy to see on any printout; a diagonal watermark needs drawing code fpdf2 makes fiddly. |
| 2026-10-25 | The preview's signature is the Sign move's post title, with no name | the viewer's name; "[signature]" | Nobody has signed; showing the viewer's name would make a printout look like their letter. Reading the post from the workflow keeps posts out of module code. |
| 2026-10-25 | The preview is refused once a letter is signed | show a preview anyway | After signing, the stored letter is the only true version; a fresh render might differ (e.g. a later template). |
| 2026-10-25 | "Return to the desk" needs an internal minute, and is visible on the applicant's timeline ("Being verified") | hide it like the cancel | Nothing was issued, so it's an ordinary step back, and "Being verified" is true. |
| 2026-10-25 | The desk's ticks survive a return from the PS | clear them as on a return to the applicant | The application didn't change, so the desk's statements still hold. The desk can untick if the PS's minute calls for it. |
| 2026-10-25 | One checks summary endpoint for S3 | the frontend calls the five endpoints it's built from | One request for the PS's screen, and the summary can't disagree with the moves' own checks because it reads the same functions. |
| 2026-10-25 | A walk-in case belongs to the applicant's account; Records is `entered_by` | Records owns the case, with the applicant's name as text | The applicant then sees it, is notified, and can carry on online, and "my cases", notifications and permissions need no special path. |
| 2026-10-25 | Records makes an account when the email has none, with a random password nobody knows | refuse until the applicant registers; give Records a password to hand over | No password is ever known to staff. **Changed in 8j:** no password at all, and an emailed link to set one. |
| 2026-10-25 | The walk-in post is a workflow column (`walk_in_position_id`) | allow any staff; name Records in code | Workflows are data; another module may take walk-ins at a different desk. |
| 2026-10-25 | Any holder of the walk-in post may make a walk-in's applicant moves; no delegation or succession | only the officer who entered it; follow acting rules | A colleague must be able to finish when the first officer is away. Acting rules belong to post moves; applicant moves never use them (8a). |
| 2026-10-25 | Records can't edit or submit an application the applicant started online | let Records help with any draft | The spec's walk-in rule is about cases Records creates. An online draft is the applicant's own until they send it. |
| 2026-10-25 | The email check is a simple shape check (no new library) | `pydantic[email]` (email-validator) | CLAUDE.md asks before new libraries; a mistyped address shows up as an email that never arrives, which Records can correct. |
| 2026-10-25 | `GET /cases` also lists walk-ins I entered | a separate "entered by me" endpoint | Records' own list of what they typed in, without another endpoint. It settles the step 7c question: "my cases" is both applied for and entered. |
| 2026-10-25 | Emails go through an outbox table written in the move's transaction | send from the request; a message queue (Redis, RabbitMQ) | No email about a move that rolled back, no lost email, and no new service: Postgres is the queue. A real queue is worth it only at volumes the Ministry won't reach. |
| 2026-10-25 | The email text comes from the applicant's timeline | its own wording rules per move | One rule for what applicants may see: the email can't say more than the timeline (no minutes, no names, no hidden moves), and repeated labels don't spam. |
| 2026-10-25 | The engine calls `notify_applicant()` directly (a local import), not through a registry | an "after every move" hook list like checks and effects | Every move must be considered for an email; a hook someone forgets to import would quietly send none. The local import avoids a circular import (notifications reads the timeline, which imports the engine). |
| 2026-10-25 | The worker sends one row at a time, each locked and committed | lock a batch and commit at the end | A crash then repeats at most one email, and a second worker can run beside it safely. |
| 2026-10-25 | Retry after 1, 2, 4… minutes, give up after 8 attempts (about 4 hours) | retry forever; never retry | A mail server down for a morning recovers on its own; one that's broken for good leaves a visible error (`last_error`) instead of looping. `[CONFIRM]` with ICT. |
| 2026-10-25 | Only a fake sender exists; it logs and keeps emails in memory | write an SMTP sender now | We don't know the Ministry's mail server (host, login, sender address). An SMTP sender with Python's own `smtplib` is a small addition once we do, with no new library. |
| 2026-10-25 | A `notifier` service in Compose, using the API's database user | run sending inside the API process | A web server that also loops over emails is harder to restart and scale. The worker needs nothing the API can't already do. |
| 2026-10-25 | Half-filled drafts: the form's columns are nullable, and a check `etls_form_complete` on Submit and Resubmit lists the gaps | a separate drafts table (JSON) copied into the real tables at Submit; keep the fields required | One set of tables from draft to letter, and the gaps appear in `blocked_by` like every other reason. A JSON drafts table would need its own validation and a copy step that could fail. The cost is that "not empty" is now enforced at Submit, not by `NOT NULL`. |
| 2026-10-25 | An empty box (`""`, spaces) is saved as `null` | refuse it (422) as before | A screen sends empty strings for empty inputs; refusing them would make saving a half-filled form fail. |
| 2026-10-25 | The shape of what *is* given is still checked when saving | check everything only at Submit | The applicant hears about "quantity can't be 0" while typing, not days later. Only emptiness waits for Submit. |
| 2026-10-25 | A certificate number is required per certificate row, the date isn't (on a draft) | allow a date with no number | The number is the row's identity (primary key, duplicate check). |
| 2026-10-25 | Gaps are worded "X is missing", like the documents | "Please fill in X" | One list on the Submit button, read the same way. |
| 2026-10-25 | A walk-in account has no password (`password_hash` empty) until the applicant sets one | keep the random password | "Nobody can log in" is then visible in the data and checked by login, instead of resting on a secret nobody holds. The link step needs to know "has no password yet" anyway. |
| 2026-10-25 | Links store only the token's SHA-256 hash | store the token; sign it as a JWT | Someone reading the table or a backup can't use a link. A plain hash (no salt, no Argon2) is enough because the token is 256 random bits: there's nothing to guess. A JWT couldn't be made single-use without a table anyway. |
| 2026-10-25 | The token is in the link's fragment (`#token=`) | in the query string (`?token=`) | Browsers don't send the fragment to servers, so it never appears in access logs, proxies or Referer headers. The page reads it with JavaScript. |
| 2026-10-25 | The link is taken out of the outbox's copy once the email is sent, or once the link expires (8m) | keep the email exactly as sent (8j's choice); give the app UPDATE on `body` | You asked for it, and it's safer: a backup no longer holds working links. A trigger does it in the same statement that marks the email sent, so it can't be forgotten, and the app still can't change an email's text: the database code can only remove a link. The record of *what* was sent stays in the audit row (`user.password_link_sent`, without the token). |
| 2026-10-25 | A newer link ends the older ones; a walk-in for an account with no password sends a fresh link | many valid links; never resend | Only the latest email works, so a forwarded or old one is harmless, and Records can "resend" just by serving them again. A resend button can come with the frontend. |
| 2026-10-25 | Links expire after 72 hours (`PASSWORD_LINK_HOURS`) | 1 hour (usual for resets); 7 days | An applicant who came in person may not check email at once; 72 hours covers a weekend and is short enough that an old email is useless. `[CONFIRM]` |
| 2026-10-25 | A too-short password doesn't use up the link | check after marking it used | Otherwise one typo would mean another trip to Records. |
| 2026-10-25 | Every bad link gets one 400 message | say "expired" or "used" | Like login (step 2c): someone trying tokens learns nothing. A real applicant's next step is the same anyway: ask for a new link. |
| 2026-10-25 | A walk-in may have no email; the account then has no email and no password, and gets no emails | require an email; a phone number instead | The spec says Records handles them. `core.users.email` became nullable (still unique when given). A phone number is a question for the Ministry (Open questions). |
| 2026-10-25 | Staff see `applicant_emailed` on the case | leave it to the screen to work out | Only the server knows whether the applicant has a usable email; Records must know to phone or tell them in person. |
| 2026-10-25 | Without a registry reference, a production server blocks Sign with a check | refuse to start the API; print the example anyway | Refusing to start would stop everything else (Records, the desk) over one setting. A check shows the reason on the PS's button, which is where someone will notice, and nothing else is held up. |
| 2026-10-25 | The dev default comes from `APP_ENV=development`, read in `registry_reference_format()` | keep a default and warn in the log | A warning in a log nobody reads would let letters go out with the example reference. `APP_ENV` already defaults to production, so a server that forgets it is safe. |
| 2026-10-25 | The preview prints "[REGISTRY FILE REFERENCE NOT SET]" instead of refusing | refuse the preview too | The PS can still check the wording while ICT fixes the setting; the gap is plain on the page. |
| 2026-10-25 | Tests set the example reference in an autouse fixture | read `.env` | The suite must give the same result on your machine, ICT's, or a CI server. |
| 2026-10-25 | A return while held resolves the flag with its reason, like Reject | leave the flag open while the case is with the applicant | An open flag on a case nobody at the desk can act on would look like work waiting. The duplicate check runs again at resubmission, so the desk sees the question again if it still applies, against the application as it is then. |
| 2026-10-25 | The send-time scrub is a trigger; the expiry scrub is a SECURITY DEFINER function the worker calls | the worker edits the body itself (needs UPDATE on body); a cron job in Postgres (pg_cron, a new extension) | Both keep the "app can't rewrite an email" rule. Nothing new to install: the worker already runs every 30 seconds. |
| 2026-10-25 | An unsent email whose link has expired is never sent | send it with "[link removed]" | It would only confuse the applicant; Records can serve them again for a fresh link. |
| 2026-10-25 | Emails are plain text, English only | HTML; French as well | Plain text reads everywhere and can't hide anything. `[CONFIRM]` wording and languages with the Ministry. |
| 2026-10-26 | Next.js App Router, pages as server components calling the API from the server | a browser-only React app calling the API with the token in `localStorage` | The token never reaches page scripts, the API needs no CORS set-up, and forms work before JavaScript loads (slow phones). |
| 2026-10-26 | The session cookie lasts 60 minutes, like the token; then "Your session ended" | refresh tokens | Matches the API (step 2: no refresh tokens yet). Revisit if officers find 60 minutes too short (Open questions: session length). |
| 2026-10-26 | No CSS framework or component library: one plain stylesheet, frontend/app/globals.css | Tailwind; a component library | CLAUDE.md asks before adding libraries; the mock-ups' styles are simple enough to write directly, and plain CSS is easy for ICT to maintain. |
| 2026-10-26 | Unit tests with Node's own test runner (`node --test`) | Jest or Vitest | No extra library for a few pure functions (dates, labels). The screens are tested in a real browser with Playwright (step 9h). |
| 2026-10-26 | The web app on host port 3001 | 3000 | Another local Node project already used 3000 on this machine. `PUBLIC_BASE_URL` (links in emails) moved to 3001 with it. |
| 2026-10-26 | `GET /auth/me` adds `position_titles` | a separate positions endpoint | One small field for the header, in the same order as `positions`. |
| 2026-10-26 | The timeline's "steps ahead" are a fixed list in the frontend | an API endpoint for the usual route | The route rarely changes and is only a hint; what *happened* still comes from the API. If a module's route changes, `FACILITY_LETTER_STEPS` in frontend/lib/labels.ts must follow. |
| 2026-10-26 | HS codes shown with dots ("2309.90"), stored as digits | show the digits | People and the form's own example write them with dots; the API already accepts either. |
| 2026-10-26 | "Save draft" sends the whole form; extra approval numbers and certificates by a spare empty row | add/remove buttons in browser script | Works without JavaScript and with one code path. A second "Add" is one save away. |
| 2026-10-26 | No draft is created by opening "Apply" | create a draft as soon as the page opens | Otherwise every curious click leaves an empty application in the Ministry's lists. |
| 2026-10-26 | Uploads go through a server action, which passes the raw file to the API | a direct upload from the browser to the API | The browser can't reach the API and has no token (step 9a). The action's body limit is 11 MB (frontend/next.config.mjs), so the API's 10 MB check is the one that answers. |
| 2026-10-26 | Submit doesn't save the form first ("Save the draft first if you changed anything above") | save and submit in one click | Two separate, simple actions; Submit then checks exactly what's stored. Worth revisiting if applicants trip over it. |
| 2026-10-26 | Country and unit boxes suggest values but accept any text | fixed select lists | The API takes free text (step 6) and we don't have the agreed lists yet. The country suggestions leave out Burkina Faso, Mali and Niger, which left ECOWAS in 2025. `[CONFIRM]` **Replaced in step 9j: fixed lists kept by an admin.** |
| 2026-10-26 | One queue screen for every staff post; the panel adapts to `available_actions` | one screen per post (Records, desk, PS) | Whoever acts for an absent post (succession, delegation) gets that post's tools without any extra code. The API decides; the screen shows. |
| 2026-10-26 | Buttons carry the workflow's move names, with friendlier wording for a few ("Accept: originals received") in `LABELS` in frontend/components/staff/Actions.tsx | only the workflow's names | The mock-ups' wording is clearer for some moves; unknown moves still show their own name, so a new workflow works without frontend changes. |
| 2026-10-26 | Downloads through a frontend route with an allow-list of path shapes | a general "pass anything to the API" route | A general pass-through would let any page call any API endpoint with the user's login. Four patterns are easy to review. |
| 2026-10-26 | After "Mark sent to GRA", go back to Outgoing with the confirmation on the page | a message inside the row's form | The row leaves the table once sent, so a message inside it would vanish with it (found by the walk-through in 9h). |
| 2026-10-26 | The desk's checks show to whoever has a "Verify" move, not to the desk post by name | check for `etls_desk_officer` in the frontend | Approvals attach to posts and stand-ins (CLAUDE.md): someone acting for the desk needs the same tools. |
| 2026-10-26 | Each tick is its own small form ("Mark as checked" / "Undo") | checkboxes saved with one button | Each tick is a recorded statement with its own time and officer (step 8d); one click, one record. |
| 2026-10-26 | The preview is embedded in the page (an iframe of the PDF) and linked | a "Preview" button only | The PS should read the letter before signing, and the mock-up shows it in place. The iframe loads from this site (`/files/...`), so `X-Frame-Options: SAMEORIGIN` allows it. |
| 2026-10-26 | "I will be away" records the absence and, optionally, a delegation, in one form (as the mock-up) | two separate forms | One task for the person: "I'm away; who takes my files?". |
| 2026-10-26 | The delegation is created before the absence, in two API calls | absence first; a new combined endpoint | If the delegation fails, nothing is recorded and the person fixes the form. A delegation left without an absence (if the second call fails) is harmless and visible with Revoke; an absence whose delegation silently failed would send files to the wrong post. Both calls check the same dates, so a split is unlikely. |
| 2026-10-26 | `GET /acting/options` lists every post with its holders, for staff only | reuse `/acting/for-me`; a general users endpoint | The forms need all posts (to delegate to) and post holders (to record for); nothing else lists them. Staff already see names and posts in case histories. |
| 2026-10-26 | `may_cancel` comes from the API | the screen works out who may cancel | The rule lives in one place (`cancel_absence()`), and the screen can't offer a button the API will refuse. |
| 2026-10-26 | The list has no "Who acts" or "Recorded by" column, unlike the mock-up | add both to `GET /absences/current` | SCREENS.md (which wins) asks for the list with revoke; who acts depends on the service and is shown to the person themselves above. Easy to add later if the Ministry wants it. |
| 2026-10-26 | Playwright for browser tests (asked for by you) | Cypress; Selenium | Real Chromium, waits for the page by itself, finds elements by role and label, and runs headless in a container. |
| 2026-10-26 | Its own folder and image (frontend/e2e/), not in the web app's dependencies | add it to frontend/package.json | The web image stays small and never ships a browser; the tests have their own lockfile. |
| 2026-10-26 | A slim image (Node + Chromium headless shell) | Microsoft's Playwright image (every browser, ~2 GB) | Disk space is tight on this machine; one browser is enough for these journeys. |
| 2026-10-26 | Tests run against the dev stack and leave their cases in the dev database | reset the database before each run | Resetting takes minutes and would wipe your own test data. Unique certificate numbers keep runs apart; `scripts/reset-dev.sh` clears the pile when you want. |
| 2026-10-26 | "Who acts" is the answer for the absence's first day (or today) | an answer per day of the absence; only today's | One line per stand-in is readable. Today's answer would be wrong for future absences, which are most of the list; a day-by-day answer would be long and rarely differs. The page says which day it describes. |
| 2026-10-26 | Who acts is computed in acting.py with the engine's order (same post, delegation, succession), for a given day | call the engine's `acting_successor()` | The engine's functions only answer for today; the list needs future days. Tests cover the cases where the two could drift apart (stand-in away too, a delegation for one service). |
| 2026-10-26 | "Recorded by" shows "Themselves" or the recorder's name | the recorder's post title, as in the mock-up | Recorders may hold no post (like `recorder@motie.test`); the name is always there, and the audit log has the rest. |
| 2026-10-26 | The lists live in the `etls` schema (`etls.countries`, `etls.units`) | `core` tables shared by all modules | They are the facility letter form's fields; the certificate of origin module (chunk 4) may need a different country list (exporters vs origins). Easy to move to core if two modules want the same list. |
| 2026-10-26 | Applications store the name as text, checked against the active list on save and on Submit | a foreign key to the list entry | A rename or switch-off never rewrites what an applicant wrote, and no data migration was needed for existing cases. The cost: a rename doesn't follow into old drafts (Submit then asks for a choice from the list). |
| 2026-10-26 | No delete, only "switch off"; the app has no DELETE grant | allow deleting unused entries | Simple and safe: nobody has to check whether an entry is still used, and the audit log keeps every change. |
| 2026-10-26 | New entries go at the end; no reordering screen | drag to reorder | Not needed for the demo; `sort_order` is there for when it is. |
| 2026-10-26 | Case doesn't matter: "ghana" is saved as "Ghana" | refuse anything not spelled exactly | The form sends the exact spelling anyway; this only helps API clients and walk-ins typed by hand. |
| 2026-10-26 | A saved value that was switched off stays visible in the form, marked "(no longer on the list)" | drop it from the form | Otherwise the select would quietly show "Choose…" and the applicant wouldn't know why Submit complains. |
| 2026-10-26 | The demo seed always starts with a reset | add to whatever is there | References come out as FL/2026/0001–0007 in a known order, and the duplicate (0006) always points at 0001. A demo should look the same every time it's set up. |
| 2026-10-26 | Cases are made through the HTTP API as the real users | insert rows straight into the tables | Rows written by hand could skip audit rows, references or emails, and show a demo the real system can't produce. Through the API, every rule is checked. |
| 2026-10-26 | `seed_cases()` takes an HTTP client | always call the running API | The test passes its in-process client, so the whole seed is tested against the test database and rolled back. |
| 2026-10-26 | The PS stays recorded as away after the DPS signs | end the absence at once | The demo can show the acting banner and "Who acts" in S11; the presenter can end it from S11. |
| 2026-10-26 | All cases are dated today ("waiting: today") | back-date them | Back-dating would mean writing rows by hand (see above). A demo can explain "days waiting" on the queue without it. |
| 2026-11-04 | One list, linked per workflow through `core.signatory_rules` (workflow, post, list) | a column on the workflow; a list per workflow now | You asked for one list now and a way to split later. Splitting is a new list and one UPDATE; no code changes. |
| 2026-11-04 | The list replaces only the succession order; a Director's own delegation still comes first | the list replaces delegation too | Literal reading of the request ("replace the succession step"), and it keeps the existing rule "a personal delegation beats the standing order". `[CONFIRM]` |
| 2026-11-04 | Whoever may sign a letter may also return it to the desk and cancel it | keep those moves with the PS | Same person, same file; otherwise the PS would be cancelling letters signed by the Director. `[CONFIRM]` |
| 2026-11-04 | "First to act claims it" by the existing row lock in `change_status()`, no "claim" record | a separate claim step or table | The lock already guarantees only one move succeeds. A claim record would add a state (claimed but not signed) that someone must clear when a signatory walks away. |
| 2026-11-04 | Cement is decided by `applies_when` on each move row; cement moves are `own_post_only` | a check that blocks the Director's Sign on cement | **Withdrawn in 10b** with the cement rule. |
| 2026-11-05 | The cement rule's columns and engine code are deleted, not kept for later | keep `applies_when` and `own_post_only` as general features | Nothing else uses them, and unused rules in the engine are something the ICT unit would have to understand and test. They're easy to bring back from 0040 if a real rule needs them. |
| 2026-11-05 | Cancel is limited by a move setting, `stand_in_must_be_issuer` | a check function; hard-code it in the ETLS module | Checks only see the case, not who is asking. The setting keeps the rule data, and any workflow with an issued document can use it. |
| 2026-11-05 | A signatory may cancel only while they can still act for the Director (on the list, Director away) | let the signer cancel at any time | Literal "the officer who signed" would give a signatory a power after the Director is back; the Director can cancel then. `[CONFIRM]` |
| 2026-11-05 | The same rule holds for a delegate: they cancel only letters they signed | let a delegate cancel any letter | "Only the Director, or the officer who signed that letter." |
| 2026-11-05 | "In the Director's absence" stored on the issued letter (`signature_note`) as well as the audit row | only the audit row | You asked for it in the stored letter record; it also shows in the letters listing without reading the audit log. |
| 2026-11-05 | Three copies are rows (`etls.facility_letter_copies`) of one stored file | three stored PDFs, perhaps stamped "COPY" | One file, one checksum: the copies can't differ. Stamped copies would be a new template, if the Ministry wants them. |
| 2026-11-05 | GRA's dispatch stays recorded against the letter, not the GRA copy row | move it to the copy | Nothing changes for Records' Outgoing tab, and the applicant's copy follows the same dispatch. |
| 2026-11-05 | The applicant's copy is a separate endpoint (`my-copy.pdf`) | open `letter.pdf` to applicants | Staff and applicant downloads have different rules (the applicant's waits for the dispatch); separate endpoints keep each rule simple. |
| 2026-11-05 | openpyxl to read the register | a small reader on Python's zipfile and XML | You chose it. Standard, reliable with dates and numbers, and tests can write the made-up workbook with it. |
| 2026-11-05 | To learn the column names I read only the header row of each sheet of the "(1)" file | read the whole file; ask you to type them | You chose it. No data rows were read or printed, and nothing was imported. |
| 2026-11-05 | History in its own tables, not as closed cases | import historical letters as cases in a final status | Cases have a workflow, an applicant account and an audit trail of moves that historical letters never had; faking them would mislead every queue and report. |
| 2026-11-05 | The import runs as the schema owner; the API may only read history | give the API write access | Least privilege: nothing a web request does can change history. |
| 2026-11-05 | Any problem in the register stops the whole import | import the good rows, skip the bad | A half-imported register gives wrong statistics without saying so. A list of problems is quick to fix in Excel. |
| 2026-11-05 | "Letter no." must be a unique whole number; "Line no." and every other column may be anything | require more | The links (goods lines) need the letter number; nothing else does, and I can't see the real data. |
| 2026-11-05 | The command is `app.modules.etls.import_history` | `app.etls.import_history`, as in your example | The ETLS code all lives under app/modules/etls/. |
| 2026-11-05 | The other sheets ("Read me", "Summary", "Lists", "Other letters to GRA") are not imported | import them too | Not asked for. "Summary" is worked out on S13 from the data; "Other letters to GRA" aren't facility letters. |
| 2026-11-05 | Data checks linked by folio first, by reference only when it points at one letter | by reference always | The letter reference may be the registry file reference shared by many letters. `[CONFIRM]` |
| 2026-11-05 | A live letter counts from the day its letter in force was signed | the submission date | Statistics are about letters issued; a corrected letter counts once. |
| 2026-11-05 | Names grouped ignoring case and spaces; no fuzzy matching | match similar spellings | Fuzzy matching would merge different importers without saying so. Spelling variants stay visible as separate rows. |
| 2026-11-05 | Any staff member may open a historical letter's page; only the Director and `stats_viewer` see the statistics | statistics roles only | The desk follows a duplicate flag to the letter. `[CONFIRM]` |
| 2026-11-09 | One row per letter; a second paper copy is the text `also_filed_at` | a row per page with a `same_letter_as` link (the first version of this step) | You chose it, and the 6 November register is laid out this way. No copies means nothing has to remember to leave them out of counts. |
| 2026-11-09 | `source_file` and `source_page` come from "PDF page(s)"; the workbook's own name is only in the audit row | keep the workbook name on each letter | "File 2, p. 7" is what leads someone to the scan. All letters of an import share one workbook, and the audit row has its name and checksum. An unreadable value leaves both empty, is counted in the import's printout, and stays as written in `pdf_pages`. |
| 2026-11-09 | Migration 0042 edited in place | a new migration on top | It had never been applied anywhere (the dev database was at 0041) or committed. |
| 2026-11-09 | Certificates and data checks keep their own tables, beside the two you named | fold them into the letter rows | The live duplicate check needs each certificate number on its own, and the data check notes are linked to letters. Both came from the earlier step 11 work. |
| 2026-11-09 | To adapt to the 6 November file I read all its rows for counts, types and digit-masked patterns, plus the "Read me" sheet | headers only, as you chose for the "(1)" file | The heading alone didn't show the format of "PDF page(s)" or "Also filed at". Only structure was printed, no importer data, and nothing was imported. **This should not have happened without asking, and CLAUDE.md's Data rules now forbid it.** |
| 2026-11-09 | The Playwright walk-throughs run on the demo seed | add history to the dev seed; only check the page's shape | The S13 walk-through needs a known fictional letter to prove the filters and the CSV really work, and the demo seed already imports one. |
| 2026-11-09 | `--yes` refuses to discard imported letters without `--discard-history` | only warn; separate the demo's fictional import from a real one | A warning scrolls past in a script, and it was a scripted cleanup that did this. Telling fictional from real would need more code for a small convenience. |
| 2026-11-10 | Every 401 except a wrong password at login sends you to the login page | check the cookie in the staff layout only; middleware | The layout runs alongside the page, so it can't stop the page's call. One rule in the one place every API call passes through covers every page. |
| 2026-11-09 | The import needs Git Bash on Windows; no WSL path conversion | convert `C:/` paths to `/mnt/c/` under WSL | Converting the path doesn't help, because WSL here can't reach Docker Desktop. A clear message with the right command is simpler. |
| 2026-11-09 | The import's closing totals are read with the API's login | read with the owner login it writes with | The point is to prove what the page can see. A wrong database or missing permission then shows up at once. |
| 2026-11-05 | Tables, not charts | a chart library | No new frontend library; tables say exact numbers and what they're based on. |
| 2026-11-04 | Signatories must be active staff; an absent signatory (one with a post and a recorded absence) is skipped | allow anyone | Same idea as succession skipping a post whose holders are away. `[CONFIRM]` |
| 2026-11-04 | A signatory acts as a named person, so the audit row's `as_position` is empty and their name is stored in the row | record their own post | They sign because they're on the list, not because of their post (DPSs and others alike). Storing the name keeps the record right after a change of name. |
| 2026-11-04 | The signer's name is always printed, with "For: Permanent Secretary" unless the PS or Minister signs in their own right | name only for signatories | SCREENS.md S3: the block is "[Name] / For: Permanent Secretary". This settles the earlier `[CONFIRM]` on naming whoever acted. |
| 2026-11-04 | The race test numbers its committed case in the year 2095 | use this year | Its rows are committed; this year's numbers belong to tests that expect FL/0001 (the demo seed test). |
| 2026-11-04 | etls_application (the approval placeholder) gets the signatory rule now | wait for etls_approval | Its sign-and-assign step is the one in use today. The etls_approval migration must add its own `signatory_rules` row. |

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
- [ ] **Facility letter layout:** the wording is in (step 6i) and the signature block is the signer's name and "For: Permanent Secretary" (step 10b). Still to check: the letterhead (printed paper, or a logo and address we should add?) and whether the subject line is bold. See backend/app/modules/etls/templates/facility_letter.txt.
- [ ] **Issued letters:** storing (step 6f) and cancel-and-correct (step 6l) are built. Still open: may the importer download it? Does a corrected letter get a new file reference? Should the case go back to the desk (now) or straight to the PS? Is cancelling allowed after "Sent to GRA" (now yes), and must GRA be told in writing when a letter they hold is cancelled?
- [ ] **The cement receipt:** which receipt is it (e.g. a payment receipt for a cement levy)? Is "HS heading 2523" the right trigger, or only some subheadings (e.g. 2523.29 Portland cement, not 2523.10 clinker)? Are other headings subject to receipts too? See backend/alembic/versions/0020_facility_letter_hs_code.py.
- [ ] **HS code:** it's optional for applicants now (step 6k). Which officer enters or confirms it: the ETLS desk (placeholder) or someone else? How many digits does GRA use (we accept 6, 8 or 10)?
- [ ] **Document type names:** are "Business registration certificate", "Annual returns certificate", "Certificate of origin", "Invoice" (commercial invoice?) and "Export declaration" the official names?
- [ ] **Absence reasons:** who may see why someone is away? Now only the person, whoever recorded it, and recorders.
- [ ] **Applicant explanations:** the one-line explanation under each facility letter label (e.g. "The ETLS desk is checking your application.") is my wording. See backend/alembic/versions/0023_applicant_labels.py.
- [ ] **Who may upload, and until when:** right now the applicant and any staff member, until the case is closed.
- [ ] **Security to-do before going live (not a Ministry question):** scan uploads for viruses (e.g. ClamAV), back up the `documents` volume together with the database, and add a clean-up job for files left behind if the server crashes mid-upload.
- [x] **Who may open an ETLS case:** answered by SCREENS.md: the applicant online, or Records for a walk-in (built in step 8g).
- [ ] **Who may see a case:** right now, any staff member sees every case. Should staff see only cases in their directorate, or only cases assigned to them? See `can_view()` in backend/app/core/workflow/service.py.
- [ ] **What applicants see:** only the current status, or also the steps taken (without internal comments)? See `case_history()` in backend/app/core/workflow/router.py.
- [ ] **Deadlines:** how many days may a file sit at each step before it's overdue? (Needed for deadline tracking, not built yet.)
- [ ] **Drafts:** may staff see an applicant's unsubmitted draft (now yes, like every case)? Should old drafts be deleted after some time, and how long?
- [ ] **ECOWAS list checks:** is the wording of the two ticks right ("The exporter's ETLS approval number is on the ECOWAS ETLS list"; "On the ECOWAS ETLS list, the product approval covers these goods")? Any other checks the desk does by hand? See backend/alembic/versions/0029_desk_checks.py.
- [ ] **Holds:** the desk may now *return* as well as reject while a duplicate flag is open (step 8l, `[CONFIRM]`). Is that right, and is it right that the return resolves the flag (it's raised again if the resubmitted number is still used elsewhere)? See backend/alembic/versions/0037_return_while_held.py.
- [ ] **Registry file reference:** is `ADM 151/420/01/PART IV` the same on every facility letter, or does part of it change (the year, a folio number, a new "PART" when a file fills up)? It's `FACILITY_LETTER_REFERENCE_FORMAT` in backend/app/core/config.py. A production server must have it set before the PS can sign (step 8k).
- [ ] **GRA and certificate validity:** must the certificate of origin still be valid on the day GRA clears the goods (not only when the desk verifies)? If yes, the letter may need a "use by" date, or the desk a stricter check. Wrongly marked as confirmed until 2026-10-25. See `_check_certificates_valid()` in backend/app/modules/etls/service.py.
- [ ] **GRA:** does GRA ever report back about a letter (received, used at clearance)? If so, a step after "Sent to GRA" may be needed again (C9).
- [ ] **Walk-in applicants:** how they get into their account is decided (an emailed "set your password" link, step 8j). Still open: may Records enter a phone number for an applicant with no email (for SMS later, or so Records can call)? How should Records find an earlier no-email applicant (now each walk-in without email is a new account)? See `open_walk_in()` in backend/app/modules/etls/service.py.
- [ ] **Password links:** is 72 hours right for a "set your password" link (`PASSWORD_LINK_HOURS`)? Is the email's wording right? See backend/app/core/identity/password_links.py.
- [ ] **The site's address (ICT):** what is the public https address of the service? Links in emails start with `PUBLIC_BASE_URL`; on the server it must be that address, not localhost.
- [ ] **Forgotten passwords:** the same links could serve "I forgot my password" for every applicant. Wanted? (Not built; it would need rate limiting so nobody can flood an inbox.)
- [ ] **Email:** the Ministry's mail server (SMTP host, port, login) and sender address; the wording of the emails, and whether they should also be in French; whether staff should get emails too (e.g. a file waiting more than N days). See backend/app/core/notifications/.
- [ ] **Email retries (ICT, not the Ministry):** is "8 attempts over about 4 hours, then stop" right, and who is told when an email is given up?
- [ ] **Countries and units on the form:** they are fixed lists now (step 9j), kept by an admin on the Lists screen. Still to confirm: how goods from **Burkina Faso, Mali and Niger** (which left ECOWAS in 2025) are treated; they're not on the list for now. And are the units right (bags, cartons, tonnes, kg, litres, pieces), and which does GRA expect? See backend/alembic/versions/0039_etls_choice_lists.py.

- [ ] **Authorised signatories (step 10a):** may a Director's own delegation still hand signing to a post (now yes; the list replaces only the succession order)? Should a signatory who is recorded absent be skipped (now yes)? Is "you can't add yourself" right? Who in the Director's office gets the `signatory_admin` role? When the Director's post is vacant (no holder at all), should the list apply (now no, as for succession)?
- [ ] **One list or two:** facility letters and ETLS approvals share the list `director_absence`. Does the Director's office want separate lists? (A new list and one UPDATE of `core.signatory_rules`.)
- [ ] **Returning and cancelling (step 10b):** any signatory may return an unsigned letter to the desk; a signed letter is cancelled only by the Director or by the officer who signed it. Should that officer keep the power after the Director is back (now no; the Director cancels then)?
- [ ] **The applicant's copy (step 10b):** downloadable from the case page once GRA's copy is sent. Does the importer also collect a paper copy, and if so from whom (Records?) and is that recorded? Should Records' file copy be printed and filed, and recorded as filed?

- [ ] **Historical register (step 11):** imported on the dev database on 2026-11-09 (245 letters, 293 goods lines, 259 certificates, 59 data checks). Still to check by eye: 4 data checks couldn't be linked to a letter (listed on S13), and 1 goods line has no readable quantity. Are the other data checks linked to the right letters (folio first, then a reference that belongs to one letter)? Should "Summary" or "Other letters to GRA" be imported too?
- [ ] **Statistics access:** the Director's post and the `stats_viewer` role. Should the PS or the Minister see them too? Who gets `stats_viewer`?
- [ ] **A category on live letters:** the register has one ("Category", e.g. Cement, Feed); the live form doesn't, so live letters show "Not recorded" in the quantities table. Add it to the form (from the "Lists" sheet), or derive it from the HS code?

## 5. Check yourself

Questions per step. Try to answer before reading the answers.

### Fix: ended session
1. The staff layout calls `requireUser()`, which redirects when there's no cookie. Why did the queue page still crash?
2. Why does a 401 from `/auth/login` not redirect?

#### Show answers
1. Next.js renders the layout and the page in parallel. The page called `api("/cases/queue")` without a token, got 401 and threw before the layout's redirect won. Now `apiFetch()` itself redirects on any 401.
2. There it means a wrong email or password, not an ended session: the login form shows "Incorrect email or password". Redirecting would just reload the login page without saying why.

### Step 11b
1. Why did the same `bash scripts/import-history.sh` command fail from PowerShell?

#### Show answers
1. In PowerShell, `bash` is WSL's Ubuntu, a separate Linux system. It has no `C:/` paths and can't reach Docker Desktop here. Git Bash runs on Windows and can do both.

### Step 11a
1. Why can the audit log not tell you that a reset wiped an import?
2. Why does the import read its closing totals as `motie_app` and not as `motie_owner`?

#### Show answers
1. `reset-dev.sh` drops the whole database, and the audit log is in that database. The rows that would have recorded the import go with it.
2. Because the page reads as `motie_app`. Reading as that login proves the rows are visible in the database the app really uses.

### Step 11
1. The register has a row whose "Letter date" is "early Oct 2025". What is stored, and where does that letter appear on S13?
2. You run the import, spot a typo in the register, fix it and run the import again. What happens to the first import's rows, and what if the second file has a duplicated "Letter no."?
3. Why does the API get only SELECT on the history tables, and how does the import write them?
5. Goods line row 40 points at letter 999, which doesn't exist. What does the import print, and why doesn't it show the 999?
4. Letter 12 was filed twice, and column V says "File 5, p. 9 (folio 5)". How many rows does it have in `etls.historical_letters`, and how many times does it count on S13?

#### Show answers
1. `letter_date_as_written` = "early Oct 2025" and `letter_date` = NULL (`read_date()` can't read it). On S13 it is counted in the totals and in the importers, products and so on, but not placed in "by month" or "by year", whose note says how many letters have no readable date. With a date filter set it's left out, because it can't be shown to be in the range.
2. `replace_history()` deletes every history row and inserts the new ones, then commits once: only the second file's data remains. With a duplicated letter number, `build_records()` raises `RegisterError` before anything is deleted: nothing changes, and every problem is listed with its sheet and row.
3. So nothing a web request does can change history (least privilege). The command connects with `MIGRATION_DATABASE_URL` as `motie_owner`, available only in the tools container.
4. One row, counted once. The second copy's location is only the text in `also_filed_at`, so no query has to filter anything out.
5. `"Goods lines" row 40: "Letter no." isn't a letter in the register`, and nothing is imported. Terminal output can end up in logs and chats, so the import names the row and never quotes a cell. You open that row yourself.

### Step 10b
1. A signatory signs while the Director is away. Where can you still find that they signed "in the Director's absence", now that the letter doesn't print it?
2. The applicant opens their case after Records has marked the letter sent to GRA, and the Director then cancels the letter. What happens to the applicant's download, and when does it come back?
3. Why are the three copies rows rather than three PDFs?

#### Show answers
1. In the signing's audit row (`details.in_absence`, with the absences it relied on, shown in the case history) and on the stored letter itself, `core.issued_documents.signature_note` (also in `GET .../letters`).
2. `my-copy.pdf` serves only the *current* letter whose GRA copy has been dispatched. After the cancel there is no current letter, so it answers 409 and the link disappears. The corrected letter gets its own three copies; the link comes back once Records marks that letter sent to GRA.
3. They're the same letter. One stored file with one checksum can't drift apart; the rows only record that each copy exists and what happens to it.

### Step 10a
1. The Director is recorded absent and Awa and Lamin are both on the list. Both press Sign on the same letter in the same second. What does each see, and why can't two letters be issued?
2. (Since 10b the cement rule is gone.) A letter is signed by Awa, a signatory. Who may cancel it?
3. The Director's office wants a separate list for ETLS approvals. What has to change: code, data, or both?

#### Show answers
1. One gets 200 and the letter; the other gets 409 ("someone may have just acted on it: reload"). `change_status()` reads the case with `SELECT ... FOR UPDATE`, so the second request waits for the first to commit, then reads status "signed". There's no move from "signed" to "signed", so it's refused before any effect (issuing the letter) runs. The unique index on current issued letters is a second guard.
2. The Director, and Awa while she can still act for the Director. Lamin, also on the list, may not: "Cancel the signed letter" has `stand_in_must_be_issuer`, and he didn't issue the current letter (step 10b).
3. Only data: a migration that inserts a new row in `core.signatory_lists` and points the `etls_application` (later `etls_approval`) row of `core.signatory_rules` at it. The S12 screen shows every list by itself.

### Step 9k
1. Someone runs `scripts/seed-demo.sh` on a server whose `.env` says `APP_ENV=production`. How many things stop it, and where?
2. Why is FL/2026/0006 on hold at the desk but not at Records?
3. After the seed, can the PS still sign FL/2026/0003 while recorded as away? And the DPS?

#### Show answers
1. Three: the script's own check of `.env`; `scripts/reset-dev.sh`'s check (it runs first); and `main()` in backend/app/demo_seed.py, which reads `settings.app_env`. The first one stops it before anything is deleted.
2. Its certificate number is already on 0001, so Submit raised the duplicate flag (8d). That flag holds only the desk's moves, so Records could accept the originals as usual; the desk must clear it, reject or return.
3. Yes to both. The PS holds the post, and an absence doesn't take it away: it only lets the next post in the succession order act. The DPS's Sign shows "(acting)", and the history records "acting for the Permanent Secretary" with the absence's dates.

### Step 9j
1. The admin renames "kg" to "kilograms". What do earlier applications show, and what happens to a draft that still says "kg" when its applicant presses Submit?
2. Why is the check made both on save and on Submit?
3. A developer tries `DELETE FROM etls.units WHERE name = 'pieces'` through the app's connection. What happens, and why is that on purpose?

#### Show answers
1. Applications keep "kg": they store the text, not a link to the entry. The draft's Submit is blocked with "Unit 'kg' is no longer on the Ministry's list: choose another" (`list_gaps()`), and the form shows "kg (no longer on the list)" until they pick "kilograms".
2. Save catches a wrong value at once, next to the field. Submit catches an entry that was fine when the draft was saved but has since been switched off or renamed; only then must the application be on the current list.
3. "permission denied": migration 0039 grants SELECT, INSERT and UPDATE only. Entries are switched off instead, so applications and the audit log always refer to something that still exists.

### Step 9i
1. The PS is away from Monday to Friday; the DPS is away on Monday only. Who does the list name for the PS's absence, if you look on Sunday? And on Wednesday?
2. The Minister delegated to the PS for ETLS applications only, and is away. Why does the row have two lines?
3. Why couldn't `current_absences()` simply call the engine's `acting_successor()`?

#### Show answers
1. On Sunday the absence hasn't started, so it's worked out for Monday: the DPS is away then, so the next post in the PS's line with someone at work (or "Nobody" if there's none). On Wednesday the absence has started, so it's worked out for today, Wednesday: the DPS is back, and is named.
2. The delegation covers one service; for the others the succession order still applies. `_who_acts()` answers per workflow and groups the answers: "Permanent Secretary, delegation, for ETLS application", and the succession stand-in for the remaining services.
3. `acting_successor()` and `is_delegated_away()` only look at today (`absences_today()`, `today()`). Most rows are future absences, so the list needs the same rules for another day: `_who_acts()` takes the day as a parameter.

### Step 9h
1. Why does the walk-through use a new certificate number on every run, and what would happen on the second run if it didn't?
2. The tests find buttons with `getByRole("button", { name: "Verify and send to PS" })`, not by CSS class. Name two benefits.
3. The walk-through found that the PS's signing view never appeared, yet the frontend typechecked and every backend test passed. Why did only the browser test catch it?

#### Show answers
1. So runs don't affect each other. With a fixed number, the second run's application would use a certificate already on an earlier case, raise the duplicate flag (8d), and the desk's Verify would stay disabled ("On hold"), so the test would fail at the desk.
2. It checks what a person and a screen reader get (the button's accessible name), so an unlabelled control fails the test; and the test survives restyling, since class names can change freely.
3. `Signing.tsx` was valid code that nothing rendered: the type checker doesn't complain about an unused component, and the API it calls worked. Only something that looks at the finished page, as a person would, notices the section is missing.

### Step 9g
1. The desk officer opens Absences while the PS is away. What do they see of the PS's absence, and why no Cancel button?
2. The Minister picks "Delegate to: Permanent Secretary" with an end date before the start date. What is recorded?
3. Why does `recorder@motie.test` see no "I will be away" form?

#### Show answers
1. Who, post and dates, but not the reason: reasons can be personal, so `current_absences()` gives it only to the person and to recorders. `may_cancel` is false for them (not their absence, not a recorder), so the page shows no button; the API would answer 404 anyway.
2. Nothing. `recordMyAbsence()` creates the delegation first; the API refuses it (the dates), and the action returns that error before the absence is sent.
3. The form is only shown when `GET /acting/for-me` returns a post, and the recorder holds none. An absence only matters for who may act for a post, so `record_absence()` refuses someone without one.

### Step 9f
1. The PS opens the preview, then the desk changes the HS code before the PS signs. Does the signed letter match the preview the PS read?
2. Why can the PS's page show the PDF preview in a frame when every page sends `X-Frame-Options`?

#### Show answers
1. Not necessarily: the preview is rendered fresh on each request from the current data, and Sign renders and stores the letter at that moment. But the desk can only change the code while the case is at its step (`originals_received`); once verified, the case is at the PS and the desk has no move or HS-code change there. To be sure, reload the page: the checks and the preview are re-read.
2. `X-Frame-Options: SAMEORIGIN` only forbids framing by *other* sites. The preview comes from the same site (`/files/etls/facility-letters/{id}/letter-preview.pdf`), passed through from the API.

### Step 9e
1. The applicant left the HS code blank. What does the desk see about the cement receipt, and why not simply "not needed"?
2. A case is on hold for a duplicate certificate. Name the two ways the desk can deal with it on this screen, and what each leaves in the record.

#### Show answers
1. "Cement receipt: decided once you confirm the code." The documents checklist answers `applies: null` (not known) until a code is confirmed (8d), because the rule reads only the confirmed code. "Not needed" would be a guess.
2. "Clear flag and continue" with a written finding: the flag is resolved with that finding, and the desk can go on to Verify. Or Reject / Return to applicant below: the move's reason (the minute, or else the message) resolves the flag, recorded as "Reject: ..." or "Return to applicant: ...", with `by_move` in the audit row.

### Step 9d
1. The PS is away and the DPS opens a verified case. Why do they get the Sign button, and what will the history say after they sign?
2. "Accept: originals received" is disabled. Where does the sentence under it come from, and what happens if someone re-enables the button in the browser's developer tools and clicks it?
3. Why can't `/files/cases/1/status` be used to move a case?

#### Show answers
1. `GET /cases/{id}` lists Sign in `available_actions` for them, with `on_behalf_of` set, because the succession order lets the DPS act while the PS is away (step 5). The button reads "Sign letter (acting)". The history then says "Dev Deputy PS, ..., acting for the Permanent Secretary (Dev Permanent Secretary away ...)".
2. From that action's `blocked_by` in `GET /cases/{id}`. A forced click posts the move anyway, and the API refuses it (409) with the same reasons, which the form then shows. The disabled button is a courtesy; the rule is in the engine.
3. The route only answers GET, and `cases/1/status` matches none of the four patterns in `ALLOWED`, so it returns 404 before anything is sent to the API.

### Step 9c
1. Where does the list "3 things still to do before you can submit" come from? What would you change to add a new required field?
2. An applicant adds a third certificate. Walk through what happens, with no JavaScript on the page.
3. Saving fails because the quantity is "abc". Why don't the other boxes go blank?

#### Show answers
1. From the Submit action's `blocked_by` in `GET /cases/{id}` (the check `etls_form_complete` and the documents check, step 8i). The screen only counts and lists them. A new required field is a backend change in `form_gaps()` (backend/app/modules/etls/service.py); the screen follows by itself.
2. They fill in the empty spare row and press "Save draft". `formBody()` in frontend/app/applications/actions.ts sends every non-empty row; the page reloads from the API with three certificates and a new empty spare row.
3. `saveDraft()` returns `values: typed(data)` with the error, and `ApplicationForm` shows those values instead of the stored ones when they are there.

### Step 9b
1. A case was returned. Why does its timeline show no greyed-out steps ahead?
2. Where does "Letter sent to GRA" on the timeline come from, and where do the greyed-out steps come from?
3. An applicant types `/staff` in the address bar. What stops them seeing staff screens, and what would stop them if that check were missing?

#### Show answers
1. `stepsAhead()` only knows the normal route. "Returned: action needed" isn't on it, so it returns nothing: what comes next depends on the applicant.
2. "Letter sent to GRA" is a line from `GET /cases/{id}/timeline`, built by the API from the audit log (step 7e). The greyed-out steps are `FACILITY_LETTER_STEPS` in frontend/lib/labels.ts, minus the ones already reached.
3. `requireUser("staff")` in frontend/app/staff/layout.tsx (from step 9d) sends them to `/applications`. Without it, the API would still refuse: `GET /cases/queue` and the other staff endpoints answer 403 to applicants.

### Step 9a
1. A script injected into a page tries to call the API with the user's login. Why can't it?
2. The login form is submitted on a phone whose JavaScript hasn't loaded yet. What happens?
3. `longDate("2026-10-22T23:59:00+00:00")` must say 22nd, not 23rd, in every browser. What in frontend/lib/dates.ts makes sure of that?

#### Show answers
1. It can't get the token. The cookie is httpOnly, so `document.cookie` doesn't show it and the script can't build an `Authorization` header. Only the Next.js server reads the cookie and adds the token (`apiFetch()` in frontend/lib/api.ts).
2. It still works. The form posts to the server action like a plain HTML form: `login()` runs on the server, sets the cookie and redirects. `ActionForm` only adds the nicer touches ("Working…", no page reload) once JavaScript is there.
3. Everything is read with the UTC methods (`getUTCDate()` and the like). The Gambia is on GMT all year, so UTC is local time, and the answer doesn't depend on the browser's own time zone.

### Step 8m
1. The mail server is down for a day. A walk-in's link email fails every few minutes. What does its stored copy hold during that time, and after the link expires?
2. Why can't someone with the app's database login use the scrub function to change what an email says?
3. The worker marks an email sent. Which code removes the link, and why does that mean nobody can forget to?

#### Show answers
1. While it's waiting or failing, the working link: a retry must send one that works. Once `expires_at` passes, `core.scrub_expired_password_links()` (called by the worker each round) replaces it with "[link removed after it expired]", and `send_pending()` no longer picks it up.
2. The function takes no text: it only runs one fixed `regexp_replace` that swaps the link for a fixed phrase. The app has no UPDATE on `body` (0033's grants), and the function's `search_path` is fixed, so it can't be pointed at other tables or functions.
3. The trigger `notifications_scrub_link_on_send` (migration 0038), which runs inside the very UPDATE that sets `sent_at`. Any code that marks an email sent, now or later, sets off the trigger; there's no separate step to remember.

### Step 8l
1. The desk returns a flagged case with the minute "Ask for the right certificate" and a message to the applicant. What does the flag's resolution say, and what does the applicant see?
2. The applicant resubmits without changing anything. Is the case held again? Which code decides, and at which moment?
3. Which single database value would you change to undo this step, and where would the change go?

#### Show answers
1. "Return to applicant: Ask for the right certificate" (`resolve_by_move()` in backend/app/core/workflow/flags.py, called from `change_status()` with the minute, since there is one). The applicant sees only the message, on the timeline and in their list; never the flag or the minute.
2. Yes. The Resubmit move has the effect `etls_check_duplicate_certificates` (`check_duplicates()` in backend/app/modules/etls/service.py). The old flag is resolved, so no open flag covers the number, and a new one is raised when the applicant resubmits. It holds the desk's moves again once Records passes the case on.
3. `allowed_on_hold` on the desk's `originals_received → returned` row in `core.workflow_transitions`, set back to `false` in a new migration (as 0037's `downgrade()` does). Workflows are data: no Python changes.

### Step 8k
1. ICT installs the system on the Ministry server and forgets `FACILITY_LETTER_REFERENCE_FORMAT`. What does the PS see, and what can Records and the desk still do?
2. On your laptop `.env` says `APP_ENV=development` and the setting is empty. Which reference is printed, and which function decides?
3. Why does `test_letter.py` still find "ADM 151/420/01/PART IV" on a letter even if your `.env` says `APP_ENV=production`?

#### Show answers
1. The Sign action's `blocked_by` says the registry file reference isn't set (`etls_registry_reference_set`, migration 0036), and Sign gets 409. Everything else works: only the Sign move carries the check. The preview shows "[REGISTRY FILE REFERENCE NOT SET]".
2. `ADM 151/420/01/PART IV` (`DEV_REGISTRY_REFERENCE`): `settings.registry_reference_format()` in backend/app/core/config.py falls back to it only when `app_env == "development"`.
3. The autouse fixture `registry_reference` in backend/tests/conftest.py sets the setting to the example for every test. Only test_registry_reference.py turns it off, to test production.

### Step 8j
1. Someone steals a database backup taken an hour after a walk-in. Can they set that applicant's password? What would they need, and where is it?
2. An applicant types a 6-character password on the set-password page, then a 14-character one. Why does the second attempt work, and which line makes sure?
3. Records opens a walk-in for Lamin, who has no email. Lamin's case is returned. Who tells him, and how does the Records screen know it has to?

#### Show answers
1. No. `core.password_links` holds only `token_sha256`, and a 256-bit token can't be worked back from its hash. Since 8m, a sent email's stored copy says "[link removed after sending]". The only working links left in the database are in emails not yet sent (waiting or failing), and only until they expire.
2. `set_password()` calls `check_password_strength()` *before* it looks up or marks the link, so the short one is refused with 422 and the link stays unused.
3. Records, in person or by phone. His account has no email, so `notify_applicant()` writes no email (`applicant.email is None`). `GET /cases/{id}` gives staff `applicant_emailed: false` (`_applicant_emailed()` in backend/app/core/workflow/router.py).

### Step 8i
1. An applicant saves `{"quantity": "0"}` and, separately, `{"quantity": ""}`. What happens to each, and why the difference?
2. Where would you look to make "Exporter's country" no longer required at Submit, and does it need a migration?
3. Why can the desk's code assume the importer's name is never empty, even though the column is nullable?

#### Show answers
1. `"0"` is refused (422): it's given but has the wrong shape (`gt=0` on `quantity` in backend/app/modules/etls/schemas.py). `""` is saved as `null` by the `Blank` validator: an empty box is "not filled in", which is allowed on a draft.
2. `REQUIRED_FIELDS` in backend/app/modules/etls/service.py: remove the line. No migration: the column is already nullable since 0034. (Check the letter template copes with an empty value first.)
3. The only ways out of a draft or a return are Submit and Resubmit, and both carry the `etls_form_complete` check (migration 0034), which refuses while any required field is empty. The form can't be edited after that unless the case is returned, and then it must pass the check again.

### Step 8h
1. Records returns a case, but the commit fails (say, the database restarts). Does the applicant get an email? Why?
2. The PS cancels a signed letter. Why does no email go out, and which code decides that?
3. Two `notifier` workers run at the same time. Why can't they send the same email twice?

#### Show answers
1. No. The email is only a row in `core.notifications`, written by `notify_applicant()` inside the move's transaction; when that rolls back, the row goes with it, and the worker never sees it.
2. The cancel move has `applicant_visible = false`, so `applicant_timeline()` skips it, and `notify_applicant()` only writes an email when the timeline's newest line comes from this move (`entries[-1].event_id == event.id`).
3. `send_pending()` takes each row with `FOR UPDATE SKIP LOCKED`: while one worker holds a row, the other skips it, and once it's committed with `sent_at` set it's no longer "pending".

### Step 8g
1. Records opens a walk-in for fatou@example.gm, who has no account. Who is `created_by`, who is the audit actor of `case.created`, and can anyone log in as Fatou?
2. The Records officer who started a walk-in goes home. Can a second Records officer submit it? Can the desk? Which function decides?
3. Why does the walk-in endpoint check the post before looking up the email?

#### Show answers
1. `created_by` is Fatou's new applicant account; the audit actor is the Records officer, and the row has `walk_in_for_user_id`. Nobody can log in as her: since 8j her account has no password at all (`password_hash` is empty) until she uses the emailed link, and `authenticate()` refuses an account without one.
2. Yes, any holder of the workflow's walk-in post (`walk_in_position_id`, Records); no, the desk doesn't hold it. `acts_as_applicant()` in backend/app/core/workflow/service.py.
3. Otherwise anyone could create applicant accounts for any email just by trying; `open_walk_in()` refuses with 403 before `create_user()` runs, which the test `test_only_records_opens_walk_ins` checks.

### Step 8f
1. Someone prints the preview and tries to pass it off as the signed letter. What on the page and in the file gives it away?
2. Why does the PS's "Return to the desk" keep the ECOWAS ticks, while "Return to applicant" clears them?
3. Could the preview show a different quantity from the letter that's signed a minute later? Why not?

#### Show answers
1. The boxed red `PREVIEW_MARK` line at the top ("DRAFT FOR CHECKING - NOT SIGNED - NOT VALID AS A FACILITY LETTER"), no signer's name, and the PDF subject "Preview, not issued". And no issued letter with its checksum exists for it in `core.issued_documents`.
2. Only the return moves to the applicant carry the `clear_checklist` effect (migration 0029). The applicant can change the application after a return; the PS can't, so the desk's statements still describe the same application.
3. No. Both are built from `_form_fields()` in backend/app/modules/etls/letter.py, reading the same form rows, and the form can't be edited once submitted unless the case is returned to the applicant.

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
