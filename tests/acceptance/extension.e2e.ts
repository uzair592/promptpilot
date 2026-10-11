import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

test("improves and replaces a prompt inside a ChatGPT-style composer", async ({
  page,
}) => {
  await page.addInitScript(() => {
    let requestNumber = 0;
    Object.defineProperty(globalThis, "chrome", {
      value: {
        runtime: {
          sendMessage: async () => {
            requestNumber += 1;
            if (requestNumber === 1) {
              return {
                ok: true,
                result: {
                  summary: "The goal needs a little more context.",
                  questions: [
                    {
                      id: "q1",
                      question: "Who is the audience?",
                      placeholder: "For example, beginner developers",
                    },
                  ],
                  improvedPrompt: "",
                  improvements: [],
                },
              };
            }
            return {
              ok: true,
              result: {
                summary: "The prompt is now specific and audience-aware.",
                questions: [],
                improvedPrompt:
                  "Write a concise professional email explaining the project to beginner developers. Use simple English and three bullet points.",
                improvements: ["Added audience", "Added format"],
              },
            };
          },
        },
      },
    });
  });
  await page.route("https://chatgpt.com/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<!doctype html><html><body><div id="prompt-textarea" contenteditable="true"></div></body></html>',
    }),
  );
  await page.goto("https://chatgpt.com/");
  await page.addScriptTag({ path: resolve("apps/extension/quality.js") });
  await page.addScriptTag({ path: resolve("apps/extension/content.js") });

  const composer = page.locator("#prompt-textarea");
  await composer.fill("write an email");

  const extension = page.locator("#promptpilot-extension-root");
  const launcher = extension.locator(".pp-launcher");
  await expect(launcher).toBeVisible();
  await launcher.click();

  await expect(extension.getByText("Who is the audience?")).toBeVisible();
  await extension
    .locator("textarea[data-index='0']")
    .fill("Beginner developers");
  await extension
    .getByRole("button", { name: "Create improved prompt" })
    .click();

  await expect(extension.locator(".pp-result")).toContainText(
    "beginner developers",
  );
  await extension.getByRole("button", { name: "Replace prompt" }).click();
  await expect(composer).toContainText("beginner developers");
  await expect(composer).toContainText("three bullet points");
});
