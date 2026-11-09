// S11, absences and delegations, in the browser. Each test ends what it
// started, so nobody is left "away" for the other walk-throughs.
import { expect, test } from "@playwright/test";

import { isoDay, loginAs } from "./helpers";

test("the PS records an absence, the DPS acts for them, and the PS ends it early", async ({ browser }) => {
  const ps = await loginAs(browser, "ps@motie.test");
  await ps.getByRole("link", { name: "Absences" }).click();
  const form = ps.getByRole("form", { name: "Record my absence" });
  await expect(ps.getByRole("region", { name: "I will be away" })).toContainText("under the agreed succession order");
  await form.getByLabel("From", { exact: true }).fill(isoDay(0));
  await form.getByLabel("To", { exact: true }).fill(isoDay(2));
  await form.getByLabel("Reason (optional)").fill("Regional trade meeting");
  await form.getByRole("button", { name: "Record my absence" }).click();
  await expect(form.getByRole("status")).toHaveText("Your absence is recorded.");

  const list = ps.getByRole("region", { name: "Current and upcoming absences" });
  const mine = list.getByRole("row", { name: /Dev Permanent Secretary/ });
  await expect(mine).toContainText("Regional trade meeting"); // the person sees their own reason
  await expect(mine).toContainText("Deputy Permanent Secretary, Administration and Finance (Dev Deputy PS), succession");
  await expect(mine).toContainText("Themselves");

  // Everyone on every screen: the stand-in sees the banner, and not the reason.
  const dps = await loginAs(browser, "dps@motie.test");
  await expect(dps.getByRole("status").filter({ hasText: "You are acting for the Permanent Secretary" })).toBeVisible();
  await dps.getByRole("link", { name: "Absences" }).click();
  const seenByDps = dps.getByRole("row", { name: /Dev Permanent Secretary/ });
  await expect(seenByDps).not.toContainText("Regional trade meeting");
  await expect(seenByDps.getByRole("button")).toHaveCount(0); // not theirs to cancel

  await mine.getByRole("button", { name: "End early" }).click();
  await expect(list.getByRole("row", { name: /Dev Permanent Secretary/ })).toHaveCount(0);
  await dps.reload();
  await expect(dps.getByText("You are acting for the Permanent Secretary")).toHaveCount(0);
});

test("the Minister delegates to the PS for one service, then revokes it", async ({ browser }) => {
  const minister = await loginAs(browser, "minister@motie.test");
  await minister.goto("/staff/absences");
  const form = minister.getByRole("form", { name: "Record my absence" });
  await form.getByLabel("From", { exact: true }).fill(isoDay(1));
  await form.getByLabel("To", { exact: true }).fill(isoDay(3));
  await form.getByLabel("Delegate to").selectOption({ label: "Permanent Secretary" });
  await form.getByLabel("For", { exact: true }).selectOption("etls_application");
  await form.getByRole("button", { name: "Record my absence" }).click();
  await expect(form.getByRole("status")).toHaveText("Your absence and the delegation are recorded.");

  const delegation = minister.getByRole("form", { name: "Delegation to the Permanent Secretary" });
  await expect(delegation).toContainText("delegated to the Permanent Secretary");
  const row = minister.getByRole("row", { name: /Dev Minister/ });
  await expect(row).toContainText("Permanent Secretary (Dev Permanent Secretary), delegation, for ETLS application");
  await delegation.getByRole("button", { name: "Revoke" }).click();
  await expect(delegation).toHaveCount(0);

  // The absence itself stays until cancelled, back on the succession order.
  await expect(row).not.toContainText("delegation");
  await row.getByRole("button", { name: "Cancel" }).click();
  await expect(row).toHaveCount(0);
});

test("a recorder records someone else's absence", async ({ browser }) => {
  const recorder = await loginAs(browser, "recorder@motie.test");
  await recorder.goto("/staff/absences");
  // The recorder holds no post, so there's no "I will be away" form for them.
  await expect(recorder.getByRole("form", { name: "Record my absence" })).toHaveCount(0);
  const form = recorder.getByRole("form", { name: "Record an absence for someone else" });
  await form.getByLabel("Who is away").selectOption({ label: "Director of Industry and Investment: Dev Director of Industry" });
  await form.getByLabel("From", { exact: true }).fill(isoDay(5));
  await form.getByLabel("To", { exact: true }).fill(isoDay(9));
  await form.getByLabel("Reason (optional)").fill("Walk-through leave");
  await form.getByRole("button", { name: "Record absence" }).click();
  await expect(form.getByRole("status")).toContainText("The absence is recorded");

  // By its reason: the demo seed has other absences for this Director.
  const row = recorder.getByRole("row", { name: /Dev Director of Industry/ }).filter({ hasText: "Walk-through leave" });
  await expect(row).toContainText("Dev Absence Recorder");
  await row.getByRole("button", { name: "Cancel" }).click();
  await expect(row).toHaveCount(0);
});
