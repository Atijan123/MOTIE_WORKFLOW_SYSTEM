// S13: the statistics page for the Director and statistics viewers. Needs the
// demo seed (scripts/seed-demo.sh) and its fictional register: one Kombo Feeds
// letter dated 14th August 2025.
import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { loginAs } from "./helpers";

test("a statistics viewer filters the figures and downloads the letters as CSV", async ({ browser }) => {
  const viewer = await loginAs(browser, "stats@motie.test");
  await viewer.getByRole("link", { name: "Statistics" }).click();
  await expect(viewer.getByRole("heading", { name: "ETLS statistics", level: 1 })).toBeVisible();
  await expect(viewer.getByRole("region", { name: "Letters by year" })).toContainText(/Based on \d+ letter/);

  const filters = viewer.getByRole("form", { name: "Filters" });
  await filters.getByLabel("From").fill("2025-01-01");
  await filters.getByLabel("Importer (part of the name)").fill("Kombo");
  await filters.getByRole("button", { name: "Show" }).click();
  await expect(viewer).toHaveURL(/date_from=2025-01-01/);
  await expect(viewer.getByRole("region", { name: "Letters", exact: true })).toContainText("match the filters");

  const csvLink = viewer.getByRole("link", { name: "Download these letters (CSV)" });
  expect(await csvLink.getAttribute("href")).toContain("importer=Kombo");
  const csv = await viewer.request.get((await csvLink.getAttribute("href")) as string);
  expect(csv.status()).toBe(200);
  expect(csv.headers()["content-type"]).toContain("text/csv");
  expect(await csv.text()).toContain("Source,Reference,Letter no.,Date,Importer");
});

test("the Director filters by date range and importer, and downloads the CSV", async ({ browser }) => {
  const director = await loginAs(browser, "director@motie.test");
  await director.getByRole("link", { name: "Statistics" }).click();
  await expect(director.getByRole("heading", { name: "ETLS statistics", level: 1 })).toBeVisible();

  const filters = director.getByRole("form", { name: "Filters" });
  await filters.getByLabel("From").fill("2025-08-01");
  await filters.getByLabel("To").fill("2025-08-31");
  await filters.getByLabel("Importer (part of the name)").fill("Kombo");
  await filters.getByRole("button", { name: "Show" }).click();
  await expect(director).toHaveURL(/date_from=2025-08-01&date_to=2025-08-31&importer=Kombo/);
  await expect(director.getByRole("region", { name: "Letters", exact: true })).toContainText(
    "1 letter match the filters: 0 signed in this system, 1 from the historical register.",
  );

  // A real browser download, so the attachment headers are exercised too.
  const [download] = await Promise.all([
    director.waitForEvent("download"),
    director.getByRole("link", { name: "Download these letters (CSV)" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("etls-facility-letters-2025-08-01-2025-08-31.csv");
  const lines = (await readFile(await download.path(), "utf-8")).replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  expect(lines[0]).toContain("Source,Reference,Letter no.,Date,Importer");
  expect(lines).toHaveLength(2); // the heading and the one letter
  expect(lines[1]).toContain("2025-08-14");
  expect(lines[1]).toContain("Kombo Feeds Ltd");
});

test("the Director sees the statistics; the desk doesn't", async ({ browser }) => {
  const director = await loginAs(browser, "director@motie.test");
  await expect(director.getByRole("link", { name: "Statistics" })).toBeVisible();
  const desk = await loginAs(browser, "desk@motie.test");
  await expect(desk.getByRole("link", { name: "Statistics" })).toHaveCount(0);
  expect((await desk.goto("/staff/statistics"))?.status()).toBe(404);
});
