// The dashboard's data and what its buttons do. It polls /api/state (the sessions) every few
// seconds and /api/project (what each project's plugins describe, `run.sh --web`) every minute.
import { useCallback, useEffect, useMemo, useReducer, useRef, type MouseEvent } from 'react';
import { message } from '../api/client';
import * as server from '../api/sessions';
import type { AppState, Item, NewSession, ProjectInfo, Session } from '../api/types';
import type { Plugins } from '../lib/board';
import { liveItems, runItems } from '../lib/items';
import { DASHBOARD_TAB, sessionPage, titled } from '../lib/session';
import { deleteAfterAsking, stopAfterAsking } from '../lib/sessionActions';
import { announceDeleted, closeTab, isFresh, itemTab, onSessionDeleted, openTab, remember, sessionTab, terminalTab } from '../lib/tabs';
import { usePolling } from './usePolling';

/** What the page draws from. It is replaced and changed in place; `draw()` draws it again. */
interface Board {
  state: AppState;
  /** project → what its plugins said about it */
  plugins: Plugins;
  loaded: boolean;
}

/** To look into from the console (and from the tests): what the page drew from, to read and to
 *  change, and a way to draw it again. */
interface DebugHandle {
  readonly state: AppState;
  readonly plugins: Plugins;
  render: () => void;
}
declare global {
  interface Window {
    dashboard?: DebugHandle;
  }
}

export interface Dashboard extends Board {
  /** Describes a project again: what its plugins show now. */
  reload: (project: string) => Promise<void>;
  start: (what: NewSession) => Promise<void>;
  openTerminal: (project: string) => Promise<void>;
  stop: (s: Session) => Promise<void>;
  remove: (s: Session) => Promise<void>;
  show: (s: Session) => void;
  openItem: (e: MouseEvent, item: Item, s?: Session) => void;
}

export function useDashboard(): Dashboard {
  const board = useRef<Board>({ state: { projects: [], sessions: [] }, plugins: {}, loaded: false }).current;
  const [, draw] = useReducer((n: number) => n + 1, 0);
  // A session's tabs opened from it here (a port it published while it ran, no longer listed once it is stopped).
  const owned = useRef(new Map<string, Set<string>>()).current;

  const reload = useCallback(async (project: string) => {
    board.plugins[project] = await server.getProject(project).catch((e): ProjectInfo => ({ lists: [], notes: [message(e)] }));
    draw();
  }, [board]);

  const refresh = useCallback(async () => {
    const before = board.state.projects.join();
    try {
      board.state = await server.getState();
    } catch {
      return;  // the server is away: what was last drawn stays
    }
    board.loaded = true;
    if (board.state.projects.join() !== before) board.state.projects.forEach(p => void reload(p));
    draw();
  }, [board, reload]);

  usePolling(refresh, 3000, { now: true });
  usePolling(() => board.state.projects.forEach(p => void reload(p)), 60000);

  // A session's tabs: its page, any item (its pull request) a plugin tied to its run, and those opened from it.
  const closeTabs = useCallback((s: Session) => {
    const said = Object.values(board.plugins).filter(info => !!info);
    const items = said.flatMap(runItems).filter(i => s.run_id && i.run_id === s.run_id).concat(liveItems(s));
    for (const name of [sessionTab(s.id), ...(owned.get(s.id) ?? []), ...items.map(i => itemTab(i.url))]) closeTab(name);
  }, [board, owned]);

  useEffect(() => {
    window.name = DASHBOARD_TAB;  // where a session page's way back lands
    window.dashboard = { get state() { return board.state; }, get plugins() { return board.plugins; }, render: draw };
    // Deleted on its own page: the tabs opened for it here go with it.
    return onSessionDeleted(closeTabs);
  }, [board, closeTabs]);

  const actions = useMemo(() => ({
    start: async (what: NewSession) => {
      const w = window.open('about:blank');  // its name is the session's id, which the server picks
      try {
        const s = await server.startSession(what);
        if (w) {
          w.name = sessionTab(s.id);
          remember(w.name, w);
          w.location.replace(sessionPage(s));
        }
        void refresh();
      } catch (e) {
        w?.close();
        alert(message(e));
      }
    },
    // Brought to the front when its tab is open; the server hands back the live one when the tab was closed.
    openTerminal: async (project: string) => {
      const w = openTab(terminalTab(project));
      if (!w || !isFresh(w)) return;
      try {
        const t = await server.startSession({ project, kind: 'shell' });
        w.location.replace(sessionPage(t));
      } catch (e) {
        w.close();
        alert(message(e));
      }
    },
    stop: async (s: Session) => {
      if (await stopAfterAsking(s, `Stop “${titled(s)}”?`)) await refresh();
    },
    remove: async (s: Session) => {
      if (!await deleteAfterAsking(s, `Stop and delete “${titled(s)}”?`)) return;
      closeTabs(s);
      announceDeleted(s);
      await refresh();
    },
    show: (s: Session) => {
      const w = openTab(sessionTab(s.id));
      if (w && isFresh(w)) w.location.replace(sessionPage(s));
    },
    // One tab per listed item. A plain click only: ctrl/middle-click still open a tab of their own, as on any link.
    openItem: (e: MouseEvent, item: Item, s?: Session) => {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      const name = itemTab(item.url);
      const w = openTab(name);
      if (s) {
        if (!owned.has(s.id)) owned.set(s.id, new Set());
        owned.get(s.id)!.add(name);
      }
      // The tab keeps its opener (this page): cut off, Chromium moves it out of reach of both the
      // lookup by name and close(). GitHub could navigate this tab through it; it is your own login.
      if (w && isFresh(w)) w.location.replace(item.url);
    },
  }), [refresh, closeTabs, owned]);

  return { ...board, reload, ...actions };
}
