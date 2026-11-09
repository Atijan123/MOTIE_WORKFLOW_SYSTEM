// S13: the statistics page for the Director and statistics viewers. The dev
// database has no historical register (only the demo seed imports a fictional
// one), so this checks the page, its filters and the CSV, not particular numbers.
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
  await expect(viewer.getByRole("region", { name: "Letters" })).toContainText("match the filters");

  const csvLink = viewer.getByRole("link", { name: "Download these letters (CSV)" });
  expect(await csvLink.getAttribute("href")).toContain("importer=Kombo");
  const csv = await viewer.request.get((await csvLink.getAttribute("href")) as string);
  expect(csv.status()).toBe(200);
  expect(csv.headers()["content-type"]).toContain("text/csv");
  expect(await csv.text()).toContain("Source,Reference,Letter no.,Date,Importer");
});

test("the Director sees the statistics; the desk doesn't", async ({ browser }) => {
  const director = await loginAs(browser, "director@motie.test");
  await expect(director.getByRole("link", { name: "Statistics" })).toBeVisible();
  const desk = await loginAs(browser, "desk@motie.test");
  await expect(desk.getByRole("link", { name: "Statistics" })).toHaveCount(0);
  expect((await desk.goto("/staff/statistics"))?.status()).toBe(404);
});
