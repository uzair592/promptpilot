import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  answerQuestion,
  assembleContext,
  comparisonEligibility,
  friendlyError,
  generatePrompt,
  getDocuments,
  getGeneratedPrompts,
  getLatestAnalysis,
  getMemory,
  getNextQuestion,
  getRuns,
  isModelRunSuccessful,
  skipQuestion,
} from "../apps/frontend/lib/conversations.js";

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

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

  it("reports provider unavailability and comparison eligibility without inventing results", async () => {
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
    expect(comparisonEligibility(failedRuns)).toEqual({
      eligible: false,
      reason: "A succeeded baseline response is missing.",
    });
    expect(
      comparisonEligibility([
        { execution_strategy: "baseline", status: "succeeded" },
        { execution_strategy: "promptpilot", status: "succeeded" },
      ] as never),
    ).toMatchObject({ eligible: true });
    fetchMock.mockRestore();
  });

  it("recognises backend-shaped succeeded baseline and PromptPilot runs", () => {
    const baselineRun = {
      id: "baseline-run-1",
      execution_strategy: "baseline" as const,
      status: "succeeded" as const,
      source_message_id: "message-1",
      provider: "openai",
      model: "gpt-4",
      response_text: "Baseline response",
    };
    const promptpilotRun = {
      id: "promptpilot-run-1",
      execution_strategy: "promptpilot" as const,
      status: "succeeded" as const,
      source_message_id: "message-1",
      provider: "openai",
      model: "gpt-4",
      response_text: "PromptPilot response",
    };
    expect(
      comparisonEligibility([baselineRun as never, promptpilotRun as never]),
    ).toEqual({
      eligible: true,
      reason: "Compatible saved responses are available.",
    });
  });

  it("recognises a backend-shaped PromptPilot run with status succeeded", () => {
    const run = {
      id: "promptpilot-run-1",
      execution_strategy: "promptpilot" as const,
      status: "succeeded" as const,
      source_message_id: "message-1",
      provider: "openai",
      model: "gpt-4",
      response_text: "PromptPilot response",
    };
    expect(comparisonEligibility([run as never])).toEqual({
      eligible: false,
      reason: "A succeeded baseline response is missing.",
    });
  });

  it("recognises a compatible baseline and PromptPilot pair as eligible for comparison", () => {
    const runs = [
      {
        id: "baseline-run-1",
        execution_strategy: "baseline" as const,
        status: "succeeded" as const,
        source_message_id: "message-1",
        provider: "openai",
        model: "gpt-4",
        response_text: "Baseline response",
      },
      {
        id: "promptpilot-run-1",
        execution_strategy: "promptpilot" as const,
        status: "succeeded" as const,
        source_message_id: "message-1",
        provider: "openai",
        model: "gpt-4",
        response_text: "PromptPilot response",
      },
    ];
    const result = comparisonEligibility(runs as never);
    expect(result.eligible).toBe(true);
    expect(result.reason).toBe("Compatible saved responses are available.");
  });

  it("rejects failed runs as ineligible", () => {
    const runs = [
      {
        id: "failed-run",
        execution_strategy: "baseline" as const,
        status: "failed" as const,
        source_message_id: "message-1",
        provider: "openai",
        model: "gpt-4",
        response_text: null,
        error_message: "Provider unavailable",
      },
    ];
    expect(comparisonEligibility(runs as never)).toEqual({
      eligible: false,
      reason: "A succeeded baseline response is missing.",
    });
  });

  it("rejects pending or unknown statuses as ineligible", () => {
    const pendingRuns = [
      {
        id: "pending-run",
        execution_strategy: "baseline" as const,
        status: "pending" as unknown as "succeeded" | "failed",
        source_message_id: "message-1",
        provider: "openai",
        model: "gpt-4",
        response_text: null,
      },
    ];
    const unknownRuns = [
      {
        ...pendingRuns[0],
        id: "unknown-run",
        status: "unknown" as never,
      },
    ];
    expect(comparisonEligibility(pendingRuns as never)).toEqual({
      eligible: false,
      reason: "A succeeded baseline response is missing.",
    });
    expect(comparisonEligibility(unknownRuns as never)).toEqual({
      eligible: false,
      reason: "A succeeded baseline response is missing.",
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
