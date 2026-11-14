import { useLayoutEffect, useRef, type RefObject } from 'react';

/** The latest value, for an effect or a timer that outlives the render it was set up in. */
export function useLatest<T>(value: T): RefObject<T> {
  const ref = useRef(value);
  useLayoutEffect(() => {
    ref.current = value;
  });
  return ref;
}
