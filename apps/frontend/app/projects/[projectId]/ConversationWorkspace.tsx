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
  Conversation,
  DocumentItem,
  GeneratedPrompt,
  Message,
  ModelRun,
  PromptAnalysis,
  QuestionSession,
  addDocumentUrl,
  analyzeMessage,
  answerQuestion,
  createConversation,
  deleteConversation,
  executePrompt,
  friendlyError,
  generatePrompt,
  getConversations,
  getConversation,
  getDocuments,
  getGeneratedPrompts,
  getLatestAnalysis,
  getMessages,
  getNextQuestion,
  getRuns,
  renameConversation,
  reassessQuestions,
  sendMessage,
  skipQuestion,
  uploadDocument,
} from "../../../lib/conversations";
import {
  assessPromptQuality,
  isSmallTalk,
  PromptQuality,
} from "../../../lib/prompt-quality";
import { recommendModels } from "../../../lib/model-recommendations";
import {
  getProviderConnections,
  getProviderCatalog,
  ProviderConnection,
  ProviderDefinition,
} from "../../../lib/orchestration";
import { ConnectionVault } from "./agents/ConnectionVault";
import { WorkspaceModal } from "./agents/WorkspaceModal";

type ToolView = "quality" | "sources";

const humanize = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export function ConversationWorkspace({
  projectId,
  projectName,
  canWrite,
}: {
  projectId: string;
  projectName: string;
  canWrite: boolean;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [analysis, setAnalysis] = useState<PromptAnalysis | null>(null);
  const [questions, setQuestions] = useState<QuestionSession | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [prompts, setPrompts] = useState<GeneratedPrompt[]>([]);
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [draft, setDraft] = useState("");
  const [url, setUrl] = useState("");
  const [toolView, setToolView] = useState<ToolView>("quality");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [allConnections, setAllConnections] = useState<ProviderConnection[]>(
    [],
  );
  const [catalog, setCatalog] = useState<ProviderDefinition[]>([]);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [introNotice, setIntroNotice] = useState("");
  const connectionRef = useRef<string | undefined>(undefined);
  const submissionKey = useRef<string | null>(null);
  const chatEnd = useRef<HTMLDivElement | null>(null);
  const replyBox = useRef<HTMLTextAreaElement | null>(null);
  const operationInFlight = useRef(false);
  const loadRequest = useRef(0);

  const source = useMemo(
    () => [...messages].reverse().find((item) => item.role === "user") ?? null,
    [messages],
  );
  const replyContext =
    questions?.answered_questions
      .map((answer) => `${answer.question}\n${answer.content}`)
      .join("\n") || "";
  const currentPrompt = useMemo(
    () => prompts.find((item) => item.source_message_id === source?.id) ?? null,
    [prompts, source],
  );
  const relatedRuns = useMemo(
    () => runs.filter((run) => run.source_message_id === source?.id),
    [runs, source],
  );
  const liveQuality = useMemo(
    () =>
      assessPromptQuality(
        questions?.next_question
          ? `${source?.content || ""}\n${replyContext}`
          : draft || `${source?.content || ""}\n${replyContext}`,
      ),
    [draft, questions?.next_question, source, replyContext],
  );
  const displayedAnalysis =
    draft.trim() && !questions?.next_question ? null : analysis;
  const displayedScore = displayedAnalysis?.overall_score ?? liveQuality.score;

  const refreshConnections = useCallback(async () => {
    const items = await getProviderConnections();
    setAllConnections(items);
    setConnections(items.filter((item) => item.status === "active"));
    const stored = localStorage.getItem("promptpilot:chat-provider");
    if (
      stored &&
      items.some((item) => item.id === stored && item.status === "active")
    ) {
      setConnectionId(stored);
      connectionRef.current = stored;
    } else if (
      connectionRef.current &&
      !items.some(
        (item) => item.id === connectionRef.current && item.status === "active",
      )
    ) {
      setConnectionId("");
      connectionRef.current = undefined;
      localStorage.removeItem("promptpilot:chat-provider");
    }
  }, []);
  const closeModels = useCallback(() => setModelsOpen(false), []);
  useEffect(() => {
    void refreshConnections().catch(() => undefined);
  }, [refreshConnections]);
  useEffect(() => {
    if (!modelsOpen) return;
    setModelsError("");
    void Promise.all([
      refreshConnections(),
      getProviderCatalog().then(setCatalog),
    ]).catch((caught) =>
      setModelsError(friendlyError(caught, "Could not load model settings.")),
    );
  }, [modelsOpen, refreshConnections]);

  const loadDocuments = useCallback(async () => {
    setDocuments(await getDocuments(projectId));
  }, [projectId]);

  const loadConversation = useCallback(
    async (conversation: Conversation) => {
      const request = ++loadRequest.current;
      setLoading(true);
      setError("");
      setDraft("");
      setMessages([]);
      setPrompts([]);
      setRuns([]);
      setAnalysis(null);
      setQuestions(null);
      try {
        const history = await getMessages(conversation.id);
        const latestSource = [...history]
          .reverse()
          .find((item) => item.role === "user");
        const [savedPrompts, savedRuns] = await Promise.all([
          getGeneratedPrompts(conversation.id),
          getRuns(conversation.id),
          loadDocuments(),
        ]);
        if (request !== loadRequest.current) return;
        let savedAnalysis: PromptAnalysis | null = null;
        let savedQuestions: QuestionSession | null = null;
        if (latestSource) {
          try {
            savedAnalysis = await getLatestAnalysis(
              conversation.id,
              latestSource.id,
            );
            try {
              savedQuestions = await getNextQuestion(
                conversation.id,
                latestSource.id,
                connectionRef.current,
              );
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
        if (request !== loadRequest.current) return;
        setMessages(history);
        setPrompts(savedPrompts);
        setRuns(savedRuns);
        setAnalysis(savedAnalysis);
        setQuestions(savedQuestions);
      } catch (loadError) {
        if (request !== loadRequest.current) return;
        setError(
          friendlyError(
            loadError,
            "PromptPilot could not restore this conversation. Retry in a moment.",
          ),
        );
      } finally {
        if (request === loadRequest.current) setLoading(false);
      }
    },
    [loadDocuments],
  );

  useEffect(() => {
    let active = true;
    getConversations(projectId)
      .then((items) => {
        if (!active) return;
        setConversations(items);
        setSelected(items[0] ?? null);
        if (items[0]) {
          void loadConversation(items[0]);
        } else {
          setLoading(false);
          void loadDocuments().catch(() => undefined);
        }
      })
      .catch((loadError) => {
        if (!active) return;
        setError(
          friendlyError(loadError, "PromptPilot could not load your chats."),
        );
        setLoading(false);
      });
    return () => {
      active = false;
      loadRequest.current += 1;
    };
  }, [projectId, loadDocuments, loadConversation]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, analysis, questions, currentPrompt, relatedRuns, busy]);

  async function act(
    key: string,
    action: () => Promise<void>,
    fallback: string,
  ) {
    if (operationInFlight.current || loading) return;
    operationInFlight.current = true;
    setBusy(key);
    setError("");
    try {
      await action();
    } catch (actionError) {
      setError(friendlyError(actionError, fallback));
    } finally {
      operationInFlight.current = false;
      setBusy("");
    }
  }

  async function newConversation() {
    await act(
      "new-chat",
      async () => {
        const item = await createConversation(projectId, "Untitled chat");
        setConversations((items) => [item, ...items]);
        setSelected(item);
        setMessages([]);
        setAnalysis(null);
        setQuestions(null);
        setPrompts([]);
        setRuns([]);
        setDraft("");
        submissionKey.current = null;
      },
      "A new chat could not be created.",
    );
  }

  async function saveTitle(id: string) {
    if (!editTitle.trim()) return;
    await act(
      "rename-chat",
      async () => {
        const updated = await renameConversation(id, editTitle.trim());
        setConversations((items) =>
          items.map((item) => (item.id === id ? updated : item)),
        );
        setSelected((item) => (item?.id === id ? updated : item));
        setEditingId(null);
      },
      "Could not rename this chat.",
    );
  }

  async function removeChat(item: Conversation) {
    if (
      !window.confirm(
        `Delete “${item.title}” and its messages? This cannot be undone.`,
      )
    )
      return;
    await act(
      "delete-chat",
      async () => {
        await deleteConversation(item.id);
        const remaining = conversations.filter((chat) => chat.id !== item.id);
        setConversations(remaining);
        setEditingId(null);
        if (selected?.id === item.id) {
          loadRequest.current += 1;
          const next = remaining[0] ?? null;
          setSelected(next);
          setMessages([]);
          setQuestions(null);
          setAnalysis(null);
          setPrompts([]);
          setRuns([]);
          setDraft("");
          if (next) void loadConversation(next);
        }
      },
      "Could not delete this chat.",
    );
  }

  async function generateFor(conversationId: string, messageId: string) {
    const prompt = await generatePrompt(
      conversationId,
      messageId,
      "structured",
      connectionRef.current,
    );
    setPrompts((items) => [
      prompt,
      ...items.filter((item) => item.version_id !== prompt.version_id),
    ]);
  }

  async function generateAfterSaving(
    conversationId: string,
    messageId: string,
  ) {
    setBusy("generate");
    try {
      await generateFor(conversationId, messageId);
    } catch (generationError) {
      setError(
        `Your prompt and replies are saved, but the model could not generate the improved prompt. ${friendlyError(generationError, "Check the backend model settings or connection.")} Use Retry generation below; you do not need to re-enter your answers.`,
      );
    }
  }

  async function analyzeAndContinue(conversationId: string, messageId: string) {
    const result = await analyzeMessage(
      conversationId,
      messageId,
      connectionRef.current,
    );
    setAnalysis(result);
    const session = await getNextQuestion(
      conversationId,
      messageId,
      connectionRef.current,
    );
    setQuestions(session);
    if (!session.next_question)
      await generateAfterSaving(conversationId, messageId);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite || loading || !draft.trim() || operationInFlight.current)
      return;
    if (questions?.next_question) {
      await submitClarification(draft);
      return;
    }
    if (isSmallTalk(draft)) {
      setIntroNotice(
        "Tell me what you want to create, understand, or fix. A greeting or reaction has no task to improve yet.",
      );
      return;
    }
    setIntroNotice("");

    await act(
      "improve",
      async () => {
        let conversation = selected;
        if (!conversation) {
          conversation = await createConversation(projectId, "Untitled chat");
          setConversations((items) => [conversation!, ...items]);
          setSelected(conversation);
        }
        const content = draft.trim();
        submissionKey.current ??= crypto.randomUUID();
        const message = await sendMessage(
          conversation.id,
          content,
          submissionKey.current,
        );
        submissionKey.current = null;
        setDraft("");
        setMessages((items) => [...items, message]);
        try {
          const titled = await getConversation(conversation.id);
          setConversations((items) =>
            items.map((item) => (item.id === titled.id ? titled : item)),
          );
          setSelected(titled);
        } catch {
          // The saved message remains usable even if refreshing its title fails.
        }
        setAnalysis(null);
        setQuestions(null);
        setPrompts((items) =>
          items.filter((item) => item.source_message_id !== message.id),
        );
        await analyzeAndContinue(conversation.id, message.id);
      },
      "PromptPilot could not improve this prompt. Your text remains available to retry.",
    );
  }

  async function submitClarification(content: string) {
    if (
      !canWrite ||
      !selected ||
      !source ||
      !questions?.next_question ||
      !content.trim()
    )
      return;
    await act(
      "answer",
      async () => {
        const result = await answerQuestion(
          selected.id,
          questions.next_question!.id,
          content.trim(),
          connectionRef.current,
        );
        const receipt = result.answered_questions.find(
          (answer) =>
            answer.question_id === questions.next_question!.id &&
            answer.content === content.trim(),
        );
        if (!receipt)
          throw new Error("The server did not confirm the reply was saved.");
        setDraft("");
        setQuestions(result);
        if (result.analysis) setAnalysis(result.analysis);
        if (!result.next_question)
          await generateAfterSaving(selected.id, source.id);
      },
      "Your reply was not confirmed. Your text is still in the box; send it again to safely retry.",
    );
  }

  async function skipCurrentQuestion() {
    if (!selected || !source || !questions?.next_question) return;
    await act(
      "skip",
      async () => {
        const result = await skipQuestion(
          selected.id,
          questions.next_question!.id,
          connectionRef.current,
        );
        setDraft("");
        setQuestions(result);
        if (!result.next_question)
          await generateAfterSaving(selected.id, source.id);
      },
      "PromptPilot could not skip that question.",
    );
  }

  async function reassessCurrentPrompt() {
    if (!selected || !source) return;
    if (draft.trim()) {
      setError(
        "Send your typed answer or clear the reply box before rechecking the questions. Your text has been kept.",
      );
      return;
    }
    await act(
      "reassess",
      async () => {
        const session = await reassessQuestions(
          selected.id,
          source.id,
          connectionRef.current,
        );
        setQuestions(session);
        if (session.analysis) setAnalysis(session.analysis);
        if (!session.analysis?.ai_succeeded)
          throw new Error(
            "The selected model could not recheck this prompt. Your replies are saved; check Models & API keys. The displayed question is an offline suggestion.",
          );
        if (!session.next_question)
          await generateAfterSaving(selected.id, source.id);
      },
      "Could not recheck the prompt with this model. Your saved answers are still available.",
    );
  }

  async function regenerate() {
    if (!selected || !source) return;
    await act(
      "generate",
      () => generateFor(selected.id, source.id),
      "The improved prompt could not be generated.",
    );
  }

  async function resumeSavedPrompt() {
    if (!selected || !source) return;
    await act(
      "improve",
      () => analyzeAndContinue(selected.id, source.id),
      "Your prompt is saved, but analysis could not finish. Retry this step without submitting a new prompt.",
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
            connectionRef.current,
          );
          setRuns((items) => [
            run,
            ...items.filter((item) => item.id !== run.id),
          ]);
        } catch (executionError) {
          setRuns(await getRuns(selected.id));
          throw executionError;
        }
      },
      "The selected AI model is unavailable. Check Models & API keys.",
    );
  }

  async function logout() {
    await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    });
    window.location.assign("/login");
  }

  return (
    <div className="pilot-shell">
      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={`pilot-sidebar ${sidebarOpen ? "sidebar-open" : ""}`}
        aria-label="PromptPilot navigation"
      >
        <div className="pilot-brand">
          <span className="pilot-mark">P</span>
          <div>
            <strong>PromptPilot</strong>
            <small>Better prompts, naturally</small>
          </div>
        </div>
        <button
          className="new-chat-button"
          onClick={newConversation}
          disabled={!canWrite || loading || Boolean(busy)}
        >
          <span>＋</span> New chat
        </button>
        <div className="sidebar-section">
          <small>TOOLS</small>
          <button
            className={toolView === "quality" ? "tool-active" : ""}
            onClick={() => setToolView("quality")}
          >
            <span>◉</span> Prompt quality
          </button>
          <button
            className={toolView === "sources" ? "tool-active" : ""}
            onClick={() => setToolView("sources")}
          >
            <span>＋</span> Sources
            {documents.length > 0 && <b>{documents.length}</b>}
          </button>
          <a
            className="sidebar-tool-link"
            href={`/projects/${projectId}/agents`}
          >
            <span>✦</span> AI delivery team
          </a>
          <button
            onClick={() => {
              setModelsOpen(true);
              setSidebarOpen(false);
            }}
          >
            <span>◈</span> Models & API keys{" "}
            {connections.length > 0 && <b>{connections.length}</b>}
          </button>
        </div>
        <div className="sidebar-section chat-history">
          <small>RECENT</small>
          {conversations.length === 0 ? (
            <p>No saved prompts yet</p>
          ) : (
            conversations.map((item) => (
              <div
                className={`chat-history-row ${selected?.id === item.id ? "chat-active" : ""}`}
                key={item.id}
              >
                {editingId === item.id ? (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void saveTitle(item.id);
                    }}
                  >
                    <input
                      aria-label="Chat title"
                      maxLength={120}
                      value={editTitle}
                      onChange={(event) => setEditTitle(event.target.value)}
                      autoFocus
                    />
                    <button
                      type="submit"
                      aria-label="Save chat title"
                      disabled={Boolean(busy)}
                    >
                      ✓
                    </button>
                  </form>
                ) : (
                  <>
                    <button
                      className="chat-history-title"
                      disabled={loading || Boolean(busy)}
                      onClick={() => {
                        setSelected(item);
                        setSidebarOpen(false);
                        void loadConversation(item);
                      }}
                      title={item.title}
                    >
                      <span>⌁</span>
                      <span>{item.title}</span>
                    </button>
                    {canWrite && (
                      <div className="chat-history-actions">
                        <button
                          aria-label={`Rename ${item.title}`}
                          title="Rename chat"
                          disabled={Boolean(busy)}
                          onClick={() => {
                            setEditingId(item.id);
                            setEditTitle(item.title);
                          }}
                        >
                          ✎
                        </button>
                        <button
                          aria-label={`Delete ${item.title}`}
                          title="Delete chat"
                          disabled={Boolean(busy)}
                          onClick={() => void removeChat(item)}
                        >
                          ×
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ))
          )}
        </div>
        <div className="sidebar-footer">
          <div>
            <span className="status-dot" /> {projectName}
          </div>
          <button onClick={logout}>Sign out</button>
        </div>
      </aside>

      <main className="pilot-chat">
        <header className="chat-header">
          <button
            className="mobile-navigation"
            aria-label="Open navigation"
            onClick={() => setSidebarOpen(true)}
          >
            ☰
          </button>
          <div>
            <strong>{selected?.title ?? "New chat"}</strong>
            <span>Prompt improvement assistant</span>
          </div>
          <div
            className="header-score"
            aria-label={`Prompt quality ${displayedScore} out of 100`}
          >
            <select
              className="chat-model-select"
              aria-label="Chat model"
              value={connectionId}
              disabled={Boolean(busy)}
              onChange={(event) => {
                if (event.target.value === "connect") {
                  setModelsOpen(true);
                  return;
                }
                setConnectionId(event.target.value);
                connectionRef.current = event.target.value || undefined;
                localStorage.setItem(
                  "promptpilot:chat-provider",
                  event.target.value,
                );
              }}
            >
              <option value="">
                Auto · {connections.at(-1)?.default_model || "backend model"}
              </option>
              {connections.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label} · {item.default_model}
                </option>
              ))}
              <option value="connect">＋ Add API key / model…</option>
            </select>
            <button
              className="chat-model-settings"
              type="button"
              aria-label="Open models and API keys"
              onClick={() => setModelsOpen(true)}
            >
              ◈ <span>Models & keys</span>
            </button>
            <QualityRing score={displayedScore} compact />
            <span>Quality</span>
          </div>
        </header>
        {!connections.length && !loading && (
          <div className="chat-connect-banner">
            <span className="connect-banner-mark">✦</span>
            <div>
              <strong>Choose the AI behind your prompts</strong>
              <span>
                Add your API key and select a model for adaptive questions and
                prompt generation.
              </span>
            </div>
            <button type="button" onClick={() => setModelsOpen(true)}>
              Connect AI →
            </button>
          </div>
        )}

        <div className="chat-scroll" aria-live="polite">
          {loading ? (
            <div className="assistant-thinking">
              Restoring your conversation…
            </div>
          ) : messages.length === 0 ? (
            <Welcome setDraft={setDraft} />
          ) : (
            <div className="chat-thread">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`chat-message ${message.role === "user" ? "from-user" : "from-pilot"}`}
                >
                  <div className="message-avatar">
                    {message.role === "user" ? "You" : "P"}
                  </div>
                  <div className="message-body">
                    <strong>
                      {message.role === "user" ? "You" : "PromptPilot"}
                    </strong>
                    <p>{message.content}</p>
                  </div>
                </div>
              ))}

              {source && (analysis || busy === "improve") && (
                <AnalysisMessage
                  analysis={analysis}
                  busy={busy === "improve"}
                />
              )}

              {source && !analysis && !busy && (
                <section className="generation-recovery" role="status">
                  <strong>
                    Your prompt is saved; analysis still needs to finish
                  </strong>
                  <p>
                    Continue with this saved text instead of submitting it
                    again.
                  </p>
                  <button
                    type="button"
                    onClick={resumeSavedPrompt}
                    disabled={!canWrite}
                  >
                    Continue saved prompt
                  </button>
                </section>
              )}

              {questions && questions.answered_questions.length > 0 && (
                <ClarificationHistory session={questions} />
              )}

              {questions?.next_question && (
                <QuestionMessage
                  session={questions}
                  onChoose={(value) => void submitClarification(value)}
                  onSkip={skipCurrentQuestion}
                  onReply={() => replyBox.current?.focus()}
                  busy={Boolean(busy)}
                  adaptive={Boolean(
                    analysis?.ai_succeeded &&
                    analysis.analysis_version === "prompt-analyzer-v3",
                  )}
                  onConnect={() => setModelsOpen(true)}
                  canReassess={Boolean(
                    connections.length || analysis?.ai_succeeded,
                  )}
                  onReassess={() => void reassessCurrentPrompt()}
                />
              )}

              {source &&
                !questions?.next_question &&
                busy === "improve" &&
                analysis && (
                  <div className="assistant-thinking">
                    Building your improved prompt…
                  </div>
                )}

              {currentPrompt && (
                <PromptResult
                  projectId={projectId}
                  prompt={currentPrompt}
                  copied={copied}
                  onCopy={async () => {
                    await navigator.clipboard.writeText(
                      currentPrompt.optimized_prompt,
                    );
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1500);
                  }}
                  onRegenerate={regenerate}
                  onExecute={execute}
                  busy={busy}
                />
              )}

              {source &&
                analysis &&
                questions?.status === "completed" &&
                !currentPrompt && (
                  <section className="generation-recovery" role="status">
                    <strong>
                      {busy === "generate"
                        ? "Generating your improved prompt…"
                        : error
                          ? "Generation needs attention"
                          : "Ready to improve this prompt"}
                    </strong>
                    <p>
                      {busy === "generate"
                        ? "Using your prompt and saved answers."
                        : error
                          ? "Your answers are saved. The error below explains what needs attention."
                          : "Continue generation with your saved prompt and answers."}
                    </p>
                    <button
                      type="button"
                      disabled={!canWrite || Boolean(busy)}
                      onClick={regenerate}
                    >
                      {busy === "generate"
                        ? "Generating…"
                        : error
                          ? "Retry generation"
                          : "Generate improved prompt"}
                    </button>
                  </section>
                )}

              {relatedRuns.map((run) => (
                <RunMessage key={run.id} run={run} />
              ))}
            </div>
          )}
          {error && (
            <div className="chat-error" role="alert">
              <strong>Something needs attention</strong>
              <span>{error}</span>
            </div>
          )}
          {introNotice && (
            <div className="chat-intro-notice" role="status">
              {introNotice}
            </div>
          )}
          <div ref={chatEnd} />
        </div>

        <form className="bottom-composer" onSubmit={submit}>
          {questions?.next_question && (
            <div className="reply-target" id="reply-target">
              <strong>Replying to PromptPilot</strong>
              <span>{questions.next_question.text}</span>
            </div>
          )}
          <div className="composer-quality">
            <span
              className={`quality-dot quality-${qualityTone(liveQuality.score)}`}
            />
            {liveQuality.score}/100 · {liveQuality.label}
          </div>
          <div className="composer-box">
            <textarea
              ref={replyBox}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={
                questions?.next_question
                  ? "Type your answer to the question above…"
                  : "Describe what you want to achieve…"
              }
              rows={2}
              disabled={!canWrite || loading || Boolean(busy)}
              aria-describedby={
                questions?.next_question ? "reply-target" : undefined
              }
              aria-label={
                questions?.next_question
                  ? "Clarification answer"
                  : "Prompt to improve"
              }
            />
            <button
              aria-label={
                questions?.next_question ? "Send answer" : "Improve prompt"
              }
              title={
                questions?.next_question ? "Send answer" : "Improve prompt"
              }
              disabled={!canWrite || loading || Boolean(busy) || !draft.trim()}
            >
              {busy === "answer"
                ? "Saving reply…"
                : busy
                  ? "Working…"
                  : questions?.next_question
                    ? "Send answer"
                    : "Improve prompt"}
            </button>
          </div>
          <small>
            {questions?.next_question
              ? "Your answer will be saved and included in the improved prompt"
              : "Enter to improve · Shift + Enter for a new line"}
          </small>
        </form>
      </main>

      <aside className="insight-panel">
        {toolView === "quality" ? (
          <QualityPanel quality={liveQuality} analysis={displayedAnalysis} />
        ) : (
          <SourcesPanel
            projectId={projectId}
            documents={documents}
            busy={busy}
            url={url}
            setUrl={setUrl}
            act={act}
            reload={loadDocuments}
          />
        )}
      </aside>
      {modelsOpen && (
        <WorkspaceModal title="Models & API keys" onClose={closeModels} wide>
          {modelsError && (
            <p className="workflow-alert error" role="alert">
              {modelsError}
              <button
                type="button"
                onClick={() => {
                  setModelsError("");
                  void Promise.all([
                    refreshConnections(),
                    getProviderCatalog().then(setCatalog),
                  ]).catch((caught) =>
                    setModelsError(
                      friendlyError(caught, "Could not load model settings."),
                    ),
                  );
                }}
              >
                Retry
              </button>
            </p>
          )}
          <ConnectionVault
            catalog={catalog}
            connections={allConnections}
            canWrite={canWrite}
            onRefresh={refreshConnections}
            onConnected={(item) => {
              setConnectionId(item.id);
              connectionRef.current = item.id;
              localStorage.setItem("promptpilot:chat-provider", item.id);
            }}
          />
        </WorkspaceModal>
      )}
    </div>
  );
}

