import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { apiOrNull } from "@/lib/api";
import { longDate, shortDateTime } from "@/lib/dates";
import { mayViewStatistics, requireUser } from "@/lib/session";
import type { HistoricalPage } from "@/lib/types";

export const metadata: Metadata = { title: "Historical facility letter" };

// The register's columns, in the register's order, as written (S13).
const COLUMNS: [keyof HistoricalPage["letter"], string][] = [
  ["letter_no", "Letter no."],
  ["folios", "Folio(s) in file"],
  ["pdf_pages", "PDF page(s)"],
  ["reference", "Letter reference"],
  ["letter_date_as_written", "Letter date"],
  ["importer", "Importer"],
  ["importer_address", "Importer address / cc"],
  ["goods", "Goods (as in letter)"],
  ["category", "Category"],
  ["exporter", "Exporter"],
  ["exporter_country", "Exporter country"],
  ["exporter_approval_as_written", "Exporter approval no. (as written)"],
  ["exporter_approval_standard", "Exporter approval no. (standard)"],
  ["product_approvals", "Product approval no(s)."],
  ["tariff_codes", "Tariff code(s)"],
  ["certificates_as_written", "Certificate of origin no(s)."],
  ["certificate_count_as_written", "No. of certificates"],
  ["bill_of_lading", "Bill of lading / container"],
  ["signed_by", "Signed by"],
  ["signed_as", "Signed as"],
  ["check_notes", "Check notes"],
  ["also_filed_at", "Also filed at (second copy of this letter)"],
];

// One letter from the imported register: read-only, not a case, no workflow.
// Any staff member may open it (the desk follows a duplicate flag here).
export default async function HistoricalLetterPage({ params }: { params: Promise<{ id: string }> }) {
  const me = await requireUser("staff");
  const page = await apiOrNull<HistoricalPage>(`/etls/history/${Number((await params).id)}`);
  if (!page) notFound();
  const l = page.letter;

  return (
    <>
      <div className="stack">
        {mayViewStatistics(me) ? (
          <Link href="/staff/statistics" className="small">
            ← Statistics
          </Link>
        ) : null}
        <span className="small muted">Historical facility letter · read-only · not a case</span>
        <h1 className="title">
          {l.reference ?? `Letter no. ${l.letter_no}`}
          {l.letter_date ? `, ${longDate(l.letter_date)}` : ""}
        </h1>
        <span className="small muted">
          {l.source_file ? `Scan: ${l.source_file}, p. ${l.source_page}. ` : ""}Row {l.source_row} of “Facility letters”; imported{" "}
          {shortDateTime(l.imported_at)}.
        </span>
      </div>

      {page.checks.length ? (
        <section className="notice notice-warn stack" aria-labelledby="checks">
          <strong id="checks">Data checks on this letter</strong>
          {page.checks.map((c, i) => (
            <span key={i}>
              {c.check_no_as_written ? `Check ${c.check_no_as_written}: ` : ""}
              {c.what_looks_wrong ?? ""}
              {c.what_to_check ? ` What to check: ${c.what_to_check}` : ""}
            </span>
          ))}
        </section>
      ) : null}

      <section className="card" aria-labelledby="as-written">
        <h2 id="as-written" style={{ fontSize: 16 }}>
          As written in the register
        </h2>
        <dl className="summary">
          {COLUMNS.map(([key, label]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{l[key] === null || l[key] === "" ? <span className="muted">(empty)</span> : String(l[key])}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card card-flush" aria-labelledby="goods">
        <h2 className="card-head" id="goods">
          Goods lines
        </h2>
        {page.goods.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Line no.</th>
                  <th>Product</th>
                  <th>Category</th>
                  <th>Quantity (as written)</th>
                  <th>Unit</th>
                </tr>
              </thead>
              <tbody>
                {page.goods.map((g, i) => (
                  <tr key={i}>
                    <td>{g.line_no_as_written}</td>
                    <td>{g.product}</td>
                    <td>{g.category}</td>
                    <td>
                      {g.quantity_as_written}
                      {g.quantity === null && g.quantity_as_written ? <span className="small warn-text"> (not a number: not counted)</span> : null}
                    </td>
                    <td>{g.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ padding: 16 }}>
            No goods lines for this letter in the register.
          </p>
        )}
      </section>

      <section className="card" aria-labelledby="certificates">
        <h2 id="certificates" style={{ fontSize: 16 }}>
          Certificates of origin
        </h2>
        <p style={{ margin: 0 }}>{page.certificates.length ? page.certificates.join(", ") : <span className="muted">None recorded.</span>}</p>
      </section>
    </>
  );
}
