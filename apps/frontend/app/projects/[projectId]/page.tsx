"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { apiBaseUrl, getProject } from "../../../lib/projects";
import { ConversationWorkspace } from "./ConversationWorkspace";

type ProjectDetail = {
  name: string;
  description: string | null;
  domain: string | null;
  status: string;
  created_at: string;
  current_user_role: string;
};

export default function ProjectPage() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getProject(params.projectId)
      .then(setProject)
      .catch(() => setError("Project not found or unavailable."));
  }, [params.projectId]);
  async function archive() {
    const response = await fetch(
      `${apiBaseUrl}/api/v1/projects/${params.projectId}/archive`,
      { method: "POST", credentials: "include" },
    );
    if (response.ok) setProject(await response.json());
  }
  if (error)
    return (
      <main className="shell">
        <section className="panel">
          <p className="error">{error}</p>
          <Link href="/dashboard">Back to dashboard</Link>
        </section>
      </main>
    );
  if (!project)
    return (
      <main className="shell">
        <p className="muted">Loading project...</p>
      </main>
    );
  const canArchive =
    project.current_user_role === "owner" && project.status === "active";
  return (
    <main className="main project-page">
      <div className="row">
        <Link href="/dashboard">Back to projects</Link>
        {canArchive && (
          <button className="secondary" onClick={archive}>
            Archive project
          </button>
        )}
      </div>
      <section className="project-header">
        <p className="muted">
          {project.domain || "General Task"} · {project.status}
        </p>
        <h1>{project.name}</h1>
        <p className="muted">{project.description || "No description yet."}</p>
        <small>
          Your role: {project.current_user_role} · Created{" "}
          {new Date(project.created_at).toLocaleDateString()}
        </small>
      </section>
      <ConversationWorkspace
        projectId={params.projectId}
        canWrite={
          project.current_user_role !== "member" && project.status === "active"
        }
      />
      <div className="placeholder-grid">
        {["Context", "Requirements", "Prompts", "Evaluations"].map((item) => (
          <section className="panel" key={item}>
            <h3>{item}</h3>
            <p className="muted">
              This workspace module is coming in a future slice.
            </p>
          </section>
        ))}
      </div>
    </main>
  );
}
