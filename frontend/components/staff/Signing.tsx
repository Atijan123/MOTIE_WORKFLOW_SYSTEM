import { api } from "@/lib/api";
import { longDate } from "@/lib/dates";
import { hsCode } from "@/lib/labels";

type Checks = {
  originals: { document: string; seen: boolean; seen_at: string | null; seen_by: string | null }[];
  checklist: { label: string; ticked: boolean; ticked_by: string | null }[];
  duplicate_flags: { message: string; resolved: boolean; resolution: string | null }[];
  hs_code_confirmed: string | null;
  hs_code_confirmed_by: string | null;
  certificates: { number: string; expires_on: string | null; valid_today: boolean }[];
  documents_missing: string[];
};

const Ok = ({ ok, children }: { ok: boolean; children: React.ReactNode }) => (
  <li style={{ color: ok ? "var(--done-text)" : "var(--warn)" }}>
    {ok ? "✓" : "✗"} {children}
  </li>
);

/** S3 (docs/design/PS.dc.html): what was checked, and the letter as it will be signed. Shown to whoever may sign:
 * the Director, an authorised signatory in the Director's absence, or (cement) the Minister or the PS. */
export async function Signing({ caseId }: { caseId: number }) {
  const c = await api<Checks>(`/etls/facility-letters/${caseId}/checks`);
  const preview = `/files/etls/facility-letters/${caseId}/letter-preview.pdf`;
  return (
    <section className="stack-lg" aria-labelledby="before-signing">
      <h3 id="before-signing">Checks done</h3>
      <ul className="small" style={{ margin: 0, paddingLeft: 0, listStyle: "none", display: "grid", gap: 6 }}>
        {c.originals.map((o) => (
          <Ok ok={o.seen} key={o.document}>
            Original {o.document.toLowerCase()} {o.seen ? `seen by ${o.seen_by} on ${longDate(o.seen_at!)}` : "not seen"}
          </Ok>
        ))}
        {c.checklist.map((t) => (
          <Ok ok={t.ticked} key={t.label}>
            {t.label}
            {t.ticked_by ? ` (${t.ticked_by})` : ""}
          </Ok>
        ))}
        <Ok ok={c.duplicate_flags.every((f) => f.resolved)}>
          {c.duplicate_flags.length
            ? `Duplicate certificate: ${c.duplicate_flags.map((f) => f.resolution ?? "not cleared").join("; ")}`
            : "No certificate number used before"}
        </Ok>
        <Ok ok={Boolean(c.hs_code_confirmed)}>
          HS code {c.hs_code_confirmed ? `${hsCode(c.hs_code_confirmed)} confirmed by ${c.hs_code_confirmed_by}` : "not confirmed"}
        </Ok>
        {c.certificates.map((cert) => (
          <Ok ok={cert.valid_today} key={cert.number}>
            Certificate {cert.number} {cert.expires_on ? `valid until ${longDate(cert.expires_on)}` : "has no issue date"}
          </Ok>
        ))}
        <Ok ok={!c.documents_missing.length}>
          {c.documents_missing.length ? `Missing: ${c.documents_missing.join(", ")}` : "All documents uploaded"}
        </Ok>
      </ul>
      <div className="spread">
        <p className="small muted">Draft preview. The signed letter is stored when you sign.</p>
        <a href={preview} target="_blank" rel="noopener" className="small">
          Open the preview on its own
        </a>
      </div>
      <iframe src={preview} title="Letter preview" className="letter-frame" />
      <p className="small muted">Signing stores this exact letter. It can be cancelled and reissued, never edited.</p>
    </section>
  );
}
