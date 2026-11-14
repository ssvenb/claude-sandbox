import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useAutoGrow } from '../../hooks/useAutoGrow';
import { usePastedImages } from '../../hooks/usePastedImages';
import { projectName } from '../../lib/session';
import { ImageTray } from '../common/Pictures';
import { useDashboardActions } from './DashboardContext';

/** Starting a session is writing its first message (pictures pasted into it go along), with the
 *  project it is for beside it: the sandbox boots behind it. */
export function NewSession({ projects }: { projects: string[] }) {
  const { start } = useDashboardActions();
  const text = useRef<HTMLTextAreaElement>(null), pick = useRef<HTMLSelectElement>(null);
  const [busy, setBusy] = useState(false);
  const pictures = usePastedImages();
  const grow = useAutoGrow(text, 0.3);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const field = text.current!;
    const task = field.value.trim(), images = pictures.take();
    field.value = '';
    grow();
    setBusy(true);
    try {
      await start({ project: pick.current?.value ?? projects[0]!, kind: 'run', task: task || undefined, images: images.length ? images : undefined });
    } finally {
      setBusy(false);
    }
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    e.currentTarget.form?.requestSubmit();
  };

  return (
    <form className="starter" onSubmit={submit}>
      <div className="field">
        <ImageTray pictures={pictures} onRemoved={() => text.current?.focus()} />
        <textarea ref={text} rows={1} name="task" placeholder="What should an agent work on?" aria-label="First message of a new session"
          onChange={grow} onPaste={pictures.onPaste} onKeyDown={onKeyDown} />
      </div>
      {projects.length > 1 && (
        <select ref={pick} name="project" aria-label="Project">
          {projects.map(p => <option key={p} value={p}>{projectName(p)}</option>)}
        </select>
      )}
      <button type="submit" className={'primary' + (busy ? ' busy' : '')} disabled={busy}>Start session</button>
    </form>
  );
}
