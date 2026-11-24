import { BusyButton } from '../common/BusyButton';
import { Icon } from '../common/Icon';
import { SyncButton } from '../common/SyncButton';
import { ThemeSwitch } from '../common/ThemeSwitch';
import { AGENTS } from '../../plugins';
import { useDashboardActions } from './DashboardContext';

/** On a phone, the button beside the new session's card that opens the menu. */
export function BoardMenuButton() {
  return (
    <button type="button" className="glyph menu" popoverTarget="board-menu" title="Menu" aria-label="Menu">
      <Icon name="more" />
    </button>
  );
}

/** What is about this whole web UI, not one project: the sandbox's settings, what the agents add
 *  (signing one in again), updating it, and the colour mode. On a desk a sidebar on the page's left;
 *  on a phone a popover from BoardMenuButton, which closes on Esc or a click elsewhere. One element
 *  either way (CSS shows the popover as the sidebar), so the agents' sign-in dialogs exist once. */
export function BoardMenu() {
  const { configureSandbox } = useDashboardActions();
  const hide = () => document.getElementById('board-menu')?.hidePopover();
  return (
    <nav id="board-menu" popover="auto" aria-label="Sandbox">
      <div className="mark"><span className="lamp" />Sandbox</div>
      <BusyButton className="term" onClick={() => { hide(); return configureSandbox(); }} title="Projects and authentications" aria-label="Sandbox settings">
        <Icon name="gear" /><span>Settings</span>
      </BusyButton>
      {AGENTS.map(({ name, Menu }) => Menu && <Menu key={name} close={hide} />)}
      <SyncButton />
      <div className="row"><ThemeSwitch /></div>
    </nav>
  );
}
