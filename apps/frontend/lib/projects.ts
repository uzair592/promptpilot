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

export async function getProjects(): Promise<Project[]> {
  const response = await fetch("/api/v1/projects", {
    credentials: "include",
  });
  if (!response.ok) throw new Error("Could not load projects");
  return (await response.json()).items as Project[];
}

export async function createProject(input: {
  name: string;
  description: string;
  domain: string;
}): Promise<Project> {
  const response = await fetch("/api/v1/projects", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error("Could not create project");
  return (await response.json()) as Project;
}

export async function getProject(id: string) {
  const response = await fetch(`/api/v1/projects/${id}`, {
    credentials: "include",
  });
  if (!response.ok) throw new Error("Could not load project");
  return response.json();
}
