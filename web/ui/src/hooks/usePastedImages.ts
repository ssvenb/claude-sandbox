import { useCallback, useMemo, useRef, useState, type ClipboardEvent } from 'react';
import type { Picture } from '../api/types';

export const PICTURE = /^image\/(png|jpeg|gif|webp)$/;
const MOST = 8, LARGEST = 5 << 20;

export interface PastedImages {
  /** The pictures held, to draw. */
  held: Picture[];
  /** Goes on the field: takes the pictures of a paste, and leaves text to be pasted as ever. */
  onPaste: (e: ClipboardEvent) => void;
  count: () => number;
  /** Hands the pictures over, and empties the tray. */
  take: () => Picture[];
  /** Puts pictures back (a message that could not be sent). */
  put: (all: Picture[]) => void;
  drop: (p: Picture) => void;
}

const read = (file: File): Promise<Picture | null> =>
  new Promise(done => {
    const reader = new FileReader();
    reader.onload = () => done({ type: file.type, data: String(reader.result).split(',')[1] ?? '' });
    reader.onerror = () => done(null);
    reader.readAsDataURL(file);
  });

/** Pictures pasted into a message: kept in a tray over the field until it is sent. */
export function usePastedImages(): PastedImages {
  const [held, setHeld] = useState<Picture[]>([]);
  const now = useRef(held);  // what is held this moment, between renders too
  const put = useCallback((all: Picture[]) => {
    now.current = all;
    setHeld(all);
  }, []);
  const onPaste = useCallback(async (e: ClipboardEvent) => {
    const files = [...e.clipboardData.files].filter(f => PICTURE.test(f.type));
    if (!files.length) return;
    e.preventDefault();
    for (const file of files) {
      if (file.size > LARGEST) { alert('An image can be at most 5 MB.'); continue; }
      if (now.current.length >= MOST) break;
      const picture = await read(file);
      if (picture && now.current.length < MOST) put([...now.current, picture]);
    }
  }, [put]);
  return useMemo(() => ({
    held,
    onPaste,
    put,
    count: () => now.current.length,
    take: () => { const all = now.current; put([]); return all; },
    drop: p => put(now.current.filter(x => x !== p)),
  }), [held, onPaste, put]);
}
