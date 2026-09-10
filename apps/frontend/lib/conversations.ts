import { apiBaseUrl } from "./projects";

export type Conversation = {
  id: string;
  project_id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
};
export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sequence: number;
  created_at: string;
};
export type PromptAnalysis = {
  id: string;
  overall_score: number;
  status: "Poor" | "Medium" | "Good";
  task_category: string;
  analysis_version: string;
  analysis_mode: string;
  fallback_used: boolean;
  dimensions: Array<{
    key: string;
    score: number | null;
    status: string;
    applicable: boolean;
    explanation: string;
  }>;
  gaps: Array<{
    id: string;
    title: string;
    description: string;
    severity: string;
    question_target: string;
  }>;
};
export type Evaluation = {
  id: string;
  project_id: string;
  conversation_id: string;
  baseline_model_run_id: string | null;
  promptpilot_model_run_id: string | null;
  method: string;
  evaluator_provider: string;
  evaluator_model: string;
  rubric_version: string;
  baseline_score: number | null;
  promptpilot_score: number | null;
  overall_delta: number | null;
  winner: "baseline" | "promptpilot" | "tie" | null;
  comparison_summary: string | null;
  baseline_strengths: string[];
  baseline_weaknesses: string[];
  promptpilot_strengths: string[];
  promptpilot_weaknesses: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  items: Array<{
    id: string;
    evaluation_id: string;
    response_label: string;
    dimension: string;
    score: number;
    explanation: string;
  }>;
};

export async function getConversations(
  projectId: string,
): Promise<Conversation[]> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/projects/${projectId}/conversations`,
    { credentials: "include" },
  );
  if (!response.ok) throw new Error("Could not load conversations");
  return (await response.json()).items as Conversation[];
}

export async function createConversation(
  projectId: string,
  title: string,
): Promise<Conversation> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/projects/${projectId}/conversations`,
    {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    },
  );
  if (!response.ok) throw new Error("Could not create conversation");
  return response.json();
}

export async function getMessages(conversationId: string): Promise<Message[]> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/messages`,
    { credentials: "include" },
  );
  if (!response.ok) throw new Error("Could not load messages");
  return (await response.json()).items as Message[];
}

export async function sendMessage(
  conversationId: string,
  content: string,
): Promise<Message> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/messages`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        "content-type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ role: "user", content }),
    },
  );
  if (!response.ok) throw new Error("Could not send message");
  return response.json();
}

export async function analyzeMessage(
  conversationId: string,
  messageId: string,
): Promise<PromptAnalysis> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/messages/${messageId}/analysis`,
    {
      method: "POST",
      credentials: "include",
    },
  );
  if (!response.ok) throw new Error("Could not analyze message");
  return response.json();
}

export async function getEvaluations(
  conversationId: string,
): Promise<Evaluation[]> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/evaluations`,
    { credentials: "include" },
  );
  if (!response.ok) throw new Error("Could not load evaluations");
  return (await response.json()).items as Evaluation[];
}

export async function compareEvaluations(
  conversationId: string,
  baselineRunId: string,
  promptpilotRunId: string,
): Promise<Evaluation> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/evaluations/compare`,
    {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        baseline_model_run_id: baselineRunId,
        promptpilot_model_run_id: promptpilotRunId,
      }),
    },
  );
  if (!response.ok) throw new Error("Could not compare responses");
  return response.json();
}

export async function evaluateRun(
  conversationId: string,
  runId: string,
): Promise<Evaluation> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/evaluations`,
    {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    },
  );
  if (!response.ok) throw new Error("Could not evaluate response");
  return response.json();
}
