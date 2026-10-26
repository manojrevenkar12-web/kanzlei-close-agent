import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

// Runs against a freshly seeded demo (`python -m kanzlei_sim seed --links <file>`): July and August
// signed off, September in progress. Tests that change data run only in the desktop project.
const links = JSON.parse(readFileSync(process.env["E2E_LINKS"] ?? "../backend/.demo-links.json", "utf8")) as {
  period: string;
  portal: Record<string, string>;
};

async function signInAs(page: Page, name: RegExp) {
  await page.goto("/anmelden");
  await page.getByRole("button", { name }).click();
}

async function noSidewaysScroll(page: Page) {
  // A phone lays out a page that is too wide at the wider size and zooms out, so compare with the
  // screen, not with innerWidth.
  const [scroll, screenWidth] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    window.screen.width,
  ]);
  expect(scroll).toBeLessThanOrEqual(screenWidth);
}

test("an advisor reviews a proposal and the month moves towards sign-off", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "changes data");
  await signInAs(page, /Claudia Hartmann/);
  await expect(page.getByRole("heading", { name: "Monatsabschluss", level: 1 })).toBeVisible();
  // Any client with a proposal under review (the test can run more than once against one seed).
  const withReview = page.getByRole("link", { name: /öffnen/ }).filter({ hasText: /\d+ prüfen/ });
  await expect(withReview.first(), "no client has a proposal under review; reseed the demo").toBeVisible();
  await withReview.first().click();

  const filters = page.getByRole("tablist", { name: "Filter" });
  const review = filters.getByRole("tab", { name: /Zu prüfen/ });
  const before = Number((await review.textContent())?.match(/\d+/)?.[0]);
  expect(before).toBeGreaterThan(0);
  await review.click();
  await page.getByRole("button", { name: "Übernehmen" }).click();
  await expect(page.getByText(/Entschieden von Claudia Hartmann/)).toBeVisible();
  await expect(review).toContainText(String(before - 1));

  await page.getByRole("link", { name: "Umsatzsteuer und Freigabe" }).click();
  await expect(page.getByRole("heading", { name: "Umsatzsteuer-Voranmeldung" })).toBeVisible();
  // One item still waits on the client, so the month cannot be signed off yet.
  await expect(page.getByRole("button", { name: "Monat festschreiben" })).toBeDisabled();
});

test("a signed-off month is locked and exports to DATEV", async ({ page }) => {
  await signInAs(page, /Claudia Hartmann/);
  await page.getByRole("tab", { name: "Aug 26" }).click();
  await page.getByRole("link", { name: /Elektro Baumann GmbH öffnen/ }).click();
  await expect(page.getByRole("button", { name: "Abschluss ausführen" })).toHaveCount(0);
  await page.getByRole("link", { name: "Umsatzsteuer und Freigabe" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "DATEV-Export (EXTF)" }).click();
  expect((await download).suggestedFilename()).toMatch(/^EXTF_/);
});

test("a client answers a question in the portal without an account", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "changes data");
  // A portal link that still has an open question.
  let found = false;
  for (const token of Object.values(links.portal)) {
    await page.goto(`/portal/${token}`);
    await expect(page.getByRole("heading", { name: /Fragen zur Buchhaltung/ })).toBeVisible();
    if ((await page.locator("form").count()) > 0) {
      found = true;
      break;
    }
  }
  expect(found, "every portal question is answered; reseed the demo").toBe(true);
  const first = page.locator("form").first();
  const options = first.getByRole("radio");
  // Pick the option that needs no file and fill whatever it asks for.
  const count = await options.count();
  for (let i = 0; i < count; i++) {
    const label = (await options.nth(i).locator("xpath=..").textContent()) ?? "";
    if (!/hochladen/i.test(label)) {
      await options.nth(i).check();
      break;
    }
  }
  for (const input of await first.locator("input:not([type=radio]):not([type=file])").all()) {
    await input.fill("Kundentermin mit Herrn Weber, Angebot Neubau");
  }
  await first.getByRole("button", { name: "Antwort senden" }).click();
  await expect(page.getByText("Beantwortet. Danke!").first()).toBeVisible();
});

test("the group engineer sees firms, never a client's items", async ({ page }) => {
  await signInAs(page, /Lena Hoffmann/);
  await expect(page.getByRole("heading", { name: "Rollout über die Kanzleien" })).toBeVisible();
  await expect(page.getByText("Steuerbüro Brandt")).toBeVisible();
  await expect(page.getByText("Elektro Baumann")).toHaveCount(0);
  await page.goto(`/mandanten/hp-10101/${links.period}`);
  await expect(page.getByRole("alert").first()).toBeVisible();
});

test("every screen fits a phone without sideways scrolling", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile", "layout check for phones");
  await signInAs(page, /Claudia Hartmann/);
  await expect(page.getByRole("link", { name: /Elektro Baumann GmbH öffnen/ })).toBeVisible();
  await noSidewaysScroll(page);
  for (const path of ["", "/rueckfragen", "/umsatzsteuer"].flatMap((t) => [
    `${links.period}${t}`,
    `2026-08${t}`,
  ])) {
    await page.goto(`/mandanten/hp-10101/${path}`);
    await expect(page.getByRole("heading", { name: "Elektro Baumann GmbH", level: 1 })).toBeVisible();
    await page.waitForTimeout(400);
    await noSidewaysScroll(page);
  }
  await page.goto("/qualitaet");
  await expect(page.getByRole("heading", { name: "Wie gut ist der Agent?" })).toBeVisible();
  await noSidewaysScroll(page);
});
