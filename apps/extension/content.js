(function startPromptPilot() {
  "use strict";

  const SELECTORS = {
    "chatgpt.com": [
      "#prompt-textarea",
      '[contenteditable="true"][data-lexical-editor="true"]',
    ],
    "claude.ai": [
      'div.ProseMirror[contenteditable="true"]',
      'fieldset div[contenteditable="true"]',
    ],
    "gemini.google.com": [
      'rich-textarea [contenteditable="true"]',
      '.ql-editor[contenteditable="true"]',
    ],
  };

  let composer = null;
  let originalPrompt = "";
  let latestResult = null;
  let busy = false;

  const host = document.createElement("div");
  host.id = "promptpilot-extension-root";
  const shadow = host.attachShadow({ mode: "open" });
  document.documentElement.append(host);

  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; }
      .pp-launcher { position: fixed; right: 20px; bottom: 88px; z-index: 2147483646; display: none; align-items: center; gap: 9px; border: 1px solid rgba(255,255,255,.16); border-radius: 999px; padding: 8px 12px 8px 9px; color: #f7f7f8; background: #171719; box-shadow: 0 8px 28px rgba(0,0,0,.3); font: 600 13px/1.2 Inter, ui-sans-serif, system-ui, sans-serif; cursor: pointer; }
      .pp-launcher:hover { background: #242428; transform: translateY(-1px); }
      .pp-launcher:disabled { cursor: wait; opacity: .75; transform: none; }
      .pp-logo { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: linear-gradient(135deg,#7c3aed,#2563eb); font-weight: 800; }
      .pp-score { min-width: 34px; padding: 4px 7px; border-radius: 999px; color: #d1fae5; background: rgba(16,185,129,.18); text-align: center; font-size: 11px; }
      .pp-backdrop { position: fixed; inset: 0; z-index: 2147483647; display: none; align-items: center; justify-content: center; padding: 20px; background: rgba(0,0,0,.55); backdrop-filter: blur(5px); font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #f4f4f5; }
      .pp-backdrop.open { display: flex; }
      .pp-card { width: min(620px,100%); max-height: min(760px,90vh); overflow: auto; border: 1px solid #34343a; border-radius: 20px; background: #18181b; box-shadow: 0 24px 90px rgba(0,0,0,.5); }
      .pp-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 22px 14px; border-bottom: 1px solid #2b2b30; }
      .pp-title { margin: 0; font-size: 18px; font-weight: 700; }
      .pp-close { border: 0; color: #a1a1aa; background: transparent; cursor: pointer; font-size: 24px; line-height: 1; }
      .pp-body { padding: 20px 22px 22px; }
      .pp-meter { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; padding: 12px; border-radius: 12px; background: #222226; }
      .pp-ring { display: grid; place-items: center; width: 52px; height: 52px; flex: 0 0 auto; border-radius: 50%; background: conic-gradient(#8b5cf6 var(--score),#34343a 0); }
      .pp-ring::after { content: attr(data-score); display: grid; place-items: center; width: 40px; height: 40px; border-radius: 50%; background: #222226; font-size: 12px; font-weight: 800; }
      .pp-muted { color: #a1a1aa; font-size: 13px; line-height: 1.5; }
      .pp-summary { margin: 0; color: #e4e4e7; font-size: 14px; line-height: 1.55; }
      .pp-question { margin-top: 16px; }
      .pp-question label { display: block; margin-bottom: 7px; font-size: 13px; font-weight: 650; }
      .pp-question textarea, .pp-result { width: 100%; border: 1px solid #3f3f46; border-radius: 12px; color: #f4f4f5; background: #242429; font: 14px/1.5 Inter, ui-sans-serif, system-ui, sans-serif; }
      .pp-question textarea { min-height: 74px; padding: 11px 12px; resize: vertical; outline: none; }
      .pp-question textarea:focus { border-color: #8b5cf6; box-shadow: 0 0 0 3px rgba(139,92,246,.16); }
      .pp-result { min-height: 190px; margin-top: 14px; padding: 14px; resize: vertical; }
      .pp-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 9px; margin-top: 18px; }
      .pp-button { border: 1px solid #3f3f46; border-radius: 10px; padding: 9px 14px; color: #f4f4f5; background: #28282d; font: 650 13px/1.2 Inter, ui-sans-serif, system-ui, sans-serif; cursor: pointer; }
      .pp-button.primary { border-color: #7c3aed; background: #7c3aed; }
      .pp-button:hover { filter: brightness(1.12); }
      .pp-button:disabled { cursor: wait; opacity: .6; }
      .pp-error { padding: 11px 12px; border: 1px solid rgba(248,113,113,.35); border-radius: 10px; color: #fecaca; background: rgba(127,29,29,.25); font-size: 13px; line-height: 1.45; }
      .pp-spinner { width: 28px; height: 28px; margin: 30px auto 14px; border: 3px solid #3f3f46; border-top-color: #8b5cf6; border-radius: 50%; animation: pp-spin .8s linear infinite; }
      @keyframes pp-spin { to { transform: rotate(360deg); } }
      @media (max-width: 560px) { .pp-launcher { right: 10px; bottom: 76px; } .pp-card { border-radius: 16px; } }
    </style>
    <button class="pp-launcher" type="button" aria-label="Improve prompt with PromptPilot">
      <span class="pp-logo">P</span><span>Improve</span><span class="pp-score">0</span>
    </button>
    <div class="pp-backdrop" role="dialog" aria-modal="true" aria-label="PromptPilot">
      <section class="pp-card">
        <header class="pp-header"><h2 class="pp-title">Improve with PromptPilot</h2><button class="pp-close" aria-label="Close">×</button></header>
        <div class="pp-body"></div>
      </section>
    </div>`;

  const launcher = shadow.querySelector(".pp-launcher");
  const scoreElement = shadow.querySelector(".pp-score");
  const backdrop = shadow.querySelector(".pp-backdrop");
  const body = shadow.querySelector(".pp-body");

  function findComposer() {
    const selectors = SELECTORS[location.hostname] || [];
    return selectors
      .map((selector) => document.querySelector(selector))
      .find(Boolean);
  }

  function readComposer(element) {
    if (!element) return "";
    if (
      element instanceof HTMLTextAreaElement ||
      element instanceof HTMLInputElement
    ) {
      return element.value;
    }
    return element.innerText || element.textContent || "";
  }

  function writeComposer(element, value) {
    element.focus();
    if (
      element instanceof HTMLTextAreaElement ||
      element instanceof HTMLInputElement
    ) {
      const prototype =
        element instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, "value").set.call(
        element,
        value,
      );
    } else {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(element);
      selection.removeAllRanges();
      selection.addRange(range);
      if (!document.execCommand("insertText", false, value)) {
        element.textContent = value;
      }
      selection.removeAllRanges();
    }
    element.dispatchEvent(
      new InputEvent("input", {
        bubbles: true,
        inputType: "insertText",
        data: value,
      }),
    );
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function sync() {
    const nextComposer = findComposer();
    if (nextComposer !== composer) composer = nextComposer;
    launcher.style.display = composer ? "flex" : "none";
    if (!composer) return;
    const quality = globalThis.PromptPilotQuality.assess(
      readComposer(composer),
    );
    scoreElement.textContent = String(quality.score);
    scoreElement.title = `${quality.score}/100 · ${quality.label}`;
  }

  function openModal(content) {
    body.innerHTML = content;
    backdrop.classList.add("open");
  }

  function closeModal() {
    backdrop.classList.remove("open");
  }

  function qualityMarkup(quality) {
    return `<div class="pp-meter"><div class="pp-ring" style="--score:${quality.score}%" data-score="${quality.score}"></div><div><strong>${quality.label}</strong><div class="pp-muted">Prompt quality · ${quality.score}/100</div></div></div>`;
  }

  function showError(message) {
    openModal(
      `<div class="pp-error">${escapeHtml(message)}</div><div class="pp-actions"><button class="pp-button" data-action="close">Close</button></div>`,
    );
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function request(message) {
    const response = await chrome.runtime.sendMessage(message);
    if (!response?.ok)
      throw new Error(
        response?.error || "PromptPilot could not complete the request.",
      );
    return response.result;
  }

  function showQuestions(result, quality, answers = [], error = "") {
    latestResult = result;
    const fields = result.questions
      .map(
        (question, index) =>
          `<div class="pp-question"><label for="pp-q-${index}">${escapeHtml(question.question)}</label><textarea id="pp-q-${index}" data-index="${index}" placeholder="${escapeHtml(question.placeholder)}">${escapeHtml(answers[index]?.answer || "")}</textarea></div>`,
      )
      .join("");
    openModal(
      `${qualityMarkup(quality)}<p class="pp-summary">${escapeHtml(result.summary)}</p><p class="pp-muted">Reply to each question below, then send your answers to PromptPilot.</p>${error ? `<div class="pp-error" role="alert">${escapeHtml(error)} Your replies are preserved below. Please retry.</div>` : ""}${fields}<div class="pp-actions"><button class="pp-button" data-action="skip">Skip questions</button><button class="pp-button primary" data-action="continue">Send answers & improve</button></div>`,
    );
  }

  function showResult(result) {
    latestResult = result;
    const quality = globalThis.PromptPilotQuality.assess(result.improvedPrompt);
    const items = result.improvements.length
      ? `<div class="pp-muted">Improved: ${result.improvements.map(escapeHtml).join(" · ")}</div>`
      : "";
    openModal(
      `${qualityMarkup(quality)}<p class="pp-summary">${escapeHtml(result.summary)}</p>${items}<textarea class="pp-result" aria-label="Improved prompt">${escapeHtml(result.improvedPrompt)}</textarea><div class="pp-actions"><button class="pp-button" data-action="copy">Copy</button><button class="pp-button primary" data-action="replace">Replace prompt</button></div>`,
    );
  }

  async function analyze() {
    if (busy) return;
    composer = findComposer();
    originalPrompt = readComposer(composer).trim();
    if (!originalPrompt) {
      showError("Write a prompt in this page first, then click Improve.");
      return;
    }
    const quality = globalThis.PromptPilotQuality.assess(originalPrompt);
    busy = true;
    launcher.disabled = true;
    openModal(
      `${qualityMarkup(quality)}<div class="pp-spinner"></div><p class="pp-muted" style="text-align:center">Reviewing your prompt…</p>`,
    );
    try {
      const result = await request({
        type: "ANALYZE_PROMPT",
        prompt: originalPrompt,
        quality,
      });
      if (result.questions.length) showQuestions(result, quality);
      else if (result.improvedPrompt) showResult(result);
      else
        throw new Error(
          "The model did not return an improved prompt. Please try again.",
        );
    } catch (error) {
      showError(error.message);
    } finally {
      busy = false;
      launcher.disabled = false;
    }
  }

  async function finishImprovement(skipAnswers) {
    if (busy) return;
    const questionResult = latestResult;
    const savedReplies = questionResult.questions.map((question, index) => ({
      question: question.question,
      answer: body.querySelector(`[data-index="${index}"]`)?.value.trim() || "",
    }));
    const answers = skipAnswers
      ? savedReplies.map((reply) => ({ ...reply, answer: "" }))
      : savedReplies;
    busy = true;
    launcher.disabled = true;
    openModal(
      '<div class="pp-spinner"></div><p class="pp-muted" style="text-align:center">Building the improved prompt…</p>',
    );
    try {
      const result = await request({
        type: "IMPROVE_PROMPT",
        prompt: originalPrompt,
        answers,
      });
      if (!result.improvedPrompt)
        throw new Error("The model did not return an improved prompt.");
      showResult(result);
    } catch (error) {
      showQuestions(
        questionResult,
        globalThis.PromptPilotQuality.assess(originalPrompt),
        savedReplies,
        error.message,
      );
    } finally {
      busy = false;
      launcher.disabled = false;
    }
  }

  launcher.addEventListener("click", analyze);
  shadow.querySelector(".pp-close").addEventListener("click", closeModal);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  body.addEventListener("click", async (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "close") closeModal();
    if (action === "continue") await finishImprovement(false);
    if (action === "skip") await finishImprovement(true);
    if (action === "copy") {
      const value =
        body.querySelector(".pp-result")?.value || latestResult.improvedPrompt;
      await navigator.clipboard.writeText(value);
      event.target.textContent = "Copied";
    }
    if (action === "replace") {
      const target = findComposer() || composer;
      if (!target)
        return showError(
          "Prompt box not found. Reload the AI page and try again.",
        );
      const value =
        body.querySelector(".pp-result")?.value || latestResult.improvedPrompt;
      writeComposer(target, value);
      closeModal();
      sync();
    }
  });

  document.addEventListener("input", sync, true);
  new MutationObserver(sync).observe(document.body, {
    childList: true,
    subtree: true,
  });
  window.setInterval(sync, 1500);
  sync();
})();
