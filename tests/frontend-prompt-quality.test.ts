import { describe, expect, it } from "vitest";

import { assessPromptQuality } from "../apps/frontend/lib/prompt-quality.js";

describe("live prompt quality meter", () => {
  it("keeps an empty prompt at zero", () => {
    expect(assessPromptQuality(" ")).toMatchObject({
      score: 0,
      label: "Needs work",
    });
  });

  it("identifies missing prompt components and recommends improvements", () => {
    const result = assessPromptQuality("Write something about sales");

    expect(result.score).toBeLessThan(50);
    expect(result.suggestions).toContain(
      "Add the background the AI needs to make a good decision.",
    );
    expect(result.criteria.find((item) => item.key === "goal")?.present).toBe(
      true,
    );
  });

  it("scores a detailed prompt strongly", () => {
    const result = assessPromptQuality(
      "Create a professional five-step report for restaurant managers. Use the attached monthly sales data, include a comparison table, identify exactly three risks, and keep the response under 700 words.",
    );

    expect(result.score).toBeGreaterThanOrEqual(85);
    expect(result.label).toBe("Excellent");
    expect(result.suggestions).toHaveLength(0);
  });
});
