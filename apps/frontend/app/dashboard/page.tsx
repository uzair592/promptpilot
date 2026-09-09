"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  apiBaseUrl,
  createProject,
  getProjects,
  Project,
} from "../../lib/projects";

type User = { display_name: string; email: string };

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch(`${apiBaseUrl}/api/v1/auth/me`, { credentials: "include" }),
      getProjects(),
    ])
      .then(async ([userResponse, loadedProjects]) => {
        if (!userResponse.ok) {
          router.replace("/login");
          return;
        }
        setUser((await userResponse.json()).user);
        setProjects(loadedProjects);
        setLoading(false);
      })
      .catch(() => {
        setError("We could not load your projects.");
        setLoading(false);
      });
  }, [router]);

  async function logout() {
    await fetch(`${apiBaseUrl}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    router.replace("/login");
  }
  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const project = await createProject({
        name: String(form.get("name")),
        description: String(form.get("description")),
        domain: String(form.get("domain")),
      });
      router.push(`/projects/${project.id}`);
    } catch {
      setError("We could not create that project.");
      setCreating(false);
    }
  }
  if (loading)
    return (
      <main className="shell">
        <p className="muted">Loading your projects...</p>
      </main>
    );
  return (
    <div className="nav">
      <aside className="sidebar">
        <h1>PromptPilot</h1>
        <p>Context engineering workspace</p>
      </aside>
      <main className="main">
        <div className="row">
          <div>
            <h2>Welcome, {user?.display_name}</h2>
            <p className="muted">{user?.email}</p>
          </div>
          <button className="secondary" onClick={logout}>
            Log out
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="row" style={{ marginTop: 32 }}>
          <h3>Projects</h3>
          <button onClick={() => setShowCreate(true)}>New project</button>
        </div>
        {projects.length === 0 ? (
          <section className="panel">
            <h3>No projects yet</h3>
            <p className="muted">
              Create a project to begin organizing your context.
            </p>
          </section>
        ) : (
          <div className="project-grid">
            {projects.map((project) => (
              <Link
                className="project-card"
                href={`/projects/${project.id}`}
                key={project.id}
              >
                <div className="row">
                  <strong>{project.name}</strong>
                  <span>{project.status}</span>
                </div>
                <p className="muted">
                  {project.description || "No description yet."}
                </p>
                <small>{project.domain || "General Task"}</small>
              </Link>
            ))}
          </div>
        )}
        {showCreate && (
          <div className="modal-backdrop">
            <section
              className="panel modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="create-title"
            >
              <div className="row">
                <h3 id="create-title">Create project</h3>
                <button
                  className="secondary"
                  onClick={() => setShowCreate(false)}
                >
                  Close
                </button>
              </div>
              <form className="form" onSubmit={submitProject}>
                <label>
                  Project name
                  <input name="name" required maxLength={160} />
                </label>
                <label>
                  Description
                  <textarea name="description" maxLength={4000} rows={4} />
                </label>
                <label>
                  Domain or task type
                  <select name="domain" defaultValue="General Task">
                    <option>General Task</option>
                    <option>Software Development</option>
                    <option>Business Analysis</option>
                    <option>Data Analysis</option>
                    <option>Marketing</option>
                    <option>Education</option>
                    <option>Writing/Content</option>
                    <option>Research</option>
                  </select>
                </label>
                <button disabled={creating}>
                  {creating ? "Creating..." : "Create project"}
                </button>
              </form>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
