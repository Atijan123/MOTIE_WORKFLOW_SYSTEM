"use server";
import { redirect } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";
import { endSession, HOME, startSession } from "@/lib/session";

export async function login(_: FormState, data: FormData): Promise<FormState> {
  let token: string;
  try {
    const answer = await api<{ access_token: string }>("/auth/login", {
      method: "POST",
      json: { email: text(data, "email"), password: data.get("password") ?? "" },
    });
    token = answer.access_token;
  } catch (error) {
    // The API gives one answer for every failure, so nothing is learned here either.
    if (error instanceof ApiError && error.status === 401) return { error: "Incorrect email or password." };
    return failed(error);
  }
  await startSession(token);
  redirect(HOME);
}

export async function logout(): Promise<void> {
  await endSession();
  redirect("/login");
}
