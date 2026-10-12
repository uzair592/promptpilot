import { expect, test } from "@playwright/test";

test("saves replies, restores pending questions, and retries generation with the same answers", async ({
  page,
}) => {
  const errorNotice = page.locator(".chat-error[role='alert']");
  const email = `reply-recovery-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Reply Recovery");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("reply-recovery-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  await page
    .getByRole("textbox", { name: "Prompt to improve" })
    .fill("Write a launch plan.");
  await page.getByRole("button", { name: "Improve prompt" }).click();
  const answerBox = page.getByRole("textbox", { name: "Clarification answer" });
  await expect(answerBox).toBeEnabled();
  const conversations = (
    await (
      await page.request.get(
        `/api/v1/projects/${page.url().split("/").pop()}/conversations`,
      )
    ).json()
  ).items;
  const root = `/api/v1/conversations/${conversations[0].id}`;
  const pending = (
    await (await page.request.get(`${root}/questions/next`)).json()
  ).next_question;
  await page.reload();
  await expect(answerBox).toBeEnabled();
  const restored = (
    await (await page.request.get(`${root}/questions/next`)).json()
  ).next_question;
  expect(restored.id).toBe(pending.id);

  await page.getByRole("button", { name: "Reply", exact: true }).click();
  await expect(answerBox).toBeFocused();
  await expect(page.locator(".reply-target")).toContainText(pending.text);
  await answerBox.fill("Three bullet points");
  let loseFirstAcknowledgement = true;
  await page.route("**/questions/*/answers", async (route) => {
    if (loseFirstAcknowledgement) {
      loseFirstAcknowledgement = false;
      const saved = await route.fetch();
      expect(saved.status()).toBe(201);
      await route.abort("failed");
    } else {
      await route.continue();
    }
  });
  await page.getByRole("button", { name: "Send answer" }).click();
  await expect(errorNotice).toContainText("Your reply was not confirmed");
  await expect(answerBox).toHaveValue("Three bullet points");
  await page.getByRole("button", { name: "Send answer" }).click();
  await expect(page.locator(".clarification-answer p")).toHaveText([
    "Three bullet points",
  ]);
  await expect(answerBox).toHaveValue("");
  await expect(page.locator(".reply-target")).not.toContainText(pending.text);

  let failGeneration = true;
  await page.route("**/prompts/generate", async (route) => {
    if (failGeneration) {
      failGeneration = false;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { message: "Simulated model timeout" } }),
      });
    } else await route.continue();
  });
  await expect(answerBox).toBeEnabled();
  await answerBox.fill("Keep it informal and short");
  await page.getByRole("button", { name: "Send answer" }).click();
  await expect(errorNotice).toContainText("Your prompt and replies are saved");
  await expect(errorNotice).toContainText("Simulated model timeout");
  await expect(
    page.getByRole("button", { name: "Retry generation" }),
  ).toBeEnabled();
  await expect(page.locator(".clarification-answer p")).toHaveText([
    "Three bullet points",
    "Keep it informal and short",
  ]);
  await page.reload();
  await expect(page.locator(".clarification-answer p")).toHaveText([
    "Three bullet points",
    "Keep it informal and short",
  ]);
  await page.getByRole("button", { name: "Generate improved prompt" }).click();
  await expect(
    page.getByRole("heading", { name: "Your prompt is ready" }),
  ).toBeVisible();
  await expect(page.locator(".optimized-prompt")).toContainText(
    "Three bullet points",
  );
  await expect(page.locator(".optimized-prompt")).toContainText(
    "Keep it informal and short",
  );
  const health = await (
    await page.request.get("http://127.0.0.1:8132/health")
  ).json();
  const input = health.generation_inputs.find(
    (item: { original_prompt: string }) =>
      item.original_prompt === "Write a launch plan.",
  );
  expect(
    input.relevant_answers.map((item: { content: string }) => item.content),
  ).toEqual(
    expect.arrayContaining([
      "Three bullet points",
      "Keep it informal and short",
    ]),
  );
  expect(
    input.relevant_answers.every((item: { question: string }) =>
      Boolean(item.question),
    ),
  ).toBe(true);
  expect(
    (await (await page.request.get(`${root}/questions/next`)).json())
      .answered_questions,
  ).toHaveLength(2);
});
