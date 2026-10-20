import { expect, test } from "@playwright/test";

test("connects a key, uses adaptive questions, assigns different models and saves before running", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Connected team reviewer");
  await page
    .getByLabel("Email")
    .fill(`connected-team-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("connected-workflow-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  const projectId = page.url().split("/").pop()!;
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".chat-connect-banner")).toBeVisible();
  const composer = await page.locator(".bottom-composer").boundingBox();
  expect(composer).not.toBeNull();
  expect(composer!.y + composer!.height).toBeLessThanOrEqual(845);
  await page.screenshot({
    path: "test-results/screenshots/chat-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "Open models and API keys" }).click();
  const dialog = page.getByRole("dialog", { name: "Models & API keys" });
  await dialog.getByLabel("Provider", { exact: true }).selectOption("gemini");
  await dialog
    .getByLabel("API key", { exact: true })
    .fill("synthetic-rejected-key");
  await dialog.getByRole("button", { name: "Load available models" }).click();
  await expect(dialog.getByRole("alert")).toContainText("API key was rejected");
  await dialog
    .getByLabel("API key", { exact: true })
    .fill("synthetic-accepted-key");
  await dialog.getByRole("button", { name: "Load available models" }).click();
  await dialog
    .getByLabel("Default model", { exact: true })
    .selectOption("acceptance-text");
  await dialog
    .getByLabel("Connection name", { exact: false })
    .fill("My Gemini team");
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/provider-connections") &&
      response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "Save and connect" }).click();
  const connection = await (await saved).json();
  expect(JSON.stringify(connection)).not.toContain("synthetic-accepted-key");
  await expect(dialog.locator(".connection-status")).toHaveText("Connected");
  await expect(dialog.getByLabel("API key", { exact: true })).toHaveValue("");
  await page.screenshot({
    path: "test-results/screenshots/connected-models.png",
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "Close Models & API keys" }).click();
  await expect(page.getByRole("combobox", { name: "Chat model" })).toHaveValue(
    connection.id,
  );
  await page
    .getByRole("textbox", { name: "Prompt to improve" })
    .fill("Build a restaurant POS");
  await page.getByRole("button", { name: "Improve prompt" }).click();
  await expect(page.locator(".question-message h3")).toHaveText(
    "Which receipt printer will your restaurant POS use?",
  );
  await page
    .getByRole("textbox", { name: "Clarification answer" })
    .fill("An 80mm USB thermal printer");
  await page.getByRole("button", { name: "Send answer" }).click();
  await expect(page.locator(".question-message h3")).toHaveText(
    "Should kitchen tickets appear on a display or print?",
  );
  await page
    .getByRole("textbox", { name: "Clarification answer" })
    .fill("A kitchen display with an audible alert");
  await page.getByRole("button", { name: "Send answer" }).click();
  await expect(
    page.getByRole("heading", { name: "Your prompt is ready" }),
  ).toBeVisible();
  await expect(page.locator(".optimized-prompt")).toContainText(
    "80mm USB thermal printer",
  );
  await expect(page.locator(".optimized-prompt")).toContainText(
    "kitchen display with an audible alert",
  );
  await expect(page.locator(".question-message")).toHaveCount(0);
  const quality = await page.locator(".large-quality strong").innerText();
  await expect(page.locator(".composer-quality")).toContainText(quality);
  const heading = await page.locator(".chat-heading > strong").boundingBox();
  const subtitle = await page.locator(".chat-heading > span").boundingBox();
  expect(subtitle!.y).toBeGreaterThanOrEqual(heading!.y + heading!.height - 1);
  await page.screenshot({
    path: "test-results/screenshots/adaptive-chat.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Plan and build this project" }).click();
  const create = page.getByRole("dialog", { name: "Create a workflow" });
  await expect(create.getByLabel("Planning model")).toHaveValue(connection.id);
  await create
    .getByRole("button", { name: "Create milestones and tasks" })
    .click();
  await expect(page.getByText("AI planned", { exact: true })).toBeVisible();
  await page
    .getByRole("navigation", { name: "AI team workspace" })
    .getByRole("button", { name: /Team models/ })
    .click();
  const rootAssignment = page.getByRole("article", {
    name: "Model assignment for Confirm product scope",
    exact: true,
  });
  await rootAssignment
    .getByLabel("Agent model", { exact: true })
    .selectOption("acceptance-review");
  await rootAssignment.getByRole("button", { name: "Save assignment" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Model assigned to Confirm product scope",
  );
  const frontend = page.getByRole("article", {
    name: "Model assignment for Build the frontend",
    exact: true,
  });
  await frontend
    .getByLabel("Agent model", { exact: true })
    .selectOption("acceptance-code");
  await frontend.getByRole("button", { name: "Save assignment" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Model assigned to Build the frontend",
  );
  await page.screenshot({
    path: "test-results/screenshots/team-models.png",
    fullPage: true,
  });
  const plans = (
    await (await page.request.get(`/api/v1/projects/${projectId}/plans`)).json()
  ).items;
  const tasks = plans[0].milestones.flatMap(
    (phase: {
      tasks: { id: string; title: string; assigned_model: string }[];
    }) => phase.tasks,
  );
  expect(
    tasks.find(
      (task: { title: string }) => task.title === "Confirm product scope",
    ).assigned_model,
  ).toBe("acceptance-review");
  expect(
    tasks.find((task: { title: string }) => task.title === "Build the frontend")
      .assigned_model,
  ).toBe("acceptance-code");
  await rootAssignment.getByRole("button", { name: "Task details" }).click();
  const inspector = page.getByLabel("Node inspector");
  await inspector
    .getByLabel("Model", { exact: true })
    .selectOption("acceptance-code");
  await inspector
    .getByRole("button", { name: "Save and run", exact: true })
    .click();
  await expect(
    inspector.getByRole("button", { name: "Approve output" }),
  ).toBeVisible();
  await expect(inspector.locator("pre").first()).toContainText(
    "acceptance-code",
  );
  await inspector.getByRole("button", { name: "Approve output" }).click();
  await expect(page.getByRole("status")).toContainText("Output approved");
  await inspector.getByRole("button", { name: /^Runs/ }).click();
  await expect(inspector.locator(".execution-history")).toContainText(
    "succeeded",
  );
  await page.screenshot({
    path: "test-results/screenshots/agent-run-history.png",
    fullPage: true,
  });
  const health = await (
    await page.request.get("http://127.0.0.1:8132/health")
  ).json();
  const analyzed = health.analysis_inputs.filter(
    (item: { original_prompt: string }) =>
      item.original_prompt === "Build a restaurant POS",
  );
  expect(analyzed.at(-1).clarification_answers).toHaveLength(2);
  expect(health.model_requests).toContainEqual({
    model: "acceptance-code",
    purpose: "completion",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Close node inspector" }).click();
  await page
    .getByRole("navigation", { name: "AI team workspace" })
    .getByRole("button", { name: /Models & API keys/ })
    .click();
  await expect(
    page
      .locator(".models-page")
      .getByRole("heading", { name: "Models & API keys" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/screenshots/models-mobile.png",
    fullPage: true,
  });
});
