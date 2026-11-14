import { useCallback, useEffect, useRef, type RefObject } from 'react';

interface FollowScroll {
  /** Goes on the scrolling element: the reader scrolled, so they decide whether it follows. */
  onScroll: () => void;
  /** Brings the newest line into view, if the reader is following. */
  settle: () => void;
  /** Follows again, wherever the reader scrolled to. */
  follow: () => void;
}

/** Keeps the newest line of a scrolling column in view, until the reader scrolls up; back at its
 *  end, it follows again. `content` is what grows inside `scroller`. */
export function useFollowScroll(scroller: RefObject<HTMLElement | null>, content: RefObject<HTMLElement | null>): FollowScroll {
  const following = useRef(true);
  const settle = useCallback(() => {
    const el = scroller.current;
    if (following.current && el) el.scrollTop = el.scrollHeight;
  }, [scroller]);
  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (el) following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, [scroller]);
  const follow = useCallback(() => {
    following.current = true;
  }, []);
  // What is in it grew (a picture loaded), or it shrank (the dock under it grew).
  useEffect(() => {
    const watch = new ResizeObserver(settle);
    for (const el of [scroller.current, content.current]) if (el) watch.observe(el);
    return () => watch.disconnect();
  }, [scroller, content, settle]);
  return { onScroll, settle, follow };
}
