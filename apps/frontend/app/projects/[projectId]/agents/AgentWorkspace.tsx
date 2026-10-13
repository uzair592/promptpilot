"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AgentTask,
  ProjectPlan,
  ProviderConnection,
  ProviderDefinition,
  ProjectRepository,
  addAgentTask,
  connectProjectRepository,
  createPlan,
  deleteAgentTask,
  getPlans,
  getProjectRepository,
  getProviderCatalog,
  getProviderConnections,
  publishAgentTask,
  runAgentTask,
  saveAgentDraft,
  updateAgentTask,
} from "../../../../lib/orchestration";
import { parseGitHubRepository } from "../../../../lib/github-repository";
import { readyWorkflowTasks } from "../../../../lib/workflow-layout";
import { WorkflowCanvas, roleNames } from "./WorkflowCanvas";
import { NodeInspector } from "./NodeInspector";
import { ConnectionVault } from "./ConnectionVault";
import { WorkspaceModal as Modal } from "./WorkspaceModal";

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
  const [connections, setConnections] = useState<ProviderConnection[]>([]),
    [catalog, setCatalog] = useState<ProviderDefinition[]>([]);
  const [plans, setPlans] = useState<ProjectPlan[]>([]),
    [repository, setRepository] = useState<ProjectRepository | null>(null);
  const [planId, setPlanId] = useState(""),
    [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"editor" | "executions">("editor"),
    [inspectorTab, setInspectorTab] = useState<"configure" | "output" | "runs">(
      "configure",
    );
  const [dialog, setDialog] = useState<
    "vault" | "repository" | "plan" | "node" | null
  >(null);
  const [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [layoutVersion, setLayoutVersion] = useState(0),
    [sidebarOpen, setSidebarOpen] = useState(false);
  const [title, setTitle] = useState(`${projectName} delivery plan`),
    [idea, setIdea] = useState(projectDescription),
    [planner, setPlanner] = useState(""),
    [startAt, setStartAt] = useState("");
  const [repoName, setRepoName] = useState(""),
    [token, setToken] = useState("");
  const [nodeTitle, setNodeTitle] = useState(""),
    [nodeDescription, setNodeDescription] = useState(""),
    [nodeRole, setNodeRole] = useState<AgentTask["role"]>("researcher");
  const operation = useRef(false);
  const transferPending = useRef(false);
  const closeDialog = useCallback(() => setDialog(null), []);
  const refresh = useCallback(async () => {
    const [savedConnections, savedPlans, savedRepository, providerCatalog] =
      await Promise.all([
        getProviderConnections(),
        getPlans(projectId),
        getProjectRepository(projectId),
        getProviderCatalog(),
      ]);
    setConnections(savedConnections);
    setPlans(savedPlans);
    setRepository(savedRepository);
    setCatalog(providerCatalog);
    if (transferPending.current) {
      setPlanner(
        savedConnections.find((item) => item.status === "active")?.id || "",
      );
      transferPending.current = false;
    }
  }, [projectId]);
  useEffect(() => {
    let active = true;
    refresh()
      .catch((caught) => {
        if (active)
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not load workflows",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [refresh]);
  useEffect(() => {
    const key = `promptpilot:delivery-idea:${projectId}`;
    const transferred = sessionStorage.getItem(key);
    if (transferred) {
      transferPending.current = true;
      setIdea(transferred.slice(0, 20000));
      sessionStorage.removeItem(key);
      setDialog("plan");
      setNotice(
        "Your improved prompt is loaded. Create its workflow, then assign models to the nodes.",
      );
    }
  }, [projectId]);
  const activePlan =
    plans.find((item) => item.id === planId) || plans[0] || null;
  const tasks = useMemo(
    () => activePlan?.milestones.flatMap((item) => item.tasks) || [],
    [activePlan],
  );
  const selected = tasks.find((task) => task.id === selectedId) || null;
  const activeConnections = connections.filter(
    (item) => item.status === "active",
  );
  const ready = readyWorkflowTasks(
    tasks,
    activeConnections.map((item) => item.id),
  );
  const running = tasks.some((task) => task.status === "running");
  useEffect(() => {
    if (!running && !busy.startsWith("run")) return;
    const interval = window.setInterval(
      () => void refresh().catch(() => undefined),
      3000,
    );
    return () => window.clearInterval(interval);
  }, [running, busy, refresh]);
  async function act(key: string, action: () => Promise<void>) {
    if (operation.current) return;
    operation.current = true;
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "The operation failed",
      );
    } finally {
      await refresh().catch(() => undefined);
      operation.current = false;
      setBusy("");
    }
  }
  function select(id: string, tab: typeof inspectorTab = "configure") {
    setSelectedId(id);
    setInspectorTab(tab);
  }
  function newPlan() {
    setTitle(`${projectName} delivery plan`);
    setPlanner(activeConnections[0]?.id || "");
    setDialog("plan");
    setSidebarOpen(false);
  }
  function submitPlan(event: FormEvent) {
    event.preventDefault();
    void act("create-plan", async () => {
      const saved = await createPlan(projectId, {
        title,
        idea,
        start_at: startAt ? new Date(startAt).toISOString() : null,
        ...(planner ? { planner_connection_id: planner } : {}),
      });
      setPlanId(saved.id);
      setSelectedId(null);
      setDialog(null);
      setView("editor");
      setNotice(
        saved.planning_mode === "ai"
          ? "Workflow generated from your idea. Select a node to review its task and model."
          : "Editable workflow created. Connect models and tailor the nodes to your project.",
      );
    });
  }
  function submitRepository(event: FormEvent) {
    event.preventDefault();
    let destination;
    try {
      destination = parseGitHubRepository(repoName);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invalid repository");
      return;
    }
    void act("repository", async () => {
      await connectProjectRepository(projectId, {
        ...destination,
        token: token.trim(),
      });
      setToken("");
      setDialog(null);
      setNotice(
        "Repository connected. Code nodes can publish reviewed drafts as pull requests.",
      );
    });
  }
  function submitNode(event: FormEvent) {
    event.preventDefault();
    if (!activePlan) return;
    void act("add-node", async () => {
      const task = await addAgentTask(activePlan.id, {
        title: nodeTitle,
        description: nodeDescription,
        role: nodeRole,
      });
      setDialog(null);
      setNodeTitle("");
      setNodeDescription("");
      select(task.id);
      setNotice("Node added. Choose its model and prerequisite nodes.");
    });
  }
  function runReady() {
    void act("run-team", async () => {
      const results = await Promise.allSettled(
        ready.map((task) => runAgentTask(task.id)),
      );
      const count = results.filter(
        (result) => result.status === "fulfilled",
      ).length;
      setNotice(
        `${count} of ${results.length} nodes produced outputs. Select a node to review its result.`,
      );
      const failures = results.filter((result) => result.status === "rejected");
      if (failures.length)
        setError(
          failures
            .map((result) =>
              result.status === "rejected"
                ? result.reason instanceof Error
                  ? result.reason.message
                  : "Model request failed"
                : "",
            )
            .filter((value, index, array) => array.indexOf(value) === index)
            .join(" "),
        );
    });
  }
  return (
    <main className="workflow-app">
      {sidebarOpen && (
        <button
          className="workflow-sidebar-overlay"
          aria-label="Close workspace navigation"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={`workflow-sidebar ${sidebarOpen ? "workflow-sidebar-open" : ""}`}
        aria-label="AI team navigation"
      >
        <a className="workflow-brand" href={`/projects/${projectId}`}>
          <span>P</span>
          <div>
            PromptPilot<small>AI workspace</small>
          </div>
        </a>
        <a className="workflow-back" href={`/projects/${projectId}`}>
          ← Prompt assistant
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <strong className="workspace-project">{projectName}</strong>
        <button
          className="workflow-new"
          onClick={newPlan}
          disabled={!canWrite || Boolean(busy)}
        >
          ＋ New workflow
        </button>
        <div className="workspace-label">
          WORKFLOWS <span>{plans.length}</span>
        </div>
        <nav className="workflow-plan-list">
          {plans.map((plan) => (
            <button
              key={plan.id}
              className={activePlan?.id === plan.id ? "selected" : ""}
              onClick={() => {
                setPlanId(plan.id);
                setSelectedId(null);
                setSidebarOpen(false);
              }}
            >
              <span>◇</span>
              <div>
                {plan.title}
                <small>
                  {plan.milestones.reduce(
                    (count, phase) => count + phase.tasks.length,
                    0,
                  )}{" "}
                  nodes
                </small>
              </div>
            </button>
          ))}
        </nav>
        <div className="workflow-sidebar-bottom">
          <button onClick={() => setDialog("vault")}>
            ◈ Model Vault <b>{activeConnections.length}</b>
          </button>
          <button onClick={() => setDialog("repository")}>
            ⌘ Repository {repository && <i />}
          </button>
          <small>Build with the models you choose.</small>
        </div>
      </aside>
      <section className="workflow-main">
        <header className="workflow-topbar">
          <button
            className="workflow-mobile-menu"
            aria-label="Open workspace navigation"
            onClick={() => setSidebarOpen(true)}
          >
            ☰
          </button>
          <div className="workflow-heading">
            <small>{projectName} / Workflows</small>
            <h1>AI delivery team</h1>
          </div>
          <div className="workflow-top-actions">
            <button
              className="workflow-secondary"
              onClick={() => setDialog("vault")}
            >
              Model Vault <span>{activeConnections.length}</span>
            </button>
            <button
              className="workflow-secondary"
              onClick={() => setDialog("repository")}
            >
              {repository ? "GitHub connected" : "Connect GitHub"}
            </button>
          </div>
        </header>
        {(error || notice) && (
          <div
            className={`workflow-alert ${error ? "error" : "success"}`}
            role={error ? "alert" : "status"}
          >
            {error || notice}
            <button
              aria-label="Dismiss notification"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              ×
            </button>
          </div>
        )}
        {loading ? (
          <div className="workflow-empty">
            <h2>Loading your workspace…</h2>
          </div>
        ) : !activePlan ? (
          <div className="workflow-empty">
            <span className="workflow-empty-symbol">◇</span>
            <small>YOUR IDEA. YOUR AI TEAM.</small>
            <h2>From a prompt to a project workflow.</h2>
            <p>
              Create a visual plan, assign the right model to each task, and
              review every handoff in one workspace.
            </p>
            <div className="workflow-empty-preview">
              <span>Project idea</span>
              <i />
              <span>Plan & assign</span>
              <i />
              <span>Build & review</span>
            </div>
            <button
              className="workflow-primary"
              onClick={newPlan}
              disabled={!canWrite}
            >
              Create your first workflow
            </button>
            <button
              className="workflow-text-button"
              onClick={() => setDialog("vault")}
            >
              Connect a model first ↗
            </button>
          </div>
        ) : (
          <>
            <div className="workflow-editor-bar">
              <div>
                <h2>{activePlan.title}</h2>
                <span className="workflow-mode">
                  {activePlan.planning_mode === "ai"
                    ? "AI planned"
                    : "Editable template"}
                </span>
              </div>
              <nav aria-label="Workspace view">
                <button
                  className={view === "editor" ? "selected" : ""}
                  onClick={() => setView("editor")}
                >
                  Editor
                </button>
                <button
                  className={view === "executions" ? "selected" : ""}
                  onClick={() => setView("executions")}
                >
                  Executions
                </button>
              </nav>
              <button
                className="workflow-primary run-workflow"
                onClick={runReady}
                disabled={!canWrite || Boolean(busy) || !ready.length}
              >
                {busy === "run-team"
                  ? "Running team…"
                  : `▶ Run ready nodes${ready.length ? ` (${ready.length})` : ""}`}
              </button>
            </div>
            <div className="workflow-phase-strip">
              {activePlan.milestones.map((phase) => (
                <span key={phase.id}>
                  <b>{phase.position}</b>
                  {phase.title}
                </span>
              ))}
            </div>
            <div className="workflow-workarea">
              <div className="workflow-editor-surface">
                {view === "editor" ? (
                  <>
                    <div className="workflow-canvas-toolbar">
                      <span>
                        <i className="connection-dot" />
                        {
                          tasks.filter((task) => task.status === "completed")
                            .length
                        }
                        /{tasks.length} approved ·{" "}
                        {
                          tasks.filter((task) => task.status === "review")
                            .length
                        }{" "}
                        awaiting review
                      </span>
                      <div>
                        <button
                          onClick={() => setLayoutVersion((value) => value + 1)}
                        >
                          Auto arrange
                        </button>
                        <button
                          onClick={() => setDialog("node")}
                          disabled={!canWrite || Boolean(busy)}
                        >
                          ＋ Add node
                        </button>
                      </div>
                    </div>
                    <WorkflowCanvas
                      planId={activePlan.id}
                      tasks={tasks}
                      title={activePlan.title}
                      selectedId={selectedId}
                      onSelect={(id) => select(id)}
                      layoutVersion={layoutVersion}
                    />
                  </>
                ) : (
                  <div className="workflow-executions">
                    <h2>Execution overview</h2>
                    <p>
                      Inspect a node to see every attempt, provider response,
                      and review note.
                    </p>
                    <table>
                      <thead>
                        <tr>
                          <th>Task</th>
                          <th>Model</th>
                          <th>State</th>
                          <th>Attempts</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {tasks.map((task) => (
                          <tr key={task.id}>
                            <td>
                              <strong>{task.title}</strong>
                              <small>{roleNames[task.role]}</small>
                            </td>
                            <td>{task.assigned_model || "Unassigned"}</td>
                            <td>
                              <span
                                className={`execution-state state-${task.status}`}
                              >
                                {task.status}
                              </span>
                            </td>
                            <td>{task.attempt_count}</td>
                            <td>
                              <button onClick={() => select(task.id, "runs")}>
                                Inspect runs ↗
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              {selected && (
                <NodeInspector
                  key={`${selected.id}:${inspectorTab}`}
                  task={selected}
                  tasks={tasks}
                  connections={connections}
                  busy={Boolean(busy)}
                  canWrite={canWrite}
                  canPublish={canManageRepository}
                  hasRepository={Boolean(repository)}
                  initialTab={inspectorTab}
                  onClose={() => setSelectedId(null)}
                  onSave={(patch) =>
                    act("save-node", async () => {
                      await updateAgentTask(selected.id, patch);
                      setNotice(
                        patch.status === "completed"
                          ? "Output approved."
                          : "Node saved.",
                      );
                    })
                  }
                  onRun={() =>
                    void act(`run-${selected.id}`, async () => {
                      await runAgentTask(selected.id);
                      setInspectorTab("output");
                      setNotice(
                        "Node finished. Review its output before approving.",
                      );
                    })
                  }
                  onDelete={() => {
                    if (
                      window.confirm(
                        `Remove “${selected.title}”? Its run history will be deleted.`,
                      )
                    )
                      void act("remove-node", async () => {
                        await deleteAgentTask(selected.id);
                        setSelectedId(null);
                      });
                  }}
                  onSaveDraft={(text) =>
                    void act("save-draft", async () => {
                      await saveAgentDraft(selected.id, text);
                      setNotice("Reviewed draft saved.");
                    })
                  }
                  onPublish={() =>
                    void act("publish", async () => {
                      const result = await publishAgentTask(selected.id);
                      setNotice(
                        `Draft pull request created: ${result.pull_request_url}`,
                      );
                    })
                  }
                />
              )}
            </div>
          </>
        )}
      </section>
      {dialog === "vault" && (
        <Modal title="Model Vault" onClose={closeDialog} wide>
          <ConnectionVault
            catalog={catalog}
            connections={connections}
            canWrite={canWrite}
            onRefresh={refresh}
          />
        </Modal>
      )}
      {dialog === "repository" && (
        <Modal title="Connect GitHub repository" onClose={closeDialog}>
          {repository && (
            <p className="repository-connected">
              Connected to{" "}
              <a href={repository.url} target="_blank" rel="noreferrer">
                {repository.owner}/{repository.repo} ↗
              </a>
            </p>
          )}
          <p className="field-note">
            Code drafts go to pull requests in the repository you choose.
          </p>
          {error && (
            <p className="workflow-alert error" role="alert">
              {error}
            </p>
          )}
          {canManageRepository ? (
            <form className="workflow-form" onSubmit={submitRepository}>
              <label>
                GitHub repository URL or owner/repo
                <input
                  value={repoName}
                  onChange={(event) => setRepoName(event.target.value)}
                  placeholder="https://github.com/uzair592/promptpilot"
                  required
                />
              </label>
              <p className="field-note">
                A profile URL has no repository name. Copy the address of the
                specific project repository.
              </p>
              <label>
                GitHub fine-grained token
                <input
                  type="password"
                  autoComplete="off"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  required
                />
              </label>
              <p className="field-note">
                Restrict the token to that repository with Contents and Pull
                requests write access.
              </p>
              <button className="workflow-primary" disabled={Boolean(busy)}>
                {busy === "repository" ? "Connecting…" : "Connect repository"}
              </button>
            </form>
          ) : (
            <p className="field-note">
              The project owner can connect a repository.
            </p>
          )}
        </Modal>
      )}
      {dialog === "plan" && (
        <Modal title="Create a workflow" onClose={closeDialog}>
          <p className="field-note">
            Describe the result. PromptPilot turns it into connected tasks you
            can inspect and change.
          </p>
          {error && (
            <p className="workflow-alert error" role="alert">
              {error}
            </p>
          )}
          <form className="workflow-form" onSubmit={submitPlan}>
            <label>
              Plan title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                required
                maxLength={160}
              />
            </label>
            <label>
              Product idea
              <textarea
                rows={7}
                value={idea}
                onChange={(event) => setIdea(event.target.value)}
                placeholder="Describe the users, features, constraints, and what done means…"
                required
                minLength={10}
              />
            </label>
            <label>
              Planning model
              <select
                value={planner}
                onChange={(event) => setPlanner(event.target.value)}
              >
                <option value="">Start with an editable template</option>
                {activeConnections.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label} · {item.default_model}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Optional start time
              <input
                type="datetime-local"
                value={startAt}
                onChange={(event) => setStartAt(event.target.value)}
              />
            </label>
            <p className="field-note">
              Start times are planning reminders. Run nodes when you are ready.
            </p>
            <button
              className="workflow-primary"
              disabled={!canWrite || Boolean(busy) || idea.trim().length < 10}
            >
              {busy === "create-plan"
                ? "Creating workflow…"
                : "Create milestones and tasks"}
            </button>
          </form>
        </Modal>
      )}
      {dialog === "node" && (
        <Modal title="Add a workflow node" onClose={closeDialog}>
          {error && (
            <p className="workflow-alert error" role="alert">
              {error}
            </p>
          )}
          <form className="workflow-form" onSubmit={submitNode}>
            <label>
              Task name
              <input
                value={nodeTitle}
                onChange={(event) => setNodeTitle(event.target.value)}
                required
              />
            </label>
            <label>
              Role
              <select
                value={nodeRole}
                onChange={(event) =>
                  setNodeRole(event.target.value as AgentTask["role"])
                }
              >
                {Object.entries(roleNames).map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Instructions
              <textarea
                rows={5}
                value={nodeDescription}
                onChange={(event) => setNodeDescription(event.target.value)}
                required
              />
            </label>
            <button
              className="workflow-primary"
              disabled={!canWrite || Boolean(busy)}
            >
              Add node
            </button>
          </form>
        </Modal>
      )}
    </main>
  );
}
