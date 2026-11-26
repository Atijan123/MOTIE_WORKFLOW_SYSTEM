import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { DocumentRow } from "@/components/DocumentUpload";
import { api, apiOrNull } from "@/lib/api";
import { longDate } from "@/lib/dates";
import type { Case, FacilityLetter, Requirement } from "@/lib/types";

import { saveDraft, submitApplication, uploadDocument } from "../../actions";
import { ApplicationForm, type FormOptions } from "@/components/ApplicationForm";

export const metadata: Metadata = { title: "Your facility letter application" };

// A2 (docs/design/Apply.dc.html) for a saved draft or a returned case: the
// form, the documents, and Submit with what's still missing.
export default async function EditApplication({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ saved?: string }>;
}) {
  const id = Number((await params).id);
  const letter = await apiOrNull<FacilityLetter>(`/etls/facility-letters/${id}`);
  if (!letter) notFound();
  const [kase, documents, options] = await Promise.all([
    api<Case>(`/cases/${id}`),
    api<Requirement[]>(`/cases/${id}/documents`),
    api<FormOptions>("/etls/form-options"),
  ]);
  if (!kase.status.editable) redirect(`/applications/${id}`);
  const { saved } = await searchParams;

  const submit = kase.available_actions.find((a) => a.to_status === "submitted");
  const blocked = submit?.blocked_by ?? [];
  const returned = kase.status.label.startsWith("Returned");
  const expiries = letter.certificates_of_origin.filter((c) => c.expires_on);

  return (
    <main className="page page-narrow">
      <Link href="/applications" className="small">
        ← My applications
      </Link>
      <div className="stack">
        <span className="small muted">{kase.reference ?? "Draft, not sent yet"}</span>
        <h1 className="title">Apply for an ETLS facility letter</h1>
      </div>
      {returned && kase.applicant_message ? (
        <div className="notice notice-warn" role="status">
          <strong>Returned by the Ministry</strong>
          <span>“{kase.applicant_message}” Fix what’s asked, then resubmit below.</span>
        </div>
      ) : null}
      {saved ? (
        <div className="notice notice-done" role="status">
          Draft saved.
        </div>
      ) : null}

      <ApplicationForm letter={letter} options={options} action={saveDraft.bind(null, id)}>
        <p className="small muted">
          A certificate is valid for six months from its issue date.
          {expiries.map((c) => ` ${c.number} is valid until ${longDate(c.expires_on!)}.`).join("")}
        </p>
      </ApplicationForm>

      <section className="card" aria-labelledby="documents">
        <div className="stack">
          <h2 id="documents">4. Documents</h2>
          <p className="small muted">PDF, PNG or JPEG, up to 10 MB each.</p>
        </div>
        <ul className="items">
          {documents
            .filter((d) => d.applies !== false)
            .map((d) => (
              <DocumentRow key={d.type} requirement={d} upload={uploadDocument.bind(null, id, d.type)} />
            ))}
        </ul>
      </section>

      <section className="card" aria-label="Submit">
        {blocked.length ? (
          <div className="stack">
            <p className="warn-text strong">
              {blocked.length} {blocked.length === 1 ? "thing" : "things"} still to do before you can submit:
            </p>
            <ul className="small warn-text" style={{ margin: 0, paddingLeft: 20 }}>
              {blocked.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="strong">Everything is filled in. Check it, then submit.</p>
        )}
        {submit?.warnings?.length ? (
          <div className="notice notice-warn">
            {submit.warnings.map((w) => (
              <span key={w}>Please note: {w}.</span>
            ))}
          </div>
        ) : null}
        <ActionForm action={submitApplication.bind(null, id)} className="row">
          <SubmitButton disabled={!submit || blocked.length > 0}>{returned ? "Resubmit application" : "Submit application"}</SubmitButton>
          <span className="small muted">Save the draft first if you changed anything above.</span>
        </ActionForm>
      </section>
    </main>
  );
}
