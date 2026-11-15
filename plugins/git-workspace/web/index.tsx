// The files a run's checkout changed, beside its chat on a desk and behind a header button on a
// smaller screen: what host/changes.py says (web_command in ../web.sh), asked again every few
// seconds while the tab is in view.
import { useEffect, useState } from 'react';
import { askPlugin } from '@ui/api/sessions';
import type { Session } from '@ui/api/types';
import { usePolling } from '@ui/hooks/usePolling';
import type { PluginUI } from '@ui/plugins';
import { Changes, type ChangedFile } from './Changes';
import './changes.css';

const FILES = (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <path d="M11.5 2.5H6a1.5 1.5 0 0 0-1.5 1.5v12A1.5 1.5 0 0 0 6 17.5h8a1.5 1.5 0 0 0 1.5-1.5V6.5zM11.5 2.5v4h4M10 9v5M7.5 11.5h5"
      fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/** The files, null while the run has no checkout on this machine (or no session is there). */
function useChangedFiles(session: Session | null): ChangedFile[] | null {
  const [files, setFiles] = useState<ChangedFile[] | null>(null);
  const id = session?.workspace ? session.id : null;
  const ask = () => {
    if (!id || document.hidden) return;
    askPlugin<ChangedFile[]>(id, 'git-workspace', 'changes')
      .then(r => setFiles(f => (JSON.stringify(f) === JSON.stringify(r) ? f : r)), () => {});
  };
  usePolling(ask, 3000);
  useEffect(ask, [id]);  // and at once, as soon as its checkout is known
  return id ? files : null;
}

export default {
  useChat(session) {
    const files = useChangedFiles(session);
    if (!files) return {};
    return {
      bar: files.length > 0 && (
        <button className="icon files side-toggle" popoverTarget="changes" aria-label={`${files.length} changed files`} title="Changed files">
          {FILES}<span>{files.length}</span>
        </button>
      ),
      aside: <Changes files={files} />,
    };
  },
} satisfies PluginUI;
