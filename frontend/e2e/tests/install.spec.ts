// Step 12h: the staff app can be installed from the browser (a PWA). Chrome
// offers "Install" when a page links a manifest with a name, a start page and
// 192 and 512 pixel icons, on https (the office server) or localhost.
// Read-only: no reset needed.
import { expect, test } from "@playwright/test";

import { STAFF_URL } from "./helpers";

test("the staff app describes itself for installing", async ({ request }) => {
  const manifest = await request.get(`${STAFF_URL}/manifest.webmanifest`);
  expect(manifest.ok()).toBeTruthy();
  const app = await manifest.json();
  expect(app).toMatchObject({ name: "MOTIE ETLS Staff", start_url: "/staff", display: "standalone" });
  const sizes = app.icons.map((i: { sizes: string; purpose: string }) => `${i.sizes} ${i.purpose}`);
  expect(sizes).toEqual(expect.arrayContaining(["192x192 any", "512x512 any", "512x512 maskable"]));
  for (const icon of app.icons) {
    const png = await request.get(`${STAFF_URL}${icon.src}`);
    expect(png.headers()["content-type"]).toBe("image/png");
  }

  const worker = await request.get(`${STAFF_URL}/sw.js`);
  expect(worker.ok()).toBeTruthy();
  // Checked for updates on every visit.
  expect(worker.headers()["cache-control"]).toContain("no-cache");
  expect((await request.get(`${STAFF_URL}/offline.html`)).ok()).toBeTruthy();
});

test("every staff page links the manifest", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: STAFF_URL })).newPage();
  await page.goto("/login");
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");
});
