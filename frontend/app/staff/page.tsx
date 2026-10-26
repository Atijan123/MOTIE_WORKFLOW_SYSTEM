import type { Metadata } from "next";
import Link from "next/link";

import { CasePanel } from "@/components/staff/CasePanel";
import { api } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

export const metadata: Metadata = { title: "My queue" };

// S1/S2/S3's list (docs/design/Records.dc.html): the cases waiting for me,
// oldest first, and the selected one beside it. What the panel shows depends
// on the step the case is at and on what the API lets me do.
export default async function Queue({ searchParams }: { searchParams: Promise<{ case?: string; done?: string }> }) {
  const sp = await searchParams;
  const queue = await api<CaseSummary[]>("/cases/queue");
  // Letters waiting only to be dispatched are on the Outgoing tab.
  const work = queue.filter((c) => !c.available_actions.length || c.available_actions.some((a) => a.to_status !== "sent_to_gra"));
  const selectedId = Number(sp.case) || work[0]?.id;

  return (
    <>
      <h1 className="title">My queue</h1>
      {sp.done ? (
        <div className="notice notice-done" role="status">
          {sp.done}
        </div>
      ) : null}
      <div className="columns">
        <section className="col-list card card-flush" aria-labelledby="waiting">
          <h2 className="card-head" id="waiting">
            Waiting, oldest first
          </h2>
          {work.length ? (
            <ul className="queue">
              {work.map((c) => (
                <li key={c.id} className={c.id === selectedId ? "selected" : undefined}>
                  <Link href={`/staff?case=${c.id}`} aria-current={c.id === selectedId ? "true" : undefined}>
                    {c.reference?.replace("MOTIE/ETLS/", "") ?? `Case ${c.id}`}
                  </Link>
                  <span className="small muted">{[c.service, c.applicant_name, c.summary].filter(Boolean).join(" · ")}</span>
                  <span className={`small ${c.days_waiting >= 2 ? "warn-text" : "muted"}`}>
                    {c.status.name} · {c.days_waiting ? `waiting ${c.days_waiting} day${c.days_waiting === 1 ? "" : "s"}` : "today"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted" style={{ padding: 16 }}>
              Nothing waiting for you.
            </p>
          )}
        </section>
        {selectedId ? <CasePanel id={selectedId} /> : null}
      </div>
    </>
  );
}
