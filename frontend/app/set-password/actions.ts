"use server";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";

export async function setPassword(_: FormState, data: FormData): Promise<FormState> {
  const password = String(data.get("password") ?? "");
  if (password !== String(data.get("confirm") ?? "")) return { error: "The two passwords aren’t the same." };
  try {
    await api("/auth/set-password", { method: "POST", json: { token: text(data, "token"), password } });
  } catch (error) {
    return failed(error);
  }
  redirect("/login?set=1");
}
