"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  Conversation,
  createConversation,
  getConversations,
  getMessages,
  Message,
  sendMessage,
} from "../../../lib/conversations";

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
