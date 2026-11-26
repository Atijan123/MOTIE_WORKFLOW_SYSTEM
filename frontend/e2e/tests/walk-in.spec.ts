// Step 13b: Records enters an application for an importer who came in
// person: the form, the documents, then Submit. In office mode this is the
// only way an application gets in. The case then waits in Records' queue.
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
  await expect(records.getByRole("region", { name: "Case" })).toContainText("Sowe Hardware");
});
