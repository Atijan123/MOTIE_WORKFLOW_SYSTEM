// Records: a new application for someone who came in person (step 13b).
import type { Metadata } from "next";

import { ApplicationForm, type FormOptions } from "@/components/ApplicationForm";
import { api } from "@/lib/api";
import { requireUser } from "@/lib/session";

import { createWalkIn } from "../actions";

export const metadata: Metadata = { title: "New walk-in application" };

export default async function NewWalkIn() {
  await requireUser("staff");
  const options = await api<FormOptions>("/etls/form-options");
  return (
    <>
      <h1 className="title">New walk-in application</h1>
      <p className="muted">For an importer who came to the Ministry in person. Fill in what they give you; you can save it half-done.</p>
      <ApplicationForm letter={null} options={options} action={createWalkIn} top={<WalkInApplicant />} />
    </>
  );
}

/** Who the application is for. Shown inside the form, so it's saved with it. */
function WalkInApplicant() {
  return (
    <fieldset className="card" aria-label="Applicant">
      <legend className="strong">The applicant</legend>
      <label className="field">
        Applicant’s full name
        <input name="applicant_name" required maxLength={200} />
      </label>
      <label className="field">
        Applicant’s email (optional)
        <input name="applicant_email" type="email" maxLength={320} />
        <span className="small muted">Used to find an earlier application of theirs. Nothing is emailed from the office server.</span>
      </label>
    </fieldset>
  );
}
