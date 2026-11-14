import type { Item, Session } from '../../api/types';
import { titled } from '../../lib/session';
import { BusyButton } from '../common/BusyButton';
import { Icon } from '../common/Icon';
import { useDashboardActions } from './DashboardContext';
import { SessionChips } from './SessionWindow';

/** An ended session, with what the page lists for it. */
export interface EndedSession {
  session: Session;
  items: Item[];
  /** Its run can be taken up again: no session of it is running. */
  resumable: boolean;
}

/** A project's ended sessions, at the foot of its panel: to read, to resume, to delete. */
export function EndedSessions({ ended }: { ended: EndedSession[] }) {
  const { show, start, remove } = useDashboardActions();
  if (!ended.length) return null;
  return (
    <>
    <h4>Ended sessions<span className="count">{ended.length}</span></h4>
    <ul className="ended">
      {ended.map(({ session: s, items, resumable }) => (
        <li key={s.id}>
          <button className="session" onClick={() => show(s)} title={s.title || ''}>
            <span className="lamp" />
            <span className="name">{titled(s)}</span>
          </button>
          <SessionChips session={s} items={items} />
          {resumable && (
            <BusyButton className="icon play" onClick={() => start({ project: s.project, kind: 'resume', run_id: s.run_id! })}
              aria-label="Resume session" title="Resume">
              <Icon name="play" />
            </BusyButton>
          )}
          <button className="icon" onClick={() => remove(s)} aria-label="Delete session" title="Delete"><Icon name="trash" /></button>
        </li>
      ))}
    </ul>
    </>
  );
}
