"use server";
// Staff server actions. Each calls one API endpoint; the API decides who may
// do what, so these only pass on what was typed or clicked.
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { longDate } from "@/lib/dates";
import { failed, text, type FormState } from "@/lib/forms";
import type { Case } from "@/lib/types";

/** Make a move. Which move is the button that was pressed (name="to_status"). */
export async function moveCase(caseId: number, _: FormState, data: FormData): Promise<FormState> {
  const toStatus = text(data, "to_status");
  let moved: Case;
  try {
    moved = await api<Case>(`/cases/${caseId}/status`, {
      method: "POST",
      json: {
        to_status: toStatus,
        comment: text(data, "comment") || null,
        // Sent only with a move that tells the applicant something; the API refuses it otherwise.
        applicant_message: data.get(`message_for_${toStatus}`) === "yes" ? text(data, "applicant_message") || null : null,
      },
    });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff", "layout");
  redirect(`/staff?done=${encodeURIComponent(`${moved.reference ?? "The case"} is now: ${moved.status.name}`)}`);
}

export async function markOriginalSeen(caseId: number, documentId: number, _: FormState): Promise<FormState> {
  try {
    await api(`/cases/${caseId}/documents/${documentId}/original-seen`, { method: "POST" });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff");
  return { done: "Recorded: original seen in person." };
}

export async function resolveFlag(caseId: number, flagId: number, _: FormState, data: FormData): Promise<FormState> {
  try {
    await api(`/cases/${caseId}/flags/${flagId}/resolve`, { method: "POST", json: { resolution: text(data, "resolution") } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff");
  return { done: "Flag cleared." };
}

export async function confirmHsCode(caseId: number, _: FormState, data: FormData): Promise<FormState> {
  try {
    await api(`/etls/facility-letters/${caseId}/hs-code`, { method: "POST", json: { hs_code: text(data, "hs_code") } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff");
  return { done: "HS code confirmed." };
}

export async function setTick(caseId: number, code: string, ticked: boolean, _: FormState): Promise<FormState> {
  try {
    await api(`/cases/${caseId}/checklist/${code}`, { method: "PUT", json: { ticked } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff");
  return {};
}

/** Records' "Mark sent to GRA", with the dispatch date (Outgoing tab). */
export async function markSentToGra(caseId: number, _: FormState, data: FormData): Promise<FormState> {
  const dispatchedOn = text(data, "dispatched_on");
  let sent: Case;
  try {
    sent = await api<Case>(`/etls/facility-letters/${caseId}/sent-to-gra`, { method: "POST", json: { dispatched_on: dispatchedOn } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff", "layout");
  // The row leaves the table, so the confirmation goes on the page instead.
  const done = `${sent.reference ?? "The letter"} marked as sent to GRA on ${longDate(dispatchedOn)}.`;
  redirect(`/staff/outgoing?done=${encodeURIComponent(done)}`);
}
