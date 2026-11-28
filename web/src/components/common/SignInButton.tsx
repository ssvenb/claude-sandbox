import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { message } from '../../api/client';
import { getSignInStatus, sendSignInCode, signInUrl } from '../../api/sessions';

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
 *  command prints, and a dialog here for the code that page ends on. When the server finds it signed
 *  out (its `signedIn`, on load and each time the page comes back into view), it asks to sign in again;
 *  a No holds until it is seen signed in once more. */
export function SignInButton({ agent, label, icon, onClick }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const ask = useRef<HTMLDialogElement>(null);
  const declined = `sandbox:sign-in-declined:${agent}`;

  useEffect(() => {
    const check = () => {
      if (document.hidden || ask.current!.open || dialog.current!.open) return;
      // No `signedIn` or no CLI on the server: nothing to ask.
      getSignInStatus(agent).then(({ signedIn }) => {
        if (signedIn) localStorage.removeItem(declined);
        else if (!localStorage.getItem(declined) && !dialog.current!.open) ask.current!.showModal();
      }, () => {});
    };
    check();
    document.addEventListener('visibilitychange', check);
    return () => document.removeEventListener('visibilitychange', check);
  }, [agent, declined]);

  const open = () => {
    onClick();
    ask.current!.close();
    window.open(signInUrl(agent), '_blank');  // a real link, so no popup blocker
    setError('');
    dialog.current!.showModal();
  };
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    try {
      await sendSignInCode(agent, String(new FormData(form).get('code') ?? ''));
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
      {createPortal(
        <dialog ref={ask} aria-labelledby={`${title}-ask`}>
          <header>
            <h2 id={`${title}-ask`}>Signed out</h2>
            <p>The server is not signed in anymore. {label} again?</p>
          </header>
          <footer>
            <button type="button" onClick={() => { localStorage.setItem(declined, '1'); ask.current!.close(); }}>Not now</button>
            {/* A click, so the tab it opens gets past the popup blocker. */}
            <button type="button" className="primary" autoFocus onClick={open}>{label}</button>
          </footer>
        </dialog>,
        document.body)}
    </>
  );
}
