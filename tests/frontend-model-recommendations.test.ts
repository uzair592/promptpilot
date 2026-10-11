import { describe, expect, it } from "vitest";

import { recommendModels } from "../apps/frontend/lib/model-recommendations.js";

describe("AI model recommendations", () => {
  it("recommends Claude for coding work", () => {
    expect(recommendModels("Build and debug a Next.js website")[0].id).toBe(
      "claude",
    );
  });

  it("recommends Gemini for image generation and visual design", () => {
    expect(
      recommendModels("Generate a product image and poster design")[0].id,
    ).toBe("gemini");
  });

  it("recommends Perplexity for current cited research", () => {
    expect(
      recommendModels("Research the latest market prices with sources")[0].id,
    ).toBe("perplexity");
  });

  it("uses ChatGPT as the general fallback", () => {
    expect(recommendModels("Help me with this task")).toMatchObject([
      { id: "chatgpt" },
    ]);
  });
});
