// An ended session sends you to the login page. The session cookie lasts as
// long as the API's token (60 minutes); once it's gone, opening a staff page
// used to crash with "Not authenticated" instead. Read-only: no reset needed.
import { expect, test } from "@playwright/test";

import { APPLICANT_URL, loginAs, PASSWORD, STAFF_URL } from "./helpers";

test("a staff page with no session cookie goes to the login page", async ({ browser }) => {
  const page = await loginAs(browser, "desk@motie.test");
  await page.context().clearCookies(); // what the browser does when the cookie expires
  await page.goto("/staff");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
});

test("a wrong password still shows its message on the login page", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: STAFF_URL })).newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill("desk@motie.test");
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Incorrect email or password")).toBeVisible();
});

// Step 12b: two apps. The public portal has no staff screens, and a staff
// password is no use there.
test("the applicant portal has no staff screens", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: APPLICANT_URL })).newPage();
  const response = await page.goto("/staff");
  expect(response?.status()).toBe(404);
});

test("a staff account can't sign in through the applicant portal", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: APPLICANT_URL })).newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill("desk@motie.test");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Incorrect email or password")).toBeVisible();
});

test("the staff app has no applicant screens", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: STAFF_URL })).newPage();
  const response = await page.goto("/applications");
  expect(response?.status()).toBe(404);
});

// Step 12d: five failures lock the account. A made-up email, unique per run,
// so no seeded account is locked for the tests after this one.
test("five wrong passwords lock the account", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: APPLICANT_URL })).newPage();
  const email = `lockout-${Date.now()}@e2e.test`;
  await page.goto("/login");
  const tryOnce = async () => {
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("not the password");
    // Wait for the form's own answer each time: the message from the try
    // before is still on the page, so seeing it proves nothing.
    await Promise.all([
      page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/login"),
      page.getByRole("button", { name: "Log in" }).click(),
    ]);
  };
  for (let i = 0; i < 5; i++) await tryOnce();
  await expect(page.getByText("Incorrect email or password")).toBeVisible();
  await tryOnce();
  await expect(page.getByText(/Too many failed attempts: this account is locked/)).toBeVisible();
});
