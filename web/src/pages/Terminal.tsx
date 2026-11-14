// A terminal: a project's shell on this machine (or an agent's own TUI, for a session started with
// "ui": "terminal"). An agent's session is otherwise a chat: see pages/Chat.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { getState } from '../api/sessions';
import type { Session } from '../api/types';
import { Gone } from '../components/common/Gone';
import { TerminalBar } from '../components/terminal/TerminalBar';
import { TerminalScreen } from '../components/terminal/TerminalScreen';
import { usePolling } from '../hooks/usePolling';
import { useTabIdentity } from '../hooks/useTabIdentity';
import { label, projectName } from '../lib/session';
import { deleteAfterAsking, stopAfterAsking } from '../lib/sessionActions';
import { announceDeleted, onSessionDeleted } from '../lib/tabs';

export default function TerminalPage() {
  const id = useMemo(() => location.hash.slice(1), []);
  // The session as the server lists it: null once it is gone, undefined until the server said.
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    const state = await getState().catch(() => null);
    if (!state) return;
    const s = state.sessions.find(s => s.id === id) ?? null;
    setSession(s);
    if (!s) window.close();  // removed: nothing left to show
  }, [id]);
  usePolling(refresh, 3000, { now: true });

  // Closing a session closes every tab of it: this one, when another page says it is gone.
  useEffect(() => onSessionDeleted(s => { if (s.id === id) window.close(); }), [id]);

  useTabIdentity(session ? `${projectName(session.project)} ${label(session)}` : null,
    !session || session.kind === 'shell' ? 'shell' : session.status ?? 'unlit');

  const shell = (s: Session) => (s.kind === 'shell' ? 'terminal' : 'session');
  const stop = async (s: Session) => {
    if (await stopAfterAsking(s, `Stop this ${shell(s)}?`)) await refresh();
  };
  const remove = async (s: Session) => {
    if (!await deleteAfterAsking(s, `Stop and delete this ${shell(s)}?`)) return;
    announceDeleted(s);
    window.close();
    await refresh();  // still here: this tab was not opened by the dashboard, so it may not close itself
  };

  return (
    <>
      <TerminalBar session={session} onStop={stop} onDelete={remove} />
      <div id="stage">
        {session !== null && <TerminalScreen session={id} onExit={refresh} />}
        <Gone id="empty" hidden={session !== null} />
      </div>
    </>
  );
}
