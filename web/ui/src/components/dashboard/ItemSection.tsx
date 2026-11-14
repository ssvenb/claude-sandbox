import type { Item, ItemList } from '../../api/types';
import { tip } from '../../lib/items';
import { BusyButton } from '../common/BusyButton';
import { StatusMark } from '../common/Chip';
import { useDashboardActions } from './DashboardContext';

/** A listed item: a link to its page, and what can be started from it (its run resumed, a
 *  session on its task: an issue's Resolve). */
function ItemRow({ project, item: i }: { project: string; item: Item }) {
  const { start, openItem } = useDashboardActions();
  return (
    <li>
      <a href={i.url} target="_blank" rel="noopener" onClick={e => openItem(e, i)} title={tip(i)}>
        <StatusMark item={i} />
        {i.ref && <span className="num">{i.ref}</span>}
        {i.note && <span className="draft">{i.note + ': '}</span>}
        {i.title}
      </a>
      {i.run_id && <BusyButton onClick={() => start({ project, kind: 'resume', run_id: i.run_id! })}>Resume</BusyButton>}
      {i.start && <BusyButton onClick={() => start({ project, kind: 'run', task: i.start!.task })} title={i.start.task}>{i.start.label}</BusyButton>}
    </li>
  );
}

/** A section of a project's panel, as a plugin lists it: its issues, its open pull requests. */
export function ItemSection({ project, list }: { project: string; list: ItemList }) {
  return (
    <>
      <h4>{list.title}<span className="count">{list.items.length}</span></h4>
      <ul>{list.items.map((i, k) => <ItemRow key={k} project={project} item={i} />)}</ul>
    </>
  );
}
