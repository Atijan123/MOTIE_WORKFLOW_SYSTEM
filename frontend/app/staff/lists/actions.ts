"use server";
// The admin's changes to the form's lists. The API checks the admin role and
// every rule (unique names, no deleting); these pass on what was typed.
import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";

export type ListKind = "countries" | "units";

export async function addListItem(kind: ListKind, _: FormState, data: FormData): Promise<FormState> {
  const name = text(data, "name");
  try {
    await api(`/etls/lists/${kind}`, { method: "POST", json: { name } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff/lists");
  return { done: `Added “${name}”.` };
}

export async function renameListItem(kind: ListKind, id: number, _: FormState, data: FormData): Promise<FormState> {
  try {
    await api(`/etls/lists/${kind}/${id}`, { method: "PATCH", json: { name: text(data, "name") } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff/lists");
  return { done: "Saved." };
}

export async function setListItemActive(kind: ListKind, id: number, active: boolean, _: FormState): Promise<FormState> {
  try {
    await api(`/etls/lists/${kind}/${id}`, { method: "PATCH", json: { active } });
  } catch (error) {
    return failed(error);
  }
  revalidatePath("/staff/lists");
  return {};
}
