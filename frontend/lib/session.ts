// Who is logged in, for server components and actions.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { api, SESSION_COOKIE } from "./api";
import type { Me } from "./types";

// The API's tokens last 60 minutes (ACCESS_TOKEN_MINUTES); the cookie no longer.
const SESSION_SECONDS = 60 * 60;

export function isStaff(me: Me): boolean {
  return me.roles.some((r) => r !== "applicant");
}

/** S13: the Director, or the stats_viewer role (the API checks it again: statistics.py may_view()). */
export function mayViewStatistics(me: Me): boolean {
  return me.roles.includes("stats_viewer") || me.positions.includes("director_of_industry");
}

/** The logged-in user, or null. Asked once per request (React's cache). */
export const getMe = cache(async (): Promise<Me | null> => {
  if (!(await cookies()).get(SESSION_COOKIE)) return null;
  return api<Me>("/auth/me");
});

/** For pages: the user, or off to the login page. `kind` keeps applicants and staff on their own screens. */
export async function requireUser(kind?: "applicant" | "staff"): Promise<Me> {
  const me = await getMe();
  if (!me) redirect("/login");
  if (kind === "staff" && !isStaff(me)) redirect("/applications");
  if (kind === "applicant" && isStaff(me)) redirect("/staff");
  return me;
}

export async function startSession(token: string): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, token, {
    // httpOnly: page scripts can't read it, so a script injected into a page
    // couldn't steal the login. SameSite=Lax: other sites can't send it with
    // their own form posts.
    httpOnly: true,
    sameSite: "lax",
    // Only over https on a real server; plain http works on localhost for development.
    secure: process.env.NODE_ENV === "production" && process.env.COOKIE_SECURE !== "false",
    path: "/",
    maxAge: SESSION_SECONDS,
  });
}

export async function endSession(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
}

export function homeFor(me: Me): string {
  return isStaff(me) ? "/staff" : "/applications";
}
