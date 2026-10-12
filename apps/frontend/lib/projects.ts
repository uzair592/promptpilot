export type Project = {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  domain: string | null;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
};

export class ProjectApiError extends Error {
  constructor(public readonly status: number) {
    super("Project request failed");
  }
}

async function requireOk(response: Response): Promise<Response> {
  if (!response.ok) throw new ProjectApiError(response.status);
  return response;
}

export async function getProjects(): Promise<Project[]> {
  const response = await requireOk(
    await fetch("/api/v1/projects", { credentials: "include" }),
  );
  return (await response.json()).items as Project[];
}

export async function createProject(input: {
  name: string;
  description: string;
  domain: string;
}): Promise<Project> {
  const response = await requireOk(
    await fetch("/api/v1/projects", {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
  return (await response.json()) as Project;
}

export async function getProject(id: string) {
  const response = await requireOk(
    await fetch(`/api/v1/projects/${id}`, { credentials: "include" }),
  );
  return response.json();
}
