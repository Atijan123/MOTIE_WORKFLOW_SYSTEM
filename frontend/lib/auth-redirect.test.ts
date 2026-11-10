import assert from "node:assert/strict";
import { test } from "node:test";

import { signInAgainPath } from "./auth-redirect.ts";

test("a 401 sends you to sign in, with or without a cookie", () => {
  assert.equal(signInAgainPath(401, "/cases/queue", true), "/login?expired=1");
  // The cookie itself expired: no token was sent, and the page used to crash here.
  assert.equal(signInAgainPath(401, "/cases/queue", false), "/login");
});

test("a wrong password at login, and other errors, are left to the caller", () => {
  assert.equal(signInAgainPath(401, "/auth/login", false), null);
  assert.equal(signInAgainPath(403, "/etls/statistics", true), null);
  assert.equal(signInAgainPath(200, "/cases/queue", true), null);
});
