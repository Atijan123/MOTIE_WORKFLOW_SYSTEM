// The whole facility letter route in the browser (SCREENS.md A1, A2, S1, S2,
// S3): an importer applies, Records sees the originals, the desk verifies, the
// Director signs for the PS, Records sends the letter to GRA, and the importer sees it.
import { expect, test, type Page } from "@playwright/test";

import { isoDay, loginAs, pdf } from "./helpers";

const DOCUMENTS = [
  "Business registration certificate",
  "Annual returns certificate",
  "Certificate of origin",
  "Invoice",
  "Export declaration",
];

/** Opens a case in a staff queue by its short reference ("FL/2026/0007"). */
async function openFromQueue(page: Page, shortRef: string) {
  await page.goto("/staff");
  await page.getByRole("link", { name: shortRef, exact: true }).click();
  await expect(page.getByRole("region", { name: "Case" })).toContainText(shortRef);
}

test("a facility letter goes from draft to Sent to GRA", async ({ browser }) => {
  // Unique per run, so a second run doesn't trip the duplicate-certificate flag.
  const certificate = `CO-E2E-${Date.now()}`;

  // --- A2: the importer fills in the form, uploads, submits --------------------
  const applicant = await loginAs(browser, "applicant@motie.test");
  await expect(applicant).toHaveURL(/\/applications/);
  await applicant.getByRole("link", { name: /Apply for a facility letter/ }).click();

  await applicant.getByLabel("Business name").fill("Kombo Feeds Ltd");
  await applicant.getByLabel("Address").fill("12 Kairaba Avenue, Serrekunda");
  await applicant.getByLabel("Product", { exact: true }).fill("Poultry feed");
  await applicant.getByLabel("Quantity").fill("1,200");
  await applicant.getByLabel("Unit").selectOption("bags");
  await applicant.getByLabel("HS code (optional)").fill("2309.90");
  await applicant.getByLabel("Exporter", { exact: true }).fill("Dakar Agro SA");
  await applicant.getByLabel("Country").selectOption("Senegal");
  await applicant.getByLabel("Exporter’s ETLS approval number").fill("SN-ETLS-0042");
  await applicant.getByLabel("Product approval number 1").fill("SN-PA-0042-01");
  await applicant.getByLabel("Certificate 1 number").fill(certificate);
  await applicant.getByLabel("Issue date").first().fill(isoDay(-10));
  await applicant.getByRole("button", { name: "Save draft" }).click();
  await expect(applicant.getByText("Draft saved.")).toBeVisible();

  // Nothing uploaded yet: Submit is disabled and says why.
  await expect(applicant.getByRole("button", { name: "Submit application" })).toBeDisabled();
  await expect(applicant.getByText("Invoice is missing")).toBeVisible();

  for (const name of DOCUMENTS) {
    const row = applicant.getByRole("form", { name: `Upload ${name}` });
    await row.getByLabel(`File for ${name}`).setInputFiles(pdf(`${name}.pdf`));
    await row.getByRole("button", { name: "Upload" }).click();
    await expect(applicant.getByText(`${name}.pdf`, { exact: true })).toBeVisible();
  }

  await expect(applicant.getByText("Everything is filled in. Check it, then submit.")).toBeVisible();
  await applicant.getByRole("button", { name: "Submit application" }).click();
  const selected = applicant.getByRole("complementary", { name: "Selected application" });
  await expect(selected).toContainText("Submitted");
  const reference = (await selected.textContent())!.match(/MOTIE\/ETLS\/FL\/\d{4}\/\d{4}/)![0];
  const shortRef = reference.replace("MOTIE/ETLS/", "");

  // --- S1: Records sees the original certificate and accepts ------------------
  const records = await loginAs(browser, "records@motie.test");
  await openFromQueue(records, shortRef);
  const accept = records.getByRole("button", { name: "Accept: originals received" });
  await expect(accept).toBeDisabled(); // the original isn't seen yet
  await records.getByRole("form", { name: "Original of Certificate of origin" }).getByRole("button").click();
  // The button gives way to the record itself.
  await expect(records.getByText(/✓ Original seen/)).toBeVisible();
  await expect(accept).toBeEnabled();
  await accept.click();
  await expect(records.getByText(`${reference} is now:`)).toBeVisible();

  // --- S2: the desk confirms the HS code, ticks the ECOWAS list, verifies -----
  const desk = await loginAs(browser, "desk@motie.test");
  await openFromQueue(desk, shortRef);
  const verify = desk.getByRole("button", { name: "Verify and send for signature" });
  await expect(verify).toBeDisabled();
  await desk.getByLabel("HS code").fill("2309.90");
  await desk.getByRole("button", { name: "Confirm code" }).click();
  await expect(desk.getByText("Confirmed: 2309.90.")).toBeVisible();
  const tick = desk.getByRole("button", { name: "Mark as checked" });
  while ((await tick.count()) > 0) {
    const before = await tick.count();
    await tick.first().click();
    await expect(tick).toHaveCount(before - 1);
  }
  await expect(verify).toBeEnabled();
  await verify.click();
  await expect(desk.getByText(`${reference} is now:`)).toBeVisible();

  // --- S3: the Director reads the checks and the preview, and signs for the PS --
  const ps = await loginAs(browser, "director@motie.test");
  await openFromQueue(ps, shortRef);
  await expect(ps.getByRole("region", { name: "Checks done" })).toContainText("HS code 2309.90 confirmed");
  await expect(ps.getByTitle("Letter preview")).toBeVisible();
  await ps.getByRole("button", { name: "Sign letter" }).click();
  await expect(ps.getByText(`${reference} is now:`)).toBeVisible();

  // --- S1 Outgoing: Records downloads the letter and marks it sent ------------
  await records.getByRole("link", { name: /Outgoing/ }).click();
  const row = records.getByRole("row", { name: new RegExp(shortRef) });
  await expect(row).toBeVisible();
  const download = await records.request.get(await row.getByRole("link", { name: "Download PDF" }).getAttribute("href") as string);
  expect(download.headers()["content-type"]).toBe("application/pdf");
  await row.getByRole("button", { name: "Mark sent to GRA" }).click();
  await expect(records.getByRole("status")).toContainText(`${reference} marked as sent to GRA on`);
  await expect(row).toHaveCount(0);

  // --- A1/A3: the importer sees the letter has gone to GRA ---------------------
  await applicant.reload();
  await expect(selected).toContainText("Letter sent to GRA");
  await applicant.getByRole("link", { name: "Open on its own page" }).click();
  await expect(applicant.getByRole("status")).toContainText("Letter sent to GRA");
});
