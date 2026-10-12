(function exposePromptPilotProtocol(global) {
  "use strict";

  const systemPrompt = `You are PromptPilot, a prompt-improvement assistant embedded in an AI website.
Return only valid JSON. Never use markdown fences.
Preserve the user's intent and language. Do not answer the prompt itself.
Ask at most 3 short clarification questions, and only when the missing information would materially change the result.
If clarification is unnecessary, return an empty questions array and a complete improved_prompt.
Use this exact shape:
{"summary":"short assessment","questions":[{"id":"q1","question":"short question","placeholder":"short example"}],"improved_prompt":"string or empty until answers are provided","improvements":["short item"]}`;

  function analyzeMessages(prompt, quality) {
    return [
      { role: "system", content: systemPrompt },
      {
        role: "user",
        content: `Improve this prompt. Its local quality score is ${quality.score}/100 (${quality.label}).\n\nORIGINAL PROMPT:\n${prompt}`,
      },
    ];
  }

  function improveMessages(prompt, answers) {
    const answerText = answers
      .map(
        (answer, index) =>
          `${index + 1}. ${answer.question}\nAnswer: ${answer.answer || "Not specified"}`,
      )
      .join("\n\n");
    return [
      { role: "system", content: systemPrompt },
      {
        role: "user",
        content: `Create the final improved prompt using the clarification answers. Return questions as an empty array.\n\nORIGINAL PROMPT:\n${prompt}\n\nCLARIFICATIONS:\n${answerText}`,
      },
    ];
  }

  function parseResponse(value) {
    const text = String(value || "").trim();
    const unfenced = text
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/, "")
      .trim();
    let parsed;
    try {
      parsed = JSON.parse(unfenced);
    } catch (_error) {
      const start = unfenced.indexOf("{");
      const end = unfenced.lastIndexOf("}");
      if (start < 0 || end <= start) {
        throw new Error(
          "The model returned an unreadable response. Please try again.",
        );
      }
      parsed = JSON.parse(unfenced.slice(start, end + 1));
    }
    const questions = Array.isArray(parsed.questions)
      ? parsed.questions.slice(0, 3).map((question, index) => ({
          id: String(question.id || `q${index + 1}`),
          question: String(question.question || "").trim(),
          placeholder: String(question.placeholder || "").trim(),
        }))
      : [];
    return {
      summary: String(parsed.summary || "Prompt reviewed.").trim(),
      questions: questions.filter((question) => question.question),
      improvedPrompt: String(parsed.improved_prompt || "").trim(),
      improvements: Array.isArray(parsed.improvements)
        ? parsed.improvements.map(String).filter(Boolean).slice(0, 5)
        : [],
    };
  }

  global.PromptPilotProtocol = {
    analyzeMessages,
    improveMessages,
    parseResponse,
  };
})(globalThis);
