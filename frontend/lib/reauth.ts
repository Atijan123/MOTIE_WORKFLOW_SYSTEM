// Step 12f: should the case's buttons ask for the password? Kept apart from
// the components so it can be unit-tested.
import type { Action, SessionInfo } from "./types";

// Ask a little early: the page may sit open for a while before the click.
const MARGIN_MS = 2 * 60_000;

/** True when one of the moves needs a recent password and it won't be recent by the time someone clicks. */
export function passwordNeeded(actions: Action[], login: SessionInfo, now = Date.now()): boolean {
  if (!actions.some((a) => a.needs_recent_password)) return false;
  return new Date(login.password_fresh_until).getTime() - now < MARGIN_MS;
}
