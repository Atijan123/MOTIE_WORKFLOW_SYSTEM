import { createHmac } from "node:crypto";

import { expect, type Browser, type Page } from "@playwright/test";

// The seeded dev users (backend/app/dev_seed.py), all with the same password.
export const PASSWORD = process.env.DEV_SEED_PASSWORD || "dev password 123";

// The two apps (step 12b): applicants use the portal, staff the staff app.
export const APPLICANT_URL = process.env.BASE_URL ?? "http://localhost:3001";
export const STAFF_URL = process.env.STAFF_URL ?? "http://localhost:3002";

/** The app `email` signs in to: the seeded applicants use the portal, everyone else is staff. */
export function appFor(email: string): string {
  return email === "applicant@motie.test" || email.endsWith("@demo.test") ? APPLICANT_URL : STAFF_URL;
}

// Every seeded staff account's authenticator secret (backend/app/dev_seed.py, DEV_TOTP_SECRET).
const DEV_TOTP_SECRET = "MOTIEDEVTOTPSECRETDEVONLY234567A";

function base32(text: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of text.replace(/=+$/, "")) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const bytes = bits.match(/.{8}/g) ?? [];
  return Buffer.from(bytes.map((b) => parseInt(b, 2)));
}

/** The code an authenticator app shows for `step` (RFC 6238, as backend/app/core/identity/totp.py). */
export function totpCode(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const number = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(number % 1_000_000).padStart(6, "0");
}

const currentStep = () => Math.floor(Date.now() / 30_000);
// The last 30-second step each account signed in with: a code works once, so
// a second sign-in in the same 30 seconds waits for the next code.
const lastStep = new Map<string, number>();

async function giveCode(page: Page, email: string) {
  let step = currentStep();
  if ((lastStep.get(email) ?? -1) >= step) {
    await page.waitForTimeout((step + 1) * 30_000 - Date.now() + 200);
    step = currentStep();
  }
  await page.getByLabel("6-digit code from your authenticator app").fill(totpCode(DEV_TOTP_SECRET, step));
  await page.getByRole("button", { name: "Sign in" }).click();
  lastStep.set(email, step);
}

/** A fresh browser session (its own cookies), on that person's app, logged in as `email`. Staff also give their code (step 12e). */
export async function loginAs(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext({ baseURL: appFor(email) });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  if (appFor(email) === STAFF_URL) {
    await expect(page).toHaveURL(/\/login\/code/);
    await giveCode(page, email);
    const signedIn = await page
      .waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    // Still here: this 30 seconds' code was already used (e.g. by the demo seed, just before). The next one.
    if (!signedIn) {
      await expect(page.getByText("That code didn't work")).toBeVisible();
      lastStep.set(email, currentStep());
      await giveCode(page, email);
    }
  }
  await expect(page).not.toHaveURL(/\/login/);
  return page;
}

/** The smallest file the API accepts as a PDF (it checks the content, not the name). */
export function pdf(name: string) {
  const body = [
    "%PDF-1.4",
    "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
    "2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj",
    "trailer << /Root 1 0 R >>",
    "%%EOF",
  ].join("\n");
  return { name, mimeType: "application/pdf", buffer: Buffer.from(body) };
}

/** "2026-10-26" for `days` days from today (negative: in the past). */
export function isoDay(days = 0): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}
