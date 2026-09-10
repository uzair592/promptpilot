"use client";

import { useState } from "react";

import { apiBaseUrl } from "../../../lib/projects";

type Package = {
  task: string;
  project_memory: { content: string; provenance: string }[];
  user_answers: { content: string; provenance: string }[];
  requirements: { content: string; provenance: string }[];
  constraints: { content: string; provenance: string }[];
  document_context: {
    content: string;
    provenance: string;
    score: number;
    metadata: Record<string, string>;
  }[];
  omitted_items: { source_type: string; identifier: string; reason: string }[];
  used_budget: number;
  budget: number;
};

export function ContextPreview({ projectId }: { projectId: string }) {
  const [task, setTask] = useState("");
  const [result, setResult] = useState<Package | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function assemble() {
    if (!task.trim()) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/projects/${projectId}/context/assemble`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task: task.trim(), budget: 8000, top_k: 5 }),
        },
      );
      if (!response.ok) throw new Error("Context assembly failed");
      setResult(await response.json());
    } catch {
      setError("Context preview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  const section = (
    title: string,
    items: { content: string; provenance: string }[],
  ) => (
    <div className="panel">
      <h4>{title}</h4>
      {items.length === 0 ? (
        <p className="muted">None selected.</p>
      ) : (
        items.map((item, index) => (
          <p key={`${title}-${index}`}>
            <b>{item.content}</b>
            <br />
            <small className="muted">{item.provenance}</small>
          </p>
        ))
      )}
    </div>
  );

  return (
    <section className="context-preview">
      <div className="row">
        <h2>Context preview</h2>
        {result && (
          <small className="muted">
            {result.used_budget}/{result.budget} characters
          </small>
        )}
      </div>
      <div className="row">
        <input
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="Task to assemble context for..."
        />
        <button onClick={assemble} disabled={loading || !task.trim()}>
          {loading ? "Assembling..." : "Preview context"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="context-grid">
          <p>
            <b>Task:</b> {result.task}
          </p>
          {section("Project memory", result.project_memory)}
          {section("Answers", result.user_answers)}
          {section("Requirements", result.requirements)}
          {section("Constraints", result.constraints)}
          <div className="panel">
            <h4>Documents</h4>
            {result.document_context.length === 0 ? (
              <p className="muted">None selected.</p>
            ) : (
              result.document_context.map((item, index) => (
                <p key={index}>
                  <b>{item.metadata.document_name || "Document"}</b> ·{" "}
                  {item.content}
                  <br />
                  <small className="muted">
                    {item.provenance} · relevance {item.score.toFixed(2)}
                  </small>
                </p>
              ))
            )}
          </div>
          {result.omitted_items.length > 0 && (
            <div className="panel">
              <h4>Omitted</h4>
              {result.omitted_items.map((item) => (
                <p key={item.identifier} className="muted">
                  {item.source_type} · {item.reason}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
