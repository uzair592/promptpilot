export type ModelRecommendation = {
  id: "chatgpt" | "claude" | "gemini" | "perplexity";
  name: string;
  label: string;
  reason: string;
  url: string;
  score: number;
};

const OPTIONS: Array<
  Omit<ModelRecommendation, "score"> & { patterns: RegExp[] }
> = [
  {
    id: "claude",
    name: "Claude",
    label: "Best for coding",
    reason:
      "Strong fit for coding, debugging, architecture, and long technical work.",
    url: "https://claude.ai/new",
    patterns: [
      /\b(code|coding|program|programming|software|website|web app|application|api|debug|bug|database|architecture|developer|typescript|javascript|python|java|react|next\.?js)\b/i,
    ],
  },
  {
    id: "gemini",
    name: "Gemini",
    label: "Best for visual work",
    reason: "Strong fit for image ideas, visual design, and multimodal tasks.",
    url: "https://gemini.google.com/app",
    patterns: [
      /\b(image|photo|picture|visual|logo|poster|illustration|design|video|diagram|mockup|infographic)\b/i,
    ],
  },
  {
    id: "perplexity",
    name: "Perplexity",
    label: "Best for web research",
    reason:
      "Useful when the result needs current web information and source links.",
    url: "https://www.perplexity.ai/",
    patterns: [
      /\b(research|latest|current|today|news|sources?|citations?|compare products?|market data|price|statistics?)\b/i,
    ],
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
    label: "Best all-rounder",
    reason:
      "Strong general choice for discussion, planning, writing, and iterative refinement.",
    url: "https://chatgpt.com/",
    patterns: [
      /\b(discuss|discussion|brainstorm|plan|writing|write|email|proposal|explain|learn|strategy|ideas?|conversation)\b/i,
    ],
  },
];

export function recommendModels(input: string): ModelRecommendation[] {
  const text = input.trim();
  const ranked = OPTIONS.map((option, index) => ({
    id: option.id,
    name: option.name,
    label: option.label,
    reason: option.reason,
    url: option.url,
    score:
      option.patterns.reduce(
        (total, pattern) => total + (pattern.test(text) ? 10 : 0),
        0,
      ) +
      (option.id === "chatgpt" ? 1 : 0) -
      index / 100,
  })).sort((left, right) => right.score - left.score);

  const matched = ranked.filter((item) => item.score >= 9);
  if (matched.length === 0) {
    return ranked.filter((item) => item.id === "chatgpt");
  }
  return matched.slice(0, 2);
}
