import { Icon } from '../common/Icon';
import { SyncButton } from '../common/SyncButton';
import { ThemeSwitch } from '../common/ThemeSwitch';

/** What is about this whole web UI, not one project, behind one button: the colours, and updating
 *  it. The browser's popover closes it on Esc or a click elsewhere. */
export function BoardMenu() {
  return (
    <>
      <button type="button" className="glyph menu" popoverTarget="board-menu" title="Menu" aria-label="Menu">
        <Icon name="more" />
      </button>
      <div id="board-menu" popover="auto">
        <div className="row"><span>Colours</span><ThemeSwitch /></div>
        <SyncButton />
      </div>
    </>
  );
}
