import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ActionForm, SubmitButton } from "@/components/ActionForm";
import { TopBar } from "@/components/TopBar";
import { getMe, homeFor } from "@/lib/session";

import { login } from "./actions";

export const metadata: Metadata = { title: "Log in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ expired?: string; set?: string }> }) {
  const me = await getMe().catch(() => null);
  if (me) redirect(homeFor(me));
  const { expired, set } = await searchParams;
  return (
    <>
      <TopBar />
      <main className="page page-phone">
        <h1 className="title">Log in</h1>
        {expired ? <div className="notice notice-info">Your session ended. Please log in again.</div> : null}
        {set ? <div className="notice notice-done">Your password is set. You can log in now.</div> : null}
        <ActionForm action={login} className="card">
          <label className="field">
            Email
            <input type="email" name="email" autoComplete="username" required />
          </label>
          <label className="field">
            Password
            <input type="password" name="password" autoComplete="current-password" required />
          </label>
          <SubmitButton>Log in</SubmitButton>
        </ActionForm>
        <p className="small muted">
          Applied in person at the Ministry? Use the link we emailed you to set your password first.
        </p>
      </main>
    </>
  );
}
