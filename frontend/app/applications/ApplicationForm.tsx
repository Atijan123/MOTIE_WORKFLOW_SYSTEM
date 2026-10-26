"use client";
// A2's form (docs/design/Apply.dc.html), sections 1 to 3. Saving sends the
// whole form; any box may be empty on a draft. There's always one spare
// empty row for another approval number or certificate, so adding one needs
// no script: fill it in and save.
import { useActionState } from "react";

import { SubmitButton } from "@/components/ActionForm";
import { hsCode } from "@/lib/labels";
import type { FacilityLetter } from "@/lib/types";

import type { DraftState } from "./actions";


export type FormOptions = { countries: string[]; units: string[] };

type Props = {
  letter: FacilityLetter | null;
  options: FormOptions; // the Ministry's lists (GET /etls/form-options), kept by an admin
  action: (state: DraftState, data: FormData) => Promise<DraftState>;
  children?: React.ReactNode; // the expiry note, under the certificates
};

export function ApplicationForm({ letter, options, action, children }: Props) {
  const [state, formAction] = useActionState(action, {});
  const v = state.values;
  // After a failed save, show what was typed; otherwise what's stored.
  const value = (name: keyof FacilityLetter & string, stored: string | null | undefined) =>
    v ? String(v[name] ?? "") : (stored ?? "");
  const approvals = v ? (v.approval as string[]) ?? [] : letter?.product_approval_numbers ?? [];
  const certs = v
    ? ((v.cert_number as string[]) ?? []).map((n, i) => ({ number: n, issued_on: ((v.cert_date as string[]) ?? [])[i] ?? "" }))
    : (letter?.certificates_of_origin ?? []).map((c) => ({ number: c.number, issued_on: c.issued_on ?? "" }));
  const certRows = [...certs.filter((c) => c.number || c.issued_on), { number: "", issued_on: "" }];
  const approvalRows = [...approvals.filter(Boolean), ""];

  return (
    <form action={formAction} className="stack-lg" aria-label="Application form">
      {state.error ? (
        <div className="notice notice-error" role="alert">
          <strong>Not saved.</strong> {state.error}
        </div>
      ) : null}

      <section className="card">
        <h2>1. Importer</h2>
        <div className="grid-2">
          <label className="field">
            Business name
            <input name="importer_name" defaultValue={value("importer_name", letter?.importer_name)} maxLength={200} />
          </label>
          <label className="field">
            Address
            <input name="importer_address" defaultValue={value("importer_address", letter?.importer_address)} maxLength={1000} />
          </label>
        </div>
      </section>

      <section className="card">
        <h2>2. Goods</h2>
        <label className="field">
          Product
          <input name="product" defaultValue={value("product", letter?.product)} maxLength={200} />
        </label>
        <div className="grid-3">
          <label className="field">
            Quantity
            <input name="quantity" inputMode="decimal" defaultValue={value("quantity", letter?.quantity ? String(Number(letter.quantity)) : "")} />
          </label>
          <Choice name="unit" label="Unit" choices={options.units} value={value("unit", letter?.unit)} />
          <label className="field">
            HS code (optional)
            <input name="hs_code" placeholder="e.g. 2309.90" defaultValue={value("hs_code", letter?.hs_code ? hsCode(letter.hs_code) : null)} maxLength={20} />
          </label>
        </div>
        <p className="small muted">Not sure of the HS code? Leave it blank. The Ministry will confirm it.</p>
      </section>

      <section className="card">
        <h2>3. Exporter and approvals</h2>
        <div className="grid-2">
          <label className="field">
            Exporter
            <input name="exporter_name" defaultValue={value("exporter_name", letter?.exporter_name)} maxLength={200} />
          </label>
          <Choice name="exporter_country" label="Country" choices={options.countries} value={value("exporter_country", letter?.exporter_country)} />
          <label className="field">
            Exporter’s ETLS approval number
            <input
              name="exporter_etls_approval_number"
              defaultValue={value("exporter_etls_approval_number", letter?.exporter_etls_approval_number)}
              maxLength={60}
            />
          </label>
          <fieldset>
            <legend>Product approval numbers</legend>
            {approvalRows.map((n, i) => (
              <input key={`a${i}-${n}`} name="approval" defaultValue={n} maxLength={60} aria-label={`Product approval number ${i + 1}`} />
            ))}
            <span className="small muted">To add another, fill in the empty box and save.</span>
          </fieldset>
        </div>
        <fieldset>
          <legend>Certificates of origin</legend>
          {certRows.map((c, i) => (
            <div className="cert-row" key={`c${i}-${c.number}`}>
              <label className="field">
                Certificate {i + 1} number
                <input name="cert_number" defaultValue={c.number} maxLength={60} />
              </label>
              <label className="field">
                Issue date
                <input type="date" name="cert_date" defaultValue={c.issued_on} />
              </label>
            </div>
          ))}
          <span className="small muted">To add another certificate, fill in the empty row and save.</span>
          {children}
        </fieldset>
      </section>

      <div className="row">
        <SubmitButton className="btn">Save draft</SubmitButton>
      </div>
    </form>
  );
}

/**
 * A select from one of the Ministry's lists. A value saved earlier that has
 * since been taken off the list stays visible, marked, so it isn't silently
 * lost; Submit then asks for another (the API's check).
 */
function Choice({ name, label, choices, value }: { name: string; label: string; choices: string[]; value: string }) {
  const gone = value && !choices.includes(value);
  return (
    <div className="field">
      {/* Not wrapped around the select: wrapped, browsers add the chosen option to its name. */}
      <label htmlFor={name}>{label}</label>
      <select id={name} name={name} defaultValue={value}>
        <option value="">Choose…</option>
        {gone ? <option value={value}>{value} (no longer on the list)</option> : null}
        {choices.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </div>
  );
}