function Welcome({ setDraft }: { setDraft: (value: string) => void }) {
  const starters = [
    "Write a professional proposal",
    "Plan a software feature",
    "Analyse business data",
  ];
  return (
    <section className="pilot-welcome">
      <div className="welcome-mark">P</div>
      <h1>What are you trying to achieve?</h1>
      <p>
        Write your rough prompt below. PromptPilot will score it, find what is
        missing, ask only useful questions, and return a stronger version.
      </p>
      <div className="starter-grid">
        {starters.map((starter) => (
          <button type="button" key={starter} onClick={() => setDraft(starter)}>
            {starter}
          </button>
        ))}
      </div>
    </section>
  );
}

function AnalysisMessage({
  analysis,
  busy,
}: {
  analysis: PromptAnalysis | null;
  busy: boolean;
}) {
  const gaps = analysis?.gaps.filter((gap) => gap.status !== "resolved") || [];
  if (!analysis)
    return (
      <div className="assistant-thinking">
        Analysing clarity, context, constraints, and format…
      </div>
    );

  return (
    <div className="chat-message from-pilot">
      <div className="message-avatar">P</div>
      <div className="message-body assistant-card">
        <strong>PromptPilot</strong>
        <div className="analysis-summary">
          <QualityRing score={analysis.overall_score} />
          <div>
            <h3>
              {analysis.overall_score >= 75
                ? "This is a solid start"
                : "I can make this much stronger"}
            </h3>
            <p>
              {gaps.length === 0
                ? "Your goal and instructions are clear. I’m preparing the improved version."
                : `I found ${gaps.length} area${gaps.length === 1 ? "" : "s"} that could reduce answer quality.`}
            </p>
          </div>
        </div>
        {gaps.length > 0 && (
          <div className="recommendation-list">
            {gaps.slice(0, 4).map((gap) => (
              <div key={gap.id}>
                <span className={`severity-dot severity-${gap.severity}`} />
                <div>
                  <strong>{gap.title}</strong>
                  <p>{gap.description}</p>
                </div>
              </div>
            ))}
          </div>
        )}
        {busy && <small>Checking whether one clarification is needed…</small>}
      </div>
    </div>
  );
}

