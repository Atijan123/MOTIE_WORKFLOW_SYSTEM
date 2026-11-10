// An ended session sends you to the login page. The session cookie lasts as
// long as the API's token (60 minutes); once it's gone, opening a staff page
// used to crash with "Not authenticated" instead. Read-only: no reset needed.
import { expect, test } from "@playwright/test";

import { loginAs } from "./helpers";

test("a staff page with no session cookie goes to the login page", async ({ browser }) => {
  const page = await loginAs(browser, "desk@motie.test");
  await page.context().clearCookies(); // what the browser does when the cookie expires
  await page.goto("/staff");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
});

test("a wrong password still shows its message on the login page", async ({ browser }) => {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill("desk@motie.test");
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Incorrect email or password")).toBeVisible();
});
