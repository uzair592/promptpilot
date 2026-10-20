"use client";

import { FormEvent, useState } from "react";
import { ModelPicker } from "../../../../components/ModelPicker";
import { AgentTask, ProviderConnection } from "../../../../lib/orchestration";
import { roleNames } from "./WorkflowCanvas";

export function TeamAssignments({
  tasks,
  connections,
  disabled,
  onSave,
  onAssignUnassigned,
  onConnect,
  onInspect,
}: {
  tasks: AgentTask[];
  connections: ProviderConnection[];
  disabled: boolean;
  onSave: (
    task: AgentTask,
    connectionId: string,
    model: string,
  ) => Promise<void>;
  onAssignUnassigned: (connectionId: string, model: string) => Promise<void>;
  onConnect: () => void;
  onInspect: (id: string) => void;
}) {
  const active = connections.filter((item) => item.status === "active");
  const [bulkConnection, setBulkConnection] = useState("");
  const [bulkModel, setBulkModel] = useState("");
  const chosen = active.find((item) => item.id === bulkConnection);
  const unassigned = tasks.filter(
    (task) =>
      !active.some((item) => item.id === task.assigned_connection_id) &&
      !["running", "completed", "cancelled"].includes(task.status),
  );
  return (
    <section className="team-assignments">
      <div className="studio-section-heading">
        <div>
          <small>YOUR MODELS. YOUR TEAM.</small>
          <h2>Give every agent the right model</h2>
          <p>
            Choose a connected API key and model for each task. One key can
            power several different models.
          </p>
        </div>
        <button className="workflow-secondary" onClick={onConnect}>
          ＋ Add provider / API key
        </button>
      </div>
      {!active.length ? (
        <div className="team-connect-required">
          <span>◈</span>
          <div>
            <h3>Connect an AI provider to run your team</h3>
            <p>
              Add your API key, load its models, then come back here to assign
              them.
            </p>
          </div>
          <button className="workflow-primary" onClick={onConnect}>
            Connect your first model
          </button>
        </div>
      ) : (
        <form
          className="team-quick-assign workflow-form"
          onSubmit={(event) => {
            event.preventDefault();
            void onAssignUnassigned(bulkConnection, bulkModel);
          }}
        >
          <div>
            <strong>Quick start</strong>
            <p>
              Use one model for {unassigned.length} unassigned tasks. You can
              change individual agents below.
            </p>
          </div>
          <label>
            Provider connection
            <select
              value={bulkConnection}
              onChange={(event) => {
                setBulkConnection(event.target.value);
                setBulkModel(
                  active.find((item) => item.id === event.target.value)
                    ?.default_model || "",
                );
              }}
              disabled={disabled}
              required
            >
              <option value="">Choose a connected provider</option>
              {active.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <ModelPicker
            key={bulkConnection}
            label="Quick start model"
            models={chosen?.available_models || []}
            value={bulkModel}
            onChange={setBulkModel}
            disabled={disabled || !chosen}
          />
          <button
            className="workflow-primary"
            disabled={
              disabled || !chosen || !bulkModel.trim() || !unassigned.length
            }
          >
            Assign unassigned tasks
          </button>
        </form>
      )}
      <div className="team-assignment-grid">
        {tasks.map((task) => (
          <AssignmentCard
            key={`${task.id}:${task.assigned_connection_id}:${task.assigned_model}`}
            task={task}
            connections={active}
            disabled={disabled || task.status === "running"}
            onSave={onSave}
            onInspect={() => onInspect(task.id)}
          />
        ))}
      </div>
    </section>
  );
}

function AssignmentCard({
  task,
  connections,
  disabled,
  onSave,
  onInspect,
}: {
  task: AgentTask;
  connections: ProviderConnection[];
  disabled: boolean;
  onSave: (
    task: AgentTask,
    connectionId: string,
    model: string,
  ) => Promise<void>;
  onInspect: () => void;
}) {
  const [connectionId, setConnectionId] = useState(
    task.assigned_connection_id || "",
  );
  const [model, setModel] = useState(task.assigned_model || "");
  const selected = connections.find((item) => item.id === connectionId);
  const assigned = connections.some(
    (item) => item.id === task.assigned_connection_id,
  );
  function save(event: FormEvent) {
    event.preventDefault();
    void onSave(task, connectionId, model);
  }
  return (
    <article
      className={`team-assignment-card role-card-${task.role}`}
      aria-label={`Model assignment for ${task.title}`}
    >
      <header>
        <span className={`team-role-icon role-icon-${task.role}`}>
          {roleNames[task.role].slice(0, 2).toUpperCase()}
        </span>
        <div>
          <small>{roleNames[task.role]}</small>
          <h3>{task.title}</h3>
        </div>
        <span className={`assignment-badge ${assigned ? "assigned" : ""}`}>
          {assigned ? "Assigned" : "Needs model"}
        </span>
      </header>
      <form className="workflow-form" onSubmit={save}>
        <label>
          Provider connection
          <select
            value={connectionId}
            onChange={(event) => {
              setConnectionId(event.target.value);
              setModel(
                connections.find((item) => item.id === event.target.value)
                  ?.default_model || "",
              );
            }}
            disabled={disabled || !connections.length}
            required
          >
            <option value="">Choose a connected provider</option>
            {connections.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label} · {item.provider}
              </option>
            ))}
          </select>
        </label>
        <ModelPicker
          key={connectionId}
          label="Agent model"
          models={selected?.available_models || []}
          value={model}
          onChange={setModel}
          disabled={disabled || !selected}
        />
        <footer>
          <button
            type="button"
            className="workflow-text-button"
            onClick={onInspect}
          >
            Task details ↗
          </button>
          <button
            className="workflow-secondary"
            disabled={disabled || !selected || !model.trim()}
          >
            {assigned ? "Save assignment" : "Assign model"}
          </button>
        </footer>
      </form>
    </article>
  );
}
