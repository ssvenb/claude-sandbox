// The browser tabs of the sandbox. Each thing has a tab of its own, found again by its name:
// opened once, brought to the front after that. Closing a session closes every tab of it: told
// on a channel, each of its pages closes itself and the dashboard closes the ones it opened.
import type { Session } from '../api/types';

const channel = new BroadcastChannel('sandbox-tabs');

/** Tells every page that a session is gone. */
export const announceDeleted = (s: Session): void => channel.postMessage(s);

/** Runs `fn` whenever another page says a session is gone. Returns how to stop listening. */
export function onSessionDeleted(fn: (s: Session) => void): () => void {
  const heard = (e: MessageEvent<Session>) => fn(e.data);
  channel.addEventListener('message', heard);
  return () => channel.removeEventListener('message', heard);
}

// The tabs this page opened, by name.
const opened = new Map<string, Window>();

/** Notes a tab this page opened, to close it later. */
export const remember = (name: string, w: Window): void => void opened.set(name, w);

/** The tab of that name, opened if there is none, at the front. Always called inside the click,
 *  before any await, or the popup blocker eats the new tab. */
export function openTab(name: string): Window | null {
  const w = window.open('', name);
  w?.focus();
  if (w) remember(name, w);
  return w;
}

/** Still empty, so ours to fill. Reading another site's tab (GitHub) throws: it is long filled. */
export function isFresh(w: Window): boolean {
  try {
    return w.location.href === 'about:blank';
  } catch {
    return false;
  }
}

export const closeTab = (name: string): void => opened.get(name)?.close();

export const sessionTab = (id: string): string => 'session-' + id;
export const itemTab = (url: string): string => 'item-' + url;
export const terminalTab = (project: string): string => 'terminal-' + project;
