import { useLayoutEffect, useRef, type RefObject } from 'react';

/** For a list of entries that ends in its + Add button (or, `first`, starts with it, the new entry
 *  next to it): returns what to call when an entry is added, so that its first input is focused
 *  once it is drawn. */
export function useFocusNew(box: RefObject<HTMLElement | null>, first = false): () => void {
  const pending = useRef(false);
  useLayoutEffect(() => {
    if (!pending.current) return;
    pending.current = false;
    const el = first ? box.current?.firstElementChild?.nextElementSibling : box.current?.lastElementChild?.previousElementSibling;
    el?.querySelector<HTMLElement>('input, select')?.focus();
  });
  return () => {
    pending.current = true;
  };
}
