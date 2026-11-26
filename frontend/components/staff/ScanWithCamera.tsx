"use client";
// "Scan with camera" (step 13g), for phones and tablets: photograph a paper
// document page by page with the rear camera, check each page, retake any,
// then save them as one PDF. Each photo goes straight to the server, which
// turns it upright and shrinks it; the previews are the server's pages. The
// app keeps nothing on the phone (and capture="environment" photos don't go
// into the phone's gallery).
import { useRef, useState, useTransition } from "react";

import { addPage, cancelScan, finishScan, removePage, type ScanState } from "@/app/staff/scan/actions";

type Props = { caseId: number; type: string; name: string; initialPages: number[]; page: string };

export function ScanWithCamera({ caseId, type, name, initialPages, page }: Props) {
  const [state, setState] = useState<ScanState>({ pages: initialPages });
  const [version, setVersion] = useState(0); // new preview URLs after a retake
  const [busy, startTransition] = useTransition();
  const retakeOf = useRef<number | null>(null);
  const camera = useRef<HTMLInputElement>(null);
  const pages = state.pages;

  function run(work: () => Promise<ScanState>) {
    startTransition(async () => {
      const next = await work();
      setState((old) => (next.error ? { ...old, error: next.error, done: undefined } : next));
      setVersion((v) => v + 1);
    });
  }

  function takePhoto(retake: number | null) {
    retakeOf.current = retake;
    camera.current?.click();
  }

  function sent(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // forget it: the server has it now
    if (!file) return;
    const data = new FormData();
    data.set("photo", file);
    const retake = retakeOf.current;
    run(() => addPage(caseId, type, retake, data));
  }

  return (
    // Open while there are pages, or a message to read (after saving, the pages
    // are gone but "Scanned and saved" must still be seen).
    <details className="scan touch-only" open={pages.length > 0 || Boolean(state.done || state.error) || undefined}>
      <summary>Scan with camera</summary>
      <div className="stack">
        {/* Rear camera on phones; the photo isn't saved to the phone. */}
        <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={sent} aria-label={`Photo for ${name}`} />
        {state.error ? (
          <div className="notice notice-error" role="alert">
            {state.error}
          </div>
        ) : null}
        {state.done ? (
          <div className="notice notice-done" role="status">
            {state.done}
          </div>
        ) : null}
        {pages.length ? (
          <ol className="scan-pages" aria-label={`Scanned pages of ${name}`}>
            {pages.map((n) => (
              <li key={n}>
                {/* eslint-disable-next-line @next/next/no-img-element -- a private, per-user image */}
                <img src={`/files/cases/${caseId}/documents/${type}/scan/pages/${n}/image?v=${version}`} alt={`Page ${n}`} />
                <div className="row">
                  <button type="button" className="btn btn-small" disabled={busy} onClick={() => takePhoto(n)}>
                    Retake {n}
                  </button>
                  <button type="button" className="link-button" disabled={busy} onClick={() => run(() => removePage(caseId, type, n))}>
                    Remove {n}
                  </button>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="small muted">Lay the page flat in good light, fill the screen with it, and hold still.</p>
        )}
        <div className="row">
          <button type="button" className="btn" disabled={busy} onClick={() => takePhoto(null)}>
            {busy ? "Working…" : `Take page ${pages.length + 1}`}
          </button>
          {pages.length ? (
            <>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => run(() => finishScan(caseId, type, page))}>
                Save {pages.length} {pages.length === 1 ? "page" : "pages"} as one PDF
              </button>
              <button type="button" className="link-button" disabled={busy} onClick={() => run(() => cancelScan(caseId, type))}>
                Cancel
              </button>
            </>
          ) : null}
        </div>
      </div>
    </details>
  );
}
