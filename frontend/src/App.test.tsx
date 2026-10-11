import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";
import type { Memory, Message, Persona, Session, User } from "./types";

const now = new Date().toISOString();
const user: User = {
  id: "u1",
  display_name: "Yousef",
  memory_enabled: true,
  created_at: now,
};
const session: Session = {
  id: "s1",
  user_id: user.id,
  status: "active",
  summary: null,
  summary_data: null,
  summary_through_message_id: null,
  started_at: now,
  ended_at: null,
};
const messages: Message[] = [
  { id: "m1", session_id: session.id, role: "user", content: "I love Thai food", created_at: now },
  { id: "m2", session_id: session.id, role: "assistant", content: "I can help with that.", created_at: now },
];
const candidate: Memory = {
  id: "memory-1",
  user_id: user.id,
  category: "cuisine_preference",
  value: { name: "thai", sentiment: "likes" },
  description: "Often chooses Thai cuisine",
  source_type: "inferred",
  confidence: 0.5,
  status: "candidate",
  created_at: now,
  updated_at: now,
  evidence: [messages[0]],
};
const persona: Persona = {
  id: "p1",
  user_id: user.id,
  version: 1,
  profile: {},
  summary: "No active durable memories yet.",
  created_at: now,
};

function json(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi(memoryRows: Memory[] = []) {
  return vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith("/users") && method === "GET") return json([user]);
    if (url.endsWith("/memories") && method === "GET") return json(memoryRows);
    if (url.endsWith("/persona")) return json(persona);
    if (url.endsWith("/sessions") && method === "GET") return json([]);
    if (url.endsWith("/sessions") && method === "POST") return json(session, 201);
    if (url.endsWith("/messages") && method === "POST") {
      return json({ message: messages[1], memories_used: [], summary_updated: false });
    }
    if (url.endsWith("/messages")) return json(messages);
    if (url.endsWith("/end")) return json({});
    if (url.endsWith("/confirm")) return json({ ...candidate, status: "active" });
    if (method === "DELETE") return json(null, 204);
    throw new Error(`Unhandled request: ${method} ${url}`);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("shows the empty chat workspace", async () => {
  vi.stubGlobal("fetch", mockApi());
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Start a new session" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Use demo prompt" })).toBeInTheDocument();
});

test("sends a message and ends the created session", async () => {
  const fetchMock = mockApi();
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  await screen.findByRole("heading", { name: "Start a new session" });

  fireEvent.click(screen.getByRole("button", { name: "Use demo prompt" }));
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByText("I can help with that.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "End session" }));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/sessions/s1/end"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});

test("displays, confirms, and deletes an inferred memory", async () => {
  const fetchMock = mockApi([candidate]);
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  await screen.findByRole("heading", { name: "Start a new session" });
  fireEvent.click(screen.getByRole("button", { name: /Memories/ }));

  expect(screen.getByText("Often chooses Thai cuisine")).toBeInTheDocument();
  expect(screen.getByText("inferred source, 50% confidence")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/memories/memory-1/confirm"),
      expect.objectContaining({ method: "POST" }),
    ),
  );

  fireEvent.click(screen.getByRole("button", { name: "Forget" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/memories/memory-1"),
      expect.objectContaining({ method: "DELETE" }),
    ),
  );
});

test("shows API failures as an accessible error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "API unavailable" }, 503)));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("API unavailable");
});
