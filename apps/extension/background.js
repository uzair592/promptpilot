"use strict";

importScripts("protocol.js");

const DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731:free";

async function callOpenRouter(messages) {
  const settings = await chrome.storage.local.get([
    "openRouterApiKey",
    "model",
  ]);
  const apiKey = String(settings.openRouterApiKey || "").trim();
  if (!apiKey) {
    throw new Error(
      "Open PromptPilot from the browser toolbar and save your OpenRouter API key first.",
    );
  }
  const response = await fetch(
    "https://openrouter.ai/api/v1/chat/completions",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/uzair592/promptpilot",
        "X-Title": "PromptPilot Extension",
      },
      body: JSON.stringify({
        model: settings.model || DEFAULT_MODEL,
        messages,
        temperature: 0.2,
        response_format: { type: "json_object" },
      }),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const reason =
      body?.error?.message || `OpenRouter request failed (${response.status}).`;
    throw new Error(reason);
  }
  const content = body?.choices?.[0]?.message?.content;
  if (!content) throw new Error("OpenRouter returned an empty response.");
  return globalThis.PromptPilotProtocol.parseResponse(content);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (
    message?.type !== "ANALYZE_PROMPT" &&
    message?.type !== "IMPROVE_PROMPT"
  ) {
    return false;
  }
  const prompt = String(message.prompt || "").trim();
  if (!prompt) {
    sendResponse({ ok: false, error: "Write a prompt before improving it." });
    return false;
  }
  const messages =
    message.type === "ANALYZE_PROMPT"
      ? globalThis.PromptPilotProtocol.analyzeMessages(prompt, message.quality)
      : globalThis.PromptPilotProtocol.improveMessages(
          prompt,
          message.answers || [],
        );
  callOpenRouter(messages)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
});
