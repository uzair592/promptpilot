"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { createProject, getProjects } from "../../lib/projects";

export default function DashboardPage() {
  const router = useRouter();
  const started = useRef(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    async function openWorkspace() {
      try {
        const userResponse = await fetch("/api/v1/auth/me", {
          credentials: "include",
        });
        if (!userResponse.ok) {
          router.replace("/login");
          return;
        }

        const projects = await getProjects();
        const active = projects.find((project) => project.status === "active");
        if (active) {
          router.replace(`/projects/${active.id}`);
          return;
        }

        const workspace = await createProject({
          name: "My PromptPilot",
          description: "My saved prompts and source material",
          domain: "General Task",
        });
        router.replace(`/projects/${workspace.id}`);
      } catch {
        setError("PromptPilot could not open your workspace. Please retry.");
      }
    }

    void openWorkspace();
  }, [router]);

  return (
    <main className="shell">
      {error ? (
        <section className="panel">
          <h1 className="brand">PromptPilot</h1>
          <p className="error">{error}</p>
          <button onClick={() => window.location.reload()}>Retry</button>
        </section>
      ) : (
        <div className="workspace-opening" role="status">
          <span className="welcome-mark">P</span>
          <strong>Opening PromptPilot…</strong>
          <small>Preparing your prompt workspace</small>
        </div>
      )}
    </main>
  );
}
