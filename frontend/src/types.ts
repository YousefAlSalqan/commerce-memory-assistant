export type User = {
  id: string;
  display_name: string;
  memory_enabled: boolean;
  created_at: string;
};
export type Session = {
  id: string;
  user_id: string;
  status: "active" | "processing" | "closed";
  summary: string | null;
  summary_data: Record<string, unknown> | null;
  summary_through_message_id: string | null;
  started_at: string;
  ended_at: string | null;
};

export type Message = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type Memory = {
  id: string;
  user_id: string;
  category: string;
  value: Record<string, unknown>;
  description: string;
  source_type: "explicit" | "inferred";
  confidence: number;
  status: "candidate" | "active" | "superseded";
  created_at: string;
  updated_at: string;
  evidence: Message[];
};

export type Persona = {
  id: string;
  user_id: string;
  version: number;
  profile: Record<string, unknown[]>;
  summary: string;
  created_at: string;
};

export type ChatResponse = {
  message: Message;
  memories_used: Memory[];
  summary_updated: boolean;
};
