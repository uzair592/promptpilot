import { createServer } from "node:http";

const port = Number(process.env.PROMPTPILOT_FAKE_PROVIDER_PORT ?? "8132");
let requestCount = 0;

function contentFor(body) {
  const format = body.response_format?.json_schema;
  if (!format) {
    return `Local deterministic response ${requestCount}`;
  }

  const input = body.messages.find(
    (message) => message.role === "user",
  )?.content;
  const parsedInput = typeof input === "string" ? JSON.parse(input) : {};

  switch (format.name) {
    case "prompt_analysis":
      return JSON.stringify({
        task_category: "general",
        dimensions: {},
        information_gaps: [],
      });
    case "generated_question":
      return JSON.stringify({
        question_text: "What is the primary audience?",
        question_type: "free_text",
        related_gap: parsedInput.gap_id,
        priority: parsedInput.priority ?? 1,
        rationale: "This acceptance question is generated locally.",
      });
    case "prompt_generation":
      return JSON.stringify({
        optimized_prompt:
          "Write a concise plan for the supplied request without inventing facts.",
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
    response.end(JSON.stringify({ status: "ok", request_count: requestCount }));
    return;
  }
  if (request.method !== "POST" || request.url !== "/v1/chat/completions") {
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
              content: contentFor(body),
            },
            finish_reason: "stop",
          },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      };
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(result));
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
