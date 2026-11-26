// Step 13b: Records enters an application for an importer who came in
// person: the form, the documents, then Submit. In office mode this is the
// only way an application gets in. It then follows the usual route; once it's
// sent to GRA, Records prints the applicant's copy and hands it over.
import { expect, test } from "@playwright/test";

import { isoDay, loginAs, pdf } from "./helpers";

const DOCUMENTS = ["Business registration certificate", "Annual returns certificate", "Certificate of origin", "Invoice", "Export declaration"];

test("Records enters a walk-in application and submits it", async ({ browser }) => {
  const records = await loginAs(browser, "records@motie.test");
  await records.getByRole("link", { name: "New walk-in" }).click();

  await records.getByLabel("Applicant’s full name").fill("Ebrima Sowe");
  await records.getByLabel("Business name").fill("Sowe Hardware");
  await records.getByLabel("Address").fill("5 Garba Jahumpa Road, Bakau");
  await records.getByLabel("Product", { exact: true }).fill("Cement blocks");
  await records.getByLabel("Quantity").fill("500");
  await records.getByLabel("Unit").selectOption("pieces");
  await records.getByLabel("Exporter", { exact: true }).fill("Dakar Blocks SA");
  await records.getByLabel("Country").selectOption("Senegal");
  await records.getByLabel("Exporter’s ETLS approval number").fill("SN-ETLS-0777");
  await records.getByLabel("Product approval number 1").fill("SN-PA-0777-01");
  await records.getByLabel("Certificate 1 number").fill(`CO-WALKIN-${Date.now()}`);
  await records.getByLabel("Issue date").first().fill(isoDay(-7));
  await records.getByRole("button", { name: "Save draft" }).click();
  await expect(records.getByText("Saved.")).toBeVisible();
  await expect(records).toHaveURL(/\/staff\/walk-in\/\d+/);

  for (const name of DOCUMENTS) {
    const row = records.getByRole("form", { name: `Upload ${name}` });
    await row.getByLabel(`File for ${name}`).setInputFiles(pdf(`${name}.pdf`));
    await row.getByRole("button", { name: "Upload" }).click();
    await expect(records.getByText(`${name}.pdf`, { exact: true })).toBeVisible();
  }
  await expect(records.getByText("Everything is filled in.")).toBeVisible();
  await records.getByRole("button", { name: "Submit application" }).click();

  // Into Records' own queue, like any application.
  await expect(records).toHaveURL(/\/staff\?case=\d+/);
  const panel = records.getByRole("region", { name: "Case" });
  await expect(panel).toContainText("Sowe Hardware");
  const shortRef = (await panel.textContent())!.match(/FL\/\d{4}\/\d{4}/)![0];

  // --- The usual route: Records accepts, the desk verifies, the Director signs.
  await records.getByRole("form", { name: "Original of Certificate of origin" }).getByRole("button").click();
  await records.getByRole("button", { name: "Accept: originals received" }).click();
  await expect(records.getByText("is now:")).toBeVisible();

  const desk = await loginAs(browser, "desk@motie.test");
  await desk.goto("/staff");
  await desk.getByRole("link", { name: shortRef, exact: true }).click();
  await desk.getByLabel("HS code").fill("6810.11");
  await desk.getByRole("button", { name: "Confirm code" }).click();
  // Wait for the answer: the checks to tick appear only after it. (Its wording
  // differs when the applicant gave no code, so wait for the checks themselves.)
  const tick = desk.getByRole("button", { name: "Mark as checked" });
  await expect(tick.first()).toBeVisible();
  while ((await tick.count()) > 0) {
    const before = await tick.count();
    await tick.first().click();
    await expect(tick).toHaveCount(before - 1);
  }
  const verify = desk.getByRole("button", { name: "Verify and send for signature" });
  await expect(verify).toBeEnabled();
  await verify.click();
  await expect(desk.getByText("is now:")).toBeVisible();

  const director = await loginAs(browser, "director@motie.test");
  await director.goto("/staff");
  await director.getByRole("link", { name: shortRef, exact: true }).click();
  await director.getByRole("button", { name: "Sign letter" }).click();
  await expect(director.getByText("is now:")).toBeVisible();

  // --- Outgoing: send to GRA, then print the applicant's copy and hand it over.
  await records.goto("/staff/outgoing");
  await records.getByRole("row", { name: new RegExp(shortRef) }).getByRole("button", { name: "Mark sent to GRA" }).click();
  const copies = records.getByRole("region", { name: "Applicant copies to hand over" });
  const row = copies.getByRole("row", { name: new RegExp(shortRef) });
  await expect(row).toContainText("Ebrima Sowe");
  const print = row.getByRole("link", { name: "Print applicant copy" });
  const copy = await records.request.get((await print.getAttribute("href"))!);
  expect(copy.headers()["content-type"]).toBe("application/pdf");
  await row.getByRole("button", { name: "Mark handed over" }).click();
  await expect(records.getByRole("status")).toContainText("applicant’s copy recorded as handed over");
  await expect(copies.getByRole("row", { name: new RegExp(shortRef) })).toHaveCount(0);
});
