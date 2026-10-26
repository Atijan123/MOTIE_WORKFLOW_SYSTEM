"use server";
// The applicant's server actions: save the draft, upload a document, submit.
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api, ApiError, apiFetch } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";
import type { FacilityLetter } from "@/lib/types";

export type DraftState = FormState & { values?: Record<string, string | string[]> };

/** The form as the API takes it. Empty boxes are sent empty: a draft may have gaps (step 8i). */
function formBody(data: FormData) {
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
function typed(data: FormData): Record<string, string | string[]> {
  const values: Record<string, string | string[]> = {};
  for (const key of new Set(data.keys())) {
    if (key.startsWith("$")) continue; // React's own fields
    const all = data.getAll(key).map(String);
    values[key] = ["approval", "cert_number", "cert_date"].includes(key) ? all : all[0];
  }
  return values;
}

export async function saveDraft(caseId: number | null, _: DraftState, data: FormData): Promise<DraftState> {
  let saved: FacilityLetter;
  try {
    saved = caseId
      ? await api<FacilityLetter>(`/etls/facility-letters/${caseId}`, { method: "PUT", json: formBody(data) })
      : await api<FacilityLetter>("/etls/facility-letters", { method: "POST", json: formBody(data) });
  } catch (error) {
    return { ...failed(error), values: typed(data) };
  }
  redirect(`/applications/${saved.case_id}/edit?saved=1`);
}

export async function uploadDocument(caseId: number, type: string, _: FormState, data: FormData): Promise<FormState> {
  const file = data.get("file");
  if (!(file instanceof File) || file.size === 0) return { error: "Choose a file first." };
  // The API takes the file as the raw body and checks its type from the content.
  const response = await apiFetch(`/cases/${caseId}/documents/${type}?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    body: Buffer.from(await file.arrayBuffer()),
    headers: { "Content-Type": "application/octet-stream" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    return { error: typeof body.detail === "string" ? body.detail : "The upload didn’t work. Please try again." };
  }
  revalidatePath(`/applications/${caseId}/edit`);
  return { done: `${file.name} uploaded.` };
}

export async function submitApplication(caseId: number, _: FormState): Promise<FormState> {
  try {
    await api(`/cases/${caseId}/status`, { method: "POST", json: { to_status: "submitted" } });
  } catch (error) {
    if (error instanceof ApiError) return { error: error.message.replace(/^Not ready: /, "Not ready yet: ") };
    throw error;
  }
  redirect(`/applications?case=${caseId}`);
}
