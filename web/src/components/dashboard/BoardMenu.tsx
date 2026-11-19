import { BusyButton } from '../common/BusyButton';
import { ClaudeLoginButton } from '../common/ClaudeLoginButton';
import { Icon } from '../common/Icon';
import { SyncButton } from '../common/SyncButton';
import { ThemeSwitch } from '../common/ThemeSwitch';
import { useDashboardActions } from './DashboardContext';

/** What is about this whole web UI, not one project, behind one button: the colour mode, the
 *  terminal, the sandbox's settings, and updating it. The browser's popover closes it on Esc or a click elsewhere. */
export function BoardMenu() {
  const { openTerminal, configureSandbox } = useDashboardActions();
  const hide = () => document.getElementById('board-menu')?.hidePopover();
  return (
    <>
      <button type="button" className="glyph menu" popoverTarget="board-menu" title="Menu" aria-label="Menu">
        <Icon name="more" />
      </button>
      <div id="board-menu" popover="auto">
        <div className="row"><ThemeSwitch /></div>
        <BusyButton className="term" onClick={() => { hide(); return openTerminal(); }} title="A shell in your home folder" aria-label="Terminal">
          <Icon name="prompt" /><span>Terminal</span>
        </BusyButton>
        <BusyButton className="term" onClick={() => { hide(); return configureSandbox(); }} title="Projects and authentications" aria-label="Sandbox settings">
          <Icon name="gear" /><span>Settings</span>
        </BusyButton>
        <ClaudeLoginButton onClick={hide} />
        <SyncButton />
      </div>
    </>
  );
}
