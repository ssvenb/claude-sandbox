import { useCallback, useEffect, useState } from 'react';

/** The browser's own setting, or a pinned day or night. */
export type ThemeMode = 'auto' | 'light' | 'dark';

const CHANGED = 'themechange';
const current = (): ThemeMode => (document.documentElement.dataset.theme as ThemeMode | undefined) ?? 'auto';

/** The page's colours: which mode is picked, and how to pick another. The pin is kept in
 *  localStorage and put on <html> as `data-theme` (before the first paint by index.html). */
export function useTheme(): [ThemeMode, (mode: ThemeMode) => void] {
  const [mode, setMode] = useState(current);
  useEffect(() => {
    const changed = () => setMode(current());
    document.addEventListener(CHANGED, changed);
    return () => document.removeEventListener(CHANGED, changed);
  }, []);
  const pick = useCallback((next: ThemeMode) => {
    if (next === 'auto') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    try {
      if (next === 'auto') localStorage.removeItem('theme');
      else localStorage.setItem('theme', next);
    } catch { /* no storage: the pin lasts as long as the page */ }
    document.dispatchEvent(new Event(CHANGED));
  }, []);
  return [mode, pick];
}

/** Runs `fn` whenever the page's colours change: the switch was used, or the browser's setting changed. */
export function useThemeChange(fn: () => void): void {
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', fn);
    document.addEventListener(CHANGED, fn);
    return () => {
      media.removeEventListener('change', fn);
      document.removeEventListener(CHANGED, fn);
    };
  }, [fn]);
}
