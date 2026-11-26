"use server";
// Records enters an application for someone who came in person (step 13b;
// the API since step 8g). In office mode this is the only way in.
import { redirect } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { formBody, typed, type DraftState } from "@/lib/facility-form";
import { failed, text, type FormState } from "@/lib/forms";
import type { FacilityLetter } from "@/lib/types";
import { upload } from "@/lib/upload";

/** A new walk-in draft: the applicant's name (and email, if they have one) and the form. */
export async function createWalkIn(_: DraftState, data: FormData): Promise<DraftState> {
  let saved: FacilityLetter;
  try {
    saved = await api<FacilityLetter>("/etls/facility-letters/walk-in", {
      method: "POST",
      json: { applicant_name: text(data, "applicant_name"), applicant_email: text(data, "applicant_email") || null, form: formBody(data) },
    });
  } catch (error) {
    return { ...failed(error), values: typed(data) };
  }
  redirect(`/staff/walk-in/${saved.case_id}?saved=1`);
}

export async function saveWalkIn(caseId: number, _: DraftState, data: FormData): Promise<DraftState> {
  try {
    await api(`/etls/facility-letters/${caseId}`, { method: "PUT", json: formBody(data) });
  } catch (error) {
    return { ...failed(error), values: typed(data) };
  }
  redirect(`/staff/walk-in/${caseId}?saved=1`);
}

export async function uploadWalkInDocument(caseId: number, type: string, _: FormState, data: FormData): Promise<FormState> {
  return upload(caseId, type, `/staff/walk-in/${caseId}`, data);
}

/** Submit for the applicant: it goes to Records' queue like any application. */
export async function submitWalkIn(caseId: number, _: FormState): Promise<FormState> {
  try {
    await api(`/cases/${caseId}/status`, { method: "POST", json: { to_status: "submitted" } });
  } catch (error) {
    if (error instanceof ApiError) return { error: error.message.replace(/^Not ready: /, "Not ready yet: ") };
    throw error;
  }
  redirect(`/staff?case=${caseId}`);
}
