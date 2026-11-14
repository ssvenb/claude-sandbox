import type { Item, Session } from '../../api/types';
import { projectName } from '../../lib/session';
import { SessionWindow } from './SessionWindow';

/** A project's running sessions. */
export interface RunningGroup {
  project: string;
  sessions: Session[];
}

interface Props {
  groups: RunningGroup[];
  /** The items on a session's row. */
  itemsOf: (s: Session) => Item[];
}

/** The left of the board: what is running now, a window per session under its project's name. */
export function RunningSessions({ groups, itemsOf }: Props) {
  return (
    <div className="running">
      <h2 className="band">Running now</h2>
      {groups.map(({ project, sessions }) => (
        <div className="group" key={project}>
          <h3 title={project}>{projectName(project)}</h3>
          <div className="windows">
            {sessions.map(s => <SessionWindow key={s.id} session={s} items={itemsOf(s)} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
