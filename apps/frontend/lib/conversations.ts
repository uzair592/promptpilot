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
  message_id: string;
  overall_score: number;
  status: string;
  task_category: string;
  analysis_version: string;
  analysis_mode: string;
  ai_provider: string | null;
  ai_model: string | null;
  ai_succeeded: boolean;
  fallback_used: boolean;
  created_at: string;
  dimensions: Array<{
    key: string;
    score: number | null;
    status: string;
    applicable: boolean;
    evidence: string | null;
    explanation: string;
  }>;
  gaps: Array<{
    id: string;
    dimension: string;
    title: string;
    description: string;
    severity: string;
    importance: string;
    question_target: string;
    status: string;
  }>;
};
export type QuestionSession = {
  id: string;
  status: string;
  stop_reason: string | null;
  next_question: {
    id: string;
    text: string;
    question_type: string;
    priority: number;
    status: string;
    source: string;
    options: string[] | null;
  } | null;
  analysis?: PromptAnalysis | null;
};
export type MemoryItem = {
  id: string;
  category: string;
  subject: string;
  content: string;
  source: string;
  status: string;
  confidence: number;
  created_at: string;
};
export type DocumentItem = {
  id: string;
  name: string;
  media_type: string;
  source_type: string;
  source_url: string | null;
  size_bytes: number;
  status: string;
  error_message: string | null;
  created_at: string;
};
export type ContextPackage = {
  task: string;
  project_memory: Array<{ content: string; provenance: string }>;
  user_answers: Array<{ content: string; provenance: string }>;
  requirements: Array<{ content: string; provenance: string }>;
  constraints: Array<{ content: string; provenance: string }>;
  document_context: Array<{
    content: string;
    provenance: string;
    source_type: string;
    score: number;
    metadata: Record<string, string>;
  }>;
  sources: Array<Record<string, string>>;
  omitted_items: Array<{
    source_type: string;
    identifier: string;
    reason: string;
  }>;
  used_budget: number;
  budget: number;
};
export type GeneratedPrompt = {
  version_id: string;
  version_number: number;
  source_message_id: string;
  created_at: string;
  original_prompt: string;
  optimized_prompt: string;
  task_summary: string;
  assumptions: string[];
  incorporated_context: string[];
  incorporated_requirements: string[];
  output_format: string;
  quality_notes: string[];
  warnings: string[];
  generation_metadata: Record<string, unknown>;
};
export type ModelRun = {
  id: string;
  prompt_version_id: string | null;
  source_message_id: string;
  execution_strategy: "baseline" | "promptpilot";
  optimized_prompt: string;
  response_text: string | null;
  provider: string;
  model: string;
  status: string;
  finish_reason: string | null;
  latency_ms: number | null;
  error_message: string | null;
  created_at: string;
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
    response_label: string;
    dimension: string;
    score: number;
    explanation: string;
  }>;
};

