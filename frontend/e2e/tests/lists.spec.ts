// The admin keeps the form's lists (countries, units); the applicant's form
// offers what's switched on. Entries can't be deleted, so this test uses a
// new name each run and switches it off at the end.
import { expect, test } from "@playwright/test";

import { loginAs } from "./helpers";

test("an admin adds a unit, the form offers it, and the admin switches it off", async ({ browser }) => {
  const unit = `drums ${Date.now()}`;

  const admin = await loginAs(browser, "admin@motie.test");
  await admin.getByRole("link", { name: "Lists" }).click();
  const add = admin.getByRole("form", { name: "Add to Units" });
  await add.getByLabel("New entry").fill(unit);
  await add.getByRole("button", { name: "Add" }).click();
  await expect(add.getByRole("status")).toHaveText(`Added “${unit}”.`);

  const applicant = await loginAs(browser, "applicant@motie.test");
  await applicant.goto("/applications/new");
  await expect(applicant.getByLabel("Unit").locator("option", { hasText: unit })).toHaveCount(1);
  // Mali, Burkina Faso and Niger are not on the list [CONFIRM].
  await expect(applicant.getByLabel("Country").locator("option", { hasText: "Mali" })).toHaveCount(0);

  await admin.getByRole("form", { name: `Switch ${unit} off` }).getByRole("button").click();
  await expect(admin.getByRole("row", { name: new RegExp(unit) })).toContainText("No, switched off");
  await applicant.reload();
  await expect(applicant.getByLabel("Unit").locator("option", { hasText: unit })).toHaveCount(0);
});

test("only admins see the lists", async ({ browser }) => {
  const records = await loginAs(browser, "records@motie.test");
  await expect(records.getByRole("link", { name: "Lists" })).toHaveCount(0);
  const response = await records.goto("/staff/lists");
  expect(response?.status()).toBe(404);
});
