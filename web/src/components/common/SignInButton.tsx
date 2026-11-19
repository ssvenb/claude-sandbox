import { useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { message, post } from '../../api/client';

interface Props {
  /** The agent whose `signIn` (its agent.json) the server runs: agents/<agent>. */
  agent: string;
  /** What the menu calls it, e.g. "Sign in to Claude". */
  label: string;
  icon: ReactNode;
  /** Before it opens: the menu it sits in closes. */
  onClick: () => void;
}

/** Signs an agent's CLI on the server in afresh: a tab the server sends on to the sign-in page its
 *  command prints, and a dialog here for the code that page ends on. */
export function SignInButton({ agent, label, icon, onClick }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const path = `/api/agents/${agent}/sign-in`;

  const open = () => {
    onClick();
    window.open(path, '_blank');  // a real link, so no popup blocker
    setError('');
    dialog.current!.showModal();
  };
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    try {
      await post(path, { code: new FormData(form).get('code') });
      form.reset();
      dialog.current!.close();
      alert('Signed in on the server.');
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className="term" title={`${label}, on the server`} aria-label={label} onClick={open}>
        {icon}<span>{label}</span>
      </button>
      {/* Out of the menu's popover, which hides as this opens. */}
      {createPortal(
        <dialog ref={dialog} aria-labelledby={title}>
          <form onSubmit={submit}>
            <header>
              <h2 id={title}>{label}</h2>
              <p>Sign in in the new tab, then paste the code it shows here.</p>
            </header>
            <div className="body">
              <input name="code" aria-label="Code" placeholder="Code" required autoFocus autoComplete="off" spellCheck={false} style={{ width: '100%' }} />
            </div>
            <footer>
              <p className="error" role="alert">{error}</p>
              <button type="button" onClick={() => dialog.current!.close()}>Cancel</button>
              <button type="submit" className="primary" disabled={busy}>Sign in</button>
            </footer>
          </form>
        </dialog>,
        document.body)}
    </>
  );
}
