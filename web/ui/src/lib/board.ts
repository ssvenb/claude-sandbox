// What the dashboard draws, worked out from the server's sessions and what each project's plugins
// say: which sessions run, which ended, and which items (a pull request) go on which session.
import type { AppState, Item, ItemList, ProjectInfo, Session, SessionStatus } from '../api/types';
import { liveItems, runItems, sections } from './items';

export type Plugins = Record<string, ProjectInfo | undefined>;

const URGENCY: Record<SessionStatus, number> = { question: 0, working: 1, starting: 2, idle: 3 };

/** The agents' sessions: terminals are not sessions. */
const agents = (state: AppState): Session[] => state.sessions.filter(s => s.kind !== 'shell');

/** The one session of a run that carries its items: the live one, else the latest. */
export function holder(state: AppState, project: string, runId: string): Session | undefined {
  const of = agents(state).filter(s => s.project === project && s.run_id === runId);
  return of.find(s => s.exit === null) ?? of.pop();
}

/** Whether a session of that run is running, in any project. */
export const isLive = (state: AppState, runId: string): boolean => state.sessions.some(s => s.run_id === runId && s.exit === null);

/** The items on a session's row: what plugins tied to its run, while it is the run's holder, and what it carries itself. */
export function tiedItems(state: AppState, plugins: Plugins, s: Session): Item[] {
  const said = plugins[s.project];
  const tied = s.run_id && said && holder(state, s.project, s.run_id) === s ? runItems(said).filter(i => i.run_id === s.run_id) : [];
  return tied.concat(liveItems(s));
}

/** A project's running sessions, the ones waiting on you first. */
export const runningIn = (state: AppState, project: string): Session[] =>
  agents(state).filter(s => s.project === project && s.exit === null)
    .sort((a, b) => URGENCY[a.status ?? 'idle'] - URGENCY[b.status ?? 'idle'] || b.started - a.started);

/** A project's ended sessions, the latest first. */
export const endedIn = (state: AppState, project: string): Session[] =>
  agents(state).filter(s => s.project === project && s.exit !== null).reverse();

/** What a project's panel lists: its plugins' sections, without the items that are on a session
 *  of their run instead, and without the sections that leaves empty (no open issue). */
export function listedIn(state: AppState, project: string, said: ProjectInfo): ItemList[] {
  return sections(said)
    .map(list => ({ title: list.title, items: list.items.filter(i => !(i.run_id && holder(state, project, i.run_id))) }))
    .filter(list => list.items.length);
}
