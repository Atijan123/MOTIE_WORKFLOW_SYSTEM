import { expect, type Browser, type Page } from "@playwright/test";

// The seeded dev users (backend/app/dev_seed.py), all with the same password.
export const PASSWORD = process.env.DEV_SEED_PASSWORD || "dev password 123";

/** A fresh browser session (its own cookies), logged in as `email`. */
export async function loginAs(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext();
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
