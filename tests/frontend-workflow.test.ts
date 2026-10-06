import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  ModelRun,
  answerQuestion,
  assembleContext,
  compareEvaluations,
  friendlyError,
  generatePrompt,
  getDocuments,
  getGeneratedPrompts,
  getLatestAnalysis,
  getMemory,
  getNextQuestion,
  getRuns,
  isModelRunSuccessful,
  selectComparisonPair,
  skipQuestion,
} from "../apps/frontend/lib/conversations.js";

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

const modelRun = (
  id: string,
  execution_strategy: ModelRun["execution_strategy"],
  overrides: Partial<ModelRun> = {},
): ModelRun => ({
  id,
  prompt_version_id:
    execution_strategy === "promptpilot" ? "prompt-version-1" : null,
  source_message_id: "message-1",
  execution_strategy,
  optimized_prompt: "Create a plan",
  response_text: `${execution_strategy} response`,
  provider: "openai",
  model: "gpt-4",
  status: "succeeded",
  finish_reason: "stop",
  latency_ms: 100,
  error_message: null,
  created_at: "2026-10-06T00:00:00Z",
  ...overrides,
});

const runtimeStatusRun = (run: ModelRun, status: string): ModelRun =>
  ({ ...run, status }) as ModelRun;

describe("persistent frontend workflow contracts", () => {
  it("uses succeeded as the shared ModelRun success interpretation", () => {
    expect(isModelRunSuccessful({ status: "succeeded" })).toBe(true);
    expect(isModelRunSuccessful({ status: "failed" })).toBe(false);
  });

  it("restores analysis and clarification progress", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        response({ id: "analysis-1", gaps: [{ id: "gap-1" }] }),
      )
      .mockResolvedValueOnce(
        response({
          id: "session-1",
          status: "active",
          next_question: { id: "q-1" },
        }),
      )
      .mockResolvedValueOnce(
        response(
          { id: "session-1", status: "active", next_question: { id: "q-2" } },
          201,
        ),
      )
      .mockResolvedValueOnce(
        response({ id: "session-1", status: "completed", next_question: null }),
      );

    await expect(
      getLatestAnalysis("conversation-1", "message-1"),
    ).resolves.toMatchObject({ id: "analysis-1" });
    await expect(getNextQuestion("conversation-1")).resolves.toMatchObject({
      status: "active",
    });
    await expect(
      answerQuestion("conversation-1", "q-1", "For finance leaders"),
    ).resolves.toMatchObject({ next_question: { id: "q-2" } });
    await expect(skipQuestion("conversation-1", "q-2")).resolves.toMatchObject({
      status: "completed",
      next_question: null,
    });
    expect(fetchMock.mock.calls[2][1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ content: "For finance leaders" }),
      }),
    );
    fetchMock.mockRestore();
  });

  it("loads project evidence and assembles empty context", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response([{ id: "memory-1", source: "user" }]))
      .mockResolvedValueOnce(
        response([
          { id: "document-1", status: "failed", error_message: "Unsupported" },
        ]),
      )
      .mockResolvedValueOnce(
        response({
          task: "Plan",
          project_memory: [],
          user_answers: [],
          requirements: [],
          constraints: [],
          document_context: [],
          sources: [],
          omitted_items: [],
          used_budget: 0,
          budget: 8000,
        }),
      );
    await expect(getMemory("project-1")).resolves.toHaveLength(1);
    await expect(getDocuments("project-1")).resolves.toMatchObject([
      { status: "failed" },
    ]);
    await expect(
      assembleContext("project-1", {
        task: "Plan",
        conversation_id: "conversation-1",
        message_id: "message-1",
      }),
    ).resolves.toMatchObject({ document_context: [], used_budget: 0 });
    expect(fetchMock.mock.calls[2][1]).toEqual(
      expect.objectContaining({ method: "POST" }),
    );
    fetchMock.mockRestore();
  });

  it("restores and generates versioned prompts linked to the source message", async () => {
    const saved = {
      version_id: "version-1",
      version_number: 1,
      source_message_id: "message-1",
      original_prompt: "Plan",
      optimized_prompt: "Create a plan",
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response([saved]))
      .mockResolvedValueOnce(
        response({ ...saved, version_id: "version-2", version_number: 2 }),
      );
    await expect(getGeneratedPrompts("conversation-1")).resolves.toMatchObject([
      saved,
    ]);
    await expect(
      generatePrompt("conversation-1", "message-1", "detailed"),
    ).resolves.toMatchObject({
      version_number: 2,
      source_message_id: "message-1",
    });
    expect(fetchMock.mock.calls[1][1]?.body).toBe(
      JSON.stringify({ message_id: "message-1", mode: "detailed" }),
    );
    fetchMock.mockRestore();
  });

  it("reports provider unavailability without inventing results", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        response({ detail: "Target provider is not configured" }, 503),
      )
      .mockResolvedValueOnce(
        response([
          {
            id: "failed-run",
            execution_strategy: "promptpilot",
            status: "failed",
            response_text: null,
            error_message: "Provider unavailable",
          },
        ]),
      );
    await expect(
      generatePrompt("conversation-1", "message-1", "structured"),
    ).rejects.toEqual(expect.objectContaining({ status: 503 }));
    expect(
      friendlyError(
        new ApiError("Target provider is not configured", 503),
        "fallback",
      ),
    ).toBe("Target provider is not configured");
    const failedRuns = await getRuns("conversation-1");
    expect(failedRuns[0]).toMatchObject({
      status: "failed",
      response_text: null,
    });
    fetchMock.mockRestore();
  });

  it("selects succeeded baseline and PromptPilot runs with matching request, provider, and model", () => {
    const baseline = modelRun("baseline-1", "baseline");
    const promptpilot = modelRun("promptpilot-1", "promptpilot");
    const result = selectComparisonPair(
      [baseline, promptpilot],
      "message-1",
      "prompt-version-1",
    );

    expect(result.eligible).toBe(true);
    if (result.eligible) {
      expect(result.pair).toEqual({ baseline, promptpilot });
    }
  });

  it("rejects runs from different source messages", () => {
    const result = selectComparisonPair(
      [
        modelRun("baseline-1", "baseline"),
        modelRun("promptpilot-1", "promptpilot", {
          source_message_id: "message-2",
        }),
      ],
      "message-1",
      "prompt-version-1",
    );

    expect(result).toMatchObject({
      eligible: false,
      reason: "No compatible response pair is available.",
      pair: null,
    });
  });

  it("rejects runs from different providers", () => {
    const result = selectComparisonPair(
      [
        modelRun("baseline-1", "baseline"),
        modelRun("promptpilot-1", "promptpilot", { provider: "anthropic" }),
      ],
      "message-1",
      "prompt-version-1",
    );

    expect(result).toMatchObject({
      eligible: false,
      reason: "The saved responses use different providers or models.",
      pair: null,
    });
  });

  it("rejects runs from different models", () => {
    const result = selectComparisonPair(
      [
        modelRun("baseline-1", "baseline"),
        modelRun("promptpilot-1", "promptpilot", { model: "gpt-4.1" }),
      ],
      "message-1",
      "prompt-version-1",
    );

    expect(result).toMatchObject({
      eligible: false,
      reason: "The saved responses use different providers or models.",
      pair: null,
    });
  });

  it("requires a successful baseline response", () => {
    const result = selectComparisonPair(
      [
        modelRun("baseline-1", "baseline", {
          status: "failed",
          response_text: null,
        }),
        modelRun("promptpilot-1", "promptpilot"),
      ],
      "message-1",
      "prompt-version-1",
    );

    expect(result).toMatchObject({
      eligible: false,
      reason: "A successful baseline response is required.",
      pair: null,
    });
  });

  it("requires a successful PromptPilot response", () => {
    const result = selectComparisonPair(
      [
        modelRun("baseline-1", "baseline"),
        modelRun("promptpilot-1", "promptpilot", {
          status: "failed",
          response_text: null,
        }),
      ],
      "message-1",
      "prompt-version-1",
    );

    expect(result).toMatchObject({
      eligible: false,
      reason: "A successful PromptPilot response is required.",
      pair: null,
    });
  });

  it("rejects pending or unknown statuses received at runtime", () => {
    for (const status of ["pending", "unknown"]) {
      const result = selectComparisonPair(
        [
          runtimeStatusRun(modelRun("baseline-1", "baseline"), status),
          modelRun("promptpilot-1", "promptpilot"),
        ],
        "message-1",
        "prompt-version-1",
      );

      expect(result).toMatchObject({
        eligible: false,
        reason: "A successful baseline response is required.",
        pair: null,
      });
    }
  });

  it("selects a compatible historical pair instead of combining unrelated latest runs", () => {
    const latestBaseline = modelRun("baseline-latest", "baseline", {
      provider: "openai",
      model: "gpt-4.1",
    });
    const olderCompatibleBaseline = modelRun(
      "baseline-compatible",
      "baseline",
      { provider: "anthropic", model: "claude-3" },
    );
    const latestPromptpilot = modelRun("promptpilot-latest", "promptpilot", {
      provider: "anthropic",
      model: "claude-3",
    });
    const olderCompatiblePromptpilot = modelRun(
      "promptpilot-compatible",
      "promptpilot",
      { provider: "openai", model: "gpt-4.1" },
    );
    const result = selectComparisonPair(
      [
        latestBaseline,
        olderCompatibleBaseline,
        latestPromptpilot,
        olderCompatiblePromptpilot,
      ],
      "message-1",
      "prompt-version-1",
    );

    expect(result.eligible).toBe(true);
    if (result.eligible) {
      expect(result.pair).toEqual({
        baseline: latestBaseline,
        promptpilot: olderCompatiblePromptpilot,
      });
    }
  });

  it("uses the selected pair's exact run IDs in the comparison request", async () => {
    const baseline = modelRun("baseline-selected", "baseline");
    const promptpilot = modelRun("promptpilot-selected", "promptpilot");
    const selection = selectComparisonPair(
      [baseline, promptpilot],
      "message-1",
      "prompt-version-1",
    );
    expect(selection.eligible).toBe(true);
    if (!selection.eligible) return;

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ id: "evaluation-1" }));
    await compareEvaluations("conversation-1", selection.pair);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      baseline_model_run_id: baseline.id,
      promptpilot_model_run_id: promptpilot.id,
      method: "heuristic",
    });
    fetchMock.mockRestore();
  });

  it("requires the active generated prompt for the PromptPilot side", () => {
    const result = selectComparisonPair(
      [
        modelRun("baseline-1", "baseline"),
        modelRun("promptpilot-old", "promptpilot", {
          prompt_version_id: "prompt-version-old",
        }),
      ],
      "message-1",
      "prompt-version-1",
    );

    expect(result).toMatchObject({
      eligible: false,
      reason: "No compatible response pair is available.",
      pair: null,
    });
  });

  it("question-session status completed remains unchanged as a separate contract", () => {
    const questionSession = {
      id: "session-1",
      status: "completed",
      stop_reason: "no_unresolved_gaps",
      next_question: null,
    };
    expect(questionSession.status).toBe("completed");
  });
});
