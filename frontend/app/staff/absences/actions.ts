"use server";
// S11's server actions. The API checks every rule (dates, who may record for
// whom, which posts you hold); these pass on what was typed.
import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";

/** "I will be away", with an optional delegation to another post. */
export async function recordMyAbsence(_: FormState, data: FormData): Promise<FormState> {
  const dates = { starts_on: text(data, "starts_on"), ends_on: text(data, "ends_on") };
  const reason = text(data, "reason") || null;
  const delegateTo = text(data, "to_position");
  try {
    // The delegation first: if it's refused, nothing is recorded and the
    // person can fix the form. A delegation with no absence is harmless; an
    // absence whose delegation silently failed would hand files to the wrong post.
    if (delegateTo) {
      await api("/delegations", {
        method: "POST",
        json: { ...dates, from_position: text(data, "from_position"), to_position: delegateTo, workflow: text(data, "workflow") || null, reason },
      });
    }
    await api("/absences", { method: "POST", json: { ...dates, reason } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff", "layout");
  return { done: delegateTo ? "Your absence and the delegation are recorded." : "Your absence is recorded." };
}

/** A recorder (PS's office, HR) records someone else's absence. */
export async function recordAbsenceFor(_: FormState, data: FormData): Promise<FormState> {
  try {
    await api("/absences", {
      method: "POST",
      json: {
        user_id: Number(text(data, "user_id")),
        starts_on: text(data, "starts_on"),
        ends_on: text(data, "ends_on"),
        reason: text(data, "reason") || null,
      },
    });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff", "layout");
  return { done: "The absence is recorded, with you as the person who recorded it." };
}

export async function cancelAbsence(absenceId: number, _: FormState): Promise<FormState> {
  try {
    await api(`/absences/${absenceId}/cancel`, { method: "POST" });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff", "layout");
  return {};
}

export async function revokeDelegation(delegationId: number, _: FormState): Promise<FormState> {
  try {
    await api(`/delegations/${delegationId}/revoke`, { method: "POST" });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff", "layout");
  return {};
}
