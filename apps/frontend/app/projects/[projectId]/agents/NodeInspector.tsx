"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ModelPicker } from "../../../../components/ModelPicker";
import {
  AgentTask,
  ProviderConnection,
  AgentRun,
  getAgentRuns,
  updateAgentTask,
} from "../../../../lib/orchestration";
import { roleNames } from "./WorkflowCanvas";

type Patch = Parameters<typeof updateAgentTask>[1];

export function NodeInspector({
  task,
  tasks,
  connections,
  busy,
  canWrite,
  canPublish,
  hasRepository,
  onClose,
  onSave,
  onRun,
  onSaveAndRun,
  onConnect,
  onDelete,
  onPublish,
  onSaveDraft,
  initialTab = "configure",
}: {
  task: AgentTask;
  tasks: AgentTask[];
  connections: ProviderConnection[];
  busy: boolean;
  canWrite: boolean;
  canPublish: boolean;
  hasRepository: boolean;
  onClose: () => void;
  onSave: (patch: Patch) => Promise<void>;
  onRun: () => void;
  onSaveAndRun: (patch: Patch) => Promise<void>;
  onConnect: () => void;
  onDelete: () => void;
  onPublish: () => void;
  onSaveDraft: (text: string) => void;
  initialTab?: "configure" | "output" | "runs";
}) {
  const [tab, setTab] = useState<"configure" | "output" | "runs">(initialTab);
  const [title, setTitle] = useState(task.title),
    [description, setDescription] = useState(task.description);
  const [connection, setConnection] = useState(
      task.assigned_connection_id || "",
    ),
    [model, setModel] = useState(task.assigned_model || "");
  const [dependencies, setDependencies] = useState(task.dependencies),
    [criteria, setCriteria] = useState(task.acceptance_criteria.join("\n"));
  const [notes, setNotes] = useState(task.review_notes || ""),
    [draft, setDraft] = useState(task.output_text || "");
  const [runs, setRuns] = useState<AgentRun[]>([]),
    [runError, setRunError] = useState("");
  const synchronizedVersion = useRef("");
  useEffect(() => {
    if (synchronizedVersion.current === task.updated_at) return;
    synchronizedVersion.current = task.updated_at;
    setTitle(task.title);
    setDescription(task.description);
    setConnection(task.assigned_connection_id || "");
    setModel(task.assigned_model || "");
    setDependencies(task.dependencies);
    setCriteria(task.acceptance_criteria.join("\n"));
    setNotes(task.review_notes || "");
    setDraft(task.output_text || "");
  }, [task.updated_at, task]);
  useEffect(() => {
    let active = true;
    getAgentRuns(task.id)
      .then((items) => {
        if (active) {
          setRuns(items);
          setRunError("");
        }
      })
      .catch(() => {
        if (active)
          setRunError(
            "Could not load execution history. Reopen this node to retry.",
          );
      });
    return () => {
      active = false;
    };
  }, [task.id, task.status, task.attempt_count]);
  const selectedConnection = connections.find((item) => item.id === connection);
  const blockers = dependencies
    .map((id) => tasks.find((item) => item.id === id))
    .filter((item) => !item || !["review", "completed"].includes(item.status));
  const editable = canWrite && !busy && task.status !== "running";
  const patch: Patch = {
    title,
    description,
    assigned_connection_id: connection || null,
    assigned_model: model || null,
    dependencies,
    acceptance_criteria: criteria
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean),
  };
  const unsaved =
    title !== task.title ||
    description !== task.description ||
    connection !== (task.assigned_connection_id || "") ||
    model !== (task.assigned_model || "") ||
    criteria !== task.acceptance_criteria.join("\n") ||
    JSON.stringify(dependencies) !== JSON.stringify(task.dependencies);
  async function save(event: FormEvent) {
    event.preventDefault();
    await onSave(patch);
  }
  return (
    <aside className="node-inspector" aria-label="Node inspector">
      <header>
        <div>
          <small>{roleNames[task.role]}</small>
          <h2>{task.title}</h2>
        </div>
        <button aria-label="Close node inspector" onClick={onClose}>
          ×
        </button>
      </header>
      <nav className="inspector-tabs" aria-label="Node details">
        <button
          className={tab === "configure" ? "selected" : ""}
          onClick={() => setTab("configure")}
        >
          Configure
        </button>
        <button
          className={tab === "output" ? "selected" : ""}
          onClick={() => setTab("output")}
        >
          Output
        </button>
        <button
          className={tab === "runs" ? "selected" : ""}
          onClick={() => setTab("runs")}
        >
          Runs {runs.length > 0 && <span>{runs.length}</span>}
        </button>
      </nav>
      <div className="inspector-content">
        {task.last_error && (
          <div className="workflow-alert error" role="alert">
            {task.last_error}
          </div>
        )}
        {tab === "configure" && (
          <form className="workflow-form" onSubmit={save}>
            <label>
              Task name
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={200}
                required
                disabled={!editable}
              />
            </label>
            <label>
              Instructions
              <textarea
                rows={5}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                required
                disabled={!editable}
              />
            </label>
            <div className="inspector-section-label">MODEL ASSIGNMENT</div>
            <button
              type="button"
              className="inspector-connect-link"
              onClick={onConnect}
            >
              ＋ Add a provider / API key
            </button>
            {!connections.some((item) => item.status === "active") && (
              <p className="plan-connect-tip">
                Connect an API key first, then choose its model here. Your
                changes stay in this inspector while you connect.
              </p>
            )}
            <label>
              Provider connection
              <select
                value={connection}
                onChange={(event) => {
                  setConnection(event.target.value);
                  setModel(
                    connections.find((item) => item.id === event.target.value)
                      ?.default_model || "",
                  );
                }}
                disabled={!editable}
              >
                <option value="">Choose a connection</option>
                {connections
                  .filter((item) => item.status === "active")
                  .map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.label} · {item.provider}
                    </option>
                  ))}
              </select>
            </label>
            <ModelPicker
              key={connection}
              label="Model"
              models={selectedConnection?.available_models || []}
              value={model}
              onChange={setModel}
              disabled={!editable || !connection}
            />
            <p className="field-note">
              Different nodes can use different models with the same provider
              key.
            </p>
            <label>
              Acceptance criteria
              <textarea
                rows={3}
                value={criteria}
                onChange={(event) => setCriteria(event.target.value)}
                placeholder="One criterion per line"
                disabled={!editable}
              />
            </label>
            <fieldset className="dependency-picker" disabled={!editable}>
              <legend>Wait for these nodes</legend>
              {tasks
                .filter((item) => item.id !== task.id)
                .map((item) => (
                  <label key={item.id}>
                    <input
                      type="checkbox"
                      checked={dependencies.includes(item.id)}
                      onChange={(event) =>
                        setDependencies((current) =>
                          event.target.checked
                            ? [...current, item.id]
                            : current.filter((id) => id !== item.id),
                        )
                      }
                    />
                    <span>{item.title}</span>
                  </label>
                ))}
            </fieldset>
            <button className="workflow-primary" disabled={!editable}>
              Save node
            </button>
            <button
              className="workflow-text-danger"
              type="button"
              disabled={!editable}
              onClick={onDelete}
            >
              Remove node
            </button>
          </form>
        )}
        {tab === "output" && (
          <div className="inspector-output">
            {!task.output_text ? (
              <div className="inspector-empty">
                <strong>No output yet</strong>
                <p>
                  Assign a model, finish prerequisite nodes, then run this task.
                </p>
              </div>
            ) : (
              <>
                <div className="output-label">
                  Model output · {task.assigned_model}
                </div>
                <pre>{task.output_text}</pre>
                {canPublish &&
                  ["frontend", "backend", "api"].includes(task.role) &&
                  !task.pull_request_url && (
                    <details>
                      <summary>Edit code draft</summary>
                      <textarea
                        aria-label="Editable JSON draft"
                        rows={10}
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                      />
                      <button
                        disabled={busy}
                        onClick={() => onSaveDraft(draft)}
                      >
                        Save reviewed draft
                      </button>
                    </details>
                  )}
                <label className="workflow-form">
                  Review notes
                  <textarea
                    aria-label="Review notes"
                    rows={3}
                    value={notes}
                    onChange={(event) => setNotes(event.target.value)}
                    placeholder="What passed review? What needs changes?"
                    disabled={!canWrite || busy}
                  />
                </label>
                {task.status === "review" && canWrite && (
                  <div className="review-actions">
                    <button
                      className="workflow-primary"
                      disabled={busy}
                      onClick={() =>
                        void onSave({
                          status: "completed",
                          review_notes: notes,
                        })
                      }
                    >
                      Approve output
                    </button>
                    <button
                      className="workflow-secondary"
                      disabled={busy}
                      onClick={() =>
                        void onSave({ status: "ready", review_notes: notes })
                      }
                    >
                      Request changes
                    </button>
                  </div>
                )}
                {hasRepository &&
                  canPublish &&
                  ["frontend", "backend", "api"].includes(task.role) &&
                  ["review", "completed"].includes(task.status) &&
                  !task.pull_request_url && (
                    <button
                      className="workflow-secondary"
                      disabled={busy}
                      onClick={onPublish}
                    >
                      Publish reviewed code to GitHub
                    </button>
                  )}
                {task.pull_request_url && (
                  <a
                    href={task.pull_request_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open draft pull request ↗
                  </a>
                )}
              </>
            )}
          </div>
        )}
        {tab === "runs" && (
          <div className="execution-history">
            {runError && <p role="alert">{runError}</p>}
            {!runs.length && !runError && (
              <div className="inspector-empty">
                <strong>No executions yet</strong>
                <p>Each model attempt will appear here with its result.</p>
              </div>
            )}
            {runs.map((run) => (
              <details key={run.id}>
                <summary>
                  <span className={`run-dot run-${run.status}`} />
                  <strong>{run.status}</strong>
                  <time>{new Date(run.started_at).toLocaleString()}</time>
                </summary>
                <small>
                  {run.provider} · {run.model}
                </small>
                {run.error_message && (
                  <p className="task-error">{run.error_message}</p>
                )}
                {run.output_text && <pre>{run.output_text}</pre>}
              </details>
            ))}
          </div>
        )}
      </div>
      <footer>
        <small>
          {blockers.length
            ? `Waiting for ${blockers.length} prerequisite node${blockers.length === 1 ? "" : "s"}`
            : model
              ? unsaved
                ? "Your changes will be saved before running"
                : "Ready when you are"
              : "Assign a connected model first"}
        </small>
        <button
          className="workflow-primary"
          disabled={
            busy ||
            !canWrite ||
            !selectedConnection ||
            selectedConnection.status !== "active" ||
            !model.trim() ||
            blockers.length > 0 ||
            ["running", "completed", "cancelled"].includes(task.status)
          }
          onClick={() => (unsaved ? void onSaveAndRun(patch) : onRun())}
        >
          {task.status === "running"
            ? "Running…"
            : task.status === "failed"
              ? "Retry node"
              : unsaved
                ? "Save and run"
                : "Run node"}
        </button>
      </footer>
    </aside>
  );
}
