import { useEffect } from 'react';
import { useLatest } from './useLatest';

/** Runs `fn` every `ms` milliseconds while the component is there; with `now`, once right away too. */
export function usePolling(fn: () => void, ms: number, { now = false }: { now?: boolean } = {}): void {
  const latest = useLatest(fn);
  useEffect(() => {
    if (now) latest.current();
    const timer = setInterval(() => latest.current(), ms);
    return () => clearInterval(timer);
  }, [latest, ms, now]);
}
