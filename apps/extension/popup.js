"use strict";

const DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731:free";
const form = document.querySelector("#settings-form");
const keyInput = document.querySelector("#api-key");
const status = document.querySelector("#status");

async function loadSettings() {
  const settings = await chrome.storage.local.get([
    "openRouterApiKey",
    "model",
  ]);
  keyInput.value = settings.openRouterApiKey || "";
  document.querySelector("#model-name").textContent =
    settings.model || DEFAULT_MODEL;
  status.textContent = settings.openRouterApiKey
    ? "API key is configured."
    : "Add your API key to begin.";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const openRouterApiKey = keyInput.value.trim();
  if (!openRouterApiKey) {
    status.textContent = "Enter an OpenRouter API key.";
    return;
  }
  await chrome.storage.local.set({ openRouterApiKey, model: DEFAULT_MODEL });
  status.textContent = "Saved. PromptPilot is ready.";
});

document.querySelector("#forget-key").addEventListener("click", async () => {
  await chrome.storage.local.remove(["openRouterApiKey", "model"]);
  keyInput.value = "";
  status.textContent = "API key removed.";
});

document.querySelector("#toggle-key").addEventListener("click", (event) => {
  const showing = keyInput.type === "text";
  keyInput.type = showing ? "password" : "text";
  event.currentTarget.textContent = showing ? "Show" : "Hide";
});

loadSettings();
