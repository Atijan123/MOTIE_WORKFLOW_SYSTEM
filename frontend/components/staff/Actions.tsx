import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { moveCase } from "@/app/staff/actions";
import type { Action } from "@/lib/types";

// Moves made elsewhere: the dispatch needs its date (Outgoing tab).
const ELSEWHERE = new Set(["sent_to_gra"]);

// The mock-ups' button wording for some moves; others use the workflow's own name.
const LABELS: Record<string, string> = {
  "Confirm originals received": "Accept: originals received",
  Verify: "Verify and send to PS",
  "Sign the facility letter": "Sign letter",
  "Return to the desk": "Return to desk",
  Reject: "Reject application",
};

/**
 * The case's buttons, one per move the API says this person may make, each
 * disabled with the API's reasons when something blocks it. One message box
 * and one minute box serve every button; the message goes only with a move
 * that tells the applicant something.
 */
export function Actions({ caseId, actions }: { caseId: number; actions: Action[] }) {
  const here = actions.filter((a) => !ELSEWHERE.has(a.to_status));
  if (!here.length) return null;
  const message = here.some((a) => a.requires_applicant_message);
  const minuteRequired = here.filter((a) => a.requires_comment).map((a) => LABELS[a.name] ?? a.name);
  const blocked = here.filter((a) => a.blocked_by?.length);
  return (
    <ActionForm action={moveCase.bind(null, caseId)} className="stack-lg" aria-label="Decide">
      {here.filter((a) => a.requires_applicant_message).map((a) => (
        <input type="hidden" name={`message_for_${a.to_status}`} value="yes" key={a.to_status} />
      ))}
      <div className="grid-2">
        {message ? (
          <label className="field">
            Message to the applicant, if returning or rejecting
            <textarea name="applicant_message" rows={3} maxLength={2000} placeholder="Shown to the applicant, e.g. The invoice scan is unreadable. Please upload a clearer copy." />
          </label>
        ) : null}
        <label className="field">
          Internal minute ({minuteRequired.length ? `required for: ${minuteRequired.join(", ")}` : "optional"})
          <textarea name="comment" rows={3} maxLength={2000} placeholder="Staff only" />
        </label>
      </div>
      <div className="row">
        {here.map((a, i) => (
          <SubmitButton
            key={a.to_status}
            name="to_status"
            value={a.to_status}
            className={i === 0 ? "btn btn-primary" : a.to_status === "rejected" ? "btn btn-danger" : "btn"}
            disabled={Boolean(a.blocked_by?.length)}
          >
            {LABELS[a.name] ?? a.name}
            {a.on_behalf_of ? " (acting)" : ""}
          </SubmitButton>
        ))}
      </div>
      {blocked.map((a) => (
        <div className="small warn-text" key={a.to_status}>
          <strong>{LABELS[a.name] ?? a.name}</strong> isn’t possible yet: {a.blocked_by!.join("; ")}.
        </div>
      ))}
      {here.flatMap((a) => a.warnings ?? []).map((w) => (
        <div className="small warn-text" key={w}>
          Please note: {w}.
        </div>
      ))}
    </ActionForm>
  );
}
