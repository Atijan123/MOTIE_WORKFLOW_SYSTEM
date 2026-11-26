import assert from "node:assert/strict";
import { test } from "node:test";

import { passwordNeeded } from "./reauth.ts";
import type { Action, SessionInfo } from "./types.ts";

const sign = { to_status: "signed", needs_recent_password: true } as Action;
const accept = { to_status: "originals_received", needs_recent_password: false } as Action;
const now = Date.parse("2026-11-26T10:00:00Z");
const freshUntil = (minutes: number): SessionInfo => ({
  ends_at: "2026-11-26T18:00:00Z",
  idle_minutes: 30,
  password_fresh_until: new Date(now + minutes * 60_000).toISOString(),
});

test("signing asks for the password once it's no longer recent (with two minutes to spare)", () => {
  assert.equal(passwordNeeded([sign], freshUntil(8), now), false);
  assert.equal(passwordNeeded([sign], freshUntil(1), now), true);
  assert.equal(passwordNeeded([sign], freshUntil(-5), now), true);
});

test("other moves never ask", () => {
  assert.equal(passwordNeeded([accept], freshUntil(-5), now), false);
});
