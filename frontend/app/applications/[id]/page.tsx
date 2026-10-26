import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Timeline } from "@/components/Timeline";
import { api, apiOrNull } from "@/lib/api";
import { goods } from "@/lib/labels";
import type { Case, FacilityLetter, TimelineEntry } from "@/lib/types";

export const metadata: Metadata = { title: "Application status" };

// A3 (docs/design/Track.dc.html): one case, made for a phone.
export default async function TrackApplication({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  const kase = await apiOrNull<Case>(`/cases/${id}`);
  if (!kase) notFound();
  const [timeline, letter] = await Promise.all([
    api<TimelineEntry[]>(`/cases/${id}/timeline`),
    apiOrNull<FacilityLetter>(`/etls/facility-letters/${id}`),
  ]);
  const warn = kase.status.label.startsWith("Returned") || kase.status.label === "Rejected";

  return (
    <main className="page page-phone">
      <Link href="/applications" className="small">
        ← My applications
      </Link>
      <div className="stack">
        <span className="small muted">{kase.reference ?? "Draft, not sent yet"}</span>
        <h1 className="title" style={{ fontSize: 24 }}>
          {goods(letter)}
        </h1>
        {letter?.exporter_name ? (
          <span className="small muted">
            From {letter.exporter_name}
            {letter.exporter_country ? `, ${letter.exporter_country}` : ""}
          </span>
        ) : null}
      </div>
      <div className={`notice ${warn ? "notice-warn" : "notice-info"}`} role="status">
        <strong>{kase.status.label}</strong>
        {kase.status.explanation ? <span>{kase.status.explanation}</span> : null}
        {kase.applicant_message ? <span>“{kase.applicant_message}”</span> : null}
        {kase.status.editable ? (
          <Link href={`/applications/${id}/edit`} className="strong">
            {kase.reference ? "Fix and resubmit" : "Continue the application"}
          </Link>
        ) : null}
      </div>
      <section className="card">
        <Timeline entries={timeline} />
      </section>
      <p className="small muted">We email you when anything changes.</p>
    </main>
  );
}
