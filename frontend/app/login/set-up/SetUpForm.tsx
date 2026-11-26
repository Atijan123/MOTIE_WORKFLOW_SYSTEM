"use client";
// The set-up, step by step: show a new QR code; take the first code from the
// app; show the recovery codes, once. The session starts with the last step.
import Link from "next/link";
import { useActionState } from "react";

import { SubmitButton } from "@/components/ActionForm";

import { confirmSetUp, startSetUp, type SetUpState, type StartState } from "../actions";

export function SetUpForm() {
  const [start, startAction] = useActionState<StartState, FormData>(startSetUp, {});
  const [done, confirmAction] = useActionState<SetUpState, FormData>(confirmSetUp, {});

  if (done.recoveryCodes) {
    return (
      <section aria-label="Recovery codes" className="recovery-codes">
        <div className="notice notice-done" role="status">Two-step sign-in is set up.</div>
        <p>
          <strong>Write down or print these recovery codes now</strong> and keep them somewhere safe, away from your
          phone. If you lose your phone, each one signs you in once. You won’t see them again.
        </p>
        <ul className="code-list">
          {done.recoveryCodes.map((code) => (
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
  if (start.alreadySetUp) {
    return (
      <p>
        Two-step sign-in is already set up for this account. <Link href="/login/code">Enter your code</Link>.
      </p>
    );
  }
  if (!start.secret) {
    return (
      <form action={startAction}>
        {start.error ? (
          <div className="notice notice-error" role="alert">
            {start.error}
          </div>
        ) : null}
        <p>Have your phone ready, with the authenticator app installed.</p>
        <SubmitButton>Show my QR code</SubmitButton>
      </form>
    );
  }
  return (
    <>
      <ol className="steps">
        <li>Open the app and add an account.</li>
        <li>Scan this code:</li>
      </ol>
      {/* SVG made by the API's QR library from the setup link: no outside content. */}
      <div className="qr" aria-label="QR code for your authenticator app" role="img" dangerouslySetInnerHTML={{ __html: start.qrSvg ?? "" }} />
      <p className="small muted">
        Can’t scan it? Type this key into the app instead:{" "}
        <code className="setup-key">{start.secret.match(/.{1,4}/g)?.join(" ")}</code>
      </p>
      <form action={confirmAction}>
        {done.error ? (
          <div className="notice notice-error" role="alert">
            {done.error}
          </div>
        ) : null}
        <label className="field">
          Then type the 6-digit code the app shows
          <input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} required />
        </label>
        <SubmitButton>Turn on two-step sign-in</SubmitButton>
      </form>
    </>
  );
}
