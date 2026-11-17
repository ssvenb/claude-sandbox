import { BusyButton } from '../common/BusyButton';
import { Icon } from '../common/Icon';
import { SyncButton } from '../common/SyncButton';
import { ThemeSwitch } from '../common/ThemeSwitch';
import { useDashboardActions } from './DashboardContext';

/** What is about this whole web UI, not one project, behind one button: the colour mode, the
 *  terminal, and updating it. The browser's popover closes it on Esc or a click elsewhere. */
export function BoardMenu() {
  const { openTerminal } = useDashboardActions();
  return (
    <>
      <button type="button" className="glyph menu" popoverTarget="board-menu" title="Menu" aria-label="Menu">
        <Icon name="more" />
      </button>
      <div id="board-menu" popover="auto">
        <div className="row"><ThemeSwitch /></div>
        <BusyButton className="term" onClick={openTerminal} title="A shell in your home folder" aria-label="Terminal">
          <Icon name="prompt" /><span>Terminal</span>
        </BusyButton>
        <SyncButton />
      </div>
    </>
  );
}
