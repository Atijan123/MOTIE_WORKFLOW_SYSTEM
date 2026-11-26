// Which front end this server is (step 12b). The same code is built twice:
//   PORTAL=applicant  the public applicant portal (app/**/page.applicant.tsx)
//   PORTAL=staff      the staff app, on the Ministry network (app/**/page.staff.tsx)
// next.config.mjs picks the pages; each build contains only its own screens.
// Unset means "applicant": a server that forgets to say is the public one,
// and the public one can do the least.
export type Portal = "staff" | "applicant";

export const PORTAL: Portal = process.env.PORTAL === "staff" ? "staff" : "applicant";

/**
 * What this server tells the API on every call (backend/app/core/identity/channel.py):
 * its portal key, the address the browser opened, and the browser's IP.
 * The IP is taken only from X-Real-IP, which the HTTPS proxy (Caddy) sets
 * itself and overwrites if a browser sends one. In development there is no
 * proxy, so there's no IP; the IP allowlist is off there.
 */
export function forwardedHeaders(
  incoming: { get(name: string): string | null },
  portalKey: string | undefined,
): Record<string, string> {
  const out: Record<string, string> = {};
  if (portalKey) out["X-Portal-Key"] = portalKey;
  const host = incoming.get("host");
  if (host) out["X-Forwarded-Host"] = host;
  const ip = incoming.get("x-real-ip");
  if (ip) out["X-Client-IP"] = ip.trim();
  return out;
}

/** The login cookie's name. Different per portal: on a developer's machine both run on localhost, and cookies ignore the port. */
export function sessionCookieName(portal: Portal): string {
  return portal === "staff" ? "motie_staff_session" : "motie_session";
}
