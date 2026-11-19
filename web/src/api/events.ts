// A chat session's events, as /api/sessions/<id>/events sends them: a snapshot of everything so
// far, then one event at a time (src/services/chat/chat-bridge.mjs speaks them, src/server/server.py adds a few).
import type { Picture, Session, SessionStatus } from './types';

export interface Model {
  id: string;
  name: string;
  description?: string;
}
export interface Command {
  name: string;
  description?: string;
  hint?: string;
}
/** What the agent said about itself once it was ready. */
export interface AgentInfo {
  agent?: string;
  model?: string;
  effort?: string;
  models?: Model[];
  efforts?: string[];
  commands?: Command[];
  /** It can be asked about the conversation beside it (side chats). */
  sides?: boolean;
}

export interface PlanItem {
  text: string;
  status: 'pending' | 'active' | 'done';
}
export interface BackgroundTask {
  id: string;
  kind?: string;
  text?: string;
  note?: string;
}

export interface QuestionOption {
  label: string;
  description?: string;
}
export interface Question {
  question: string;
  header?: string;
  multi?: boolean;
  plan?: string;
  options: QuestionOption[];
}
export type Answers = Record<string, string> | null;

export type ToolInput = Record<string, unknown>;

export interface AskEvent {
  type: 'ask';
  id: string;
  questions: Question[];
  done?: boolean;
  answers?: Answers;
}

/** A side chat as the server keeps it: a conversation of its own about the session's. */
export interface SideChat {
  id: string;
  title: string;
  state: SessionStatus;
  events: ChatEvent[];
}

/** An event with `side` is of that side chat, not of the session's conversation. */
export type ChatEvent = { side?: string } & (
  | { type: 'boot'; text: string }
  | { type: 'hello'; agent: string }
  | ({ type: 'ready' } & AgentInfo)
  | { type: 'user'; text: string; id?: string; images?: Picture[]; files?: string[]; queued?: boolean }
  | { type: 'sent'; id: string }
  | { type: 'text' | 'delta'; id: string; kind?: 'text' | 'thinking'; text: string; parent?: string }
  | { type: 'tool'; id: string; name?: string; title?: string; input?: ToolInput; parent?: string; done?: boolean; output?: unknown; error?: boolean; partial?: boolean }
  | { type: 'result'; id: string; output?: unknown; error?: boolean; done?: boolean; partial?: boolean }
  | { type: 'progress'; id: string; seconds?: number; text?: string }
  | AskEvent
  | { type: 'asked'; id: string }
  | { type: 'turn'; duration?: number; cost?: number; context?: { used: number; max: number }; error?: string }
  | { type: 'notice'; level?: string; text: string }
  | { type: 'status'; state: SessionStatus }
  | { type: 'model'; id: string }
  | { type: 'effort'; level: string }
  | { type: 'todos'; items: PlanItem[] | null }
  | { type: 'tasks'; items?: BackgroundTask[] }
  | { type: 'side-closed' }
  | { type: 'exit'; code: number });

export interface Snapshot {
  type: 'snapshot';
  events: ChatEvent[];
  info: AgentInfo;
  todos: PlanItem[] | null;
  tasks?: BackgroundTask[];
  sides?: SideChat[];
  ready: boolean;
  status: SessionStatus;
  session: Session;
}

export type StreamMessage = Snapshot | ChatEvent;
