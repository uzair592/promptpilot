# PromptPilot browser extension

The Manifest V3 extension improves a prompt directly inside ChatGPT, Claude, or Gemini. It shows a live local quality score, asks up to three useful clarification questions, and places the improved prompt back into the website's prompt box. It never submits the prompt automatically.

## Install locally in Chrome or Edge

1. Download or clone this repository.
2. Open `chrome://extensions` in Chrome or `edge://extensions` in Edge.
3. Turn on **Developer mode**.
4. Select **Load unpacked** and choose the `apps/extension` folder.
5. Pin PromptPilot, open its toolbar popup, paste your OpenRouter API key, and select **Save key**.
6. Open or reload ChatGPT, Claude, or Gemini. Write a prompt and select the floating **Improve** button.

No Render, Vercel, database, or local server is required for the extension. The extension automatically uses the configured free OpenRouter model. Free-model availability and limits are controlled by OpenRouter and can change.

## Privacy and release scope

The API key is stored in `chrome.storage.local` and used only by the extension's background service worker to call OpenRouter. It is not injected into supported websites. This is appropriate for a locally installed examiner/demo build. Before publishing to a browser store for untrusted public distribution, route model calls through an authenticated backend so end users do not need to supply a provider key.
