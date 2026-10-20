import { expect, test } from "@playwright/test";

test("edits a persisted workflow, discovers provider options, and validates repository input", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Workflow reviewer");
  await page.getByLabel("Email").fill(`workflow-ui-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("visual-workflow-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  const promptBox = page.getByRole("textbox", { name: "Prompt to improve" });
  await promptBox.fill("hi");
  await expect(page.locator(".composer-quality")).toContainText("0/100");
  await expect(page.locator(".large-quality")).toContainText("0/100");
  await page.getByRole("button", { name: "Improve prompt" }).click();
  await expect(page.getByRole("status")).toContainText("no task to improve");
  await page
    .getByRole("link", { name: "AI delivery team", exact: false })
    .click();
  await page
    .getByRole("button", { name: "Create your first workflow" })
    .click();
  const create = page.getByRole("dialog", { name: "Create a workflow" });
  await create.getByLabel("Plan title").fill("Restaurant POS delivery");
  await create
    .getByLabel("Product idea")
    .fill(
      "Build a restaurant POS with inventory, kitchen tickets and thermal receipts.",
    );
  const savedPlan = page.waitForResponse(
    (response) =>
      response.url().endsWith("/plans") &&
      response.request().method() === "POST",
  );
  await create
    .getByRole("button", { name: "Create milestones and tasks" })
    .click();
  await expect(page.getByLabel("Workflow canvas")).toBeVisible();
  const plan = await (await savedPlan).json();
  const initialNodes = plan.milestones.reduce(
    (count: number, phase: { tasks: unknown[] }) => count + phase.tasks.length,
    0,
  );
  await expect(page.locator(".workflow-node")).toHaveCount(initialNodes);
  await page
    .getByRole("button", {
      name: "Configure Define product requirements",
      exact: true,
    })
    .click();
  const inspector = page.getByLabel("Node inspector");
  await inspector.getByLabel("Task name").fill("Confirm restaurant workflows");
  await inspector
    .getByRole("button", { name: "Save node", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Configure Confirm restaurant workflows",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close node inspector" }).click();
  const node = page.getByRole("button", {
    name: "Configure Confirm restaurant workflows",
    exact: true,
  });
  const before = await node.getAttribute("style");
  const box = await node.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + 30, box!.y + 30);
  await page.mouse.down();
  await page.mouse.move(box!.x + 65, box!.y + 65, { steps: 6 });
  await page.mouse.up();
  const after = await node.getAttribute("style");
  expect(after).not.toBe(before);
  await page.reload();
  await expect(node).toBeVisible();
  await expect(node).toHaveAttribute("style", after!);
  await page.getByRole("button", { name: "Add node", exact: false }).click();
  const add = page.getByRole("dialog", { name: "Add a workflow node" });
  await add.getByLabel("Task name").fill("Audit thermal receipt layout");
  await add
    .getByLabel("Instructions")
    .fill("Check 80mm receipt readability and PKR totals.");
  await add.getByLabel("Role").selectOption("tester");
  await add.getByRole("button", { name: "Add node", exact: true }).click();
  await expect(page.locator(".workflow-node")).toHaveCount(initialNodes + 1);
  await expect(inspector.getByLabel("Task name")).toHaveValue(
    "Audit thermal receipt layout",
  );
  await inspector
    .getByRole("checkbox", { name: "Confirm restaurant workflows" })
    .check();
  await inspector
    .getByRole("button", { name: "Save node", exact: true })
    .click();
  await expect(page.locator(".workflow-alert.success")).toContainText(
    "Node saved",
  );
  await page.screenshot({
    path: "test-results/screenshots/visual-workflow-inspector.png",
    fullPage: true,
  });
  page.once("dialog", (dialog) => dialog.accept());
  await inspector
    .getByRole("button", { name: "Remove node", exact: true })
    .click();
  await expect(page.locator(".workflow-node")).toHaveCount(initialNodes);
  await page.getByRole("button", { name: "Fit workflow" }).click();
  await page.screenshot({
    path: "test-results/screenshots/visual-workflow.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open workspace navigation" }).click();
  await expect(
    page.getByRole("button", { name: "New workflow", exact: false }),
  ).toBeVisible();
});

test("Model Vault includes Grok and custom APIs and the GitHub form accepts repository URLs", async ({
  page,
}) => {
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Provider reviewer");
  await page.getByLabel("Email").fill(`providers-ui-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("visual-provider-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  await page
    .getByRole("link", { name: "AI delivery team", exact: false })
    .click();
  await page
    .locator(".workflow-top-actions")
    .getByRole("button", { name: "Models & API keys", exact: true })
    .click();
  const vault = page.locator(".models-page");
  await vault.getByLabel("Provider", { exact: true }).selectOption("grok");
  await expect(vault.getByLabel("Default model")).toBeVisible();
  await vault.getByLabel("Provider", { exact: true }).selectOption("custom");
  await expect(vault.getByLabel("API base URL")).toBeVisible();
  await page.screenshot({
    path: "test-results/screenshots/model-vault.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Connect GitHub", exact: true })
    .click();
  const repo = page.getByRole("dialog", { name: "Connect GitHub repository" });
  await repo
    .getByLabel("GitHub repository URL or owner/repo")
    .fill("https://github.com/uzair592");
  await repo
    .getByLabel("GitHub fine-grained token")
    .fill("synthetic-not-live-token");
  await repo
    .getByRole("button", { name: "Connect repository", exact: true })
    .click();
  await expect(repo.getByRole("alert")).toContainText("profile");
  let destination;
  await page.route("**/api/v1/projects/*/repository", async (route) => {
    if (route.request().method() !== "PUT") {
      await route.continue();
      return;
    }
    destination = route.request().postDataJSON();
    await route.fulfill({
      json: {
        owner: "uzair592",
        repo: "promptpilot",
        default_branch: "main",
        url: "https://github.com/uzair592/promptpilot",
      },
    });
  });
  await repo
    .getByLabel("GitHub repository URL or owner/repo")
    .fill("https://github.com/uzair592/promptpilot");
  await repo
    .getByRole("button", { name: "Connect repository", exact: true })
    .click();
  await expect(repo).not.toBeVisible();
  expect(destination).toMatchObject({ owner: "uzair592", repo: "promptpilot" });
});
