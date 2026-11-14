// What a project's plugins list, and which of it belongs to a run's session.
import type { Item, ItemList, ProjectInfo, Session } from '../api/types';

/** An item's tooltip: its ref, note, title and branch, then what its status mark means. */
export const tip = (i: Item): string =>
  [(i.ref ? i.ref + ' ' : '') + (i.note ? i.note + ': ' : '') + i.title + (i.branch ? ` (${i.branch})` : ''), i.status_text]
    .filter(Boolean)
    .join('\n');

/** What a plugin publishes for a running session (its servers' ports) links from wherever this
 *  page was opened: `{host}` in its url is this page's own host name. */
export const here = (i: Item): Item => ({ ...i, url: i.url.replaceAll('{host}', location.hostname) });

/** The items a session carries itself, while it runs. */
export const liveItems = (s: Session): Item[] => (s.items ?? []).map(here);

/** The items plugins tied to a run (a pull request on the run's branch), from their sections or
 *  listed for runs only (which show nowhere else), and those they put on a run's session. */
export const runItems = (said: ProjectInfo): Item[] =>
  [...said.lists.flatMap(list => list.items), ...(said.run_items ?? [])].filter(i => i.run_id).concat(said.session_items ?? []);

/** Lists a plugin made, and a section for each run item that names one (a run's open pull request). */
export function sections(said: ProjectInfo): ItemList[] {
  const lists = said.lists.map(list => ({ title: list.title, items: [...list.items] }));
  for (const i of said.run_items ?? []) {
    if (!i.run_id || !i.section) continue;
    let list = lists.find(l => l.title === i.section);
    if (!list) lists.push((list = { title: i.section, items: [] }));
    list.items.push(i);
  }
  return lists;
}
