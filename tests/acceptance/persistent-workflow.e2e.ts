import { expect, test } from "@playwright/test";

test("registers, completes, and restores the persistent product workflow", async ({
  page,
}) => {
  const email = `acceptance-${Date.now()}@example.com`;
  const password = "acceptance-test-password";

  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Acceptance User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  const registrationResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/auth/register"),
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const response = await registrationResponse;
  expect(response.status()).toBe(201);
  expect(new URL(response.url()).origin).toBe(new URL(page.url()).origin);
  expect(response.headers()["cache-control"]).toContain("no-store");
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  await expect(page.getByText("PromptPilot", { exact: true })).toBeVisible();

  const registeredCookies = await page.context().cookies();
  expect(
    registeredCookies.some(
      (cookie) =>
        cookie.name === "promptpilot_acceptance_session" && cookie.httpOnly,
    ),
  ).toBe(true);

  const frontendHealth = await page.request.get("/healthz");
  expect(frontendHealth.status()).toBe(404);
  const attemptedOpenProxy = await page.request.get(
    "/api/v1/http://127.0.0.1:8132/health",
  );
  expect(attemptedOpenProxy.status()).toBe(404);
  const providerBeforeWorkflow = await page.request.get(
    "http://127.0.0.1:8132/health",
  );
  expect((await providerBeforeWorkflow.json()).request_count).toBe(0);

  const logoutResponse = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith("/api/v1/auth/logout") &&
      candidate.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign out" }).click();
  const loggedOut = await logoutResponse;
  expect(loggedOut.status()).toBe(204);
  expect(new URL(loggedOut.url()).origin).toBe(new URL(page.url()).origin);
  expect(loggedOut.headers()["cache-control"]).toContain("no-store");
  await expect(page).toHaveURL(/\/login$/);
  await page.waitForLoadState("load");
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  const loginResponse = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith("/api/v1/auth/login") &&
      candidate.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  const loggedIn = await loginResponse;
  expect(loggedIn.status()).toBe(200);
  expect(new URL(loggedIn.url()).origin).toBe(new URL(page.url()).origin);
  expect(loggedIn.headers()["cache-control"]).toContain("no-store");
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  await expect(page.getByText("PromptPilot", { exact: true })).toBeVisible();
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);

  await expect(page.getByText("My PromptPilot", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "New prompt" }).click();
  const promptBox = page.getByRole("textbox", { name: "Prompt to improve" });
  await promptBox.fill(
    "Create a clear, concise plan for launching a community workshop.",
  );
  await expect(page.getByText(/\/100 ·/)).toBeVisible();
  const savedRequest = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/conversations/") &&
      response.url().endsWith("/messages") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Improve prompt" }).click();
  expect((await savedRequest).status()).toBe(201);
  await expect(
    page.getByText("Create a clear, concise plan", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText(/I found \d+ area/)).toBeVisible();

  const skipQuestion = page.getByRole("button", { name: "Skip", exact: true });
  const promptReady = page.getByRole("heading", {
    name: "Your prompt is ready",
  });
  for (let count = 0; count < 20; count += 1) {
    await expect
      .poll(
        async () =>
          (await promptReady.isVisible().catch(() => false)) ||
          (await skipQuestion.isVisible().catch(() => false)),
      )
      .toBe(true);
    if (await promptReady.isVisible().catch(() => false)) break;
    await expect(skipQuestion).toBeVisible();
    const skipped = page.waitForResponse(
      (response) =>
        response.url().includes("/skip") &&
        response.request().method() === "POST",
    );
    await skipQuestion.click();
    await skipped;
  }
  await expect(promptReady).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy prompt" })).toBeVisible();

  await page.getByRole("button", { name: "Test original" }).click();
  await expect(page.getByText(/Local deterministic response/)).toBeVisible();
  await page.getByRole("button", { name: "Test improved" }).click();
  await expect(page.getByText(/Local deterministic response/)).toHaveCount(2);

  await page.reload();
  await expect(
    page.getByText("Create a clear, concise plan", { exact: false }),
  ).toBeVisible();
  await expect(promptReady).toBeVisible();
  await expect(page.getByText(/Local deterministic response/)).toHaveCount(2);

  const fakeProviderResponse = await page.request.get(
    "http://127.0.0.1:8132/health",
  );
  const fakeProviderHealth = await fakeProviderResponse.json();
  expect(fakeProviderHealth).toMatchObject({ status: "ok" });
  expect(fakeProviderHealth.request_count).toBeGreaterThan(0);
});
