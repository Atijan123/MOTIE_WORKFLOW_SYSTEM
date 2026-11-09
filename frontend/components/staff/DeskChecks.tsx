import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { confirmHsCode, resolveFlag, setTick } from "@/app/staff/actions";
import { api } from "@/lib/api";
import { longDate } from "@/lib/dates";
import { hsCode } from "@/lib/labels";
import type { FacilityLetter, Requirement } from "@/lib/types";

type Flag = { id: number; code: string; message: string; blocking: boolean; resolved_at: string | null };
type Duplicate = {
  number: string;
  other_cases: { case_id: number; reference: string; status: string; submitted_at: string; importer_name: string }[];
  // Letters from the imported register (step 11).
  historical_letters: { letter_id: number; described: string }[];
};
type Tick = { code: string; label: string; at_current_step: boolean; ticked: boolean; ticked_at: string | null };

/** S2 (docs/design/Desk.dc.html): the duplicate flag, the HS code and the ECOWAS list ticks. */
export async function DeskChecks({ caseId, letter, documents }: { caseId: number; letter: FacilityLetter; documents: Requirement[] }) {
  const [flags, duplicates, ticks] = await Promise.all([
    api<Flag[]>(`/cases/${caseId}/flags`),
    api<Duplicate[]>(`/etls/facility-letters/${caseId}/duplicates`),
    api<Tick[]>(`/cases/${caseId}/checklist`),
  ]);
  const open = flags.filter((f) => !f.resolved_at && f.blocking);
  const receipt = documents.find((d) => d.type === "cement_receipt");
  const receiptText =
    receipt?.applies === true ? "Cement receipt: needed for this code." : receipt?.applies === false ? "Cement receipt: not needed for this code." : "Cement receipt: decided once you confirm the code.";

  return (
    <>
      {open.map((f) => (
        <section className="notice notice-warn stack-lg" key={f.id} aria-label="On hold">
          <strong>{f.message}</strong>
          {duplicates.map((d) => (
            <span key={d.number}>
              Certificate {d.number} is also on{" "}
              {d.other_cases.map((o, i) => (
                <span key={o.case_id}>
                  {i ? "; " : ""}
                  <a href={`/staff?case=${o.case_id}`}>{o.reference.replace("MOTIE/ETLS/", "")}</a> ({o.importer_name}, {o.status.toLowerCase()},
                  submitted {longDate(o.submitted_at)})
                </span>
              ))}
              {d.historical_letters.map((h, i) => (
                <span key={h.letter_id}>
                  {d.other_cases.length || i ? "; " : ""}
                  used on <a href={`/staff/history/${h.letter_id}`}>{h.described}</a>
                </span>
              ))}
              .
            </span>
          ))}
          <ActionForm action={resolveFlag.bind(null, caseId, f.id)} className="stack-lg">
            <label className="field">
              Your finding (required)
              <textarea name="resolution" rows={2} required maxLength={2000} placeholder="e.g. Checked with the exporter: number reused in error; certificate is genuine and covers this consignment." />
            </label>
            <div className="row">
              <SubmitButton>Clear flag and continue</SubmitButton>
              <span className="small">Or reject or return the application below: your reason there also clears the flag.</span>
            </div>
          </ActionForm>
        </section>
      ))}

      <section className="stack-lg" aria-labelledby="checks">
        <h3 id="checks">Checks before verifying</h3>
        <ActionForm action={confirmHsCode.bind(null, caseId)} className="row row-end">
          <label className="field" style={{ width: 200 }}>
            HS code
            <input name="hs_code" defaultValue={hsCode(letter.hs_code_confirmed ?? letter.hs_code ?? "")} required maxLength={20} />
          </label>
          <SubmitButton className="btn">{letter.hs_code_confirmed ? "Change code" : "Confirm code"}</SubmitButton>
          <span className="small muted">
            {letter.hs_code_confirmed
              ? `Confirmed: ${hsCode(letter.hs_code_confirmed)}. `
              : letter.hs_code
                ? `Applicant declared ${hsCode(letter.hs_code)}. `
                : "Applicant left this blank. "}
            {receiptText}
          </span>
        </ActionForm>
        <fieldset>
          <legend>Checked on the ECOWAS ETLS list</legend>
          {ticks
            .filter((t) => t.at_current_step)
            .map((t) => (
              <ActionForm action={setTick.bind(null, caseId, t.code, !t.ticked)} className="row" key={t.code}>
                <span aria-hidden="true" style={{ fontSize: 22 }}>
                  {t.ticked ? "☑" : "☐"}
                </span>
                <span>{t.label}</span>
                <SubmitButton className="btn btn-small">{t.ticked ? "Undo" : "Mark as checked"}</SubmitButton>
              </ActionForm>
            ))}
        </fieldset>
      </section>
    </>
  );
}
