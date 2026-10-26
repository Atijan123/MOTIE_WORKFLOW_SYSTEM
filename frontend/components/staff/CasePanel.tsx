import { notFound } from "next/navigation";

import { api, apiOrNull } from "@/lib/api";
import { longDate } from "@/lib/dates";
import { goods, hsCode } from "@/lib/labels";
import type { Case, FacilityLetter, HistoryEvent, Requirement } from "@/lib/types";

import { Actions } from "./Actions";
import { Documents } from "./Documents";
import { History } from "./History";

/** One case for staff: summary, documents, the step's own checks, the buttons, and the history. */
export async function CasePanel({ id }: { id: number }) {
  const kase = await apiOrNull<Case>(`/cases/${id}`);
  if (!kase) notFound();
  const [letter, documents, history] = await Promise.all([
    apiOrNull<FacilityLetter>(`/etls/facility-letters/${id}`),
    api<Requirement[]>(`/cases/${id}/documents`),
    api<HistoryEvent[]>(`/cases/${id}/history`),
  ]);
  const step = kase.status.code;
  // Records' tick: whoever may accept the originals (the API checks it again).
  const canSeeOriginals = kase.available_actions.some((a) => a.to_status === "originals_received" && step === "submitted");

  return (
    <div className="col-main">
      <section className="card" aria-label="Case">
        <div className="spread" style={{ alignItems: "flex-start" }}>
          <div className="stack">
            <span className="small muted">
              {kase.reference ?? "Draft"}
              {kase.submitted_at ? ` · submitted ${longDate(kase.submitted_at)}` : ""}
              {kase.entered_by ? " · walk-in" : ""}
            </span>
            <h2>{letter?.importer_name ?? "Application"}</h2>
            <span className="small muted">
              {goods(letter)}
              {letter?.exporter_name ? ` from ${letter.exporter_name}${letter.exporter_country ? `, ${letter.exporter_country}` : ""}` : ""}
            </span>
          </div>
          <span className={kase.on_hold ? "pill pill-warn" : "pill"}>{kase.on_hold ? "On hold" : kase.status.name}</span>
        </div>
        {kase.applicant_emailed === false ? (
          <div className="notice notice-info small">This applicant has no email: tell them of each step yourself.</div>
        ) : null}
        {letter ? <Summary letter={letter} /> : null}
        <Documents caseId={id} requirements={documents} canSeeOriginals={canSeeOriginals} />
        <Actions caseId={id} actions={kase.available_actions} />
      </section>
      <History events={history} />
    </div>
  );
}

function Summary({ letter }: { letter: FacilityLetter }) {
  return (
    <dl className="summary">
      <div>
        <dt>Importer</dt>
        <dd>{[letter.importer_name, letter.importer_address].filter(Boolean).join(", ")}</dd>
      </div>
      <div>
        <dt>Goods</dt>
        <dd>
          {goods(letter)}
          {letter.hs_code ? ` (HS ${hsCode(letter.hs_code)} declared)` : ""}
        </dd>
      </div>
      <div>
        <dt>Exporter</dt>
        <dd>
          {letter.exporter_name}, {letter.exporter_country} · ETLS approval {letter.exporter_etls_approval_number}
        </dd>
      </div>
      <div>
        <dt>Product approvals</dt>
        <dd>{letter.product_approval_numbers.join(", ")}</dd>
      </div>
      <div>
        <dt>Certificates of origin</dt>
        <dd>
          {letter.certificates_of_origin
            .map((c) => `${c.number}${c.issued_on ? ` (issued ${longDate(c.issued_on)}, valid until ${longDate(c.expires_on!)})` : ""}`)
            .join("; ")}
        </dd>
      </div>
    </dl>
  );
}
