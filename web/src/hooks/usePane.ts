import { useCallback, useState } from 'react';

export interface PaneState {
  /** How wide it is, in pixels, when it is shown. */
  width: number;
  /** It is put away. */
  shut: boolean;
  /** The narrowest and the widest it goes; the widest also leaves the chat its room. */
  min: number;
  max: number;
  resize: (width: number) => void;
  toggle: () => void;
  /** Back to the width it came with. */
  reset: () => void;
}

/** A panel beside the chat: how wide the reader made it and whether they put it away, kept in
 *  this browser (localStorage) for every session's page. */
export function usePane(name: string, initial: number, min: number, most: number): PaneState {
  const key = 'pane-' + name;
  const [state, setState] = useState(() => {
    try {
      const kept = JSON.parse(localStorage.getItem(key) || '{}') as { width?: unknown; shut?: unknown };
      return { width: typeof kept.width === 'number' ? kept.width : initial, shut: kept.shut === true };
    } catch {
      return { width: initial, shut: false };
    }
  });
  const max = Math.max(min, Math.min(most, Math.round(innerWidth * 0.4)));
  const set = useCallback((change: Partial<typeof state>) => setState(was => {
    const now = { ...was, ...change };
    try { localStorage.setItem(key, JSON.stringify(now)); } catch { /* no storage: for this page only */ }
    return now;
  }), [key]);
  return {
    width: Math.min(max, Math.max(min, state.width)), shut: state.shut, min, max,
    resize: useCallback((width: number) => set({ width: Math.round(width) }), [set]),
    toggle: useCallback(() => setState(was => {
      const now = { ...was, shut: !was.shut };
      try { localStorage.setItem(key, JSON.stringify(now)); } catch { /* as above */ }
      return now;
    }), [key]),
    reset: useCallback(() => set({ width: initial }), [set, initial]),
  };
}
