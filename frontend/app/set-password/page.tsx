import type { Metadata } from "next";

import { TopBar } from "@/components/TopBar";

import { SetPasswordForm } from "./SetPasswordForm";

export const metadata: Metadata = { title: "Set your password", referrer: "no-referrer" };

export default function SetPasswordPage() {
  return (
    <>
      <TopBar />
      <main className="page page-phone">
        <h1 className="title">Set your password</h1>
        <p className="lead">
          The Ministry opened an application for you. Choose a password to follow it online. The link works once.
        </p>
        <noscript>
          <div className="notice notice-warn">This page needs JavaScript switched on to read your link.</div>
        </noscript>
        <SetPasswordForm />
      </main>
    </>
  );
}
