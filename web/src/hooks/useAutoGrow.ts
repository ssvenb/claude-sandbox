import { useCallback, type RefObject } from 'react';

/** A text field as tall as what is written in it, up to `most` of the window's height.
 *  Returns what to call when its text changed. */
export function useAutoGrow(field: RefObject<HTMLTextAreaElement | null>, most: number): () => void {
  return useCallback(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, innerHeight * most) + 'px';
  }, [field, most]);
}
