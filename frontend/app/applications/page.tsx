import type { Metadata } from "next";
import Link from "next/link";

import { Timeline } from "@/components/Timeline";
import { api, apiOrNull } from "@/lib/api";
import { longDate } from "@/lib/dates";
import { goods, pillClass } from "@/lib/labels";
import type { Case, CaseSummary, FacilityLetter, TimelineEntry } from "@/lib/types";

export const metadata: Metadata = { title: "My applications" };

// A1 (docs/design/Main.dc.html): the services, any case returned to me, my
// cases, and the selected case's timeline.
export default async function MyApplications({ searchParams }: { searchParams: Promise<{ case?: string }> }) {
  const cases = await api<CaseSummary[]>("/cases");
  const asked = Number((await searchParams).case);
  const selected = cases.find((c) => c.id === asked) ?? cases.find((c) => c.reference) ?? cases[0];
  const needsAction = cases.filter((c) => c.status.editable && c.applicant_message);

  return (
    <main className="page">
      <h1 className="title">ETLS services</h1>
      <section aria-label="Start a new application" className="grid-3">
        <ServiceCard who="Gambian producers" title="Get products approved under ETLS">
          Once approved by ECOWAS, your products can be exported duty-free across the region.
        </ServiceCard>
        <ServiceCard who="Gambian exporters" title="Request a certificate of origin">
          For a shipment of an approved product. One product per certificate.
        </ServiceCard>
        <ServiceCard who="Importers" title="Apply for a facility letter" href="/applications/new">
          For ETLS goods from another ECOWAS country, so GRA can clear them without duty.
        </ServiceCard>
      </section>

      <h2 className="title-2">My applications</h2>
      {needsAction.map((c) => (
        <div className="notice notice-warn spread" role="status" key={c.id}>
          <div className="stack">
            <strong>Action needed on {c.reference}</strong>
            <span>Returned by the Ministry: “{c.applicant_message}”</span>
          </div>
          <Link href={`/applications/${c.id}/edit`} className="strong">
            Fix and resubmit
          </Link>
        </div>
      ))}

      {cases.length === 0 ? (
        <p className="muted">You have no applications yet. Choose a service above to start one.</p>
      ) : (
        <div className="columns">
          <section className="col-main card card-flush">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Reference</th>
                    <th>Goods</th>
                    <th>Submitted</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => (
                    <tr key={c.id} className={c.id === selected?.id ? "selected" : undefined}>
                      <td>
                        <Link href={c.status.editable ? `/applications/${c.id}/edit` : `/applications?case=${c.id}`} className="strong">
                          {c.reference ? c.reference.replace("MOTIE/ETLS/", "") : "Draft"}
                        </Link>
                      </td>
                      <td>{c.summary}</td>
                      <td>{c.submitted_at ? longDate(c.submitted_at) : <span className="muted">Not sent yet</span>}</td>
                      <td>
                        <span className={pillClass(c.status.label)}>{c.status.label}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {selected ? <SelectedCase id={selected.id} /> : null}
        </div>
      )}
    </main>
  );
}

function ServiceCard({ who, title, href, children }: { who: string; title: string; href?: string; children: React.ReactNode }) {
  const body = (
    <>
      <span className="eyebrow">{who}</span>
      <span className="strong" style={{ fontSize: 18 }}>
        {title}
      </span>
      <span className="small muted">{children}</span>
      {href ? null : <span className="small muted">Coming soon</span>}
    </>
  );
  return href ? (
    <Link href={href} className="card" style={{ gap: 8, padding: 20, textDecoration: "none", color: "inherit" }}>
      {body}
    </Link>
  ) : (
    <div className="card" style={{ gap: 8, padding: 20, opacity: 0.7 }} aria-disabled="true">
      {body}
    </div>
  );
}

async function SelectedCase({ id }: { id: number }) {
  const [kase, timeline, letter] = await Promise.all([
    api<Case>(`/cases/${id}`),
    api<TimelineEntry[]>(`/cases/${id}/timeline`),
    apiOrNull<FacilityLetter>(`/etls/facility-letters/${id}`),
  ]);
  return (
    <aside className="col-side card" aria-label="Selected application">
      <div className="stack">
        <span className="small muted">{kase.reference ?? "Draft, not sent yet"}</span>
        <h2>{goods(letter)}</h2>
        {letter?.exporter_name ? (
          <span className="small muted">
            From {letter.exporter_name}
            {letter.exporter_country ? `, ${letter.exporter_country}` : ""}
          </span>
        ) : null}
      </div>
      <Timeline entries={timeline} explanation={kase.status.explanation} />
      <div className="spread small">
        <span className="muted">We’ll email you at each step.</span>
        <Link href={`/applications/${id}`}>Open on its own page</Link>
      </div>
    </aside>
  );
}
