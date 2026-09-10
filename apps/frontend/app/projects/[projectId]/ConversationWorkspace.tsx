"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  Conversation,
  createConversation,
  getConversations,
  getMessages,
  Message,
  sendMessage,
  analyzeMessage,
  PromptAnalysis,
} from "../../../lib/conversations";
import { apiBaseUrl } from "../../../lib/projects";

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
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [analysis, setAnalysis] = useState<Record<string, PromptAnalysis>>({});
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [generationMode, setGenerationMode] = useState("structured");
  const [generated, setGenerated] = useState<
    Record<
      string,
      {
        optimized_prompt: string;
        original_prompt: string;
        task_summary: string;
        warnings: string[];
        incorporated_context: string[];
      }
    >
  >({});
  useEffect(() => {
    getConversations(projectId)
      .then((items) => {
        setConversations(items);
        setSelected(items[0] ?? null);
        setLoading(false);
      })
      .catch(() => {
        setError("We could not load conversations.");
        setLoading(false);
      });
  }, [projectId]);
  useEffect(() => {
    if (!selected) {
      setMessages([]);
      return;
    }
    getMessages(selected.id)
      .then(setMessages)
      .catch(() => setError("We could not load message history."));
  }, [selected]);
  async function newConversation() {
    const title = window.prompt("Conversation title", "New conversation");
    if (!title?.trim()) return;
    try {
      const item = await createConversation(projectId, title);
      setConversations((items) => [item, ...items]);
      setSelected(item);
    } catch {
      setError("We could not create that conversation.");
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !draft.trim()) return;
    setSending(true);
    setError("");
    const content = draft.trim();
    setDraft("");
    try {
      const message = await sendMessage(selected.id, content);
      setMessages((items) => [...items, message]);
    } catch {
      setDraft(content);
      setError("We could not send that message.");
    } finally {
      setSending(false);
    }
  }
  async function analyze(message: Message) {
    setAnalyzing(message.id);
    setError("");
    try {
      const result = await analyzeMessage(message.conversation_id, message.id);
      setAnalysis((items) => ({ ...items, [message.id]: result }));
    } catch {
      setError("Analysis could not be completed. Please try again.");
    } finally {
      setAnalyzing(null);
    }
  }
  async function generate(message: Message) {
    setGenerating(message.id);
    setError("");
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/conversations/${selected?.id}/prompts/generate`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message_id: message.id,
            mode: generationMode,
          }),
        },
      );
      if (!response.ok) throw new Error("Generation failed");
      const generatedPrompt = await response.json();
      setGenerated((items) => ({
        ...items,
        [message.id]: generatedPrompt,
      }));
    } catch {
      setError("Prompt generation could not be completed.");
    } finally {
      setGenerating(null);
    }
  }
  if (loading) return <p className="muted">Loading conversations...</p>;
  return (
    <div className="conversation-shell">
      <aside className="conversation-sidebar">
        <div className="row">
          <strong>Conversations</strong>
          {canWrite && (
            <button onClick={newConversation} title="New conversation">
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
              onClick={() => setSelected(item)}
            >
              {item.title}
            </button>
          ))
        )}
      </aside>
      <section className="conversation-main">
        {selected ? (
          <>
            <h2>{selected.title}</h2>
            <div className="message-list">
              {messages.length === 0 ? (
                <p className="muted">
                  Send the first message to start this conversation.
                </p>
              ) : (
                messages.map((message) => (
                  <article
                    className={`message message-${message.role}`}
                    key={message.id}
                  >
                    <small>{message.role}</small>
                    <p>{message.content}</p>
                    {message.role === "user" && (
                      <button
                        type="button"
                        onClick={() => analyze(message)}
                        disabled={analyzing === message.id}
                      >
                        {analyzing === message.id
                          ? "Analyzing..."
                          : "Analyze prompt"}
                      </button>
                    )}
                    {analysis[message.id] && (
                      <div className="prompt-meter">
                        <strong>
                          Prompt quality: {analysis[message.id].overall_score}
                          /100 ({analysis[message.id].status})
                        </strong>
                        <small>
                          {analysis[message.id].fallback_used
                            ? "Baseline analysis"
                            : "AI-assisted analysis"}
                        </small>
                        {analysis[message.id].dimensions
                          .filter((item) => item.applicable)
                          .map((item) => (
                            <p key={item.key}>
                              <b>{item.key.replaceAll("_", " ")}</b>:{" "}
                              {item.score}/100 - {item.explanation}
                            </p>
                          ))}
                        {analysis[message.id].gaps.length > 0 && (
                          <>
                            <b>Information gaps</b>
                            {analysis[message.id].gaps.map((gap) => (
                              <p key={gap.id}>
                                {gap.severity}: {gap.title} - {gap.description}
                              </p>
                            ))}
                          </>
                        )}
                      </div>
                    )}
                    {analysis[message.id] && canWrite && (
                      <>
                        <select
                          value={generationMode}
                          onChange={(event) =>
                            setGenerationMode(event.target.value)
                          }
                          aria-label="Generation mode"
                        >
                          <option value="minimal">Minimal</option>
                          <option value="structured">Structured</option>
                          <option value="detailed">Detailed</option>
                        </select>
                        <button
                          type="button"
                          onClick={() => generate(message)}
                          disabled={generating === message.id}
                        >
                          {generating === message.id
                            ? "Generating..."
                            : "Generate optimized prompt"}
                        </button>
                      </>
                    )}
                    {generated[message.id] && (
                      <div className="prompt-meter">
                        <h3>Original prompt</h3>
                        <p>{generated[message.id].original_prompt}</p>
                        <h3>Optimized prompt</h3>
                        <p>{generated[message.id].optimized_prompt}</p>
                        <small>{generated[message.id].task_summary}</small>
                        {generated[message.id].warnings.map((warning) => (
                          <p className="muted" key={warning}>
                            Warning: {warning}
                          </p>
                        ))}
                        <small>
                          Context sources:{" "}
                          {generated[message.id].incorporated_context.length}
                        </small>
                        <button
                          type="button"
                          onClick={() =>
                            navigator.clipboard.writeText(
                              generated[message.id].optimized_prompt,
                            )
                          }
                        >
                          Copy optimized prompt
                        </button>
                      </div>
                    )}
                  </article>
                ))
              )}
            </div>
            {error && <p className="error">{error}</p>}
            {canWrite ? (
              <form className="composer" onSubmit={submit}>
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder="Describe what you want to work on..."
                  rows={3}
                  disabled={sending}
                />
                <button disabled={sending || !draft.trim()}>
                  {sending ? "Sending..." : "Send"}
                </button>
              </form>
            ) : (
              <p className="muted">
                You have read-only access to this project.
              </p>
            )}
          </>
        ) : (
          <div className="empty-state">
            <p className="muted">Create a conversation to begin.</p>
            {canWrite && (
              <button onClick={newConversation}>New conversation</button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
