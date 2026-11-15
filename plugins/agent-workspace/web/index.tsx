// A button with the session's buttons that opens its run's mirrored checkout in VS Code, served by
// host/vscode.py under /plugins/agent-workspace/ (web_server in ../web.sh), in a tab that closes
// with the session.
import { useEffect, useRef } from 'react';
import { message } from '@ui/api/client';
import { BusyButton } from '@ui/components/common/BusyButton';
import { LEAVE, type PluginUI } from '@ui/plugins';
import './vscode.css';

const VSCODE = (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path fill="currentColor" fillRule="evenodd" d="M17 1.5 22 4v16l-5 2.5-9.4-8.6-4.3 3.3L2 16.5v-9l1.3-.7 4.3 3.3zm0 5.7L10.7 12l6.3 4.8z" />
  </svg>
);

export default {
  useChat(session) {
    const tab = useRef<Window | null>(null);
    useEffect(() => {
      const close = () => tab.current?.close();
      addEventListener(LEAVE, close);
      return () => removeEventListener(LEAVE, close);
    }, []);
    const folder = session?.workspace;
    if (!folder) return {};
    const url = '/plugins/agent-workspace/?folder=' + encodeURIComponent(folder);
    // The tab opens at once, or a popup blocker would stop it; VS Code goes in once it answers.
    const open = async () => {
      const w = (tab.current = window.open('', 'code-' + folder));
      try {
        const r = await fetch(url);
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.error ?? `VS Code answered ${r.status}`);
        w?.location.replace(url);
      } catch (e) {
        w?.close();
        alert(message(e));
      }
    };
    return {
      actions: <BusyButton className="icon vscode" onClick={open} aria-label="VS Code" title="VS Code">{VSCODE}</BusyButton>,
    };
  },
} satisfies PluginUI;
