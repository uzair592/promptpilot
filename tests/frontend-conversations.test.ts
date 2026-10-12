import { describe, expect, it, vi } from "vitest";

import {
  createConversation,
  answerQuestion,
  getNextQuestion,
  friendlyError,
  getMessages,
  sendMessage,
} from "../apps/frontend/lib/conversations.js";

describe("frontend conversation API helpers", () => {
  it("sends a clarification to its question, never as a new prompt", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          answered_questions: [{ content: "Three bullet points" }],
        }),
        { status: 201 },
      ),
    );
    await answerQuestion("conversation-1", "question-1", "Three bullet points");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/conversations/conversation-1/questions/question-1/answers",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ content: "Three bullet points" }),
      }),
    );
    fetchMock.mockRestore();
  });

  it("scopes restored questions to the source message", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ next_question: null })));
    await getNextQuestion("conversation-1", "message-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/conversations/conversation-1/questions/next?message_id=message-1",
      expect.anything(),
    );
    fetchMock.mockRestore();
  });

  it("shows the backend model error instead of discarding its message", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { message: "Prompt generation is temporarily unavailable" },
        }),
        { status: 503 },
      ),
    );
    let error: unknown;
    try {
      await getNextQuestion("conversation-1");
    } catch (caught) {
      error = caught;
    }
    expect(friendlyError(error, "Generic failure")).toBe(
      "Prompt generation is temporarily unavailable",
    );
    fetchMock.mockRestore();
  });
  it("creates a conversation and loads ordered history", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ id: "conversation-1", title: "Planning" }),
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [{ id: "message-1", sequence: 1, content: "Hello" }],
          }),
          { status: 200 },
        ),
      );
    await expect(
      createConversation("project-1", "Planning"),
    ).resolves.toMatchObject({ id: "conversation-1" });
    await expect(getMessages("conversation-1")).resolves.toEqual([
      { id: "message-1", sequence: 1, content: "Hello" },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fetchMock.mockRestore();
  });

  it("sends only a user message with an idempotency key", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "00000000-0000-4000-8000-000000000001",
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "message-1", role: "user" }), {
        status: 201,
      }),
    );
    await expect(sendMessage("conversation-1", "Hello")).resolves.toMatchObject(
      { role: "user" },
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/conversations/conversation-1/messages",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "00000000-0000-4000-8000-000000000001",
        }),
      }),
    );
    fetchMock.mockRestore();
  });
});
