import assert from "node:assert/strict";
import { test } from "node:test";

import { hsCode } from "./labels.ts";

test("HS codes are written with dots", () => {
  assert.equal(hsCode("230990"), "2309.90");
  assert.equal(hsCode("25232900"), "2523.29.00");
  assert.equal(hsCode("2309901000"), "2309.90.10.00");
  assert.equal(hsCode("2309.90"), "2309.90"); // already written out: left alone
});
