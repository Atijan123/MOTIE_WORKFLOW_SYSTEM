// S12: the Director's office keeps the authorised signatories list. Entries are
// never deleted, so this test takes Dev Signatory Two off and puts them back,
// leaving the list as the dev seed made it (with two more history rows).
import { expect, test } from "@playwright/test";

import { loginAs } from "./helpers";

test("the Director's office removes a signatory and adds them back", async ({ browser }) => {
  const office = await loginAs(browser, "signatories@motie.test");
  await office.getByRole("link", { name: "Signatories" }).click();
  await expect(office.getByRole("heading", { name: "Authorised signatories", level: 1 })).toBeVisible();

  const current = office.getByRole("table", { name: "Current signatories" });
  await expect(current.getByRole("row", { name: /Dev Signatory One/ })).toContainText("Dev Signatory Admin");
  await office.getByRole("form", { name: "Remove Dev Signatory Two" }).getByRole("button").click();
  await expect(current.getByRole("row", { name: /Dev Signatory Two/ })).toHaveCount(0);

  const add = office.getByRole("form", { name: /^Add to / });
  await add.getByLabel("Add an officer").selectOption({ label: "Dev Signatory Two" });
  await add.getByRole("button", { name: "Add" }).click();
  await expect(add.getByRole("status")).toHaveText("Dev Signatory Two is on the list from now on.");
  await expect(current.getByRole("row", { name: /Dev Signatory Two/ })).toBeVisible();

  // The removal stays on record.
  await office.getByText(/Earlier signatories/).click();
  await expect(office.getByRole("table", { name: "Earlier signatories" }).getByRole("row", { name: /Dev Signatory Two/ }).first()).toBeVisible();
});

test("only the Director's office sees the list", async ({ browser }) => {
  const director = await loginAs(browser, "director@motie.test");
  await expect(director.getByRole("link", { name: "Signatories" })).toHaveCount(0);
  expect((await director.goto("/staff/signatories"))?.status()).toBe(404);
});

test("S11 tells the Director the signatories sign while they are away", async ({ browser }) => {
  const director = await loginAs(browser, "director@motie.test");
  await director.getByRole("link", { name: "Absences" }).click();
  await expect(director.getByRole("region", { name: "I will be away" })).toContainText(
    "any officer on the authorised signatories list can sign (Dev Signatory One, Dev Signatory Two)",
  );
});
