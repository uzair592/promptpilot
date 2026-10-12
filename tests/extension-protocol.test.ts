import { describe, expect, it } from "vitest";

// @ts-expect-error This classic browser script intentionally has no module declaration.
await import("../apps/extension/protocol.js");

const protocol = (
  globalThis as typeof globalThis & {
    PromptPilotProtocol: {
      analyzeMessages: (
        prompt: string,
        quality: { score: number; label: string },
      ) => Array<{ role: string; content: string }>;
      parseResponse: (value: string) => {
        questions: unknown[];
        improvedPrompt: string;
      };
    };
  }
).PromptPilotProtocol;

describe("extension OpenRouter protocol", () => {
  it("asks the model to improve rather than answer the prompt", () => {
    const messages = protocol.analyzeMessages("Write an email", {
      score: 20,
      label: "Needs work",
    });
    expect(messages[0].content).toContain("Do not answer the prompt itself");
    expect(messages[1].content).toContain("Write an email");
  });

  it("parses fenced JSON and limits clarification questions", () => {
    const result = protocol.parseResponse(
      '```json\n{"summary":"Needs context","questions":[{"question":"One?"},{"question":"Two?"},{"question":"Three?"},{"question":"Four?"}],"improved_prompt":"Better prompt","improvements":[]}\n```',
    );
    expect(result.questions).toHaveLength(3);
    expect(result.improvedPrompt).toBe("Better prompt");
  });

  it("rejects a response without a JSON object", () => {
    expect(() => protocol.parseResponse("not json")).toThrow(
      "unreadable response",
    );
  });
});
