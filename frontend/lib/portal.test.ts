import assert from "node:assert/strict";
import { test } from "node:test";

import { forwardedHeaders, sessionCookieName } from "./portal.ts";

const incoming = (values: Record<string, string>) => ({ get: (name: string) => values[name] ?? null });

test("the API is told the portal key, the browser's address and the proxy's IP", () => {
  assert.deepEqual(forwardedHeaders(incoming({ host: "staff.motie.test", "x-real-ip": " 10.0.0.7 " }), "the-key"), {
    "X-Portal-Key": "the-key",
    "X-Forwarded-Host": "staff.motie.test",
    "X-Client-IP": "10.0.0.7",
  });
});

test("a browser's own X-Forwarded-For is never passed on as its IP", () => {
  // Anyone can send X-Forwarded-For; only X-Real-IP, set by Caddy, is used.
  const headers = forwardedHeaders(incoming({ host: "localhost:3002", "x-forwarded-for": "10.0.0.1" }), "k");
  assert.equal(headers["X-Client-IP"], undefined);
});

test("no key configured: no key header at all", () => {
  assert.equal(forwardedHeaders(incoming({}), undefined)["X-Portal-Key"], undefined);
});

test("the two apps keep their logins in different cookies", () => {
  assert.notEqual(sessionCookieName("staff"), sessionCookieName("applicant"));
});
