// The first staff sign-in (step 12e): set up an authenticator app. The API
// makes a new secret each time this page opens; scan it, then type the code.
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { TopBar } from "@/components/TopBar";
import { api, ApiError } from "@/lib/api";
import type { SetUpStart } from "@/lib/types";

import { challenge } from "../actions";
import { SetUpForm } from "./SetUpForm";

export const metadata: Metadata = { title: "Set up two-step sign-in" };

export default async function SetUpPage() {
  let start: SetUpStart;
  try {
    start = await api<SetUpStart>("/auth/two-step/set-up", { method: "POST", json: { challenge: await challenge() } });
  } catch (error) {
    // Already set up (e.g. a second tab): just ask for the code.
    if (error instanceof ApiError && error.status === 409) redirect("/login/code");
    if (error instanceof ApiError && error.status === 401) redirect("/login?expired=1");
    throw error;
  }
  return (
    <>
      <TopBar subtitle="ETLS Services · Staff" />
      <main className="page page-phone">
        <h1 className="title">Set up two-step sign-in</h1>
        <div className="card">
          <p>
            Staff sign in with their password <strong>and</strong> a code from an authenticator app on their phone
            (for example Google Authenticator, Microsoft Authenticator or Aegis).
          </p>
          <ol className="steps">
            <li>Open the app and add an account.</li>
            <li>Scan this code:</li>
          </ol>
          {/* SVG made by the API's QR library from the setup link: no outside content. */}
          <div className="qr" aria-label="QR code for your authenticator app" role="img" dangerouslySetInnerHTML={{ __html: start.qr_svg }} />
          <p className="small muted">
            Can’t scan it? Type this key into the app instead: <code className="setup-key">{start.secret.match(/.{1,4}/g)?.join(" ")}</code>
          </p>
          <SetUpForm />
        </div>
        <p className="small muted">If you reload this page you get a new code: scan the new one.</p>
      </main>
    </>
  );
}
