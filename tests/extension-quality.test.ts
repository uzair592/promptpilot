import { describe, expect, it } from "vitest";

// @ts-expect-error This classic browser script intentionally has no module declaration.
await import("../apps/extension/quality.js");

type QualityResult = { score: number; label: string; suggestions: string[] };
const quality = (
  globalThis as typeof globalThis & {
    PromptPilotQuality: { assess: (prompt: string) => QualityResult };
  }
).PromptPilotQuality;

describe("extension prompt quality", () => {
  it("scores an empty prompt at zero", () => {
    expect(quality.assess("")).toMatchObject({ score: 0, label: "Needs work" });
  });

  it("rewards a specific prompt with constraints, audience, and format", () => {
    const result = quality.assess(
      "Create a professional 5-step markdown plan for beginner developers. Include two examples, use the provided project context, and keep it under 400 words.",
    );
    expect(result.score).toBeGreaterThanOrEqual(85);
    expect(result.label).toBe("Excellent");
  });

  it("returns actionable suggestions for a weak prompt", () => {
    expect(quality.assess("help me").suggestions).toHaveLength(3);
  });
});
