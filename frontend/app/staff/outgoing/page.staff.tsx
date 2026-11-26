import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { api } from "@/lib/api";
import { longDate, todayIso } from "@/lib/dates";
import type { CaseSummary } from "@/lib/types";

import { markSentToGra } from "../actions";

export const metadata: Metadata = { title: "Outgoing letters" };

type Letter = { id: number; status: string; issued_at: string; download_url: string };

// S1's Outgoing tab (docs/design/RecordsOutgoing.dc.html): signed letters to
// send to GRA. Download the stored letter, send it, then record the date.
export default async function Outgoing({ searchParams }: { searchParams: Promise<{ done?: string }> }) {
  const { done } = await searchParams;
  const signed = await api<CaseSummary[]>("/cases/queue?status=signed");
  const toSend = signed.filter((c) => c.available_actions.some((a) => a.to_status === "sent_to_gra"));
  const letters = await Promise.all(toSend.map((c) => api<Letter[]>(`/etls/facility-letters/${c.id}/letters`)));

  return (
    <>
      <div className="stack">
        <h1 className="title">Outgoing letters</h1>
        <p className="muted">Signed facility letters to dispatch to GRA. Print the stored letter, send it, then record the dispatch.</p>
      </div>
      {done ? (
        <div className="notice notice-done" role="status">
          {done}
        </div>
      ) : null}
      {toSend.length ? (
        <section className="card card-flush">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Importer and goods</th>
                  <th>Signed</th>
                  <th>Letter</th>
                  <th>Dispatch</th>
                </tr>
              </thead>
              <tbody>
                {toSend.map((c, i) => {
                  const current = letters[i].find((l) => l.status === "current");
                  const ref = c.reference?.replace("MOTIE/ETLS/", "") ?? `Case ${c.id}`;
                  return (
                    <tr key={c.id}>
                      <td>
                        <Link href={`/staff?case=${c.id}`} className="strong">
                          {ref}
                        </Link>
                      </td>
                      <td>
                        {c.applicant_name}
                        <br />
                        <span className="small muted">{c.summary}</span>
                      </td>
                      <td>{current ? longDate(current.issued_at) : "–"}</td>
                      <td>
                        <a href={`/files/etls/facility-letters/${c.id}/letter.pdf`}>Download PDF</a>
                      </td>
                      <td>
                        <ActionForm action={markSentToGra.bind(null, c.id)} className="row" aria-label={`Dispatch ${ref}`}>
                          <input type="date" name="dispatched_on" defaultValue={todayIso()} max={todayIso()} required aria-label={`Dispatch date for ${ref}`} style={{ width: 170 }} />
                          <SubmitButton className="btn btn-primary btn-small">Mark sent to GRA</SubmitButton>
                        </ActionForm>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <p className="muted">No signed letters waiting to be sent.</p>
      )}
      <p className="small muted">The importer is copied on each letter and sees “Letter sent to GRA” once you mark it.</p>
    </>
  );
}
