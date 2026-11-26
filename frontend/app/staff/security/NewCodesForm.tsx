"use client";
import { useActionState } from "react";

import { SubmitButton } from "@/components/ActionForm";

import { newRecoveryCodes, type CodesState } from "./actions";

export function NewCodesForm() {
  const [state, formAction] = useActionState<CodesState, FormData>(newRecoveryCodes, {});
  if (state.recoveryCodes) {
    return (
      <section aria-label="New recovery codes" className="recovery-codes">
        <div className="notice notice-done" role="status">
          New recovery codes made. Your old ones no longer work.
        </div>
        <p>
          <strong>Write down or print these now.</strong> You won’t see them again.
        </p>
        <ul className="code-list">
          {state.recoveryCodes.map((code) => (
            <li key={code}>
              <code>{code}</code>
            </li>
          ))}
        </ul>
      </section>
    );
  }
  return (
    <form action={formAction} aria-label="Make new recovery codes">
      {state.error ? (
        <div className="notice notice-error" role="alert">
          {state.error}
        </div>
      ) : null}
      <label className="field">
        A current code from your authenticator app
        <input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} required />
      </label>
      <SubmitButton className="btn">Make new recovery codes</SubmitButton>
    </form>
  );
}
