"use server";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { failed, text, type FormState } from "@/lib/forms";
import { endSession, HOME, startSession } from "@/lib/session";
import type { LoginAnswer, SetUpDone } from "@/lib/types";

// Between the password and the code (step 12e), the API's challenge waits in
// this cookie: httpOnly (page scripts can't read it), for 5 minutes only.
const CHALLENGE_COOKIE = "motie_staff_challenge";
const CHALLENGE_SECONDS = 5 * 60;

export async function login(_: FormState, data: FormData): Promise<FormState> {
  let answer: LoginAnswer;
  try {
    answer = await api<LoginAnswer>("/auth/login", {
      method: "POST",
      json: { email: text(data, "email"), password: data.get("password") ?? "" },
    });
  } catch (error) {
    // The API gives one answer for every failure, so nothing is learned here either.
    if (error instanceof ApiError && error.status === 401) return { error: "Incorrect email or password." };
    return failed(error);
  }
  if (answer.next === "done" && answer.access_token) {
    await startSession(answer.access_token);
    redirect(HOME);
  }
  (await cookies()).set(CHALLENGE_COOKIE, answer.challenge ?? "", {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production" && process.env.COOKIE_SECURE !== "false",
    path: "/login",
    maxAge: CHALLENGE_SECONDS,
  });
  redirect(answer.next === "set_up" ? "/login/set-up" : "/login/code");
}

/** The challenge from the password step, or off to the start if it has gone. */
export async function challenge(): Promise<string> {
  const value = (await cookies()).get(CHALLENGE_COOKIE)?.value;
  if (!value) redirect("/login?expired=1");
  return value;
}

async function finish(token: string): Promise<void> {
  (await cookies()).delete({ name: CHALLENGE_COOKIE, path: "/login" });
  await startSession(token);
}

/** The second step: a code from the authenticator app, or a recovery code. */
export async function submitCode(_: FormState, data: FormData): Promise<FormState> {
  const path = data.get("kind") === "recovery" ? "/auth/login/recovery-code" : "/auth/login/code";
  let answer: LoginAnswer;
  try {
    answer = await api<LoginAnswer>(path, { method: "POST", json: { challenge: await challenge(), code: text(data, "code") } });
  } catch (error) {
    return failed(error);
  }
  await finish(answer.access_token ?? "");
  redirect(HOME);
}

export type SetUpState = FormState & { recoveryCodes?: string[] };

/** The first code from a newly set-up authenticator. Signs in and shows the recovery codes, once. */
export async function confirmSetUp(_: SetUpState, data: FormData): Promise<SetUpState> {
  let answer: SetUpDone;
  try {
    answer = await api<SetUpDone>("/auth/two-step/confirm", {
      method: "POST",
      json: { challenge: await challenge(), code: text(data, "code") },
    });
  } catch (error) {
    return failed(error);
  }
  await finish(answer.access_token ?? "");
  return { recoveryCodes: answer.recovery_codes };
}

export async function logout(): Promise<void> {
  await endSession();
  redirect("/login");
}
