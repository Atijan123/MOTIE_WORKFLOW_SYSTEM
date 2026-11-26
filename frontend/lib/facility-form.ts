// The facility letter form as the API takes it (A2, and Records' walk-in
// screen, step 13b). Shared by both apps' server actions; no Next.js here.
import { text, type FormState } from "./forms";

export type DraftState = FormState & { values?: Record<string, string | string[]> };

/** The form as the API takes it. Empty boxes are sent empty: a draft may have gaps (step 8i). */
export function formBody(data: FormData) {
  const numbers = data.getAll("cert_number").map(String);
  const dates = data.getAll("cert_date").map(String);
  return {
    importer_name: text(data, "importer_name"),
    importer_address: text(data, "importer_address"),
    product: text(data, "product"),
    // "1,200" is how people write it; the API wants 1200.
    quantity: text(data, "quantity").replace(/[,\s]/g, ""),
    unit: text(data, "unit"),
    hs_code: text(data, "hs_code"),
    exporter_name: text(data, "exporter_name"),
    exporter_country: text(data, "exporter_country"),
    exporter_etls_approval_number: text(data, "exporter_etls_approval_number"),
    product_approval_numbers: data.getAll("approval").map((v) => String(v).trim()).filter(Boolean),
    certificates_of_origin: numbers
      .map((number, i) => ({ number: number.trim(), issued_on: (dates[i] ?? "").trim() }))
      .filter((c) => c.number || c.issued_on), // the spare empty row
  };
}

/** What was typed, to put back in the boxes if saving fails. */
export function typed(data: FormData): Record<string, string | string[]> {
  const values: Record<string, string | string[]> = {};
  for (const key of new Set(data.keys())) {
    if (key.startsWith("$")) continue; // React's own fields
    const all = data.getAll(key).map(String);
    values[key] = ["approval", "cert_number", "cert_date"].includes(key) ? all : all[0];
  }
  return values;
}

