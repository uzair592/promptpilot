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
  ApiError,
  ContextPackage,
  Conversation,
  DocumentItem,
  Evaluation,
  GeneratedPrompt,
  MemoryItem,
  Message,
  ModelRun,
  PromptAnalysis,
  QuestionSession,
  addDocumentUrl,
  analyzeMessage,
  answerQuestion,
  assembleContext,
  compareEvaluations,
  createConversation,
  executePrompt,
  friendlyError,
  generatePrompt,
  getConversations,
  getDocuments,
  getEvaluations,
  getGeneratedPrompts,
  getLatestAnalysis,
  getMemory,
  getMessages,
  getNextQuestion,
  getRuns,
  isModelRunSuccessful,
  sendMessage,
  skipQuestion,
  uploadDocument,
} from "../../../lib/conversations";

const stages = [
  "Request",
  "Analysis",
  "Clarify",
  "Evidence",
  "Context",
  "Generated prompt",
  "Execution",
  "Evaluation",
] as const;
const labels: Record<string, string> = {
  audience: "Audience",
  constraints: "Constraints",
  context: "Background context",
  output_format: "Output format",
  task: "Objective",
  requirements: "Requirements",
  instruction_following: "Instruction Following",
  contextual_grounding: "Contextual Grounding",
};
const humanize = (value: string) =>
  labels[value] ??
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const date = (value: string) => new Date(value).toLocaleString();

