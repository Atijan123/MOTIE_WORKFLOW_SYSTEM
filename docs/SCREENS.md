# Screens spec: ETLS services

The agreed screen designs, written down so the backend and frontend can be checked against them.
Source: the design canvas "MOTIE ETLS Facility Letter Screens" (16 screens), October 2026.
Items marked `[CONFIRM]` are assumptions still to check with the ETLS desk.

## Global rules (all screens)

- **Every application goes to Records first.** No service skips Records.
- **Applicants see plain status labels**, never internal step names or staff names. Each workflow needs a mapping from internal status to applicant label (listed per service below).
- **Every case page for staff shows its history** from the audit log, newest first, including "acting for [position]" and the absence or delegation it relied on.
- **Acting banner:** when a staff member is acting for an absent position, a banner says so on every screen, e.g. "You are acting for the Director of Industry & Investment (absent 20th–24th October)".
- **Disabled actions explain why** (e.g. "Tick ‘Original seen’ to accept"). The API must be able to say what is blocking a move.
- **Returning needs a written reason.** A return has two texts: a **message to the applicant** (shown to them) and an optional **internal minute** (staff only). Rejecting also needs a reason.
- **Drafts:** every application starts as a draft the applicant can edit and upload to; "Submit" moves it to Records. A returned case becomes editable again and is resubmitted with the same reference and history.
- **Case history is newest first**, with the actor's name and post title, and absence or delegation dates when someone acted for another post.
- **Dates** in the Ministry format: "16th October, 2026".
- **Case reference numbers** per service, a sequence per service per year, assigned when the applicant submits: `MOTIE/ETLS/FL/2026/0001` (facility letter), `MOTIE/ETLS/AP/…` (approval), `MOTIE/ETLS/CO/…` (certificate of origin). This is the tracking number shown to applicants and staff.
- **The Ministry's registry file reference** (e.g. `ADM 151/420/01/PART IV`) is separate: it is what the facility letter prints at the top. Kept as a setting until the desk explains its parts `[CONFIRM]`. A real server must have it set: until then the Director's Sign is disabled, saying why (built 8k).
- **Uploads:** PDF, PNG or JPEG, max 10 MB, type checked from content.
- **Email (one service for everything):** the system sends email through an outbox and a background sender, never inside the user's request. Recipients can be applicants, staff, or **external contacts with no account** (e.g. NAC members from other institutions). Every email is logged: to whom, what, when, delivery status, linked to its case or meeting. Wording comes from editable templates.
  - Applicants: at each status change and when a case is returned.
  - Staff: optionally when a case lands in their queue (daily digest, not one email per case) `[CONFIRM]`.
  - NAC members: meeting invitations, packs, inspection notices, minutes and decisions (S6, S7).
- **Sensitive content is never attached.** Meeting packs contain companies' cost figures, so emails carry a **link** to download the pack, valid for a limited time and logged when opened, not the file itself. Notification emails say what changed, not the case details.
- **Queues** show how long each case has waited at its current step.
- **Walk-ins:** Records can create any application on behalf of an applicant; recorded as such.

## Applicant screens

### A1. Services and my applications (`Main`)
- Three service cards: ETLS approval (Gambian producers), certificate of origin (Gambian exporters), facility letter (importers).
- Notice for any case returned to me, with the reason and a "Fix and resubmit" link.
- Table of my cases: reference, goods, submitted date, applicant status label.
- Selected case: timeline of applicant status labels with dates.

