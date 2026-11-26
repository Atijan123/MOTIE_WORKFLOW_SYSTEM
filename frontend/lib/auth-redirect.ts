// Where to send someone when the API answers 401, or null to let the caller
// show the error. Kept apart from api.ts (which needs Next.js) so it can be
// unit-tested.

// Where a 401 means "that password or code was wrong", for the form to say,
// not "your session has ended" (step 12e added the code steps).
const CHECKS_A_SECRET = [
  "/auth/login",
  "/auth/login/code",
  "/auth/login/recovery-code",
  "/auth/two-step/set-up",
  "/auth/two-step/confirm",
  "/auth/two-step/recovery-codes",
];

/**
 * Any 401 means "sign in (again)": the token expired, or the cookie holding
 * it did (it lasts as long as the token), so there may be no token at all.
 * The exceptions are a wrong password or code, which the form shows.
 */
export function signInAgainPath(status: number, path: string, hadToken: boolean): string | null {
  if (status !== 401 || CHECKS_A_SECRET.includes(path)) return null;
  return hadToken ? "/login?expired=1" : "/login";
}
