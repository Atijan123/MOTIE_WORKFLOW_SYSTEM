import { dayRange, shortDateTime } from "@/lib/dates";
import type { HistoryEvent } from "@/lib/types";

// Plain words for the audit log's actions; a move shows its own name.
const WORDS: Record<string, string> = {
  "case.created": "Opened",
  "case.form_updated": "Form changed",
  "case.reference_assigned": "Reference given",
  "case.document_uploaded": "Document uploaded",
  "case.original_seen": "Original seen in person",
  "case.flag_raised": "Put on hold",
  "case.flag_resolved": "Hold cleared",
  "case.hs_code_confirmed": "HS code confirmed",
  "case.ticked": "Checked",
  "case.unticked": "Check removed",
  "case.document_issued": "Letter issued and stored",
  "case.document_cancelled": "Letter cancelled",
  "case.letter_dispatched": "Dispatch date recorded",
};

function what(e: HistoryEvent): string {
  const d = e.details as Record<string, string | null | undefined>;
  if (e.action === "case.status_changed") return d.transition ?? "Moved";
  const base = WORDS[e.action] ?? e.action.replace(/^case\./, "").replaceAll("_", " ");
  if (e.action === "case.flag_raised" && d.message) return `${base}: ${d.message}`;
  if (e.action === "case.flag_resolved" && d.resolution) return `${base}: ${d.resolution}`;
  if (e.action === "case.hs_code_confirmed" && d.confirmed) return `${base}: ${d.confirmed}`;
  if (e.action === "case.reference_assigned" && d.reference) return `${base}: ${d.reference}`;
  if (e.action === "case.created" && (e.details as Record<string, unknown>).walk_in_for_user_id) return "Opened for a walk-in applicant";
  return base;
}

function who(e: HistoryEvent): React.ReactNode {
  if (!e.actor_name) return "System";
  const as = e.actor_title ? `${e.actor_name}, ${e.actor_title}` : e.actor_name;
  if (!e.acting_for) return as;
  if (e.acting_for.basis === "signatory") {
    // "Awa Bah, authorised signatory for the Director …, in the Director's absence (… away …)"
    const away = e.acting_for.absences.map((a) => `${a.person} away ${dayRange(a.starts_on, a.ends_on)}`).join("; ");
    return (
      <>
        {as}, <b>authorised signatory for the {e.acting_for.title}, {e.acting_for.in_absence}</b>
        {away ? ` (${away})` : ""}
      </>
    );
  }
  const why =
    e.acting_for.delegation
      ? `delegated ${dayRange(e.acting_for.delegation.starts_on, e.acting_for.delegation.ends_on)}`
      : e.acting_for.absences.map((a) => `${a.person} away ${dayRange(a.starts_on, a.ends_on)}`).join("; ");
  return (
    <>
      {as}, <b>acting for the {e.acting_for.title}</b>
      {why ? ` (${why})` : ""}
    </>
  );
}

/** The staff history panel: newest first, with names, posts and "acting for". */
export function History({ events }: { events: HistoryEvent[] }) {
  return (
    <aside className="col-side card" aria-labelledby="history">
      <h2 id="history">History</h2>
      <ol className="history">
        {events.map((e, i) => {
          const d = e.details as Record<string, string | null | undefined>;
          return (
            <li key={i}>
              <span className="strong">{what(e)}</span>
              {d.comment ? <span className="small">Minute: “{d.comment}”</span> : null}
              {d.applicant_message ? <span className="small">Told the applicant: “{d.applicant_message}”</span> : null}
              <span className="small muted">
                {who(e)} · {shortDateTime(e.occurred_at)}
              </span>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