### A2. Facility letter application (`Apply`)
- Importer: business name, address.
- Goods: product, quantity (number), unit, HS code (optional).
- Exporter: name, country, ETLS approval number, one or more product approval numbers, one or more certificates of origin, **each with its number and issue date** (so the system can check the six-month validity).
- Documents checklist: business registration, annual returns certificate, certificate of origin (with note: bring the original to Records), invoice, export declaration, receipt (cement only, shown as "not known yet" until the **desk confirms** the HS code; a code the applicant declares does not decide it).
- Save draft, with any fields still empty (built 8i); Submit is disabled until the form is complete and the required documents are uploaded, with a count of what is missing.
- **Certificate warning at submission:** if a certificate of origin expires (six months after its issue date) within 30 days, the applicant is warned but may still submit (built 8c).
- **Applicant labels (facility letter):** Draft → Submitted ("Bring the original certificate of origin to Records") → Originals checked → Being verified → Awaiting signature → Letter signed → Letter sent to GRA. Plus: Returned: action needed (with the message), Rejected (with the reason). Cancelling a signed letter is invisible to the applicant: the cancel itself is hidden and the case simply shows "Being verified" again. If the cancelled letter had already been sent to GRA, the corrected letter's "sent to GRA" shows as **"Corrected letter issued"** (decided 2026-10-24).

### A3. Status on a phone (`Track`)
- One case: reference, goods, exporter, current applicant status with a one-line explanation, timeline.

### A4. ETLS approval application (`ApplyApproval`), following the ECOWAS application form
- **Part I, identity of enterprise:** business name, registration number, head office address, P.O. box, telephone, email, sector and branch of activity, legal status (select), number and location of factories, preferential treatment granted by The Gambia (optional), existing ETLS approval number (optional).
- **Part II, products (one or more), each with:** trade description, tariff item (HS code), brand name or label, origin criterion claimed (wholly produced / change of tariff position / value added), value added % (when value added).
- **Part III:** short description of the manufacturing process.
- **Documents:** application letter; ECOWAS application form completed and signed (parts I–IV), with a link to the blank form; business registration; company statutes; amortisation schedule; text granting preferential treatment (only if listed); official tariff classification documents (optional).
- Note: bring a sample of each product to Records.

### A5. Approval progress and approved products (`ApprovalStatus`)
- Applicant labels: Submitted → Accepted by the Ministry → Technical review → Factory visit → National Approvals Committee decision → Sent to the ECOWAS Commission → Approved by ECOWAS.
- Factory visit notice with date when scheduled.
- My approved products: product, ECOWAS enterprise and product approval numbers, "Request a certificate of origin" button. Products still in progress shown as such.

### A6. Certificate of origin request (`RequestCO`), box numbers as on the ECOWAS certificate
- Choose an approved product (only ECOWAS-approved products from the register).
- Auto-filled from the register: box 1 producer and registration number, box 3 origin criterion and scheme, box 5 tariff nomenclature, box 6 approval number.
- Entered: box 2 consignee name and address, box 4 quantity, nature of goods and number of packages, box 7 gross weight or other measure, box 8 invoice value; commercial invoice upload.
- Box 9 declaration: name of person declaring, place, declaration checkbox (date is the submission date).
- Applicant labels: Submitted → Accepted by Records → Being checked → Certified by the Ministry → Certified by Customs → Ready to collect → Collected.

## Staff screens: facility letters

