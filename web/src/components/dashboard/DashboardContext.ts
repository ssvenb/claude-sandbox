import { createContext, useContext, type MouseEvent } from 'react';
import type { Item, NewSession, Session } from '../../api/types';

/** What the dashboard's buttons do. Whatever opens a tab opens it inside the click. */
export interface DashboardActions {
  /** Starts a session, in a new tab. */
  start: (what: NewSession) => Promise<void>;
  /** A project's terminal, a shell on this machine in its directory: one per project. */
  openTerminal: (project: string) => Promise<void>;
  stop: (s: Session) => Promise<void>;
  remove: (s: Session) => Promise<void>;
  /** A session's page, in its one tab. */
  show: (s: Session) => void;
  /** A listed item's page, in its one tab; `s` is the session it is listed on. */
  openItem: (e: MouseEvent, item: Item, s?: Session) => void;
  /** Opens a project's settings. */
  configure: (project: string) => Promise<void>;
}

export const DashboardContext = createContext<DashboardActions | null>(null);

export function useDashboardActions(): DashboardActions {
  const actions = useContext(DashboardContext);
  if (!actions) throw new Error('not inside the dashboard');
  return actions;
}
