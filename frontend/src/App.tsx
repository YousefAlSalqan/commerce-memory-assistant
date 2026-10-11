import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Memory, Message, Persona, Session, User } from "./types";

type View = "chat" | "memories" | "persona" | "sessions";

const categoryLabels: Record<string, string> = {
  dietary_restriction: "Dietary",
  allergy: "Allergy",
  cuisine_preference: "Cuisine",
  budget: "Budget",
  merchant_preference: "Merchant",
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function App() {
  const bootstrapped = useRef(false);
  const [view, setView] = useState<View>("chat");
  const [users, setUsers] = useState<User[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [persona, setPersona] = useState<Persona | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [input, setInput] = useState("");
  const [newUser, setNewUser] = useState("");
  const [selectedTranscript, setSelectedTranscript] = useState<Message[]>([]);
  const [editing, setEditing] = useState<Memory | null>(null);
  const [editDescription, setEditDescription] = useState("");
  const [editValue, setEditValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refreshUserData = useCallback(async (selected: User) => {
    const [nextMemories, nextPersona, nextSessions] = await Promise.all([
      api.memories(selected.id),
      api.persona(selected.id),
      api.sessions(selected.id),
    ]);
    setMemories(nextMemories);
    setPersona(nextPersona);
    setSessions(nextSessions);
    const active = nextSessions.find((item) => item.status === "active") ?? null;
    setSession(active);
    setMessages(active ? await api.messages(active.id) : []);
  }, []);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    void (async () => {
      try {
        let available = await api.users();
        if (!available.length) available = [await api.createUser("Yousef")];
        setUsers(available);
        setUser(available[0]);
        await refreshUserData(available[0]);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Unable to load the application.");
      } finally {
        setLoading(false);
      }
    })();
  }, [refreshUserData]);

  async function selectUser(id: string) {
    const selected = users.find((item) => item.id === id);
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      setUser(selected);
      await refreshUserData(selected);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to change profiles.");
    } finally {
      setBusy(false);
    }
  }

  async function addUser(event: FormEvent) {
    event.preventDefault();
    if (!newUser.trim()) return;
    setBusy(true);
    try {
      const created = await api.createUser(newUser.trim());
      setUsers((current) => [...current, created]);
      setUser(created);
      setNewUser("");
      await refreshUserData(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to create the profile.");
    } finally {
      setBusy(false);
    }
  }

  async function ensureSession() {
    if (session) return session;
    if (!user) throw new Error("Select a user first.");
    const created = await api.createSession(user.id);
    setSession(created);
    setSessions((current) => [created, ...current]);
    return created;
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const content = input.trim();
    if (!content || busy) return;
    setBusy(true);
    setError("");
    setInput("");
    try {
      const active = await ensureSession();
      await api.sendMessage(active.id, content);
      setMessages(await api.messages(active.id));
    } catch (reason) {
      setInput(content);
      setError(reason instanceof Error ? reason.message : "Unable to send the message.");
    } finally {
      setBusy(false);
    }
  }

  async function endSession() {
    if (!session || !user) return;
    setBusy(true);
    setError("");
    try {
      await api.endSession(session.id);
      setSession(null);
      setMessages([]);
      await refreshUserData(user);
      setView("memories");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to end the session.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleMemory() {
    if (!user) return;
    const updated = await api.updateUser(user.id, { memory_enabled: !user.memory_enabled });
    setUser(updated);
    setUsers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function confirmMemory(id: string) {
    await api.confirmMemory(id);
    if (user) await refreshUserData(user);
  }

  async function deleteMemory(id: string) {
    if (!window.confirm("Forget this memory and its evidence?")) return;
    await api.deleteMemory(id);
    if (user) await refreshUserData(user);
  }

  function beginEdit(memory: Memory) {
    setEditing(memory);
    setEditDescription(memory.description);
    setEditValue(JSON.stringify(memory.value, null, 2));
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editing || !user) return;
    try {
      await api.correctMemory(editing.id, JSON.parse(editValue), editDescription);
      setEditing(null);
      await refreshUserData(user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The correction could not be saved.");
    }
  }

  async function showTranscript(item: Session) {
    setSelectedTranscript(await api.messages(item.id));
  }

  if (loading) {
    return <main className="center-state" aria-live="polite">Loading memory workspace...</main>;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">R</span>
          <div><strong>Recall</strong><span>Commerce memory lab</span></div>
        </div>

        <nav aria-label="Primary navigation">
          {(["chat", "memories", "persona", "sessions"] as View[]).map((item) => (
            <button
              className={view === item ? "nav-button active" : "nav-button"}
              key={item}
              onClick={() => setView(item)}
            >
              {item[0].toUpperCase() + item.slice(1)}
              {item === "memories" && <span>{memories.filter((m) => m.status === "active").length}</span>}
            </button>
          ))}
        </nav>

        <div className="profile-block">
          <label htmlFor="profile">Demo profile</label>
          <select id="profile" value={user?.id ?? ""} onChange={(event) => void selectUser(event.target.value)}>
            {users.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}
          </select>
          <form className="new-user" onSubmit={addUser}>
            <label htmlFor="new-user">Add profile</label>
            <div><input id="new-user" value={newUser} onChange={(event) => setNewUser(event.target.value)} /><button disabled={busy}>Add</button></div>
          </form>
          <label className="consent-row">
            <input type="checkbox" checked={user?.memory_enabled ?? false} onChange={() => void toggleMemory()} />
            Save long-term memory
          </label>
        </div>
      </aside>

      <main className="workspace">
        {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError("")} aria-label="Dismiss error">Close</button></div>}

        {view === "chat" && (
          <section className="chat-layout">
            <div className="chat-column">
              <header className="page-header">
                <div><p>Conversation</p><h1>{session ? "Active session" : "Start a new session"}</h1></div>
                {session && <button className="secondary" onClick={() => void endSession()} disabled={busy}>End session</button>}
              </header>
              <div className="transcript" aria-live="polite">
                {!messages.length && (
                  <div className="empty-state">
                    <h2>Make memory visible</h2>
                    <p>State a durable preference, end the session, then start another conversation to see it applied.</p>
                    <button onClick={() => setInput("I'm vegetarian, allergic to peanuts, and I usually spend under $25 per meal. I love Thai food.")}>Use demo prompt</button>
                  </div>
                )}
                {messages.map((message) => (
                  <article className={`message ${message.role}`} key={message.id}>
                    <span>{message.role === "user" ? user?.display_name : "Recall"}</span>
                    <p>{message.content}</p>
                  </article>
                ))}
              </div>
              <form className="composer" onSubmit={send}>
                <label htmlFor="message">Message</label>
                <textarea id="message" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Describe what you want to order" rows={2} />
                <button disabled={busy || !input.trim()}>{busy ? "Working..." : "Send"}</button>
              </form>
            </div>
            <aside className="context-panel">
              <p className="section-label">Active memory</p>
              <h2>What the assistant knows</h2>
              {!memories.some((memory) => memory.status === "active") && <p className="muted">No active memories yet.</p>}
              {memories.filter((memory) => memory.status === "active").map((memory) => (
                <div className="context-memory" key={memory.id}>
                  <span>{categoryLabels[memory.category]}</span>
                  <strong>{memory.description}</strong>
                </div>
              ))}
              <div className="session-key"><span>Session ID</span><code>{session?.id ?? "Created with first message"}</code></div>
            </aside>
          </section>
        )}

        {view === "memories" && (
          <section>
            <header className="page-header"><div><p>Evidence-backed profile</p><h1>Memories</h1></div></header>
            {!memories.length && <div className="empty-state compact"><h2>No memories saved</h2><p>End a session containing a durable preference to create one.</p></div>}
            <div className="memory-list">
              {memories.map((memory) => (
                <article className="memory-row" key={memory.id}>
                  <div className="memory-main">
                    <div className="memory-meta"><span>{categoryLabels[memory.category]}</span><span>{memory.status}</span></div>
                    <h2>{memory.description}</h2>
                    <p>{memory.source_type} source, {Math.round(memory.confidence * 100)}% confidence</p>
                    {!!memory.evidence.length && <details><summary>View evidence</summary>{memory.evidence.map((item) => <blockquote key={item.id}>{item.content}</blockquote>)}</details>}
                  </div>
                  <div className="row-actions">
                    {memory.status === "candidate" && <button onClick={() => void confirmMemory(memory.id)}>Confirm</button>}
                    {memory.status !== "superseded" && <button onClick={() => beginEdit(memory)}>Correct</button>}
                    <button className="danger" onClick={() => void deleteMemory(memory.id)}>Forget</button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {view === "persona" && (
          <section>
            <header className="page-header"><div><p>Generated snapshot</p><h1>Customer persona</h1></div>{persona && <span className="version">Version {persona.version}</span>}</header>
            {persona && <div className="persona-layout"><div className="persona-summary"><p>{persona.summary}</p><small>Generated {formatDate(persona.created_at)}</small></div><div className="profile-data">{Object.entries(persona.profile).map(([key, values]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{values.length ? values.join(", ") : "None"}</strong></div>)}</div></div>}
          </section>
        )}

        {view === "sessions" && (
          <section>
            <header className="page-header"><div><p>Conversation history</p><h1>Sessions</h1></div></header>
            {!sessions.length && <div className="empty-state compact"><h2>No sessions yet</h2><p>Send a message to begin the first session.</p></div>}
            <div className="session-layout">
              <div className="session-list">{sessions.map((item) => <button key={item.id} onClick={() => void showTranscript(item)}><span><strong>{formatDate(item.started_at)}</strong><small>{item.status}</small></span><p>{item.summary ?? "Session in progress"}</p><code>{item.id}</code></button>)}</div>
              <div className="history-transcript">{!selectedTranscript.length ? <p className="muted">Select a session to inspect its transcript.</p> : selectedTranscript.map((message) => <article className={`message ${message.role}`} key={message.id}><span>{message.role}</span><p>{message.content}</p></article>)}</div>
            </div>
          </section>
        )}
      </main>

      {editing && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setEditing(null)}>
          <form className="modal" onSubmit={saveEdit} onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="edit-title">
            <h2 id="edit-title">Correct memory</h2>
            <label htmlFor="description">Description</label>
            <input id="description" value={editDescription} onChange={(event) => setEditDescription(event.target.value)} />
            <label htmlFor="value">Structured value</label>
            <textarea id="value" rows={7} value={editValue} onChange={(event) => setEditValue(event.target.value)} />
            <div><button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button><button>Save correction</button></div>
          </form>
        </div>
      )}
    </div>
  );
}
