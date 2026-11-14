import { message, post } from '../../api/client';
import { BusyButton } from './BusyButton';
import { Icon } from './Icon';

const TITLE = 'Update: pull main, run install.sh, restart the server';

async function sync() {
  if (!confirm(TITLE + '?\nSessions keep running: the restarted server takes them back.')) return;
  try {
    const { restarting } = await post<{ restarting: boolean }>('/api/sync');
    if (!restarting) return alert('Updated. This server does not run as claude-sandbox-web.service: restart it yourself.');
    // Back once the restarted server answers.
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 2000));
      if (await fetch('/api/state').then(r => r.ok, () => false)) return location.reload();
    }
    alert('The server has not come back: see journalctl --user -u claude-sandbox-web.service');
  } catch (e) {
    alert(message(e));
  }
}

/** Brings this checkout up to date with main and restarts the web UI with it. */
export function SyncButton() {
  return (
    <BusyButton className="sync" title={TITLE} aria-label={TITLE} onClick={sync}>
      <Icon name="sync" />
    </BusyButton>
  );
}
