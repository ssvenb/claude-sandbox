import { useCallback, useEffect, useRef } from 'react';
import { useLatest } from './useLatest';

export interface StreamHandlers {
  /** A message of the stream, as its text. */
  onMessage: (data: string) => void;
  /** The stream is open: at first, and again after each reconnect. */
  onOpen?: () => void;
  /** The stream broke; `closed` says the browser gave up on it instead of reconnecting. */
  onError?: (closed: boolean) => void;
  /** Named events of the stream (`event: exit`), by name. */
  events?: Record<string, (data: string) => void>;
}

/** A server-sent event stream (EventSource) for as long as the component is there. Returns how
 *  to close it sooner: once nothing more will come. */
export function useEventStream(url: string, handlers: StreamHandlers): () => void {
  const latest = useLatest(handlers);
  const source = useRef<EventSource | null>(null);
  const names = Object.keys(handlers.events ?? {}).join(' ');
  useEffect(() => {
    const es = (source.current = new EventSource(url));
    es.onopen = () => latest.current.onOpen?.();
    es.onmessage = e => latest.current.onMessage(e.data);
    es.onerror = () => latest.current.onError?.(es.readyState === EventSource.CLOSED);
    for (const name of names.split(' ').filter(Boolean))
      es.addEventListener(name, e => latest.current.events?.[name]?.((e as MessageEvent<string>).data));
    return () => es.close();
  }, [url, names, latest]);
  return useCallback(() => source.current?.close(), []);
}
