"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  AgentTask,
  ProjectPlan,
  ProviderConnection,
  ProviderName,
  ProjectRepository,
  addProviderConnection,
  connectProjectRepository,
  createPlan,
  getPlans,
  getProjectRepository,
  getProviderConnections,
  publishAgentTask,
  runAgentTask,
  saveAgentDraft,
  testProviderConnection,
  updateAgentTask,
} from "../../../../lib/orchestration";
import { parseGitHubRepository } from "../../../../lib/github-repository";

const providerDefaults: Record<ProviderName, string> = {
  openrouter: "openrouter/free",
  openai: "gpt-5-mini",
  anthropic: "claude-sonnet-4-5",
  gemini: "gemini-2.5-flash",
};

const providerLabels: Record<ProviderName, string> = {
  openrouter: "OpenRouter",
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
};

function message(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong";
}

export function AgentWorkspace({
  projectId,
  projectName,
  projectDescription,
  canWrite,
  canManageRepository,
}: {
  projectId: string;
  projectName: string;
  projectDescription: string;
  canWrite: boolean;
  canManageRepository: boolean;
}) {
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [repository, setRepository] = useState<ProjectRepository | null>(null);
  const [repoName, setRepoName] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [plans, setPlans] = useState<ProjectPlan[]>([]);
  const [provider, setProvider] = useState<ProviderName>("openrouter");
  const [label, setLabel] = useState("My OpenRouter");
  const [model, setModel] = useState(providerDefaults.openrouter);
  const [apiKey, setApiKey] = useState("");
  const [title, setTitle] = useState(`${projectName} delivery plan`);
  const [idea, setIdea] = useState(projectDescription);
  const [startAt, setStartAt] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    const [savedConnections, savedPlans, savedRepository] = await Promise.all([
      getProviderConnections(),
      getPlans(projectId),
      getProjectRepository(projectId),
    ]);
    setConnections(savedConnections);
    setPlans(savedPlans);
    setRepository(savedRepository);
  }, [projectId]);

  useEffect(() => {
    refresh().catch((loadError) => setError(message(loadError)));
  }, [refresh]);

  useEffect(() => {
    const key = `promptpilot:delivery-idea:${projectId}`;
    const transferred = sessionStorage.getItem(key);
    if (transferred) {
      setIdea(transferred.slice(0, 20000));
      sessionStorage.removeItem(key);
      setNotice(
        "Improved prompt loaded. Review the idea before creating your plan.",
      );
    }
  }, [projectId]);

  const activePlan = plans[0] || null;
  const taskCount = useMemo(
    () =>
      activePlan?.milestones.reduce(
        (count, item) => count + item.tasks.length,
        0,
      ) || 0,
    [activePlan],
  );

  async function act(key: string, action: () => Promise<void>) {
    if (busy) return;
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (actionError) {
      setError(message(actionError));
    } finally {
      setBusy("");
    }
  }

  function changeProvider(value: ProviderName) {
    setProvider(value);
    setModel(providerDefaults[value]);
    setLabel(`My ${providerLabels[value]}`);
  }

  function saveConnection(event: FormEvent) {
    event.preventDefault();
    void act("add-provider", async () => {
      await addProviderConnection({
        provider,
        label,
        api_key: apiKey,
        default_model: model,
      });
      setApiKey("");
      setNotice("Connection saved. Test it before running a task.");
      await refresh();
    });
  }

  function generatePlan(event: FormEvent) {
    event.preventDefault();
    void act("create-plan", async () => {
      await createPlan(projectId, {
        title,
        idea,
        start_at: startAt ? new Date(startAt).toISOString() : null,
      });
      setNotice(
        "Delivery plan created and roles routed to your active providers.",
      );
      await refresh();
    });
  }

  function saveRepository(event: FormEvent) {
    event.preventDefault();
    let destination;
    try {
      destination = parseGitHubRepository(repoName);
    } catch (parseError) {
      setError(message(parseError));
      return;
    }
    void act("github", async () => {
      await connectProjectRepository(projectId, {
        ...destination,
        token: githubToken,
      });
      setGithubToken("");
      setNotice(
        "GitHub repository connected. Review code output before publishing a draft PR.",
      );
      await refresh();
    });
  }

  async function assignTask(task: AgentTask, connectionId: string) {
    await act(`assign-${task.id}`, async () => {
      await updateAgentTask(task.id, {
        assigned_connection_id: connectionId || null,
      });
      await refresh();
    });
  }

  function readyTasks(): AgentTask[] {
    const tasks = activePlan?.milestones.flatMap((item) => item.tasks) || [];
    const byId = new Map(tasks.map((task) => [task.id, task]));
    return tasks.filter(
      (task) =>
        task.assigned_connection_id &&
        ["backlog", "scheduled", "ready", "failed"].includes(task.status) &&
        task.dependencies.every((id) =>
          ["review", "completed"].includes(byId.get(id)?.status || ""),
        ),
    );
  }

  function runReadyTasks() {
    const candidates = readyTasks();
    if (candidates.length === 0) {
      setNotice(
        "No tasks are ready yet. Connect models or finish prerequisite tasks.",
      );
      return;
    }
    void act("run-ready", async () => {
      const results = await Promise.allSettled(
        candidates.map((task) => runAgentTask(task.id)),
      );
      const succeeded = results.filter(
        (result) => result.status === "fulfilled",
      ).length;
      await refresh();
      setNotice(
        `${succeeded} of ${candidates.length} ready tasks completed. Review their outputs before publishing.`,
      );
      if (succeeded < candidates.length) {
        setError(
          "Some model runs failed. Check each task and retry after fixing its provider or model.",
        );
      }
    });
  }

  return (
    <main className="agent-page">
      <header className="agent-topbar">
        <div>
          <a href={`/projects/${projectId}`}>← Back to PromptPilot</a>
          <h1>AI delivery team</h1>
          <p>
            {projectName} · Plan work, assign specialists, and review every
            model output.
          </p>
        </div>
        <div className="agent-stat">
          <strong>
            {connections.filter((item) => item.status === "active").length}
          </strong>
          <span>connected models</span>
        </div>
        <div className="agent-stat">
          <strong>{taskCount}</strong>
          <span>planned tasks</span>
        </div>
      </header>

      <section className="agent-safety-note">
        <strong>Human-controlled execution</strong>
        <span>
          Keys stay encrypted on the backend. Models run only when you click Run
          now. Code outputs can be published to a GitHub draft PR after you
          review them. Scheduled times are reminders only. Nothing merges or
          deploys automatically.
        </span>
      </section>

      {error && (
        <p className="agent-alert error" role="alert">
          {error}
        </p>
      )}
      {notice && <p className="agent-alert success">{notice}</p>}

      <div className="agent-layout">
        <aside className="agent-settings">
          <section className="agent-card">
            <small>GITHUB REPOSITORY</small>
            <h2>Review code as pull requests</h2>
            {repository && (
              <p>
                Connected:{" "}
                <a href={repository.url} target="_blank" rel="noreferrer">
                  {repository.owner}/{repository.repo}
                </a>
              </p>
            )}
            {canManageRepository && (
              <form className="agent-form" onSubmit={saveRepository}>
                <label>
                  GitHub repository URL or owner/repo
                  <input
                    value={repoName}
                    onChange={(event) => setRepoName(event.target.value)}
                    placeholder="https://github.com/uzair592/promptpilot"
                    required
                  />
                </label>
                <p className="muted">
                  Open the specific repository on GitHub and copy its address. A
                  profile URL alone has no repository name.
                </p>
                <label>
                  GitHub fine-grained token (Contents and Pull requests write
                  access)
                  <input
                    type="password"
                    autoComplete="off"
                    value={githubToken}
                    onChange={(event) => setGithubToken(event.target.value)}
                    required
                  />
                </label>
                <button disabled={Boolean(busy)}>Connect repository</button>
              </form>
            )}
          </section>
          <section className="agent-card">
            <div className="agent-section-heading">
              <div>
                <small>MODEL VAULT</small>
                <h2>Connect providers</h2>
              </div>
            </div>
            <p className="muted">
              Add as many providers and models as you need. Each connection has
              its own model and key; you can add another below. PromptPilot
              never shows a saved key again.
            </p>
            <p className="muted">
              To use two models from one provider, save two connections with
              different names. You can reuse your provider key.
            </p>
            <form className="agent-form" onSubmit={saveConnection}>
              <label>
                Provider
                <select
                  value={provider}
                  onChange={(event) =>
                    changeProvider(event.target.value as ProviderName)
                  }
                >
                  <option value="openrouter">OpenRouter</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="gemini">Google Gemini</option>
                </select>
              </label>
              <label>
                Connection name
                <input
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  required
                />
              </label>
              <label>
                Default model
                <input
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  required
                />
              </label>
              <label>
                API key
                <input
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  required
                />
              </label>
              <button disabled={!canWrite || Boolean(busy)}>
                Add provider or model
              </button>
            </form>
            <div className="connection-list">
              {connections.map((connection) => (
                <div className="connection-row" key={connection.id}>
                  <div>
                    <span
                      className={`provider-icon provider-${connection.provider}`}
                    >
                      {connection.provider.slice(0, 1).toUpperCase()}
                    </span>
                    <div>
                      <strong>{connection.label}</strong>
                      <small>
                        {connection.default_model} · {connection.masked_key}
                      </small>
                    </div>
                  </div>
                  <button
                    className="secondary"
                    disabled={Boolean(busy) || connection.status === "disabled"}
                    onClick={() =>
                      void act(`test-${connection.id}`, async () => {
                        const result = await testProviderConnection(
                          connection.id,
                        );
                        setNotice(
                          `${connection.label}: ${result.available_models.length} models available.`,
                        );
                        await refresh();
                      })
                    }
                  >
                    {busy === `test-${connection.id}`
                      ? "Testing…"
                      : connection.last_test_status === "passed"
                        ? "✓ Connected"
                        : "Test"}
                  </button>
                </div>
              ))}
              {connections.length === 0 && (
                <p className="empty-copy">
                  No provider connected yet. OpenRouter is enough to begin.
                </p>
              )}
            </div>
          </section>

          <section className="agent-card">
            <small>NEW DELIVERY PLAN</small>
            <h2>Turn an idea into phases</h2>
            <form className="agent-form" onSubmit={generatePlan}>
              <label>
                Plan title
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  required
                />
              </label>
              <label>
                Product idea
                <textarea
                  rows={7}
                  value={idea}
                  onChange={(event) => setIdea(event.target.value)}
                  placeholder="Describe users, the problem, essential features, constraints, and what done means…"
                  required
                />
              </label>
              <label>
                Optional start time
                <input
                  type="datetime-local"
                  value={startAt}
                  onChange={(event) => setStartAt(event.target.value)}
                />
              </label>
              <button
                disabled={!canWrite || Boolean(busy) || idea.trim().length < 10}
              >
                {busy === "create-plan"
                  ? "Creating team plan…"
                  : "Create milestones and tasks"}
              </button>
            </form>
          </section>
        </aside>

        <section className="agent-board">
          {!activePlan ? (
            <div className="agent-empty">
              <span>✦</span>
              <h2>Your AI team is ready to be planned</h2>
              <p>
                Connect at least one provider, describe the product, and
                PromptPilot will create an ordered delivery plan with
                independent implementation and testing roles.
              </p>
            </div>
          ) : (
            <>
              <div className="plan-heading">
                <div>
                  <small>ACTIVE PLAN</small>
                  <h2>{activePlan.title}</h2>
                  <p>{activePlan.summary}</p>
                </div>
                <span>{activePlan.status}</span>
                {canWrite && (
                  <button
                    type="button"
                    disabled={Boolean(busy) || readyTasks().length === 0}
                    onClick={runReadyTasks}
                  >
                    {busy === "run-ready"
                      ? "Running team…"
                      : `Run ready tasks (${readyTasks().length})`}
                  </button>
                )}
              </div>
              <div className="milestone-list">
                {activePlan.milestones.map((milestone) => (
                  <article className="milestone" key={milestone.id}>
                    <div className="milestone-heading">
                      <span>{milestone.position}</span>
                      <div>
                        <h3>{milestone.title}</h3>
                        <p>{milestone.description}</p>
                      </div>
                      {milestone.due_at && (
                        <time>
                          {new Date(milestone.due_at).toLocaleDateString()}
                        </time>
                      )}
                    </div>
                    <div className="task-list">
                      {milestone.tasks.map((task) => (
                        <div className="agent-task" key={task.id}>
                          <div className="task-main">
                            <div className="task-labels">
                              <span className={`role-pill role-${task.role}`}>
                                {task.role}
                              </span>
                              <span
                                className={`status-pill status-${task.status}`}
                              >
                                {task.status}
                              </span>
                            </div>
                            <h4>{task.title}</h4>
                            <p>{task.description}</p>
                            <small>{task.assignment_reason}</small>
                            {task.last_error && (
                              <p className="task-error">{task.last_error}</p>
                            )}
                            {task.output_text && (
                              <details>
                                <summary>Review model output</summary>
                                <pre>{task.output_text}</pre>
                                {canManageRepository &&
                                  ["frontend", "backend", "api"].includes(
                                    task.role,
                                  ) &&
                                  task.status === "review" &&
                                  !task.pull_request_url && (
                                    <div className="agent-form">
                                      <label>
                                        Editable JSON draft
                                        <textarea
                                          rows={8}
                                          value={
                                            drafts[task.id] ?? task.output_text
                                          }
                                          onChange={(event) =>
                                            setDrafts((current) => ({
                                              ...current,
                                              [task.id]: event.target.value,
                                            }))
                                          }
                                        />
                                      </label>
                                      <button
                                        type="button"
                                        className="secondary"
                                        disabled={Boolean(busy)}
                                        onClick={() =>
                                          void act(
                                            `draft-${task.id}`,
                                            async () => {
                                              await saveAgentDraft(
                                                task.id,
                                                drafts[task.id] ??
                                                  task.output_text!,
                                              );
                                              setNotice(
                                                "Draft saved. Review it before publishing.",
                                              );
                                              await refresh();
                                            },
                                          )
                                        }
                                      >
                                        Save reviewed draft
                                      </button>
                                    </div>
                                  )}
                              </details>
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
                          </div>
                          <div className="task-actions">
                            <select
                              aria-label={`Provider for ${task.title}`}
                              value={task.assigned_connection_id || ""}
                              onChange={(event) =>
                                void assignTask(task, event.target.value)
                              }
                              disabled={!canWrite || Boolean(busy)}
                            >
                              <option value="">Unassigned</option>
                              {connections
                                .filter((item) => item.status === "active")
                                .map((connection) => (
                                  <option
                                    value={connection.id}
                                    key={connection.id}
                                  >
                                    {connection.provider} ·{" "}
                                    {connection.default_model}
                                  </option>
                                ))}
                            </select>
                            <button
                              disabled={
                                !canWrite ||
                                Boolean(busy) ||
                                !task.assigned_connection_id ||
                                task.status === "completed"
                              }
                              onClick={() =>
                                void act(`run-${task.id}`, async () => {
                                  await runAgentTask(task.id);
                                  setNotice(
                                    `${task.title} completed and is ready for review.`,
                                  );
                                  await refresh();
                                })
                              }
                            >
                              {busy === `run-${task.id}`
                                ? "Running…"
                                : "Run now"}
                            </button>
                            {canManageRepository &&
                              repository &&
                              task.status === "review" &&
                              ["frontend", "backend", "api"].includes(
                                task.role,
                              ) &&
                              !task.pull_request_url && (
                                <button
                                  className="secondary"
                                  disabled={Boolean(busy)}
                                  onClick={() =>
                                    void act(`publish-${task.id}`, async () => {
                                      const result = await publishAgentTask(
                                        task.id,
                                      );
                                      setNotice(
                                        `Draft pull request created: ${result.pull_request_url}`,
                                      );
                                      await refresh();
                                    })
                                  }
                                >
                                  Publish reviewed code to GitHub
                                </button>
                              )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
