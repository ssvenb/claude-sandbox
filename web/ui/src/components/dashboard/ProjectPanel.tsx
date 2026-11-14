import type { ItemList, ProjectInfo } from '../../api/types';
import { projectName } from '../../lib/session';
import { BusyButton } from '../common/BusyButton';
import { Icon } from '../common/Icon';
import { Loading } from '../common/Spinner';
import { useDashboardActions } from './DashboardContext';
import { EndedSessions, type EndedSession } from './EndedSessions';
import { ItemSection } from './ItemSection';

interface Props {
  /** The project's directory. */
  project: string;
  /** What its plugins say about it, once they did. */
  info?: ProjectInfo;
  /** What its plugins list (issues, a run's open pull request), without what is on a session's row instead. */
  lists: ItemList[];
  ended: EndedSession[];
}

/** A project: its buttons, what its plugins list for it (the page only draws it), and its ended
 *  sessions at its foot. */
export function ProjectPanel({ project, info, lists, ended }: Props) {
  const { configure, openTerminal, start } = useDashboardActions();
  return (
    <section className="project">
      <div className="head">
        <h3 title={project}>{projectName(project)}{info?.agent && <small>{info.agent}</small>}</h3>
        <BusyButton className="glyph" onClick={() => configure(project)} title="Settings" aria-label="Settings"><Icon name="gear" /></BusyButton>
        <BusyButton className="glyph" onClick={() => openTerminal(project)} title="Terminal" aria-label="Terminal"><Icon name="prompt" /></BusyButton>
        <BusyButton className="glyph primary" onClick={() => start({ project, kind: 'run' })} title="New session" aria-label="New session"><Icon name="plus" /></BusyButton>
      </div>
      <div className="notes">
        {info ? info.notes.map((note, k) => <p key={k}>{note}</p>) : <Loading as="p" text="Loading" />}
      </div>
      {lists.map(list => <ItemSection key={list.title} project={project} list={list} />)}
      <EndedSessions ended={ended} />
    </section>
  );
}
