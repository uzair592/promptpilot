export type ProviderName = "openai" | "anthropic" | "gemini" | "openrouter";

export type ProviderConnection = {
  id: string;
  provider: ProviderName;
  label: string;
  masked_key: string;
  default_model: string;
  status: "untested" | "active" | "invalid" | "disabled";
  last_tested_at: string | null;
  last_test_status: string | null;
  last_test_message: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentTask = {
  id: string;
  project_id: string;
  plan_id: string;
  milestone_id: string;
  title: string;
  description: string;
  role:
    | "orchestrator"
    | "product_manager"
    | "researcher"
    | "frontend"
    | "backend"
    | "api"
    | "tester";
  assignment_reason: string;
  assigned_connection_id: string | null;
  assigned_provider: ProviderName | null;
  assigned_model: string | null;
  acceptance_criteria: string[];
  dependencies: string[];
  status: string;
  scheduled_for: string | null;
  output_text: string | null;
  pull_request_url: string | null;
  last_error: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
};

export type PlanMilestone = {
  id: string;
  plan_id: string;
  title: string;
  description: string;
  position: number;
  status: string;
  due_at: string | null;
  tasks: AgentTask[];
};

export type ProjectPlan = {
  id: string;
  project_id: string;
  title: string;
  summary: string;
  status: string;
  created_at: string;
  updated_at: string;
  milestones: PlanMilestone[];
};

export type ProjectRepository = {
  owner: string;
  repo: string;
  default_branch: string;
  url: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      error?: { message?: string };
      detail?: string;
    };
    throw new Error(body.error?.message || body.detail || "Request failed");
  }
  return (await response.json()) as T;
}

export async function getProviderConnections(): Promise<ProviderConnection[]> {
  return (
    await api<{ items: ProviderConnection[] }>("/api/v1/provider-connections")
  ).items;
}

export function addProviderConnection(input: {
  provider: ProviderName;
  label: string;
  api_key: string;
  default_model: string;
}): Promise<ProviderConnection> {
  return api("/api/v1/provider-connections", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function testProviderConnection(
  id: string,
): Promise<{ connection: ProviderConnection; available_models: string[] }> {
  return api(`/api/v1/provider-connections/${id}/test`, { method: "POST" });
}

export async function getPlans(projectId: string): Promise<ProjectPlan[]> {
  return (
    await api<{ items: ProjectPlan[] }>(`/api/v1/projects/${projectId}/plans`)
  ).items;
}

export function createPlan(
  projectId: string,
  input: { title: string; idea: string; start_at: string | null },
): Promise<ProjectPlan> {
  return api(`/api/v1/projects/${projectId}/plans`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateAgentTask(
  taskId: string,
  input: {
    assigned_connection_id?: string | null;
    scheduled_for?: string | null;
    status?: string;
  },
): Promise<AgentTask> {
  return api(`/api/v1/agent-tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function runAgentTask(taskId: string): Promise<{ status: string }> {
  return api(`/api/v1/agent-tasks/${taskId}/run`, { method: "POST" });
}

export async function getProjectRepository(
  projectId: string,
): Promise<ProjectRepository | null> {
  const response = await fetch(`/api/v1/projects/${projectId}/repository`, {
    credentials: "include",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("Could not load the project repository");
  return (await response.json()) as ProjectRepository;
}

export function connectProjectRepository(
  projectId: string,
  input: { owner: string; repo: string; token: string },
): Promise<ProjectRepository> {
  return api(`/api/v1/projects/${projectId}/repository`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function publishAgentTask(
  taskId: string,
): Promise<{ pull_request_url: string }> {
  return api(`/api/v1/agent-tasks/${taskId}/publish`, { method: "POST" });
}

export function saveAgentDraft(
  taskId: string,
  output_text: string,
): Promise<AgentTask> {
  return api(`/api/v1/agent-tasks/${taskId}/draft`, {
    method: "PATCH",
    body: JSON.stringify({ output_text }),
  });
}
