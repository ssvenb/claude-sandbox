import { createContext, useContext } from 'react';
import type { Answers } from '../../api/events';

/** What the parts of a conversation can do to its session. */
export interface ChatActions {
  /** Answers a question of the agent's, or dismisses it. */
  answer: (ask: string, reply: { answers: Answers } | { cancel: true }) => void;
  /** Starts the run again, in this tab. */
  resume: () => Promise<void>;
  /** Stops a task the agent runs: in the background, or one a tool call waits on. */
  stopTask: (task: string) => Promise<unknown>;
  /** Sends the task a tool call waits on to the background. */
  background: (call: string) => Promise<unknown>;
  /** A message that could not be sent: tries again, or takes it back into the field to change. */
  resend: (nonce: string) => void;
  edit: (nonce: string) => void;
}

export const ChatContext = createContext<ChatActions | null>(null);

export function useChatActions(): ChatActions {
  const actions = useContext(ChatContext);
  if (!actions) throw new Error('not inside a chat');
  return actions;
}
