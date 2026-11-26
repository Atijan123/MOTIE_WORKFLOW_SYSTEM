// Who is logged in, for server components and actions.
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import { api, SESSION_COOKIE } from "./api";
import { PORTAL } from "./portal";
import type { Me } from "./types";


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

/**
 * For pages: the user, or off to the login page. `kind` keeps applicants and
 * staff on their own screens. Each app only has its own pages (next.config.mjs),
 * and the API refuses a staff login through the applicant portal and the
 * reverse; this is one more check, in case a page is ever misnamed.
 */
export async function requireUser(kind?: "applicant" | "staff"): Promise<Me> {
  if (kind && kind !== PORTAL) notFound();
  const me = await getMe();
  if (!me) redirect("/login");
  if (kind && (kind === "staff") !== isStaff(me)) notFound();
  return me;
}

/** Keep the token in the cookie for as long as its session lasts (`seconds`, from the API:
 * 8 hours for staff, 60 minutes for applicants). The API also signs staff out after 30 idle minutes. */
export async function startSession(token: string, seconds: number): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, token, {
    // httpOnly: page scripts can't read it, so a script injected into a page
    // couldn't steal the login. SameSite=Lax: other sites can't send it with
    // their own form posts.
    httpOnly: true,
    sameSite: "lax",
    // Only over https on a real server; plain http works on localhost for development.
    secure: process.env.NODE_ENV === "production" && process.env.COOKIE_SECURE !== "false",
    path: "/",
    maxAge: seconds,
  });
}

/** Sign out: end the session on the server (so a copied token stops working too), then forget the cookie. */
export async function endSession(): Promise<void> {
  if ((await cookies()).get(SESSION_COOKIE)) {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined); // already ended: fine
  }
  (await cookies()).delete(SESSION_COOKIE);
}

/** Each app's home. (Whoever is signed in to an app is of its kind: the API makes sure.) */
export const HOME = PORTAL === "staff" ? "/staff" : "/applications";
