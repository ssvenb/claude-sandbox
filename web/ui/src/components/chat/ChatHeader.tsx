import type { AgentInfo } from '../../api/events';
import type { Item, Session, SessionStatus } from '../../api/types';
import { projectName, SHORT, titled } from '../../lib/session';
import { BusyButton } from '../common/BusyButton';
import { Chip } from '../common/Chip';
import { HomeLink } from '../common/HomeLink';
import { Icon } from '../common/Icon';
import { ThemeSwitch } from '../common/ThemeSwitch';

interface Props {
  /** The session, once the server said which it is. */
  session: Session | null;
  /** The session is no longer there. */
  gone: boolean;
  info: AgentInfo;
  /** How it is doing, or null once it ended. */
  state: SessionStatus | null;
  /** What its project's plugins tie to its run, and what it publishes: its pull request, its ports. */
  items: Item[];
  onStop: () => void;
  onDelete: () => void;
  /** Opens its checkout in VS Code. */
  onCode: () => Promise<void>;
}

/** Which session this is and how it is doing, with the buttons that end it. */
export function ChatHeader({ session, gone, info, state, items, onStop, onDelete, onCode }: Props) {
  if (gone) {
    return (
      <header id="bar">
        <HomeLink toItsTab={false} />
        <div className="who"><b>No session</b></div>
      </header>
    );
  }
  if (!session) return <header id="bar" />;
  const agent = info.agent && (info.model ? `${info.agent}, ${info.model}` : info.agent);
  return (
    <header id="bar">
      <HomeLink />
      <div className="who">
        <b title={session.title || ''}>{titled(session)}</b>
        <span>{[projectName(session.project), session.run_id, agent].filter(Boolean).join(' / ')}</span>
      </div>
      <div className="chips">{items.map((i, k) => <Chip key={k} item={i} />)}</div>
      <span className={'state ' + (state ?? 'ended')}>
        <span className={'lamp ' + (state ?? '')} />
        {state ? SHORT[state] : 'Ended'}
      </span>
      {session.workspace && (
        <BusyButton className="icon vscode" onClick={onCode} aria-label="VS Code" title="VS Code"><Icon name="vscode" /></BusyButton>
      )}
      {state && (
        <button className="icon stop" onClick={onStop} aria-label="Stop session" title="Stop"><Icon name="stop" /></button>
      )}
      <button className="icon" onClick={onDelete} aria-label="Delete session" title="Delete"><Icon name="trash" /></button>
      <ThemeSwitch />
    </header>
  );
}
