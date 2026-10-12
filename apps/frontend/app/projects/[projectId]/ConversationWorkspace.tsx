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
  executePrompt,
  friendlyError,
  generatePrompt,
  getConversations,
  getDocuments,
  getGeneratedPrompts,
  getLatestAnalysis,
  getMessages,
  getNextQuestion,
  getRuns,
  sendMessage,
  skipQuestion,
  uploadDocument,
} from "../../../lib/conversations";
import {
  assessPromptQuality,
  PromptQuality,
} from "../../../lib/prompt-quality";
import { recommendModels } from "../../../lib/model-recommendations";

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
        const item = await createConversation(projectId, "New prompt");
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

  async function generateFor(conversationId: string, messageId: string) {
    const prompt = await generatePrompt(
      conversationId,
      messageId,
      "structured",
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
    const result = await analyzeMessage(conversationId, messageId);
    setAnalysis(result);
    const session = await getNextQuestion(conversationId, messageId);
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

    await act(
      "improve",
      async () => {
        let conversation = selected;
        if (!conversation) {
          conversation = await createConversation(projectId, "New prompt");
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
        );
        setDraft("");
        setQuestions(result);
        if (!result.next_question)
          await generateAfterSaving(selected.id, source.id);
      },
      "PromptPilot could not skip that question.",
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
      "The configured AI model is unavailable. Check the server-side OpenRouter settings.",
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
      <aside className="pilot-sidebar" aria-label="PromptPilot navigation">
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
          <span>＋</span> New prompt
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
        </div>
        <div className="sidebar-section chat-history">
          <small>RECENT</small>
          {conversations.length === 0 ? (
            <p>No saved prompts yet</p>
          ) : (
            conversations.map((item) => (
              <button
                key={item.id}
                className={selected?.id === item.id ? "chat-active" : ""}
                disabled={loading || Boolean(busy)}
                onClick={() => {
                  setSelected(item);
                  void loadConversation(item);
                }}
              >
                <span>⌁</span>
                <span>{item.title}</span>
              </button>
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
          <div>
            <strong>{selected?.title ?? "New prompt"}</strong>
            <span>Prompt improvement assistant</span>
          </div>
          <div
            className="header-score"
            aria-label={`Prompt quality ${liveQuality.score} out of 100`}
          >
            <QualityRing
              score={analysis?.overall_score ?? liveQuality.score}
              compact
            />
            <span>Quality</span>
          </div>
        </header>

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
                        ? "Sending your saved answers to the model…"
                        : "Your prompt and replies are saved"}
                    </strong>
                    <p>
                      The improved prompt will use the saved clarification
                      answers. You do not need to type them again.
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
          <QualityPanel quality={liveQuality} analysis={analysis} />
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
}: {
  session: QuestionSession;
  onChoose: (value: string) => void;
  onSkip: () => void;
  onReply: () => void;
  busy: boolean;
}) {
  const question = session.next_question!;
  return (
    <div className="chat-message from-pilot">
      <div className="message-avatar">P</div>
      <div className="message-body question-message">
        <strong>One useful question</strong>
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
      </div>
    </div>
  );
}

function PromptResult({
  prompt,
  copied,
  onCopy,
  onRegenerate,
  onExecute,
  busy,
}: {
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
