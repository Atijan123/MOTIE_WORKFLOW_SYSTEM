import type { Metadata } from "next";
import Link from "next/link";

import { saveDraft } from "../actions";
import { ApplicationForm } from "../ApplicationForm";

export const metadata: Metadata = { title: "Apply for a facility letter" };

// A2 before the first save: nothing is stored until "Save draft", so
// opening the page and leaving makes no empty application.
export default function NewApplication() {
  return (
    <main className="page page-narrow">
      <Link href="/applications" className="small">
        ← My applications
      </Link>
      <div className="stack">
        <h1 className="title">Apply for an ETLS facility letter</h1>
        <p className="lead">
          For goods made by an ETLS-approved company in another ECOWAS country. The Ministry writes to GRA asking for
          the goods to be cleared without duty.
        </p>
      </div>
      <ApplicationForm letter={null} action={saveDraft.bind(null, null)} />
      <section className="card">
        <h2>4. Documents</h2>
        <p className="muted">Save the draft first; then you can upload the documents here.</p>
      </section>
    </main>
  );
}
