import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { markOriginalSeen } from "@/app/staff/actions";
import { longDate } from "@/lib/dates";
import type { Requirement } from "@/lib/types";

/** The case's documents with view links; for papers whose original must be seen, the Records tick (S1). */
export function Documents({ caseId, requirements, canSeeOriginals }: { caseId: number; requirements: Requirement[]; canSeeOriginals: boolean }) {
  const shown = requirements.filter((r) => r.applies !== false);
  return (
    <section className="stack-lg" aria-labelledby="docs">
      <h3 id="docs">Documents</h3>
      <ul className="items">
        {shown.map((r) => {
          const latest = r.documents[0];
          return (
            <li key={r.type}>
              <div className="stack">
                <span className="strong">{r.name}</span>
                {!latest ? <span className="small warn-text">Not uploaded{r.applies === null ? " (may not be needed)" : ""}</span> : null}
                {latest && r.original_required ? (
                  r.original_pending ? (
                    canSeeOriginals ? (
                      <ActionForm action={markOriginalSeen.bind(null, caseId, latest.id)} aria-label={`Original of ${r.name}`}>
                        <SubmitButton className="btn btn-small">Original seen in person</SubmitButton>
                      </ActionForm>
                    ) : (
                      <span className="small warn-text">Original not seen yet</span>
                    )
                  ) : (
                    <span className="small" style={{ color: "var(--done-text)" }}>
                      ✓ Original seen {latest.original_seen_at ? longDate(latest.original_seen_at) : ""}
                    </span>
                  )
                ) : null}
              </div>
              {latest ? (
                <a href={`/files/cases/${caseId}/documents/${latest.id}/file`} target="_blank" rel="noopener">
                  View
                </a>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
