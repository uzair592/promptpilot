export type PromptQualityCriterion = {
  key:
    "goal" | "context" | "specificity" | "constraints" | "format" | "audience";
  label: string;
  score: number;
  maximum: number;
  present: boolean;
  suggestion: string;
};

export type PromptQuality = {
  score: number;
  label: "Needs work" | "Getting there" | "Strong" | "Excellent";
  criteria: PromptQualityCriterion[];
  suggestions: string[];
};

const contains = (value: string, expressions: RegExp[]) =>
  expressions.some((expression) => expression.test(value));

export function isSmallTalk(value: string): boolean {
  return /^(hi|hello|hey|hi there|hello there|amazing|great|awesome|nice|ok|okay|thanks|thank you|good morning|good evening)$/i.test(
    value.trim().replace(/[.!?]+$/, ""),
  );
}

export function assessPromptQuality(rawPrompt: string): PromptQuality {
  const prompt = rawPrompt.trim();
  const words = prompt ? prompt.split(/\s+/).length : 0;

  const goal =
    words >= 3 &&
    contains(prompt, [
      /\b(create|write|build|design|explain|analyse|analyze|compare|summarize|plan|generate|review|fix|help|prepare|develop|make)\b/i,
      /\bi (?:need|want|would like)\b/i,
    ]);
  const context =
    words >= 30 ||
    contains(prompt, [
      /\b(context|background|currently|because|for my|based on|given that|the project|the business|attached|provided)\b/i,
    ]);
  const specificity =
    words >= 16 &&
    contains(prompt, [
      /\b\d+(?:\.\d+)?\b/,
      /\b(example|include|must|exactly|specifically|such as|using|with)\b/i,
    ]);
  const constraints = contains(prompt, [
    /\b(must|must not|do not|don't|without|only|limit|maximum|minimum|avoid|deadline|within|under|no more than)\b/i,
  ]);
  const format = contains(prompt, [
    /\b(table|bullet|list|json|markdown|email|report|code|script|paragraph|steps?|format|template|presentation|pdf|csv)\b/i,
  ]);
  const audience = contains(prompt, [
    /\b(audience|reader|customer|client|examiner|student|beginner|expert|manager|developer|tone|formal|professional|simple english)\b/i,
  ]);

  const criteria: PromptQualityCriterion[] = [
    {
      key: "goal",
      label: "Clear goal",
      score: goal ? 20 : words ? 8 : 0,
      maximum: 20,
      present: goal,
      suggestion: "State the exact action or outcome you want.",
    },
    {
      key: "context",
      label: "Useful context",
      score: context ? 20 : words >= 12 ? 8 : 0,
      maximum: 20,
      present: context,
      suggestion: "Add the background the AI needs to make a good decision.",
    },
    {
      key: "specificity",
      label: "Specific details",
      score: specificity ? 20 : words >= 10 ? 8 : 0,
      maximum: 20,
      present: specificity,
      suggestion: "Include concrete details, examples, data, or requirements.",
    },
    {
      key: "constraints",
      label: "Constraints",
      score: constraints ? 15 : 0,
      maximum: 15,
      present: constraints,
      suggestion: "Mention important limits, exclusions, or rules.",
    },
    {
      key: "format",
      label: "Output format",
      score: format ? 15 : 0,
      maximum: 15,
      present: format,
      suggestion: "Say how the answer should be structured or formatted.",
    },
    {
      key: "audience",
      label: "Audience or tone",
      score: audience ? 10 : 0,
      maximum: 10,
      present: audience,
      suggestion: "Name the intended audience or preferred tone.",
    },
  ];
  if (isSmallTalk(prompt)) {
    for (const criterion of criteria) {
      criterion.score = 0;
      criterion.present = false;
    }
  }
  const score = Math.min(
    100,
    criteria.reduce((total, criterion) => total + criterion.score, 0),
  );
  const label =
    score >= 85
      ? "Excellent"
      : score >= 65
        ? "Strong"
        : score >= 40
          ? "Getting there"
          : "Needs work";

  return {
    score,
    label,
    criteria,
    suggestions: criteria
      .filter((criterion) => !criterion.present)
      .map((criterion) => criterion.suggestion)
      .slice(0, 3),
  };
}
