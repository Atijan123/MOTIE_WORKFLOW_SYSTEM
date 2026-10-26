// Run with `npm test` (Node's own test runner; no test library needed).
// The cases match test_the_date_is_written_the_ministrys_way in
// backend/tests/modules/etls/test_letter.py.
import assert from "node:assert/strict";
import { test } from "node:test";

import { dayRange, longDate, ordinal, shortDateTime } from "./dates.ts";

test("ordinals", () => {
  const expected: Record<number, string> = {
    1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 11: "11th", 12: "12th", 13: "13th",
    21: "21st", 22: "22nd", 23: "23rd", 31: "31st",
  };
  for (const [n, text] of Object.entries(expected)) assert.equal(ordinal(Number(n)), text);
});

test("the Ministry's long date", () => {
  assert.equal(longDate("2026-09-16"), "16th September, 2026");
  assert.equal(longDate("2026-10-01"), "1st October, 2026");
  assert.equal(longDate("2026-10-22T23:59:00+00:00"), "22nd October, 2026");
  assert.equal(longDate("2026-11-13"), "13th November, 2026");
});

test("absence ranges", () => {
  assert.equal(dayRange("2026-10-20", "2026-10-24"), "20th–24th October");
  assert.equal(dayRange("2026-10-30", "2026-11-03"), "30th October – 3rd November");
  assert.equal(dayRange("2026-12-29", "2027-01-02"), "29th December, 2026 – 2nd January, 2027");
  assert.equal(dayRange("2026-10-20", "2026-10-20"), "20th October");
});

test("history times", () => {
  assert.equal(shortDateTime("2026-10-15T11:02:00Z"), "15th Oct, 11:02");
});
