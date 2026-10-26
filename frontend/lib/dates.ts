// Dates the Ministry's way: "16th October, 2026". The same rules as
// long_date() in backend/app/core/dates.py, so screens and letters agree.
//
// The Gambia is on GMT all year (UTC+0, no summer time), so dates are read in
// UTC. That way the server and every browser show the same day.

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function ordinal(n: number): string {
  // 11th, 12th and 13th break the 1st/2nd/3rd pattern.
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

/** "2026-10-16" or "2026-10-16T09:30:00+00:00" (or a Date) -> "16th October, 2026". */
export function longDate(value: string | Date): string {
  const d = toDate(value);
  return `${ordinal(d.getUTCDate())} ${MONTHS[d.getUTCMonth()]}, ${d.getUTCFullYear()}`;
}

/** "16th Oct, 09:30": for history lines, where the year is rarely needed. */
export function shortDateTime(value: string | Date): string {
  const d = toDate(value);
  const time = `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
  return `${ordinal(d.getUTCDate())} ${MONTHS[d.getUTCMonth()].slice(0, 3)}, ${time}`;
}

/** "20th–24th October", "30th October – 3rd November", "29th December, 2026 – 2nd January, 2027". */
export function dayRange(start: string, end: string): string {
  const a = toDate(start);
  const b = toDate(end);
  const month = (d: Date) => MONTHS[d.getUTCMonth()];
  if (a.getUTCFullYear() !== b.getUTCFullYear()) return `${longDate(a)} – ${longDate(b)}`;
  if (a.getUTCMonth() !== b.getUTCMonth()) {
    return `${ordinal(a.getUTCDate())} ${month(a)} – ${ordinal(b.getUTCDate())} ${month(b)}`;
  }
  if (a.getUTCDate() === b.getUTCDate()) return `${ordinal(a.getUTCDate())} ${month(a)}`;
  return `${ordinal(a.getUTCDate())}–${ordinal(b.getUTCDate())} ${month(a)}`;
}

/** Today in The Gambia, as "2026-10-16" (for date inputs). */
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function toDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  // A bare date ("2026-10-16") is read as midnight UTC, which is what we want.
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) throw new Error(`Not a date: ${value}`);
  return d;
}
