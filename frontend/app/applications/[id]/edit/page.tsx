import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { api, apiOrNull } from "@/lib/api";
import { longDate } from "@/lib/dates";
import type { Case, FacilityLetter, Requirement } from "@/lib/types";

import { saveDraft, submitApplication, uploadDocument } from "../../actions";
import { ApplicationForm } from "../../ApplicationForm";

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
  const [kase, documents] = await Promise.all([api<Case>(`/cases/${id}`), api<Requirement[]>(`/cases/${id}/documents`)]);
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

      <ApplicationForm letter={letter} action={saveDraft.bind(null, id)}>
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
              <DocumentRow key={d.type} caseId={id} requirement={d} />
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

const Uploaded = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2F7A55" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" role="img" aria-label="Uploaded">
    <path d="M5 12l5 5L20 7" />
  </svg>
);
const NotYet = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9AA5AE" strokeWidth="2" role="img" aria-label="Not uploaded">
    <circle cx="12" cy="12" r="9" />
  </svg>
);

function DocumentRow({ caseId, requirement: r }: { caseId: number; requirement: Requirement }) {
  const latest = r.documents[0];
  const undecided = r.applies === null;
  return (
    <li className={undecided ? "not-yet" : undefined}>
      <div className="stack">
        <div className="row" style={{ gap: 12 }}>
          {latest ? <Uploaded /> : <NotYet />}
          <span className="strong">{r.name}</span>
        </div>
        {r.original_required ? <span className="small warn-text" style={{ paddingLeft: 32 }}>Bring the original to Records. Copies are not accepted.</span> : null}
        {undecided ? (
          <span className="small muted" style={{ paddingLeft: 32 }}>
            Needed only in some cases. We’ll tell you once the Ministry has confirmed the HS code.
          </span>
        ) : null}
        {latest ? <span className="small muted" style={{ paddingLeft: 32 }}>{latest.filename}</span> : null}
      </div>
      <ActionForm action={uploadDocument.bind(null, caseId, r.type)} className="row" aria-label={`Upload ${r.name}`}>
        <input type="file" name="file" accept="application/pdf,image/png,image/jpeg" required aria-label={`File for ${r.name}`} style={{ maxWidth: 230 }} />
        <SubmitButton className="btn btn-small">{latest ? "Replace" : "Upload"}</SubmitButton>
      </ActionForm>
    </li>
  );
}