Route: Records (originals seen) → ETLS officer (verify) → **Director of Industry & Investment signs "For: Permanent Secretary"** (the PS does not sign facility letters). **When the Director is absent, any officer on the authorised signatories list can sign** (see "Authorised signatories" below). **Every facility letter, cement included, follows this route**; cement only adds the receipt to the documents, decided by the HS code the desk confirms. Every signature records who signed and, in the audit log and the stored letter, that they signed in the Director's absence. → **one stored letter, three copies: Records' file copy, GRA's copy (Records dispatches it from Outgoing), and the applicant's copy (downloadable from their case page once GRA's copy is marked sent)** → sent. "Letter sent to GRA" is the final status; there is no separate manual "Close" step unless GRA turns out to report back `[CONFIRM]`. How the applicant collects a paper copy, if they need one, `[CONFIRM]`.

### S1. Records queue (`Records`)
- Queue of all services, oldest first, with service, applicant, goods and days waiting.
- Case: documents list with view links; for facility letters, "Original seen in person" on the certificate of origin.
- Accept (disabled until originals seen) or return to applicant with reason.
- **Outgoing tab:** signed facility letters to dispatch. Download the stored letter, then "Mark sent to GRA" with the dispatch date.

### S2. ETLS desk verification (`Desk`)
- Duplicate certificate flag: which earlier case used the number, its status and date; finding (required) to clear; **or reject or return directly while the flag is open** (the reason also resolves the flag; a resubmission is checked again) `[CONFIRM]` (built 8l).
- The check also searches the **imported historical letters** (S13): the flag says "used on historical letter [ref], [date], [importer]", linking to that letter's page.
- Application summary.
- HS code: enter or confirm; shows whether the cement receipt applies.
- Checks against the ECOWAS ETLS list, each a recorded tick: exporter approval listed; product approval covers the goods.
- Certificate validity is **computed** from the issue dates on the form: Verify is blocked while any certificate is more than six months past its issue date (decided 2026-10-24, built 8c). Whether GRA also needs it still valid on the day of clearance is not confirmed `[CONFIRM]`.
- Verify (disabled until flag cleared, HS code confirmed, checks ticked, documents complete) or return to applicant.
- History panel.

### S3. Director signs the letter for the PS (`PS` board, to be renamed)
- Letters awaiting signature; summary of checks done (originals seen, ECOWAS list checked, no duplicates).
- Letter preview in the Ministry's wording, signature block "[Name] / For: Permanent Secretary". The letter does not print "in the Director's absence"; the audit log and the stored letter record it.
- Sign (stores the letter) or return to the ETLS officer; any officer on the list may return a letter nobody has signed yet. **Cancel and reissue a signed letter: only the Director, or the officer who signed that letter** `[CONFIRM]`.
- Shown in the Director's queue; while the Director is recorded absent, also in the queue of every officer on the authorised signatories list (S12). The first to sign takes it; the others' queues clear.
- Signing stores one letter and records its three copies: Records' file copy; GRA's copy, in Records' Outgoing tab to dispatch; the applicant's copy, downloadable from their case page (A1, A3) once GRA's copy is marked sent. A cancelled letter's copies stay on record; the corrected letter gets three of its own.

### S12. Authorised signatories (Director's office)
- **The Director's office keeps the list** of officers authorised to sign for the Director when the Director is absent. There is **no fixed rule** that a DPS acts; DPSs, senior officers and others can be on the list.
- The list names officers (people), each with: post, date added, date removed, added by. Changes are audited.
- Applies to **facility letters and ETLS approvals** (sign and assign). One list for both unless the Director's office wants separate lists `[CONFIRM]`.
- While the Director is recorded absent, the item appears in the queue of every officer on the list; the first to act takes it and it leaves the others' queues.
- The audit log and the stored letter record the officer's name and "in the Director's absence". The printed letter shows only their name and "For: Permanent Secretary", as the Ministry's letters do.
- Cancel and reissue of a letter a signatory signed: that officer or the Director only `[CONFIRM]`. Any officer on the list may return a letter not yet signed.
- **Cement facility letters are no exception:** they are signed like any other (decided 2026-11-04). Only the receipt requirement differs (A2).

### S11. Absences and delegations (all staff)
- **My absences:** a post holder records their own absence (dates, reason optional) or delegates to another post (dates, all workflows or one). For the Director: shows that officers on the authorised signatories list can sign while they are away. For other posts: shows who acts for them under the succession order.
- **Record for someone else:** staff with the `absence_recorder` role (PS's office, HR `[CONFIRM]`) record an absence on a post holder's behalf; audited as "recorded by".
- List of current and upcoming absences, with revoke for delegations.

### S13. ETLS statistics (`Statistics`), the Director and the `stats_viewer` role
- **History:** the Ministry's Excel register of earlier facility letters (sheets "Facility letters", one row per letter; "Goods lines"; "Data checks") is imported from the server's command line (`scripts/import-history.sh`, the file read in place, never copied into the system's code). Historical letters are read-only, are not cases and have no workflow. Every column is kept as written, with the scan file and page it came from. Where a second paper copy of a letter sits ("Also filed at") is kept as text on that letter, not as another letter. Re-running the import replaces the previous one.
- **Figures**, live and historical letters together, each saying **how many letters it is based on**:
  - letters by month and by year (letters with no readable date are counted and said, but not placed);
  - top importers, exporters, exporter countries and products;
  - quantities by category and unit (**different units are never added together**);
  - certificates of origin used on more than one letter;
  - letters by signatory.
- **Filters:** date range and importer. **Download the filtered table as CSV**, one row per letter.
- **Historical letter page:** every column as written (including "Also filed at"), goods lines, certificates, and the **data check notes** from the register's "Data checks" sheet linked to it. Data checks the import can't link to a letter are listed on the statistics page.
- Live applications record no "category": they show as "Not recorded" `[CONFIRM]`.

## Staff screens: ETLS approval

The approval workflow is a new `etls_approval` workflow; the placeholder `etls_application` is retired.
**Per-product outcomes:** the case status tracks the file (with NAC, with ECOWAS, done); each product carries its own decision (NAC: approve / not approve / defer; ECOWAS: approved / not approved).

Route: Records (samples received) → Minister → PS → Director of Industry & Investment (signs and assigns; when absent, any officer on the authorised signatories list) → officer (technical review and inspection) → NAC → ECOWAS submission → ECOWAS outcome → approved register.

### S4. Minute a file (`Minute`), used by the Minister and the PS
- Summary: products with tariff items, criteria and value added; documents complete; samples received.
- Minute text; minute to the next position (Minister → PS, PS → Director); return to Records.

### S5. Sign and assign (`Assign`), Director or an authorised signatory acting
- Minutes so far; choose officer; minute to officer; sign and assign, or return to PS.

### S6. Technical review (`Review`), assigned officer
- Per product: finding (meets criterion / query applicant / does not meet).
- Cost price limits from part IV of the form: officer enters ex-factory cost price, salaries and wages, external works and services, financial charges; system shows each as % of cost price against the form's limits (20%, 10%, 3%) and flags any over the limit.
- Factory inspection: date (shown to applicant), inspection team chosen from the NAC members list, report upload. "Email the inspection notice" sends the date, place and company to the team. `[CONFIRM]` inspections are by the NAC.
- Recommendation to the committee; send to NAC (disabled until inspection report uploaded) or ask the applicant for information.

### S7. NAC decisions (`NAC`), secretary records the meeting
- **NAC members list** (kept by the secretary): name, institution, email, phone, active or not. Members do not need system accounts.
- Meeting date, time and place; downloadable meeting pack (PDF).
- **Members for this meeting:** each member with invitation status (not sent / sent / delivered / failed), pack link opened or not, and attendance (ticked after the meeting).
- "Email invitation and pack link" to all or selected members; "Send reminder" the day before `[CONFIRM]`; "Email minutes and decisions" after the meeting.
- **Decision per product**, not per case: approve / not approve / defer, with reason for not approve or defer.
- Signed minutes upload; record decisions. Approved products go to the portal holder; applicants are told of other decisions.

### S8. ECOWAS submission and outcome (`Ecowas`), portal login holder
- Products approved by the NAC: download submission pack, mark as sent (date).
- Record ECOWAS decision per product: approved / not approved, enterprise approval number, product approval number, notification date, notification letter upload. Saving adds approved products to the **approved products register** and notifies the applicant.

## Staff screens: certificates of origin

Route: Records (complete) → ETLS desk (verify) → authorised officer certifies box 10 `[CONFIRM: Director of Industry & Investment]` → Customs certification recorded (box 11) → collected.

### S9. Certificate verification (`CODesk`)
- Table comparing request with register and invoice: box 6 approval number, box 5 tariff, box 3 criterion, box 4 goods and packages, box 8 invoice value; each matches or is flagged.
- Note for the exporter; verified (send for certification) or return to exporter.

### S10. Certify, Customs and collection (`COCertify`)
- Box 10: certified by the authorised officer, with date; certificate number `[CONFIRM: pre-printed form number]`; reprint only as "Duplicate".
- Box 11: export document model number, dated, Customs place, date certified by Customs.
- Collection: who collected the single original and when.
- Certificate details panel; valid until six months from issue.
- One certificate covers one product.
