import { apiBaseUrl } from "./projects";

export type Conversation = {
  id: string;
  project_id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
};
export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sequence: number;
  created_at: string;
};

export async function getConversations(
  projectId: string,
): Promise<Conversation[]> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/projects/${projectId}/conversations`,
    { credentials: "include" },
  );
  if (!response.ok) throw new Error("Could not load conversations");
  return (await response.json()).items as Conversation[];
}

export async function createConversation(
  projectId: string,
  title: string,
): Promise<Conversation> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/projects/${projectId}/conversations`,
    {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    },
  );
  if (!response.ok) throw new Error("Could not create conversation");
  return response.json();
}

export async function getMessages(conversationId: string): Promise<Message[]> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/messages`,
    { credentials: "include" },
  );
  if (!response.ok) throw new Error("Could not load messages");
  return (await response.json()).items as Message[];
}

export async function sendMessage(
  conversationId: string,
  content: string,
): Promise<Message> {
  const response = await fetch(
    `${apiBaseUrl}/api/v1/conversations/${conversationId}/messages`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        "content-type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ role: "user", content }),
    },
  );
  if (!response.ok) throw new Error("Could not send message");
  return response.json();
}
