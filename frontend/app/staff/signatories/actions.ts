"use server";
// S12's server actions. The API checks the signatory_admin role and every rule
// (staff only, not yourself, not twice); these pass on what was chosen.
import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";
import type { Signatory } from "@/lib/types";

export async function addSignatory(listCode: string, _: FormState, data: FormData): Promise<FormState> {
  let added: Signatory;
  try {
    added = await api<Signatory>(`/signatories/${encodeURIComponent(listCode)}/members`, {
      method: "POST",
      json: { user_id: Number(text(data, "user_id")) },
    });
  } catch (error) {
    return failed(error);
  }
  // The whole staff area: the new signatory's queue and banner change too.
  revalidatePath("/staff", "layout");
  return { done: `${added.name} is on the list from now on.` };
}

export async function removeSignatory(id: number, name: string, _: FormState): Promise<FormState> {
  try {
    await api(`/signatories/members/${id}/remove`, { method: "POST" });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff", "layout");
  return { done: `${name} is off the list from now on.` };
}
