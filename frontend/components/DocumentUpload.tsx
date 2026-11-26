// A document row with its upload box (A2 and Records' walk-in screen).
import { ActionForm, SubmitButton } from "@/components/ActionForm";
import type { FormState } from "@/lib/forms";
import type { Requirement } from "@/lib/types";

const Uploaded = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2F7A55" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" role="img" aria-label="Uploaded">
    <path d="M5 12l5 5L20 7" />
  </svg>
);
const NotYet = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9AA5AE" strokeWidth="2" role="img" aria-label="Not uploaded">
    <circle cx="12" cy="12" r="9" />
  </svg>
);

/** One document the case needs: whether it's there, and a file box to upload or replace it.
 * `upload` is the app's own server action (applicant: A2; Records: the walk-in screen). */
export function DocumentRow({
  requirement: r,
  upload,
  children,
}: {
  requirement: Requirement;
  upload: (state: FormState, data: FormData) => Promise<FormState>;
  children?: React.ReactNode; // more ways to add it (step 13g: the phone camera)
}) {
  const latest = r.documents[0];
  const undecided = r.applies === null;
  return (
    <li className={undecided ? "not-yet" : undefined}>
      <div className="stack">
        <div className="row" style={{ gap: 12 }}>
          {latest ? <Uploaded /> : <NotYet />}
          <span className="strong">{r.name}</span>
        </div>
        {r.original_required ? <span className="small warn-text" style={{ paddingLeft: 32 }}>Bring the original to Records. Copies are not accepted.</span> : null}
        {undecided ? (
          <span className="small muted" style={{ paddingLeft: 32 }}>
            Needed only in some cases. We’ll tell you once the Ministry has confirmed the HS code.
          </span>
        ) : null}
        {latest ? <span className="small muted" style={{ paddingLeft: 32 }}>{latest.filename}</span> : null}
      </div>
      <ActionForm action={upload} className="row" aria-label={`Upload ${r.name}`}>
        <input type="file" name="file" accept="application/pdf,image/png,image/jpeg" required aria-label={`File for ${r.name}`} style={{ maxWidth: 230 }} />
        <SubmitButton className="btn btn-small">{latest ? "Replace" : "Upload"}</SubmitButton>
      </ActionForm>
      {children}
    </li>
  );
}
