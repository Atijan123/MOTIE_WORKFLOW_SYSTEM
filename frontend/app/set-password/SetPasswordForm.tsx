"use client";
// The emailed link is /set-password#token=... The part after "#" never
// reaches any server, so only this script can read it. It's then taken out
// of the address bar, so it isn't left in the browser's history or bookmarks.
import { useEffect, useState } from "react";

import { ActionForm, SubmitButton } from "@/components/ActionForm";

import { setPassword } from "./actions";

export function SetPasswordForm() {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const found = new URLSearchParams(window.location.hash.slice(1)).get("token");
    setToken(found ?? "");
    if (found) window.history.replaceState(null, "", window.location.pathname);
  }, []);

  if (token === null) return <p className="muted">Loading…</p>;
  if (!token) {
    return (
      <div className="notice notice-warn">
        This page needs the link from your email. Open the email and use the link in it, or ask Records at the
        Ministry for a new one.
      </div>
    );
  }
  return (
    <ActionForm action={setPassword} className="card">
      <input type="hidden" name="token" value={token} />
      <label className="field">
        New password
        <input type="password" name="password" autoComplete="new-password" minLength={12} required />
      </label>
      <label className="field">
        The same password again
        <input type="password" name="confirm" autoComplete="new-password" minLength={12} required />
      </label>
      <p className="small muted">At least 12 characters. A few words you’ll remember works well.</p>
      <SubmitButton>Set my password</SubmitButton>
    </ActionForm>
  );
}
