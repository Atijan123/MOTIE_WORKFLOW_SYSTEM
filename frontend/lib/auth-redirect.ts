// Where to send someone when the API answers 401, or null to let the caller
// show the error. Kept apart from api.ts (which needs Next.js) so it can be
// unit-tested.

/**
 * Any 401 means "sign in (again)": the token expired, or the cookie holding
 * it did (it lasts as long as the token), so there may be no token at all.
 * The one exception is a wrong password at login, which the login form shows.
 */
export function signInAgainPath(status: number, path: string, hadToken: boolean): string | null {
  if (status !== 401 || path === "/auth/login") return null;
  return hadToken ? "/login?expired=1" : "/login";
}
