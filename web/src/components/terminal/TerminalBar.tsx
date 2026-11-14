import type { Session } from '../../api/types';
import { label, projectName, SAYS } from '../../lib/session';
import { HomeLink } from '../common/HomeLink';
import { Icon } from '../common/Icon';
import { ThemeSwitch } from '../common/ThemeSwitch';

interface Props {
  /** The session; null once it is gone, undefined until the server said. */
  session: Session | null | undefined;
  onStop: (s: Session) => void;
  onDelete: (s: Session) => void;
}

/** Which terminal this is and how it is doing, with the buttons that end it. */
export function TerminalBar({ session: s, onStop, onDelete }: Props) {
  if (s === undefined) return <header id="bar" />;
  if (!s) return <header id="bar"><span className="what">No session</span></header>;
  const running = s.exit === null;
  return (
    <header id="bar">
      <HomeLink />
      <strong>{projectName(s.project)}</strong>
      <span className={'what' + (running ? ' lit' : '') + (s.status === 'question' ? ' ask' : '')}>
        {label(s) + (!running ? `, exited ${s.exit}` : s.status ? ', ' + SAYS[s.status] : ', running')}
      </span>
      {running && <button className="icon stop" onClick={() => onStop(s)} aria-label="Stop session"><Icon name="stop" />Stop</button>}
      <button className="icon" onClick={() => onDelete(s)} aria-label="Delete session"><Icon name="trash" />Delete</button>
      <ThemeSwitch />
    </header>
  );
}
