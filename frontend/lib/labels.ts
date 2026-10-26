import type { FacilityLetter } from "./types";

// What applicants see of a facility letter's progress (SCREENS.md A2). The
// API gives the steps already taken (the timeline); these are the ones still
// ahead, for the greyed-out part of the timeline.
export const FACILITY_LETTER_STEPS = [
  "Submitted",
  "Originals checked",
  "Being verified",
  "Awaiting signature",
  "Letter signed",
  "Letter sent to GRA",
];

/** The steps after `current`; none when it isn't on the normal path (returned, rejected, done). */
export function stepsAhead(current: string): string[] {
  const at = FACILITY_LETTER_STEPS.indexOf(current === "Resubmitted" ? "Submitted" : current);
  return at === -1 ? (current === "Draft" ? FACILITY_LETTER_STEPS : []) : FACILITY_LETTER_STEPS.slice(at + 1);
}

/** The colour of a status label. */
export function pillClass(label: string): string {
  if (label.startsWith("Returned") || label === "Rejected") return "pill pill-warn";
  if (label === "Letter sent to GRA" || label === "Corrected letter issued") return "pill pill-done";
  if (label === "Draft") return "pill pill-neutral";
  return "pill";
}

/** "1,200 bags of poultry feed", as the mock-ups write the goods. */
export function goods(letter: FacilityLetter | null): string {
  if (!letter) return "Application";
  const amount = [letter.quantity ? Number(letter.quantity).toLocaleString("en-GB") : null, letter.unit].filter(Boolean).join(" ");
  return [amount, letter.product].filter(Boolean).join(" of ") || "Not filled in yet";
}

/** "230990" -> "2309.90", "2309901000" -> "2309.90.10.00": the API keeps digits only; people write the dots. */
export function hsCode(digits: string): string {
  if (!/^\d{6,}$/.test(digits)) return digits;
  return [digits.slice(0, 4), ...(digits.slice(4).match(/\d{1,2}/g) ?? [])].join(".");
}
