import { useLayoutEffect, useRef, type RefObject } from 'react';

/** For a list of entries that ends in its + Add button: returns what to call when an entry is
 *  added, so that its first input is focused once it is drawn. */
export function useFocusNew(box: RefObject<HTMLElement | null>): () => void {
  const pending = useRef(false);
  useLayoutEffect(() => {
    if (!pending.current) return;
    pending.current = false;
    box.current?.lastElementChild?.previousElementSibling?.querySelector<HTMLElement>('input, select')?.focus();
  });
  return () => {
    pending.current = true;
  };
}
