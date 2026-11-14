// What a session is called, and how it says it is doing.
import type { Session, SessionStatus } from '../api/types';

/** A project's name: the last part of its path. */
export const projectName = (path: string): string => path.replace(/\/+$/, '').split('/').pop() ?? '';

/** A session's short name: its run. */
export const label = (s: Session): string => (s.kind === 'shell' ? 'terminal' : s.run_id + (s.kind === 'resume' ? ' (resumed)' : ''));

/** What a session is called: what it was first asked, else its run. */
export const titled = (s: Session): string => s.title || (s.kind === 'shell' ? 'Terminal' : 'Session ' + s.run_id);

export const SAYS: Record<SessionStatus, string> = {
  starting: 'starting its sandbox',
  working: 'working',
  idle: 'idle, waiting for its next task',
  question: 'waiting on your answer',
};
export const SHORT: Record<SessionStatus, string> = { starting: 'Starting', working: 'Working', idle: 'Idle', question: 'Needs you' };

/** A session's page: its chat, or the terminal of one that runs in a pty. */
export const sessionPage = (s: Pick<Session, 'id' | 'ui'>): string => (s.ui === 'chat' ? '/chat#' : '/session#') + s.id;

/** The session this page is for: named after the `#` of its address. */
export const sessionIdFromLocation = (): string => location.hash.slice(1);

/** The tab the dashboard lives in, where a session's way back lands. */
export const DASHBOARD_TAB = 'sandbox-dashboard';
