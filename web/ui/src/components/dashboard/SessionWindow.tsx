import type { Item, Session } from '../../api/types';
import { SAYS, titled } from '../../lib/session';
import { Chip } from '../common/Chip';
import { Icon } from '../common/Icon';
import { useDashboardActions } from './DashboardContext';

/** An item on a session's row: opens in its own tab, which closes with the session. */
export function SessionChips({ session, items }: { session: Session; items: Item[] }) {
  const { openItem } = useDashboardActions();
  return <>{items.map((i, k) => <Chip key={k} item={i} onClick={e => openItem(e, i, session)} />)}</>;
}

/** What a running session is at right now: the messages waiting for its sandbox, the tool it
 *  runs, else what it last said. */
function Doing({ session: s }: { session: Session }) {
  if (s.status === 'starting') return <div className="doing">{s.waiting ? `${s.waiting} message${s.waiting > 1 ? 's' : ''} waiting` : ''}</div>;
  if (s.status === 'working' && s.activity) return <div className="doing tool">{s.activity}</div>;
  return <div className="doing">{(s.said ?? '').replace(/[#*`>|]/g, '').replace(/\s+/g, ' ').slice(0, 180)}</div>;
}

interface Props {
  session: Session;
  /** Its pull request, its ports. */
  items: Item[];
}

/** A running session as a window: what it was asked and what it is at right now. How it is
 *  doing is its colour (its class), spelled out only for a screen reader. */
export function SessionWindow({ session: s, items }: Props) {
  const { show, stop } = useDashboardActions();
  return (
    <article className={'window ' + s.status} aria-label={`${titled(s)}: ${s.status ? SAYS[s.status] : ''}`}>
      <div className="name">
        <button className="open" onClick={() => show(s)} title={s.title || ''}>{titled(s)}</button>
        <button className="icon stop" onClick={() => stop(s)} aria-label="Stop session" title="Stop"><Icon name="stop" /></button>
      </div>
      <Doing session={s} />
      <div className="chips"><SessionChips session={s} items={items} /></div>
    </article>
  );
}
