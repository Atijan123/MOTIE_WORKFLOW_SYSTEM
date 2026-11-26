import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { api } from "@/lib/api";
import { longDate } from "@/lib/dates";
import { mayViewStatistics, requireUser } from "@/lib/session";
import type { Figure, Statistics } from "@/lib/types";

export const metadata: Metadata = { title: "ETLS statistics" };

type Search = { date_from?: string; date_to?: string; importer?: string };

/** Only the three filters, and only well-formed ones, go to the API and into the CSV link. */
function query(sp: Search): string {
  const params = new URLSearchParams();
  for (const key of ["date_from", "date_to"] as const) {
    if (sp[key] && /^\d{4}-\d{2}-\d{2}$/.test(sp[key]!)) params.set(key, sp[key]!);
  }
  if (sp.importer?.trim()) params.set("importer", sp.importer.trim().slice(0, 200));
  return params.toString();
}

const numberFormat = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 3 });

// S13 (docs/SCREENS.md): live and historical facility letters together. Every
// table says how many letters it's based on; the CSV is exactly the letters
// behind the figures.
export default async function StatisticsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const me = await requireUser("staff");
  if (!mayViewStatistics(me)) notFound();
  const sp = await searchParams;
  const q = query(sp);
  const s = await api<Statistics>(`/etls/statistics${q ? `?${q}` : ""}`);
  const filtered = Boolean(q);

  return (
    <>
      <div className="stack">
        <h1 className="title">ETLS statistics</h1>
        <p className="muted">
          Facility letters signed in this system and those imported from the historical register. Names written differently
          (capitals, spaces) count as one.
        </p>
      </div>

      <form className="card" method="get" aria-label="Filters">
        <div className="grid-3">
          <label className="field">
            From
            <input type="date" name="date_from" defaultValue={sp.date_from ?? ""} />
          </label>
          <label className="field">
            To
            <input type="date" name="date_to" defaultValue={sp.date_to ?? ""} />
          </label>
          <label className="field">
            Importer (part of the name)
            <input name="importer" defaultValue={sp.importer ?? ""} maxLength={200} />
          </label>
        </div>
        <div className="row">
          <button type="submit" className="btn btn-primary">
            Show
          </button>
          {filtered ? <Link href="/staff/statistics">Clear filters</Link> : null}
          <a href={`/files/etls/statistics/letters.csv${q ? `?${q}` : ""}`} className="btn">
            Download these letters (CSV)
          </a>
        </div>
      </form>

      <section className="card" aria-label="Letters">
        <p className="strong" style={{ margin: 0 }}>
          {s.letters} letter{s.letters === 1 ? "" : "s"}
          {filtered ? " match the filters" : ""}: {s.live} signed in this system, {s.historical} from the historical register.
        </p>
        {s.undated ? <p className="small muted">{s.undated} of them have no readable date.</p> : null}
        {s.filters.date_from || s.filters.date_to ? (
          <p className="small muted">
            Dates: {s.filters.date_from ? longDate(s.filters.date_from) : "the start"} to{" "}
            {s.filters.date_to ? longDate(s.filters.date_to) : "today"}. Letters with no readable date are left out.
          </p>
        ) : null}
      </section>

      <div className="grid-2">
        <CountTable title="Letters by year" figure={s.by_year} heading="Year" />
        <CountTable title="Letters by month" figure={s.by_month} heading="Month" />
        <CountTable title="Top importers" figure={s.importers} heading="Importer" />
        <CountTable title="Top exporters" figure={s.exporters} heading="Exporter" />
        <CountTable title="Top exporter countries" figure={s.exporter_countries} heading="Country" />
        <CountTable title="Top products" figure={s.products} heading="Product" />
        <CountTable title="Letters by signatory" figure={s.signatories} heading="Signed by" />
      </div>

      <section className="card card-flush" aria-labelledby="quantities">
        <div className="card-head stack">
          <h2 id="quantities" style={{ fontSize: 16 }}>
            Quantities by category and unit
          </h2>
          <span className="small muted" style={{ fontWeight: 400 }}>
            Based on {s.quantities.based_on} letter{s.quantities.based_on === 1 ? "" : "s"}. Different units are never added
            together. {s.quantities.lines_without_quantity ? `${s.quantities.lines_without_quantity} goods line(s) have no readable quantity or unit and are not counted.` : ""}
          </span>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Unit</th>
                <th style={{ textAlign: "right" }}>Total</th>
                <th style={{ textAlign: "right" }}>Letters</th>
              </tr>
            </thead>
            <tbody>
              {s.quantities.rows.map((r) => (
                <tr key={`${r.category}|${r.unit}`}>
                  <td>{r.category}</td>
                  <td>{r.unit}</td>
                  <td style={{ textAlign: "right" }}>{numberFormat.format(Number(r.total))}</td>
                  <td style={{ textAlign: "right" }}>{r.letters}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card card-flush" aria-labelledby="shared">
        <div className="card-head stack">
          <h2 id="shared" style={{ fontSize: 16 }}>
            Certificates of origin used more than once
          </h2>
          <span className="small muted" style={{ fontWeight: 400 }}>
            Based on {s.shared_certificates.based_on} letter{s.shared_certificates.based_on === 1 ? "" : "s"} with a certificate
            number.
          </span>
        </div>
        {s.shared_certificates.rows.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Certificate</th>
                  <th>Used on</th>
                </tr>
              </thead>
              <tbody>
                {s.shared_certificates.rows.map((r) => (
                  <tr key={r.number}>
                    <td>{r.number}</td>
                    <td>{r.letters.join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ padding: 16 }}>
            None.
          </p>
        )}
      </section>

      {s.unlinked_checks.length ? (
        <section className="card card-flush" aria-labelledby="unlinked">
          <div className="card-head stack">
            <h2 id="unlinked" style={{ fontSize: 16 }}>
              Data checks not linked to a letter
            </h2>
            <span className="small muted" style={{ fontWeight: 400 }}>
              From the register’s “Data checks” sheet: the import couldn’t tell which letter these are about.
            </span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Check no.</th>
                  <th>Folio(s)</th>
                  <th>Reference</th>
                  <th>What looks wrong</th>
                  <th>What to check</th>
                </tr>
              </thead>
              <tbody>
                {s.unlinked_checks.map((c, i) => (
                  <tr key={i}>
                    <td>{c.check_no_as_written}</td>
                    <td>{c.folios}</td>
                    <td>{c.reference}</td>
                    <td>{c.what_looks_wrong}</td>
                    <td>{c.what_to_check}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </>
  );
}

function CountTable({ title, figure, heading }: { title: string; figure: Figure; heading: string }) {
  const id = title.toLowerCase().replaceAll(" ", "-");
  return (
    <section className="card card-flush" aria-labelledby={id}>
      <div className="card-head stack">
        <h2 id={id} style={{ fontSize: 16 }}>
          {title}
        </h2>
        <span className="small muted" style={{ fontWeight: 400 }}>
          Based on {figure.based_on} letter{figure.based_on === 1 ? "" : "s"}. {figure.note ?? ""}
        </span>
      </div>
      {figure.rows.length ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{heading}</th>
                <th style={{ textAlign: "right" }}>Letters</th>
              </tr>
            </thead>
            <tbody>
              {figure.rows.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td style={{ textAlign: "right" }}>{r.letters}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted" style={{ padding: 16 }}>
          No letters.
        </p>
      )}
    </section>
  );
}