function ClarificationHistory({ session }: { session: QuestionSession }) {
  return (
    <div className="clarification-history">
      {session.answered_questions.map((item) => (
        <div
          key={item.id}
          className="chat-message from-user clarification-answer"
        >
          <div className="message-avatar">You</div>
          <div className="message-body">
            <small>Answer to: {item.question}</small>
            <p>{item.content}</p>
            <span className="answer-saved">✓ Saved for prompt generation</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function QuestionMessage({
  session,
  onChoose,
  onSkip,
  onReply,
  busy,
  adaptive,
  onConnect,
  canReassess,
  onReassess,
}: {
  session: QuestionSession;
  onChoose: (value: string) => void;
  onSkip: () => void;
  onReply: () => void;
  busy: boolean;
  adaptive: boolean;
  onConnect: () => void;
  canReassess: boolean;
  onReassess: () => void;
}) {
  const question = session.next_question!;
  return (
    <div className="chat-message from-pilot">
      <div className="message-avatar">P</div>
      <div className="message-body question-message">
        <strong>One useful question</strong>
        <span
          className={`question-source ${adaptive || question.source === "ai" ? "adaptive" : ""}`}
        >
          {adaptive || question.source === "ai"
            ? "Based on your prompt and replies"
            : "Offline suggestion"}
        </span>
        <h3>{question.text}</h3>
        {question.options && (
          <div className="answer-options">
            {question.options.map((option) => (
              <button
                type="button"
                key={option}
                onClick={() => onChoose(option)}
                disabled={busy}
              >
                {option}
              </button>
            ))}
          </div>
        )}
        <div className="question-guidance">
          <span>Reply in the main box below</span>
          <button type="button" onClick={onReply} disabled={busy}>
            Reply
          </button>
          <button
            type="button"
            className="subtle-button"
            onClick={onSkip}
            disabled={busy}
          >
            Skip
          </button>
        </div>
        {canReassess && !adaptive ? (
          <button
            type="button"
            className="question-connect-link"
            disabled={busy}
            onClick={onReassess}
          >
            Recheck with selected model ↗
          </button>
        ) : (
          !adaptive &&
          question.source !== "ai" && (
            <button
              className="question-connect-link"
              type="button"
              onClick={onConnect}
            >
              Connect a model for adaptive questions ↗
            </button>
          )
        )}
      </div>
    </div>
  );
}

function PromptResult({
  projectId,
  prompt,
  copied,
  onCopy,
  onRegenerate,
  onExecute,
  busy,
}: {
  projectId: string;
  prompt: GeneratedPrompt;
  copied: boolean;
  onCopy: () => void;
  onRegenerate: () => void;
  onExecute: (strategy: "baseline" | "promptpilot") => void;
  busy: string;
}) {
  const recommendations = recommendModels(
    `${prompt.original_prompt}\n${prompt.optimized_prompt}`,
  );
  return (
    <div className="chat-message from-pilot">
      <div className="message-avatar">P</div>
      <div className="message-body prompt-result">
        <div className="result-heading">
          <div>
            <span className="success-pill">Improved</span>
            <h3>Your prompt is ready</h3>
          </div>
          <small>Version {prompt.version_number}</small>
        </div>
        <div className="optimized-prompt">{prompt.optimized_prompt}</div>
        <div className="delivery-choice">
          <strong>What would you like to do next?</strong>
          <p>
            Use the prompt in an AI chat, or plan this project with your AI
            team.
          </p>
          <a
            href={`/projects/${projectId}/agents`}
            onClick={() =>
              sessionStorage.setItem(
                `promptpilot:delivery-idea:${projectId}`,
                prompt.optimized_prompt,
              )
            }
          >
            Plan and build this project →
          </a>
        </div>
        {prompt.quality_notes.length > 0 && (
          <div className="improvement-notes">
            {prompt.quality_notes.slice(0, 3).map((note) => (
              <span key={note}>✓ {note}</span>
            ))}
          </div>
        )}
        <div className="result-actions">
          <button onClick={onCopy}>{copied ? "Copied" : "Copy prompt"}</button>
          <button
            className="secondary-action"
            onClick={onRegenerate}
            disabled={Boolean(busy)}
          >
            {busy === "generate" ? "Improving…" : "Improve again"}
          </button>
          <button
            className="secondary-action"
            onClick={() => onExecute("baseline")}
            disabled={Boolean(busy)}
          >
            Test original
          </button>
          <button
            className="secondary-action"
            onClick={() => onExecute("promptpilot")}
            disabled={Boolean(busy)}
          >
            Test improved
          </button>
        </div>
        <div className="model-recommendations">
          <div className="model-recommendation-heading">
            <strong>Best AI for this prompt</strong>
            <span>PromptPilot recommendation</span>
          </div>
          <div className="model-recommendation-list">
            {recommendations.map((recommendation, index) => (
              <div key={recommendation.id} className="model-recommendation">
                <div>
                  <span>{index === 0 ? "Recommended" : "Also suitable"}</span>
                  <strong>{recommendation.name}</strong>
                  <small>{recommendation.reason}</small>
                </div>
                <a
                  href={recommendation.url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => {
                    void navigator.clipboard.writeText(prompt.optimized_prompt);
                  }}
                  title={`Copy the improved prompt and open ${recommendation.name}`}
                >
                  Copy &amp; open {recommendation.name} ↗
                </a>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function RunMessage({ run }: { run: ModelRun }) {
  return (
    <div className="chat-message from-pilot">
      <div className="message-avatar">AI</div>
      <div className="message-body run-message">
        <div className="result-heading">
          <strong>
            {run.execution_strategy === "baseline"
              ? "Original prompt response"
              : "Improved prompt response"}
          </strong>
          <span className={`run-status run-${run.status}`}>
            {humanize(run.status)}
          </span>
        </div>
        <p>
          {run.response_text ??
            run.error_message ??
            "No response was returned."}
        </p>
        <small>
          {run.provider} · {run.model}
          {run.latency_ms ? ` · ${run.latency_ms} ms` : ""}
        </small>
      </div>
    </div>
  );
}

function QualityPanel({
  quality,
  analysis,
}: {
  quality: PromptQuality;
  analysis: PromptAnalysis | null;
}) {
  const score = analysis?.overall_score ?? quality.score;
  const gap = analysis?.gaps.find((item) => item.status !== "resolved");
  return (
    <div className="tool-panel-content">
      <div className="tool-panel-heading">
        <span>Prompt quality</span>
        <small>Live</small>
      </div>
      <div className="large-quality">
        <QualityRing score={score} />
        <div>
          <strong>{score}/100</strong>
          <span>{qualityLabel(score)}</span>
        </div>
      </div>
      <p className="panel-intro">
        A strong prompt clearly communicates the goal, context, limits,
        audience, and expected output.
      </p>
      <div className="criteria-list">
        {quality.criteria.map((criterion) => (
          <div key={criterion.key}>
            <span
              className={
                criterion.present ? "criterion-good" : "criterion-missing"
              }
            >
              {criterion.present ? "✓" : "·"}
            </span>
            <div>
              <strong>{criterion.label}</strong>
              <small>
                {criterion.present ? "Detected" : criterion.suggestion}
              </small>
            </div>
            <b>
              {criterion.score}/{criterion.maximum}
            </b>
          </div>
        ))}
      </div>
      {gap && (
        <div className="next-improvement">
          <strong>Best next improvement</strong>
          <p>{gap.description}</p>
        </div>
      )}
    </div>
  );
}

function SourcesPanel({
  projectId,
  documents,
  busy,
  url,
  setUrl,
  act,
  reload,
}: {
  projectId: string;
  documents: DocumentItem[];
  busy: string;
  url: string;
  setUrl: (value: string) => void;
  act: (
    key: string,
    action: () => Promise<void>,
    fallback: string,
  ) => Promise<void>;
  reload: () => Promise<void>;
}) {
  return (
    <div className="tool-panel-content">
      <div className="tool-panel-heading">
        <span>Sources</span>
        <small>{documents.length}</small>
      </div>
      <p className="panel-intro">
        Add optional material PromptPilot should consider. You do not need to
        select a service or model.
      </p>
      <label className="source-upload">
        <span>＋</span>
        <strong>Upload a file</strong>
        <small>PDF, DOCX, TXT, CSV or XLSX</small>
        <input
          type="file"
          accept=".txt,.md,.pdf,.docx,.csv,.xlsx"
          disabled={Boolean(busy)}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            void act(
              "file",
              async () => {
                await uploadDocument(projectId, file);
                await reload();
              },
              "That file could not be processed.",
            );
          }}
        />
      </label>
      <div className="url-source">
        <input
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="Paste a public URL"
        />
        <button
          disabled={Boolean(busy) || !url.trim()}
          onClick={() =>
            void act(
              "url",
              async () => {
                await addDocumentUrl(projectId, url.trim());
                setUrl("");
                await reload();
              },
              "That URL could not be processed.",
            )
          }
        >
          Add
        </button>
      </div>
      <div className="source-list">
        {documents.length === 0 ? (
          <p>No sources added. PromptPilot can still improve your prompt.</p>
        ) : (
          documents.map((document) => (
            <div key={document.id}>
              <span>▤</span>
              <div>
                <strong>{document.name}</strong>
                <small>{humanize(document.status)}</small>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function QualityRing({
  score,
  compact = false,
}: {
  score: number;
  compact?: boolean;
}) {
  const safeScore = Math.max(0, Math.min(100, Math.round(score)));
  return (
    <div
      className={`quality-ring ${compact ? "quality-ring-compact" : ""}`}
      style={{ "--quality": `${safeScore * 3.6}deg` } as React.CSSProperties}
      aria-hidden="true"
    >
      <span>{safeScore}</span>
    </div>
  );
}

const qualityLabel = (score: number) =>
  score >= 85
    ? "Excellent"
    : score >= 65
      ? "Strong"
      : score >= 40
        ? "Getting there"
        : "Needs work";
const qualityTone = (score: number) =>
  score >= 75 ? "good" : score >= 40 ? "medium" : "low";
