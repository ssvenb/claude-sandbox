import { useEffect, useRef, useState, type ButtonHTMLAttributes, type MouseEvent } from 'react';

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick' | 'type'> {
  /** May return a promise: the button turns until it settles. Whatever it opens in a new tab,
   *  it opens before its first await. */
  onClick: (e: MouseEvent<HTMLButtonElement>) => unknown;
}

/** A button that does something slow turns until it is done, and cannot be pressed twice. */
export function BusyButton({ onClick, className = '', children, ...rest }: Props) {
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const click = async (e: MouseEvent<HTMLButtonElement>) => {
    if (busy) return;
    setBusy(true);
    try {
      await onClick(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  return (
    <button type="button" {...rest} className={(className + (busy ? ' busy' : '')).trim() || undefined} disabled={busy} onClick={click}>
      {children}
    </button>
  );
}
