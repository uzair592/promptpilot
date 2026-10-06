import { expect, test } from "@playwright/test";

test("registers, completes, and restores the persistent product workflow", async ({
  page,
}) => {
  const email = `acceptance-${Date.now()}@example.com`;
  const password = "acceptance-test-password";

  await page.goto("/register");
  await page.getByLabel("Display name").fill("Acceptance User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  const registrationResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/auth/register"),
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const response = await registrationResponse;
  expect(response.status(), await response.text()).toBe(201);
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Welcome, Acceptance User" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "New project" }).click();
  const projectDialog = page.getByRole("dialog");
  await projectDialog.getByLabel("Project name").fill("Acceptance Project");
  await projectDialog
    .getByLabel("Description")
    .fill("Isolated browser acceptance workflow");
  const projectResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/projects") &&
      response.request().method() === "POST",
  );
  await projectDialog.getByRole("button", { name: "Create project" }).click();
  const createdProject = await projectResponse;
  expect(createdProject.status(), await createdProject.text()).toBe(201);
  const project = (await createdProject.json()) as { id: string };
  await page.goto(`/projects/${project.id}`);
  await expect(
    page.getByRole("heading", { name: "Acceptance Project" }),
  ).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept("Acceptance conversation"));
  await page.getByRole("button", { name: "Create conversation" }).click();
  await expect(
    page.getByRole("heading", { name: "Acceptance conversation" }),
  ).toBeVisible();
  await expect(
    page.getByText("No request has been submitted in this conversation.", {
      exact: true,
    }),
  ).toBeVisible();

  await page
    .getByRole("textbox", { name: "Request" })
    .fill("Create a clear, concise plan for launching a community workshop.");
  await page.getByRole("button", { name: "Save request" }).click();
  await expect(
    page.getByText("Create a clear, concise plan", { exact: false }),
  ).toBeVisible();

  const workflow = page.getByRole("navigation", { name: "Prompt workflow" });
  await workflow.getByRole("button", { name: /Analysis/ }).click();
  await page.getByRole("button", { name: "Analyze request" }).click();
  await expect(page.getByText("Information gaps")).toBeVisible();

  await workflow.getByRole("button", { name: /Clarify/ }).click();
  const skipQuestion = page.getByRole("button", {
    name: "Skip question",
    exact: true,
  });
  const noQuestions = page.getByText("No questions remaining.", {
    exact: true,
  });
  for (let count = 0; count < 20; count += 1) {
    if (await noQuestions.isVisible().catch(() => false)) break;
    await expect(skipQuestion).toBeVisible();
    const currentQuestion = await page
      .locator(".question-card h3")
      .textContent();
    const skipped = page.waitForResponse(
      (response) =>
        response.url().includes("/skip") &&
        response.request().method() === "POST",
    );
    await skipQuestion.click();
    await skipped;
    await expect
      .poll(async () => {
        if (await noQuestions.isVisible().catch(() => false)) return true;
        return (
          (await page.locator(".question-card h3").textContent()) !==
          currentQuestion
        );
      })
      .toBe(true);
  }
  await expect(noQuestions).toBeVisible();

  await workflow.getByRole("button", { name: /Context/ }).click();
  await page.getByRole("button", { name: "Assemble context" }).click();
  await expect(page.getByText("of 8,000 characters used")).toBeVisible();

  await workflow.getByRole("button", { name: /Generated prompt/ }).click();
  await page.getByRole("button", { name: "Generate prompt" }).click();
  await expect(page.getByText("PromptPilot prompt · v1")).toBeVisible();

  await workflow.getByRole("button", { name: /Execution/ }).click();
  const runButtons = page.getByRole("button", { name: "Run", exact: true });
  await expect(runButtons).toHaveCount(2);
  await runButtons.nth(0).click();
  await expect(page.getByText(/Local deterministic response/)).toBeVisible();
  await expect(runButtons).toHaveCount(2);
  await runButtons.nth(1).click();
  await expect(page.getByText("PromptPilot response")).toBeVisible();

  await workflow.getByRole("button", { name: /Evaluation/ }).click();
  const compare = page.getByRole("button", {
    name: "Compare saved responses",
  });
  await expect(compare).toBeEnabled();
  await compare.click();
  await expect(page.locator(".evaluation")).toBeVisible();

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Acceptance conversation" }),
  ).toBeVisible();
  await expect(
    page.getByText("Create a clear, concise plan", { exact: false }),
  ).toBeVisible();

  const restoredWorkflow = page.getByRole("navigation", {
    name: "Prompt workflow",
  });
  await restoredWorkflow.getByRole("button", { name: /Analysis/ }).click();
  await expect(page.getByText("Information gaps")).toBeVisible();
  await restoredWorkflow.getByRole("button", { name: /Clarify/ }).click();
  await expect(page.getByText("No questions remaining.")).toBeVisible();
  await restoredWorkflow
    .getByRole("button", { name: /Generated prompt/ })
    .click();
  await expect(page.getByText("PromptPilot prompt · v1")).toBeVisible();
  await restoredWorkflow.getByRole("button", { name: /Execution/ }).click();
  await expect(page.getByText(/Local deterministic response/)).toHaveCount(2);
  await expect(page.getByText("PromptPilot response")).toBeVisible();
  await restoredWorkflow.getByRole("button", { name: /Evaluation/ }).click();
  await expect(page.locator(".evaluation")).toBeVisible();

  for (const stageIndex of [0, 1, 2, 5, 6, 7]) {
    await expect(
      restoredWorkflow.getByRole("button").nth(stageIndex).locator("span"),
    ).toHaveText("✓");
  }

  const fakeProviderResponse = await page.request.get(
    "http://127.0.0.1:8132/health",
  );
  const fakeProviderHealth = await fakeProviderResponse.json();
  expect(fakeProviderHealth).toMatchObject({ status: "ok" });
  expect(fakeProviderHealth.request_count).toBeGreaterThan(0);
});
