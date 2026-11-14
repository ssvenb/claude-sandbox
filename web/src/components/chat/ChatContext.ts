import { createContext, useContext } from 'react';
import type { Answers } from '../../api/events';

/** What the parts of a conversation can do to its session. */
export interface ChatActions {
  /** Answers a question of the agent's, or dismisses it. */
  answer: (ask: string, reply: { answers: Answers } | { cancel: true }) => void;
  /** Starts the run again, in this tab. */
  resume: () => Promise<void>;
  /** Stops something the agent runs in the background. */
  stopTask: (task: string) => Promise<unknown>;
}

export const ChatContext = createContext<ChatActions | null>(null);

export function useChatActions(): ChatActions {
  const actions = useContext(ChatContext);
  if (!actions) throw new Error('not inside a chat');
  return actions;
}