export function comparisonEligibility(runs: ModelRun[]): {
  eligible: boolean;
  reason: string;
} {
  const baseline = runs.some(
    (run) =>
      run.execution_strategy === "baseline" && run.status === "completed",
  );
  const promptpilot = runs.some(
    (run) =>
      run.execution_strategy === "promptpilot" && run.status === "completed",
  );
  if (!baseline)
    return {
      eligible: false,
      reason: "A completed baseline response is missing.",
    };
  if (!promptpilot)
    return {
      eligible: false,
      reason: "A completed PromptPilot response is missing.",
    };
  return {
    eligible: true,
    reason: "Compatible saved responses are available.",
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : init?.body
          ? { "content-type": "application/json" }
          : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = "The request could not be completed.";
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {}
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const friendlyError = (error: unknown, fallback: string): string => {
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "Your session expired. Sign in again to continue.";
    if (error.status === 403 || error.status === 404)
      return "This item is unavailable or you no longer have access.";
    if ([409, 422, 503].includes(error.status)) return error.message;
  }
  return fallback;
};

export async function getConversations(
  projectId: string,
): Promise<Conversation[]> {
  return (
    await api<{ items: Conversation[] }>(
      `/api/v1/projects/${projectId}/conversations`,
    )
  ).items;
}
export const createConversation = (projectId: string, title: string) =>
  api<Conversation>(`/api/v1/projects/${projectId}/conversations`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
export async function getMessages(conversationId: string): Promise<Message[]> {
  return (
    await api<{ items: Message[] }>(
      `/api/v1/conversations/${conversationId}/messages`,
    )
  ).items;
}
export const sendMessage = (
  conversationId: string,
  content: string,
  idempotencyKey = crypto.randomUUID(),
) =>
  api<Message>(`/api/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ role: "user", content }),
  });
export const analyzeMessage = (conversationId: string, messageId: string) =>
  api<PromptAnalysis>(
    `/api/v1/conversations/${conversationId}/messages/${messageId}/analysis`,
    { method: "POST" },
  );
export const getLatestAnalysis = (conversationId: string, messageId: string) =>
  api<PromptAnalysis>(
    `/api/v1/conversations/${conversationId}/messages/${messageId}/analysis`,
  );
export const getNextQuestion = (conversationId: string) =>
  api<QuestionSession>(
    `/api/v1/conversations/${conversationId}/questions/next`,
  );
export const answerQuestion = (
  conversationId: string,
  questionId: string,
  content: string,
) =>
  api<QuestionSession>(
    `/api/v1/conversations/${conversationId}/questions/${questionId}/answers`,
    { method: "POST", body: JSON.stringify({ content }) },
  );
export const skipQuestion = (conversationId: string, questionId: string) =>
  api<QuestionSession>(
    `/api/v1/conversations/${conversationId}/questions/${questionId}/skip`,
    { method: "POST" },
  );
export const getMemory = (projectId: string) =>
  api<MemoryItem[]>(`/api/v1/projects/${projectId}/memory`);
export const getDocuments = (projectId: string) =>
  api<DocumentItem[]>(`/api/v1/projects/${projectId}/documents`);
export const addDocumentUrl = (projectId: string, url: string) =>
  api<DocumentItem>(`/api/v1/projects/${projectId}/documents/url`, {
    method: "POST",
    body: JSON.stringify({ url }),
  });
export const uploadDocument = (projectId: string, file: File) => {
  const body = new FormData();
  body.set("file", file);
  return api<DocumentItem>(`/api/v1/projects/${projectId}/documents`, {
    method: "POST",
    body,
  });
};
export const assembleContext = (
  projectId: string,
  input: {
    task: string;
    conversation_id: string;
    message_id: string;
    analysis_id?: string;
  },
) =>
  api<ContextPackage>(`/api/v1/projects/${projectId}/context/assemble`, {
    method: "POST",
    body: JSON.stringify({ ...input, budget: 8000, top_k: 5 }),
  });
export const getGeneratedPrompts = (conversationId: string) =>
  api<GeneratedPrompt[]>(`/api/v1/conversations/${conversationId}/prompts`);
export const generatePrompt = (
  conversationId: string,
  messageId: string,
  mode: string,
) =>
  api<GeneratedPrompt>(
    `/api/v1/conversations/${conversationId}/prompts/generate`,
    { method: "POST", body: JSON.stringify({ message_id: messageId, mode }) },
  );
export const getRuns = (conversationId: string) =>
  api<ModelRun[]>(`/api/v1/conversations/${conversationId}/prompts/runs`);
export const executePrompt = (
  conversationId: string,
  versionId: string,
  messageId: string,
  strategy: "baseline" | "promptpilot",
) =>
  api<ModelRun>(
    `/api/v1/conversations/${conversationId}/prompts/${versionId}/execute`,
    {
      method: "POST",
      body: JSON.stringify({ strategy, message_id: messageId }),
    },
  );
export async function getEvaluations(
  conversationId: string,
): Promise<Evaluation[]> {
  return (
    await api<{ items: Evaluation[] }>(
      `/api/v1/conversations/${conversationId}/evaluations`,
    )
  ).items;
}
export const compareEvaluations = (
  conversationId: string,
  baselineRunId: string,
  promptpilotRunId: string,
) =>
  api<Evaluation>(
    `/api/v1/conversations/${conversationId}/evaluations/compare`,
    {
      method: "POST",
      body: JSON.stringify({
        baseline_model_run_id: baselineRunId,
        promptpilot_model_run_id: promptpilotRunId,
        method: "heuristic",
      }),
    },
  );
export const evaluateRun = (conversationId: string, runId: string) =>
  api<Evaluation>(
    `/api/v1/conversations/${conversationId}/runs/${runId}/evaluate`,
    { method: "POST", body: JSON.stringify({ method: "heuristic" }) },
  );
