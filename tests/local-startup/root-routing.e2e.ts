import { mkdirSync } from "node:fs";

import { expect, test } from "@playwright/test";

test("root routes through registration, persisted session, and logout", async ({
  page,
}) => {
  const screenshotDirectory = "test-results/screenshots";
  const email = `local-startup-${Date.now()}@example.com`;
  mkdirSync(screenshotDirectory, { recursive: true });

  const rootNavigation = await page.goto("http://localhost:3000/");
  expect(rootNavigation).not.toBeNull();
  expect(rootNavigation?.status()).not.toBe(404);
  await expect(page).toHaveURL("http://localhost:3000/login");
  await expect(page.getByText("This page could not be found")).toHaveCount(0);
  await page.screenshot({
    path: `${screenshotDirectory}/root-after-redirect.png`,
    fullPage: true,
  });

  await page.goto("http://localhost:3000/login");
  await expect(
    page.getByRole("heading", { name: "PromptPilot" }),
  ).toBeVisible();
  await page.screenshot({
    path: `${screenshotDirectory}/login.png`,
    fullPage: true,
  });

  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page).toHaveURL("http://localhost:3000/register");
  await page.screenshot({
    path: `${screenshotDirectory}/registration.png`,
    fullPage: true,
  });
  await page.getByLabel("Display name").fill("Local Startup User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("local-startup-password");

  const registration = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/auth/register") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create account" }).click();
  expect((await registration).status()).toBe(201);
  await expect(page).toHaveURL("http://localhost:3000/dashboard");
  await expect(
    page.getByRole("heading", { name: "Welcome, Local Startup User" }),
  ).toBeVisible();
  await page.screenshot({
    path: `${screenshotDirectory}/dashboard.png`,
    fullPage: true,
  });

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Welcome, Local Startup User" }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);

  await page.goto("http://localhost:3000/");
  await expect(page).toHaveURL("http://localhost:3000/dashboard");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("http://localhost:3000/login");
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
  await page.goto("http://localhost:3000/dashboard");
  await expect(page).toHaveURL("http://localhost:3000/login");
});
