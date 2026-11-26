"use client";
// The first code from the new authenticator, then the recovery codes: shown
// once, here, and never again. The session is already started by then.
import Link from "next/link";
import { useActionState } from "react";

import { SubmitButton } from "@/components/ActionForm";

import { confirmSetUp, type SetUpState } from "../actions";

export function SetUpForm() {
  const [state, formAction] = useActionState<SetUpState, FormData>(confirmSetUp, {});
  if (state.recoveryCodes) {
    return (
      <section aria-label="Recovery codes" className="recovery-codes">
        <div className="notice notice-done" role="status">Two-step sign-in is set up.</div>
        <p>
          <strong>Write down or print these recovery codes now</strong> and keep them somewhere safe, away from your
          phone. If you lose your phone, each one signs you in once. You won’t see them again.
        </p>
        <ul className="code-list">
          {state.recoveryCodes.map((code) => (
            <li key={code}>
              <code>{code}</code>
            </li>
          ))}
        </ul>
        <Link href="/staff" className="btn btn-primary">
          I’ve saved them: continue
        </Link>
      </section>
    );
  }
  return (
    <form action={formAction}>
      {state.error ? (
        <div className="notice notice-error" role="alert">
          {state.error}
        </div>
      ) : null}
      <label className="field">
        Then type the 6-digit code the app shows
        <input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} required />
      </label>
      <SubmitButton>Turn on two-step sign-in</SubmitButton>
    </form>
  );
}
