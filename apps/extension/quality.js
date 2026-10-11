(function exposePromptQuality(global) {
  "use strict";

  const contains = (value, expressions) =>
    expressions.some((expression) => expression.test(value));

  function assess(rawPrompt) {
    const prompt = String(rawPrompt || "").trim();
    const words = prompt ? prompt.split(/\s+/).length : 0;
    const checks = [
      {
        label: "Clear goal",
        weight: 20,
        partial: words ? 8 : 0,
        present:
          words >= 3 &&
          contains(prompt, [
            /\b(create|write|build|design|explain|analyse|analyze|compare|summarize|plan|generate|review|fix|help|prepare|develop|make)\b/i,
            /\bi (?:need|want|would like)\b/i,
          ]),
        suggestion: "State the exact action or outcome you want.",
      },
      {
        label: "Useful context",
        weight: 20,
        partial: words >= 12 ? 8 : 0,
        present:
          words >= 30 ||
          contains(prompt, [
            /\b(context|background|currently|because|for my|based on|given that|the project|the business|attached|provided)\b/i,
          ]),
        suggestion: "Add the background the AI needs.",
      },
      {
        label: "Specific details",
        weight: 20,
        partial: words >= 10 ? 8 : 0,
        present:
          words >= 16 &&
          contains(prompt, [
            /\b\d+(?:\.\d+)?\b/,
            /\b(example|include|must|exactly|specifically|such as|using|with)\b/i,
          ]),
        suggestion: "Include concrete details, examples, or requirements.",
      },
      {
        label: "Constraints",
        weight: 15,
        partial: 0,
        present: contains(prompt, [
          /\b(must|must not|do not|don't|without|only|limit|maximum|minimum|avoid|deadline|within|under|no more than)\b/i,
        ]),
        suggestion: "Mention important limits or exclusions.",
      },
      {
        label: "Output format",
        weight: 15,
        partial: 0,
        present: contains(prompt, [
          /\b(table|bullet|list|json|markdown|email|report|code|script|paragraph|steps?|format|template|presentation|pdf|csv)\b/i,
        ]),
        suggestion: "Say how the answer should be formatted.",
      },
      {
        label: "Audience or tone",
        weight: 10,
        partial: 0,
        present: contains(prompt, [
          /\b(audience|reader|customer|client|examiner|student|beginner|expert|manager|developer|tone|formal|professional|simple english)\b/i,
        ]),
        suggestion: "Name the audience or preferred tone.",
      },
    ];
    const score = Math.min(
      100,
      checks.reduce(
        (total, check) =>
          total + (check.present ? check.weight : check.partial),
        0,
      ),
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
      criteria: checks.map((check) => ({
        label: check.label,
        present: check.present,
      })),
      suggestions: checks
        .filter((check) => !check.present)
        .map((check) => check.suggestion)
        .slice(0, 3),
    };
  }

  global.PromptPilotQuality = { assess };
})(globalThis);