export function ConversationWorkspace({
  projectId,
  canWrite,
}: {
  projectId: string;
  canWrite: boolean;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [analysis, setAnalysis] = useState<PromptAnalysis | null>(null);
  const [questions, setQuestions] = useState<QuestionSession | null>(null);
  const [memory, setMemory] = useState<MemoryItem[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [context, setContext] = useState<ContextPackage | null>(null);
  const [prompts, setPrompts] = useState<GeneratedPrompt[]>([]);
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [stage, setStage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [answer, setAnswer] = useState("");
  const [mode, setMode] = useState("structured");
  const [url, setUrl] = useState("");
  const [copied, setCopied] = useState(false);
  const submissionKey = useRef<string | null>(null);

  const source = useMemo(
    () => [...messages].reverse().find((item) => item.role === "user") ?? null,
    [messages],
  );
  const currentPrompt = useMemo(
    () => prompts.find((item) => item.source_message_id === source?.id) ?? null,
    [prompts, source],
  );
  const relatedRuns = useMemo(
    () =>
      runs.filter(
        (run) =>
          run.source_message_id === source?.id &&
          (!currentPrompt ||
            run.prompt_version_id === currentPrompt.version_id ||
            run.execution_strategy === "baseline"),
      ),
    [runs, currentPrompt, source],
  );
  const baseline = relatedRuns.find(
    (run) => run.execution_strategy === "baseline" && isModelRunSuccessful(run),
  );
  const pilot = relatedRuns.find(
    (run) =>
      run.execution_strategy === "promptpilot" && isModelRunSuccessful(run),
  );
  const relatedEvaluations = evaluations.filter(
    (evaluation) =>
      evaluation.baseline_model_run_id === baseline?.id &&
      evaluation.promptpilot_model_run_id === pilot?.id,
  );

  const loadProjectEvidence = useCallback(async () => {
    const [savedMemory, savedDocuments] = await Promise.all([
      getMemory(projectId),
      getDocuments(projectId),
    ]);
    setMemory(savedMemory);
    setDocuments(savedDocuments);
  }, [projectId]);

  const loadConversation = useCallback(
    async (conversation: Conversation) => {
      setLoading(true);
      setError("");
      setContext(null);
      setAnalysis(null);
      setQuestions(null);
      try {
        const history = await getMessages(conversation.id);
        setMessages(history);
        const latestSource = [...history]
          .reverse()
          .find((item) => item.role === "user");
        const baseLoads = await Promise.all([
          getGeneratedPrompts(conversation.id),
          getRuns(conversation.id),
          getEvaluations(conversation.id),
          loadProjectEvidence(),
        ]);
        setPrompts(baseLoads[0]);
        setRuns(baseLoads[1]);
        setEvaluations(baseLoads[2]);
        if (latestSource) {
          try {
            const savedAnalysis = await getLatestAnalysis(
              conversation.id,
              latestSource.id,
            );
            setAnalysis(savedAnalysis);
            try {
              setQuestions(await getNextQuestion(conversation.id));
            } catch (questionError) {
              if (!(
                questionError instanceof ApiError &&
                questionError.status === 404
              ))
                throw questionError;
            }
          } catch (analysisError) {
            if (!(
              analysisError instanceof ApiError && analysisError.status === 404
            ))
              throw analysisError;
          }
        }
      } catch (loadError) {
        setError(
          friendlyError(
            loadError,
            "We could not restore this conversation. Check your connection and retry.",
          ),
        );
      } finally {
        setLoading(false);
      }
    },
    [loadProjectEvidence],
  );

  useEffect(() => {
    getConversations(projectId)
      .then((items) => {
        setConversations(items);
        setSelected(items[0] ?? null);
        if (!items[0]) {
          setLoading(false);
          loadProjectEvidence().catch(() =>
            setError("Evidence could not be loaded."),
          );
        }
      })
      .catch((loadError) => {
        setError(friendlyError(loadError, "We could not load conversations."));
        setLoading(false);
      });
  }, [projectId, loadProjectEvidence]);
  useEffect(() => {
    if (selected) void loadConversation(selected);
  }, [selected, loadConversation]);

  async function act(
    key: string,
    action: () => Promise<void>,
    fallback: string,
  ) {
    if (busy) return;
    setBusy(key);
    setError("");
    try {
      await action();
    } catch (actionError) {
      setError(friendlyError(actionError, fallback));
    } finally {
      setBusy("");
    }
  }

  async function newConversation() {
    const title = window.prompt("Conversation title", "New request");
    if (!title?.trim()) return;
    await act(
      "conversation",
      async () => {
        const item = await createConversation(projectId, title.trim());
        setConversations((items) => [item, ...items]);
        setSelected(item);
        setStage(0);
      },
      "We could not create that conversation.",
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !draft.trim()) return;
    const content = draft.trim();
    submissionKey.current ??= crypto.randomUUID();
    await act(
      "send",
      async () => {
        const message = await sendMessage(
          selected.id,
          content,
          submissionKey.current!,
        );
        submissionKey.current = null;
        setDraft("");
        setMessages((items) => [...items, message]);
        setAnalysis(null);
        setQuestions(null);
        setContext(null);
        setStage(1);
      },
      "Your request was not saved. Your text is still here; retry when ready.",
    );
  }

  async function runAnalysis() {
    if (!selected || !source) return;
    await act(
      "analysis",
      async () => {
        const result = await analyzeMessage(selected.id, source.id);
        setAnalysis(result);
        setQuestions(await getNextQuestion(selected.id));
        setStage(1);
      },
      "Analysis could not be completed. Please retry.",
    );
  }

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !questions?.next_question || !answer.trim()) return;
    await act(
      "answer",
      async () => {
        const result = await answerQuestion(
          selected.id,
          questions.next_question!.id,
          answer.trim(),
        );
        setQuestions(result);
        if (result.analysis) setAnalysis(result.analysis);
        setAnswer("");
        await loadProjectEvidence();
      },
      "Your answer was not saved. It remains in the field so you can retry.",
    );
  }

  async function skip() {
    if (!selected || !questions?.next_question) return;
    await act(
      "skip",
      async () =>
        setQuestions(
          await skipQuestion(selected.id, questions.next_question!.id),
        ),
      "The question could not be skipped.",
    );
  }

  async function assemble() {
    if (!selected || !source) return;
    await act(
      "context",
      async () => {
        setContext(
          await assembleContext(projectId, {
            task: source.content,
            conversation_id: selected.id,
            message_id: source.id,
            ...(analysis ? { analysis_id: analysis.id } : {}),
          }),
        );
      },
      "Context could not be assembled. Please retry.",
    );
  }

  async function generate() {
    if (!selected || !source) return;
    await act(
      "generate",
      async () => {
        const item = await generatePrompt(selected.id, source.id, mode);
        setPrompts((items) => [
          item,
          ...items.filter((saved) => saved.version_id !== item.version_id),
        ]);
      },
      "Prompt generation is unavailable. Confirm the generation provider is configured, then retry.",
    );
  }

  async function execute(strategy: "baseline" | "promptpilot") {
    if (!selected || !source || !currentPrompt) return;
    await act(
      `execute-${strategy}`,
      async () => {
        try {
          const run = await executePrompt(
            selected.id,
            currentPrompt.version_id,
            source.id,
            strategy,
          );
          setRuns((items) => [run, ...items]);
        } catch (executionError) {
          setRuns(await getRuns(selected.id));
          throw executionError;
        }
      },
      "Model execution is unavailable. A target provider must be configured on the server; no response was invented.",
    );
  }

  async function compare() {
    if (!selected || !baseline || !pilot) return;
    await act(
      "compare",
      async () => {
        const result = await compareEvaluations(
          selected.id,
          baseline.id,
          pilot.id,
        );
        setEvaluations((items) => [result, ...items]);
      },
      "Evaluation failed. The saved runs remain available to retry.",
    );
  }

  const evidenceCount = memory.length + documents.length;
  const completed = [
    Boolean(source),
    Boolean(analysis),
    questions?.status === "completed",
    evidenceCount > 0,
    Boolean(context),
    Boolean(currentPrompt),
    relatedRuns.some((run) => isModelRunSuccessful(run)),
    relatedEvaluations.length > 0,
  ];

  if (loading && !selected)
    return (
      <div className="workspace-loading" role="status">
        Loading saved workflow…
      </div>
    );
  return (
    <div className="workflow-shell">
      <aside className="conversation-sidebar">
        <div className="row">
          <strong>Conversations</strong>
          {canWrite && (
            <button
              onClick={newConversation}
              disabled={Boolean(busy)}
              aria-label="Create conversation"
            >
              +
            </button>
          )}
        </div>
        {conversations.length === 0 ? (
          <p className="muted">No conversations yet.</p>
        ) : (
          conversations.map((item) => (
            <button
              className={`conversation-item ${selected?.id === item.id ? "selected" : ""}`}
              key={item.id}
              onClick={() => {
                setSelected(item);
                setStage(0);
              }}
            >
              {item.title}
            </button>
          ))
        )}
      </aside>
      <section className="workflow-main">
        {error && (
          <div className="error" role="alert">
            {error}
            {error.includes("session expired") && <a href="/login"> Sign in</a>}
          </div>
        )}
        {!selected ? (
          <div className="empty-state">
            <h2>Start with a conversation</h2>
            <p className="muted">
              Create one to save a request and move through the PromptPilot
              workflow.
            </p>
            {canWrite && (
              <button onClick={newConversation}>New conversation</button>
            )}
          </div>
        ) : (
          <>
            <header className="workflow-heading">
              <div>
                <small className="eyebrow">Active conversation</small>
                <h2>{selected.title}</h2>
              </div>
              <span className="save-state">Saved to project</span>
            </header>
            <nav className="stage-nav" aria-label="Prompt workflow">
              {stages.map((item, index) => (
                <button
                  key={item}
                  className={stage === index ? "active" : ""}
                  onClick={() => setStage(index)}
                >
                  <span>{completed[index] ? "✓" : index + 1}</span>
                  {item}
                </button>
              ))}
            </nav>
            {loading ? (
              <div className="workspace-loading" role="status">
                Restoring saved workflow…
              </div>
            ) : (
              <div className="stage-content">
                {stage === 0 && (
                  <section>
                    <StageTitle
                      title="Original request"
                      description="Your latest saved request is the source for every later step."
                    />
                    {source ? (
                      <div className="request-card">
                        <small>
                          Original request · {date(source.created_at)}
                        </small>
                        <p>{source.content}</p>
                      </div>
                    ) : (
                      <p className="empty-note">
                        No request has been submitted in this conversation.
                      </p>
                    )}
                    {canWrite && (
                      <form className="composer" onSubmit={submit}>
                        <label className="grow">
                          Request
                          <textarea
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                            placeholder="Describe the outcome you need, relevant constraints, audience, and format…"
                            rows={4}
                            disabled={busy === "send"}
                          />
                        </label>
                        <button disabled={Boolean(busy) || !draft.trim()}>
                          {busy === "send"
                            ? "Saving…"
                            : source
                              ? "Add new request"
                              : "Save request"}
                        </button>
                      </form>
                    )}
                  </section>
                )}
                {stage === 1 && (
                  <section>
                    <StageTitle
                      title="Request analysis"
                      description="See what is clear and which details may still be needed."
                    />
                    {!source ? (
                      <p className="empty-note">Submit a request first.</p>
                    ) : !analysis ? (
                      <ActionEmpty
                        text="Analysis has not been started."
                        action="Analyze request"
                        onClick={runAnalysis}
                        disabled={!canWrite || Boolean(busy)}
                      />
                    ) : (
                      <>
                        <div className="score-card">
                          <div className="score">
                            {analysis.overall_score}
                            <small>/100</small>
                          </div>
                          <div>
                            <h3>{analysis.status}</h3>
                            <p>
                              {humanize(analysis.task_category)} ·{" "}
                              {analysis.fallback_used
                                ? "Deterministic analysis"
                                : "Provider-assisted analysis"}
                            </p>
                          </div>
                          {canWrite && (
                            <button
                              className="secondary"
                              onClick={runAnalysis}
                              disabled={Boolean(busy)}
                            >
                              {busy === "analysis" ? "Analyzing…" : "Run again"}
                            </button>
                          )}
                        </div>
                        <div className="analysis-grid">
                          {analysis.dimensions
                            .filter((item) => item.applicable)
                            .map((item) => (
                              <article className="detail-card" key={item.key}>
                                <div className="row">
                                  <strong>{humanize(item.key)}</strong>
                                  <span className={`badge ${item.status}`}>
                                    {item.score ?? "—"}
                                  </span>
                                </div>
                                <p>{item.explanation}</p>
                                {item.evidence && (
                                  <small className="muted">
                                    Evidence: {item.evidence}
                                  </small>
                                )}
                              </article>
                            ))}
                        </div>
                        <h3>Information gaps</h3>
                        {analysis.gaps.length === 0 ? (
                          <p className="success-note">
                            No information gaps were identified.
                          </p>
                        ) : (
                          analysis.gaps.map((gap) => (
                            <article className="gap-card" key={gap.id}>
                              <span className={`badge ${gap.severity}`}>
                                {humanize(gap.severity)}
                              </span>
                              <div>
                                <strong>{gap.title}</strong>
                                <p>{gap.description}</p>
                                <small>
                                  {humanize(gap.dimension)} ·{" "}
                                  {humanize(gap.status)}
                                </small>
                              </div>
                            </article>
                          ))
                        )}
                        <details>
                          <summary>Technical details</summary>
                          <p className="muted">
                            Analysis {analysis.analysis_version} ·{" "}
                            {analysis.analysis_mode} ·{" "}
                            {analysis.ai_provider ?? "No provider"}{" "}
                            {analysis.ai_model ?? ""}
                          </p>
                        </details>
                      </>
                    )}
                  </section>
                )}
                {stage === 2 && (
                  <section>
                    <StageTitle
                      title="Clarify the request"
                      description="Answer only what is useful. Every saved answer becomes traceable project evidence."
                    />
                    {!analysis ? (
                      <p className="empty-note">
                        Run analysis before clarification.
                      </p>
                    ) : !questions ? (
                      <p className="empty-note">
                        No clarification session is available.
                      </p>
                    ) : questions.next_question ? (
                      <div className="question-card">
                        <div className="row">
                          <small>
                            Current question · priority{" "}
                            {questions.next_question.priority}
                          </small>
                          <span className="badge">
                            {humanize(questions.next_question.source)}
                          </span>
                        </div>
                        <h3>{questions.next_question.text}</h3>
                        <form onSubmit={submitAnswer}>
                          <label>
                            Your answer
                            <textarea
                              value={answer}
                              onChange={(event) =>
                                setAnswer(event.target.value)
                              }
                              rows={4}
                              disabled={Boolean(busy)}
                            />
                          </label>
                          <div className="button-row">
                            <button disabled={Boolean(busy) || !answer.trim()}>
                              {busy === "answer"
                                ? "Saving answer…"
                                : "Save answer"}
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              onClick={skip}
                              disabled={Boolean(busy)}
                            >
                              {busy === "skip" ? "Skipping…" : "Skip question"}
                            </button>
                          </div>
                        </form>
                      </div>
                    ) : (
                      <div className="success-note">
                        <strong>No questions remaining.</strong>
                        <p>
                          {questions.stop_reason === "no_unresolved_gaps"
                            ? "PromptPilot has reached the end of the clarification stage."
                            : "This clarification session is complete."}
                        </p>
                      </div>
                    )}
                  </section>
                )}
                {stage === 3 && (
                  <section>
                    <StageTitle
                      title="Project evidence"
                      description="Review the saved facts, clarification answers, documents, and their provenance."
                      actions={
                        <button
                          className="secondary"
                          onClick={() =>
                            loadProjectEvidence().catch(() =>
                              setError("Evidence could not be refreshed."),
                            )
                          }
                        >
                          Refresh
                        </button>
                      }
                    />
                    <div className="evidence-grid">
                      <div>
                        <h3>Memory and answers</h3>
                        {memory.length === 0 ? (
                          <p className="empty-note">
                            No saved project facts or answers.
                          </p>
                        ) : (
                          memory.map((item) => (
                            <article className="evidence-item" key={item.id}>
                              <div className="row">
                                <strong>{item.subject}</strong>
                                <span className="badge">
                                  {humanize(item.category)}
                                </span>
                              </div>
                              <p>{item.content}</p>
                              <small>
                                Source: {humanize(item.source)} · Confidence{" "}
                                {item.confidence}%
                              </small>
                            </article>
                          ))
                        )}
                      </div>
                      <div>
                        <h3>Documents and sources</h3>
                        {documents.length === 0 ? (
                          <p className="empty-note">
                            No documents or URLs have been added.
                          </p>
                        ) : (
                          documents.map((item) => (
                            <article className="evidence-item" key={item.id}>
                              <div className="row">
                                <strong>{item.name}</strong>
                                <span className={`badge ${item.status}`}>
                                  {humanize(item.status)}
                                </span>
                              </div>
                              <small>
                                {humanize(item.source_type)} ·{" "}
                                {Math.ceil(item.size_bytes / 1024)} KB
                              </small>
                              {item.source_url && (
                                <p className="truncate">{item.source_url}</p>
                              )}
                              {item.error_message && (
                                <p className="error-inline">
                                  Processing failed: {item.error_message}
                                </p>
                              )}
                            </article>
                          ))
                        )}
                      </div>
                    </div>
                    {canWrite && (
                      <EvidenceForms
                        busy={busy}
                        url={url}
                        setUrl={setUrl}
                        onUrl={() =>
                          act(
                            "url",
                            async () => {
                              await addDocumentUrl(projectId, url.trim());
                              setUrl("");
                              await loadProjectEvidence();
                            },
                            "The URL could not be processed.",
                          )
                        }
                        onFile={(file) =>
                          act(
                            "file",
                            async () => {
                              await uploadDocument(projectId, file);
                              await loadProjectEvidence();
                            },
                            "The document could not be uploaded.",
                          )
                        }
                      />
                    )}
                  </section>
                )}
                {stage === 4 && (
                  <section>
                    <StageTitle
                      title="Assembled context"
                      description="The original request stays separate from supporting evidence selected for generation."
                      actions={
                        <button
                          onClick={assemble}
                          disabled={!source || Boolean(busy)}
                        >
                          {busy === "context"
                            ? "Assembling…"
                            : context
                              ? "Reassemble"
                              : "Assemble context"}
                        </button>
                      }
                    />
                    {!context ? (
                      <p className="empty-note">
                        No context has been assembled for this request.
                      </p>
                    ) : (
                      <>
                        <div className="budget">
                          <span
                            style={{
                              width: `${Math.min(100, (context.used_budget / context.budget) * 100)}%`,
                            }}
                          />
                          <small>
                            {context.used_budget.toLocaleString()} of{" "}
                            {context.budget.toLocaleString()} characters used
                          </small>
                        </div>
                        <div className="context-columns">
                          <ContextList
                            title="Project memory"
                            items={context.project_memory}
                          />
                          <ContextList
                            title="Clarification answers"
                            items={context.user_answers}
                          />
                          <ContextList
                            title="Requirements"
                            items={context.requirements}
                          />
                          <ContextList
                            title="Constraints"
                            items={context.constraints}
                          />
                        </div>
                        <h3>Retrieved documents</h3>
                        {context.document_context.length === 0 ? (
                          <p className="empty-note">
                            No relevant document context was selected.
                          </p>
                        ) : (
                          context.document_context.map((item, index) => (
                            <article
                              className="evidence-item"
                              key={`${item.provenance}-${index}`}
                            >
                              <strong>
                                {item.metadata.document_name ??
                                  "Document source"}
                              </strong>
                              <p>{item.content}</p>
                              <small>
                                {item.provenance} · Relevance{" "}
                                {item.score.toFixed(2)}
                              </small>
                            </article>
                          ))
                        )}
                        {context.omitted_items.length > 0 && (
                          <details>
                            <summary>
                              {context.omitted_items.length} omitted item(s)
                            </summary>
                            {context.omitted_items.map((item) => (
                              <p key={item.identifier}>
                                {humanize(item.source_type)}: {item.reason}
                              </p>
                            ))}
                          </details>
                        )}
                      </>
                    )}
                  </section>
                )}
                {stage === 5 && (
                  <section>
                    <StageTitle
                      title="Generated PromptPilot prompt"
                      description="Generate a saved, versioned prompt from the request and available context."
                      actions={
                        <div className="button-row">
                          <label>
                            Mode
                            <select
                              value={mode}
                              onChange={(event) => setMode(event.target.value)}
                            >
                              <option value="minimal">Minimal</option>
                              <option value="structured">Structured</option>
                              <option value="detailed">Detailed</option>
                            </select>
                          </label>
                          <button
                            onClick={generate}
                            disabled={!source || !canWrite || Boolean(busy)}
                          >
                            {busy === "generate"
                              ? "Generating…"
                              : "Generate prompt"}
                          </button>
                        </div>
                      }
                    />
                    {!currentPrompt ? (
                      <p className="empty-note">
                        No generated prompt exists for the active request.
                      </p>
                    ) : (
                      <>
                        <div className="prompt-compare">
                          <article>
                            <small>Original request</small>
                            <p>{currentPrompt.original_prompt}</p>
                          </article>
                          <article className="generated">
                            <div className="row">
                              <small>
                                PromptPilot prompt · v
                                {currentPrompt.version_number}
                              </small>
                              <button
                                className="text-button"
                                onClick={async () => {
                                  await navigator.clipboard.writeText(
                                    currentPrompt.optimized_prompt,
                                  );
                                  setCopied(true);
                                  window.setTimeout(
                                    () => setCopied(false),
                                    1500,
                                  );
                                }}
                              >
                                {copied ? "Copied" : "Copy"}
                              </button>
                            </div>
                            <p>{currentPrompt.optimized_prompt}</p>
                          </article>
                        </div>
                        <div className="metadata-row">
                          <span>
                            {String(
                              currentPrompt.generation_metadata
                                .generation_mode ?? mode,
                            )}
                          </span>
                          <span>
                            {String(
                              currentPrompt.generation_metadata.provider ??
                                "Unknown provider",
                            )}{" "}
                            /{" "}
                            {String(
                              currentPrompt.generation_metadata.model ??
                                "Unknown model",
                            )}
                          </span>
                          <span>{date(currentPrompt.created_at)}</span>
                        </div>
                        {currentPrompt.warnings.map((warning) => (
                          <p className="warning-note" key={warning}>
                            Warning: {warning}
                          </p>
                        ))}
                      </>
                    )}
                  </section>
                )}
                {stage === 6 && (
                  <section>
                    <StageTitle
                      title="Target execution"
                      description="Run only through a configured server-side target provider. PromptPilot never asks for credentials here."
                    />
                    {!currentPrompt ? (
                      <p className="empty-note">
                        Generate a prompt before model execution.
                      </p>
                    ) : (
                      <div className="run-grid">
                        {(["baseline", "promptpilot"] as const).map(
                          (strategy) => {
                            const run = relatedRuns.find(
                              (item) => item.execution_strategy === strategy,
                            );
                            return (
                              <article className="run-card" key={strategy}>
                                <div className="row">
                                  <h3>
                                    {strategy === "baseline"
                                      ? "Baseline response"
                                      : "PromptPilot response"}
                                  </h3>
                                  {run && (
                                    <span className={`badge ${run.status}`}>
                                      {humanize(run.status)}
                                    </span>
                                  )}
                                </div>
                                {run?.response_text ? (
                                  <p>{run.response_text}</p>
                                ) : run?.error_message ? (
                                  <p className="error-inline">
                                    {run.error_message}
                                  </p>
                                ) : (
                                  <p className="muted">
                                    No saved response. If no provider is
                                    configured, execution will remain
                                    unavailable.
                                  </p>
                                )}
                                {run && (
                                  <small>
                                    {run.provider} / {run.model}
                                    {run.latency_ms
                                      ? ` · ${run.latency_ms} ms`
                                      : ""}
                                  </small>
                                )}
                                {canWrite && (
                                  <button
                                    onClick={() => execute(strategy)}
                                    disabled={Boolean(busy)}
                                  >
                                    {busy === `execute-${strategy}`
                                      ? "Running…"
                                      : run?.status === "failed"
                                        ? "Retry"
                                        : "Run"}
                                  </button>
                                )}
                              </article>
                            );
                          },
                        )}
                      </div>
                    )}
                  </section>
                )}
                {stage === 7 && (
                  <section>
                    <StageTitle
                      title="Evaluation and comparison"
                      description="Scores shown here come only from saved compatible model runs."
                      actions={
                        <button
                          onClick={compare}
                          disabled={!baseline || !pilot || Boolean(busy)}
                        >
                          {busy === "compare"
                            ? "Evaluating…"
                            : "Compare saved responses"}
                        </button>
                      }
                    />
                    {!baseline || !pilot ? (
                      <p className="empty-note">
                        A succeeded baseline response and a succeeded
                        PromptPilot response are both required. Run the missing
                        strategy in Execution.
                      </p>
                    ) : relatedEvaluations.length === 0 ? (
                      <p className="empty-note">
                        Compatible runs are available, but they have not been
                        evaluated.
                      </p>
                    ) : (
                      <EvaluationView evaluation={relatedEvaluations[0]} />
                    )}
                  </section>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function StageTitle({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="stage-title">
      <div>
        <h2>{title}</h2>
        <p className="muted">{description}</p>
      </div>
      {actions}
    </div>
  );
}
function ActionEmpty({
  text,
  action,
  onClick,
  disabled,
}: {
  text: string;
  action: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <div className="empty-note">
      <p>{text}</p>
      <button onClick={onClick} disabled={disabled}>
        {action}
      </button>
    </div>
  );
}
function ContextList({
  title,
  items,
}: {
  title: string;
  items: Array<{ content: string; provenance: string }>;
}) {
  return (
    <div>
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="muted">None selected.</p>
      ) : (
        items.map((item, index) => (
          <article className="context-item" key={`${title}-${index}`}>
            <p>{item.content}</p>
            <small>{item.provenance}</small>
          </article>
        ))
      )}
    </div>
  );
}
function EvidenceForms({
  busy,
  url,
  setUrl,
  onUrl,
  onFile,
}: {
  busy: string;
  url: string;
  setUrl: (value: string) => void;
  onUrl: () => void;
  onFile: (file: File) => void;
}) {
  return (
    <div className="evidence-actions">
      <label>
        Add a public URL
        <div className="button-row">
          <input
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://…"
          />
          <button
            type="button"
            onClick={onUrl}
            disabled={Boolean(busy) || !url.trim()}
          >
            {busy === "url" ? "Adding…" : "Add URL"}
          </button>
        </div>
      </label>
      <label>
        Upload a document
        <input
          type="file"
          accept=".txt,.md,.pdf,.docx,.csv,.xlsx"
          disabled={Boolean(busy)}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onFile(file);
          }}
        />
      </label>
    </div>
  );
}
function EvaluationView({ evaluation }: { evaluation: Evaluation }) {
  const dimensions = [
    "relevance",
    "completeness",
    "instruction_following",
    "contextual_grounding",
    "clarity",
  ];
  return (
    <div className="evaluation">
      <div className="score-row">
        <div>
          <small>Baseline</small>
          <strong>{evaluation.baseline_score?.toFixed(1) ?? "—"}</strong>
        </div>
        <div>
          <small>PromptPilot</small>
          <strong>{evaluation.promptpilot_score?.toFixed(1) ?? "—"}</strong>
        </div>
        <div>
          <small>Difference</small>
          <strong>
            {evaluation.overall_delta === null
              ? "—"
              : `${evaluation.overall_delta > 0 ? "+" : ""}${evaluation.overall_delta.toFixed(1)}`}
          </strong>
        </div>
      </div>
      <p>
        {evaluation.comparison_summary || "No comparison summary was provided."}
      </p>
      <small>
        Method: {humanize(evaluation.method)} · Rubric{" "}
        {evaluation.rubric_version} · {evaluation.evaluator_provider}/
        {evaluation.evaluator_model}
      </small>
      <div className="dimension-table">
        {dimensions.map((dimension) => {
          const base = evaluation.items.find(
            (item) =>
              item.response_label === "baseline" &&
              item.dimension === dimension,
          );
          const prompt = evaluation.items.find(
            (item) =>
              item.response_label === "promptpilot" &&
              item.dimension === dimension,
          );
          return (
            <div className="dimension-row" key={dimension}>
              <strong>{humanize(dimension)}</strong>
              <span>{base?.score ?? "—"}</span>
              <span>{prompt?.score ?? "—"}</span>
              <small>
                {prompt?.explanation ?? base?.explanation ?? "No detail"}
              </small>
            </div>
          );
        })}
      </div>
    </div>
  );
}
