import type { ChatResponse, Memory, Message, Persona, Session, User } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const api = {
  users: () => request<User[]>("/users"),
  createUser: (displayName: string) =>
    request<User>("/users", {
      method: "POST",
      body: JSON.stringify({ display_name: displayName }),
    }),
  updateUser: (id: string, values: Partial<Pick<User, "display_name" | "memory_enabled">>) =>
    request<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(values) }),
  sessions: (userId: string) => request<Session[]>(`/users/${userId}/sessions`),
  createSession: (userId: string) =>
    request<Session>(`/users/${userId}/sessions`, { method: "POST" }),
  messages: (sessionId: string) => request<Message[]>(`/sessions/${sessionId}/messages`),
  sendMessage: (sessionId: string, content: string) =>
    request<ChatResponse>(`/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  endSession: (sessionId: string) =>
    request(`/sessions/${sessionId}/end`, { method: "POST" }),
  memories: (userId: string) => request<Memory[]>(`/users/${userId}/memories`),
  confirmMemory: (memoryId: string) =>
    request<Memory>(`/memories/${memoryId}/confirm`, { method: "POST" }),
  correctMemory: (memoryId: string, value: Record<string, unknown>, description: string) =>
    request<Memory>(`/memories/${memoryId}`, {
      method: "PATCH",
      body: JSON.stringify({ value, description }),
    }),
  deleteMemory: (memoryId: string) =>
    request<void>(`/memories/${memoryId}`, { method: "DELETE" }),
  persona: (userId: string) => request<Persona>(`/users/${userId}/persona`),
};
