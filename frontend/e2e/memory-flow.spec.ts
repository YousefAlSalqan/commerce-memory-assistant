import { expect, test } from "@playwright/test";

test("carries explicit memories into a later session", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Add profile").fill(`E2E ${Date.now()}`);
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByRole("heading", { name: "Start a new session" })).toBeVisible();

  await page.getByRole("button", { name: "Use demo prompt" }).click();
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/I can help with that/)).toBeVisible();

  await page.getByRole("button", { name: "End session" }).click();
  await expect(page.getByRole("heading", { name: "Memories" })).toBeVisible();
  await expect(page.getByText("Follows a vegetarian diet")).toBeVisible();
  await expect(page.getByText("Allergic to peanuts", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Chat" }).click();
  await page.getByLabel("Message").fill("What should I order tonight?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/Based on what I remember/)).toBeVisible();
});
