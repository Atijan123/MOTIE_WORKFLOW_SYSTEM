"use server";
import { api } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";

export type CodesState = FormState & { recoveryCodes?: string[] };

/** A new set of recovery codes; needs a current code from the phone (step 12e). */
export async function newRecoveryCodes(_: CodesState, data: FormData): Promise<CodesState> {
  try {
    const answer = await api<{ recovery_codes: string[] }>("/auth/two-step/recovery-codes", {
      method: "POST",
      json: { code: text(data, "code") },
    });
    return { recoveryCodes: answer.recovery_codes };
  } catch (error) {
    return failed(error);
  }
}
