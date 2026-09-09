import { describe, expect, it, vi } from "vitest";

import {
  createConversation,
  getMessages,
  sendMessage,
} from "../apps/frontend/lib/conversations.js";

describe("frontend conversation API helpers", () => {
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
      "http://localhost:8000/api/v1/conversations/conversation-1/messages",
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
