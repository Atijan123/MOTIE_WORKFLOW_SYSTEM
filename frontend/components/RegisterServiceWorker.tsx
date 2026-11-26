"use client";
// Registers public/sw.js (step 12h). Browsers only allow service workers on
// https (or http://localhost), which the office server has (Caddy).
import { useEffect } from "react";

export function RegisterServiceWorker() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined); // not installable then; the app still works
    }
  }, []);
  return null;
}
