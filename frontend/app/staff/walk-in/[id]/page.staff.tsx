// Records finishes a walk-in application: the form, the documents, Submit (step 13b).
import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { ApplicationForm, type FormOptions } from "@/components/ApplicationForm";
import { DocumentRow } from "@/components/DocumentUpload";
import { scannedPages } from "@/components/staff/CasePanel";
import { ScanWithCamera } from "@/components/staff/ScanWithCamera";
import { api, apiOrNull } from "@/lib/api";
import { requireUser } from "@/lib/session";
import type { Case, FacilityLetter, Requirement } from "@/lib/types";

import { saveWalkIn, submitWalkIn, uploadWalkInDocument } from "../actions";

export const metadata: Metadata = { title: "Walk-in application" };

export default async function WalkIn({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ saved?: string }>;
}) {
  await requireUser("staff");
  const id = Number((await params).id);
  const letter = await apiOrNull<FacilityLetter>(`/etls/facility-letters/${id}`);
  if (!letter) notFound();
  const [kase, documents, options] = await Promise.all([
    api<Case>(`/cases/${id}`),
    api<Requirement[]>(`/cases/${id}/documents`),
    api<FormOptions>("/etls/form-options"),
  ]);
  const submit = kase.available_actions.find((a) => a.to_status === "submitted");
  // Submitted already, or not one Records may edit: the usual case page.
  if (!submit) redirect(`/staff?case=${id}`);
  const blocked = submit.blocked_by ?? [];
  const scan = await scannedPages(id, documents);
  const { saved } = await searchParams;

  return (
    <>
      <Link href="/staff" className="small">
        ← My queue
      </Link>
      <h1 className="title">Walk-in application</h1>
      {saved ? (
        <div className="notice notice-done" role="status">
          Saved.
        </div>
      ) : null}
      <ApplicationForm letter={letter} options={options} action={saveWalkIn.bind(null, id)} />

      <section className="card" aria-labelledby="documents">
        <div className="stack">
          <h2 id="documents">Documents</h2>
          <p className="small muted">PDF, PNG or JPEG, up to 10 MB each. Scan the applicant’s papers, or photograph them.</p>
        </div>
        <ul className="items">
          {documents
            .filter((d) => d.applies !== false)
            .map((d) => (
              <DocumentRow key={d.type} requirement={d} upload={uploadWalkInDocument.bind(null, id, d.type)}>
                <ScanWithCamera caseId={id} type={d.type} name={d.name} initialPages={scan[d.type] ?? []} page={`/staff/walk-in/${id}`} />
              </DocumentRow>
            ))}
        </ul>
      </section>

      <section className="card" aria-label="Submit">
        {blocked.length ? (
          <div className="stack">
            <p className="warn-text strong">Still to do before it can be submitted:</p>
            <ul className="small warn-text" style={{ margin: 0, paddingLeft: 20 }}>
              {blocked.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="strong">Everything is filled in. Check it with the applicant, then submit.</p>
        )}
        <ActionForm action={submitWalkIn.bind(null, id)} className="row">
          <SubmitButton disabled={blocked.length > 0}>Submit application</SubmitButton>
          <span className="small muted">Save first if you changed anything above.</span>
        </ActionForm>
      </section>
    </>
  );
}
