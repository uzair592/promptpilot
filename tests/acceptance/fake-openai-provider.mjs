import { createServer } from "node:http";

const port = Number(process.env.PROMPTPILOT_FAKE_PROVIDER_PORT ?? "8132");
let requestCount = 0;
const generationInputs = [];
const analysisInputs = [];
const modelRequests = [];
const modelIds = ["acceptance-text", "acceptance-code", "acceptance-review"];

function contentFor(body) {
  const system =
    body.systemInstruction?.parts?.map((part) => part.text).join("\n") ||
    body.messages?.find((message) => message.role === "system")?.content ||
    "";
  const names = {
    AIAnalysis: "prompt_analysis",
    GeneratedQuestion: "generated_question",
    PromptGenerationResult: "prompt_generation",
    PlannedWorkflow: "planned_workflow",
  };
  const schemaName = Object.keys(names).find((name) =>
    system.includes(`"title": "${name}"`),
  );
  const format =
    body.response_format?.json_schema ||
    (schemaName ? { name: names[schemaName] } : null);
  modelRequests.push({
    model: body.model,
    purpose: format?.name || "completion",
  });
  if (!format)
    return `Local deterministic response ${requestCount} from ${body.model || "model"}`;
  const input =
    body.contents?.[0]?.parts?.[0]?.text ||
    body.messages?.find((message) => message.role === "user")?.content;
  const parsedInput = typeof input === "string" ? JSON.parse(input) : {};

  switch (format.name) {
    case "prompt_analysis": {
      let context;
      try {
        context = JSON.parse(parsedInput.prompt);
      } catch {
        context = { original_prompt: parsedInput.prompt };
      }
      const original = context.original_prompt || "";
      const answers = context.clarification_answers || [];
      analysisInputs.push({
        original_prompt: original,
        clarification_answers: answers,
      });
      const restaurant = /\bPOS\b|restaurant/i.test(original);
      const candidates = restaurant
        ? [
            [
              "constraints",
              "Receipt hardware",
              "Which receipt printer will your restaurant POS use?",
            ],
            [
              "requirements",
              "Kitchen workflow",
              "Should kitchen tickets appear on a display or print?",
            ],
          ]
        : [
            [
              "context",
              "Launch scope",
              "What are you launching, and who is the plan for?",
            ],
            [
              "output",
              "Plan format",
              "How detailed should this launch plan be?",
            ],
          ];
      return JSON.stringify({
        task_category: restaurant ? "software_development" : "general",
        dimensions: {},
        information_gaps: candidates
          .slice(answers.length)
          .map(([dimension, title, question]) => ({
            dimension,
            title,
            description: `A decision for ${original}`,
            severity: "important",
            importance: "high",
            question_target: question,
          })),
      });
    }
    case "planned_workflow":
      return JSON.stringify({
        milestones: [
          {
            title: "Plan and build",
            description: "A small workflow for the supplied idea",
            tasks: [
              {
                key: "scope",
                title: "Confirm product scope",
                description:
                  "Review the supplied product requirements and hand off a concise scope.",
                role: "product_manager",
                acceptance_criteria: [
                  "Requirements and assumptions are explicit",
                ],
                dependencies: [],
              },
              {
                key: "frontend",
                title: "Build the frontend",
                description: "Draft the frontend for the agreed scope.",
                role: "frontend",
                acceptance_criteria: ["The primary user flow is covered"],
                dependencies: ["scope"],
              },
              {
                key: "backend",
                title: "Build the backend",
                description: "Draft the backend for the agreed scope.",
                role: "backend",
                acceptance_criteria: ["API validation is described"],
                dependencies: ["scope"],
              },
              {
                key: "qa",
                title: "Review the implementation",
                description:
                  "Review both implementation drafts and identify checks to run.",
                role: "tester",
                acceptance_criteria: ["Review findings are actionable"],
                dependencies: ["frontend", "backend"],
              },
            ],
          },
        ],
      });
    case "generated_question":
      return JSON.stringify({
        question_text:
          parsedInput.gap_target || "What is the primary audience?",
        question_type: "free_text",
        related_gap: parsedInput.gap_id,
        priority: parsedInput.priority ?? 1,
        rationale: "This acceptance question is generated locally.",
      });
    case "prompt_generation":
      generationInputs.push(parsedInput.input);
      return JSON.stringify({
        optimized_prompt:
          "Write a concise plan for the supplied request without inventing facts.\n" +
          (parsedInput.input?.relevant_answers || [])
            .map((item) => `${item.question}: ${item.content}`)
            .join("\n"),
        task_summary: "Create a concise plan.",
        assumptions: [],
        incorporated_context: [],
        incorporated_requirements: [],
        output_format: "A concise plan",
        quality_notes: ["Grounded in the request"],
        warnings: [],
        generation_metadata: {},
      });
    case "response_evaluation":
      return JSON.stringify({
        response_a: {
          relevance: 80,
          completeness: 80,
          instruction_following: 80,
          contextual_grounding: 80,
          clarity: 80,
          explanations: {},
          evidence: {},
        },
        response_b: {
          relevance: 80,
          completeness: 80,
          instruction_following: 80,
          contextual_grounding: 80,
          clarity: 80,
          explanations: {},
          evidence: {},
        },
      });
    default:
      throw new Error(`Unexpected structured request: ${format.name}`);
  }
}

const server = createServer((request, response) => {
  if (request.method === "GET" && request.url === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify({
        status: "ok",
        request_count: requestCount,
        generation_inputs: generationInputs,
        analysis_inputs: analysisInputs,
        model_requests: modelRequests,
      }),
    );
    return;
  }
  if (
    request.method === "GET" &&
    (request.url === "/v1/models" || request.url?.startsWith("/v1beta/models?"))
  ) {
    const credential =
      request.headers.authorization || request.headers["x-goog-api-key"] || "";
    if (String(credential).includes("rejected")) {
      response.writeHead(401);
      response.end(
        JSON.stringify({ error: { message: "Synthetic key rejected" } }),
      );
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify(
        request.url.startsWith("/v1beta")
          ? {
              models: modelIds.map((name) => ({
                name: `models/${name}`,
                supportedGenerationMethods: ["generateContent"],
              })),
            }
          : { data: modelIds.map((id) => ({ id })) },
      ),
    );
    return;
  }
  const gemini = request.url?.includes(":generateContent");
  if (
    request.method !== "POST" ||
    (request.url !== "/v1/chat/completions" && !gemini)
  ) {
    response.writeHead(404);
    response.end();
    return;
  }

  let rawBody = "";
  request.setEncoding("utf8");
  request.on("data", (chunk) => {
    rawBody += chunk;
  });
  request.on("end", () => {
    try {
      requestCount += 1;
      const body = JSON.parse(rawBody);
      if (gemini) body.model = request.url.split("/models/")[1].split(":")[0];
      const generated = contentFor(body);
      const result = {
        id: `local-${requestCount}`,
        object: "chat.completion",
        created: 0,
        model: body.model,
        choices: [
          {
            index: 0,
            message: {
              role: "assistant",
              content: generated,
            },
            finish_reason: "stop",
          },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      };
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify(
          gemini
            ? {
                candidates: [{ content: { parts: [{ text: generated }] } }],
                usageMetadata: { promptTokenCount: 1, candidatesTokenCount: 1 },
              }
            : result,
        ),
      );
    } catch (error) {
      response.writeHead(400, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          error: error instanceof Error ? error.message : "Invalid request",
        }),
      );
    }
  });
});

server.listen(port, "127.0.0.1");
