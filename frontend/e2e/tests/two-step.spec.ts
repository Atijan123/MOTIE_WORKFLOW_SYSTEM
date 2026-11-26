// Step 12e: two-step sign-in for staff. The first sign-in sets up an
// authenticator and shows the recovery codes; a recovery code then signs in once.
// Uses firstlogin@motie.test, which the dev seed leaves without an
// authenticator: after a reset, this test can run once.
import { expect, test } from "@playwright/test";

import { PASSWORD, STAFF_URL, totpCode } from "./helpers";

test("the first sign-in sets up an authenticator; a recovery code signs in once", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: STAFF_URL })).newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill("firstlogin@motie.test");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page).toHaveURL(/\/login\/set-up/);
  await expect(page.getByRole("img", { name: "QR code for your authenticator app" })).toBeVisible();
  // What a person would type into the app instead of scanning.
  const key = (await page.locator(".setup-key").innerText()).replace(/\s/g, "");
  await page.getByLabel("Then type the 6-digit code the app shows").fill(totpCode(key, Math.floor(Date.now() / 30_000)));
  await page.getByRole("button", { name: "Turn on two-step sign-in" }).click();

  const codes = page.getByRole("region", { name: "Recovery codes" }).locator("code");
  await expect(codes).toHaveCount(10);
  const first = await codes.first().innerText();
  await page.getByRole("link", { name: "I’ve saved them: continue" }).click();
  await expect(page).toHaveURL(/\/staff$/);

  // Lost phone: a recovery code instead of the app's code.
  const again = await (await browser.newContext({ baseURL: STAFF_URL })).newPage();
  const signIn = async () => {
    await again.goto("/login");
    await again.getByLabel("Email").fill("firstlogin@motie.test");
    await again.getByLabel("Password").fill(PASSWORD);
    await again.getByRole("button", { name: "Log in" }).click();
    await expect(again).toHaveURL(/\/login\/code/);
    await again.getByRole("link", { name: "Use a recovery code" }).click();
    await again.getByLabel("Recovery code").fill(first);
    await again.getByRole("button", { name: "Sign in" }).click();
  };
  await signIn();
  await expect(again).toHaveURL(/\/staff$/);
  await again.context().clearCookies();
  // The same recovery code a second time: refused.
  await signIn();
  await expect(again.getByText("That code didn't work")).toBeVisible();
});

test("a password alone doesn't sign staff in", async ({ browser }) => {
  const page = await (await browser.newContext({ baseURL: STAFF_URL })).newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill("desk@motie.test");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/login\/code/);
  // Skipping the code: the staff pages still send you to sign in.
  await page.goto("/staff");
  await expect(page).toHaveURL(/\/login/);
});
