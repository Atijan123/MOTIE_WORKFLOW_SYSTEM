"use server";
// The applicant's server actions: save the draft, upload a document, submit.
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { upload } from "@/lib/upload";
import { formBody, typed, type DraftState } from "@/lib/facility-form";
import { failed, type FormState } from "@/lib/forms";
import type { FacilityLetter } from "@/lib/types";

export type { DraftState };

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

export async function uploadDocument(caseId: number, type: string, state: FormState, data: FormData): Promise<FormState> {
  return upload(caseId, type, `/applications/${caseId}/edit`, data);
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
