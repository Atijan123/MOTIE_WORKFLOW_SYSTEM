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

/** A fresh browser session (its own cookies), on that person's app, logged in as `email`. */
export async function loginAs(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext({ baseURL: appFor(email) });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
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
