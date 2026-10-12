"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getProject } from "../../../../lib/projects";
import { AgentWorkspace } from "./AgentWorkspace";

export default function AgentTeamPage() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<{
    name: string;
    description: string | null;
    status: string;
    current_user_role: string;
  } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getProject(params.projectId)
      .then(setProject)
      .catch(() => setError("Project not found or unavailable."));
  }, [params.projectId]);

  if (error)
    return (
      <main className="agent-page">
        <p className="agent-alert error">{error}</p>
      </main>
    );
  if (!project)
    return (
      <main className="agent-page">
        <p>Loading AI team…</p>
      </main>
    );
  return (
    <AgentWorkspace
      projectId={params.projectId}
      projectName={project.name}
      projectDescription={project.description || ""}
      canWrite={
        project.current_user_role !== "member" && project.status === "active"
      }
      canManageRepository={
        project.current_user_role === "owner" && project.status === "active"
      }
    />
  );
}
