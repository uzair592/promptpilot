"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getProject } from "../../../lib/projects";
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
  if (error)
    return (
      <main className="shell">
        <section className="panel">
          <p className="error">{error}</p>
          <a href="/dashboard">Back to dashboard</a>
        </section>
      </main>
    );
  if (!project)
    return (
      <main className="shell">
        <p className="muted">Loading project...</p>
      </main>
    );
  return (
    <main className="promptpilot-app">
      <ConversationWorkspace
        projectId={params.projectId}
        projectName={project.name}
        canWrite={
          project.current_user_role !== "member" && project.status === "active"
        }
      />
    </main>
  );
}
