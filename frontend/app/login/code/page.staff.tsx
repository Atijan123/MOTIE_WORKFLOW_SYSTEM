// Staff sign-in, second step (step 12e): the 6-digit code from the
// authenticator app, or one of the recovery codes for a lost phone.
import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { TopBar } from "@/components/TopBar";

import { challenge, submitCode } from "../actions";

export const metadata: Metadata = { title: "Your sign-in code" };

export default async function CodePage({ searchParams }: { searchParams: Promise<{ recovery?: string }> }) {
  await challenge(); // back to the start if the password step has expired
  const recovery = Boolean((await searchParams).recovery);
  return (
    <>
      <TopBar subtitle="ETLS Services · Staff" />
      <main className="page page-phone">
        <h1 className="title">{recovery ? "Use a recovery code" : "Your sign-in code"}</h1>
        <ActionForm action={submitCode} className="card">
          <input type="hidden" name="kind" value={recovery ? "recovery" : "app"} />
          {recovery ? (
            <label className="field">
              Recovery code
              <input name="code" autoComplete="off" autoCapitalize="characters" spellCheck={false} required />
            </label>
          ) : (
            <label className="field">
              6-digit code from your authenticator app
              <input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} required autoFocus />
            </label>
          )}
          <SubmitButton>Sign in</SubmitButton>
        </ActionForm>
        <p className="small muted">
          {recovery ? (
            <Link href="/login/code">Use the code from my app instead</Link>
          ) : (
            <>
              Lost your phone? <Link href="/login/code?recovery=1">Use a recovery code</Link>. Each one works once.
            </>
          )}
        </p>
      </main>
    </>
  );
}
