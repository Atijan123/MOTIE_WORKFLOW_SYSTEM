// "Security": the staff member's own two-step sign-in (step 12e).
import type { Metadata } from "next";

import { api } from "@/lib/api";
import { requireUser } from "@/lib/session";
import type { TwoStepStatus } from "@/lib/types";

import { NewCodesForm } from "./NewCodesForm";

export const metadata: Metadata = { title: "Security" };

export default async function SecurityPage() {
  await requireUser("staff");
  const status = await api<TwoStepStatus>("/auth/two-step");
  return (
    <>
      <h1 className="title">Security</h1>
      <section className="card" aria-label="Two-step sign-in">
        <h2>Two-step sign-in</h2>
        <p>{status.set_up ? "On: you sign in with your password and a code from your authenticator app." : "Not set up."}</p>
        <p>
          Recovery codes left: <strong>{status.recovery_codes_left}</strong> of 10.
          {status.recovery_codes_left <= 3 ? " Make a new set soon." : null}
        </p>
        <p className="small muted">
          Making a new set stops the old ones working. Lost your phone and your codes? Ask the system administrator to
          reset your two-step sign-in, in person.
        </p>
        <NewCodesForm />
      </section>
    </>
  );
}
