// The first staff sign-in (step 12e): set up an authenticator app.
// This page does nothing by itself: the buttons below do each step (server
// actions). Saving the session cookie makes Next.js re-render the page, so a
// page that asked the API for a secret as it rendered would start over, and
// lose the recovery codes just shown.
import type { Metadata } from "next";

import { TopBar } from "@/components/TopBar";

import { SetUpForm } from "./SetUpForm";

export const metadata: Metadata = { title: "Set up two-step sign-in" };

export default function SetUpPage() {
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
          <SetUpForm />
        </div>
      </main>
    </>
  );
}
