// The terminal itself: xterm.js on a session's pty. What the pty writes comes on the session's
// stream, what is typed goes back as it is.
import { FitAddon } from '@xterm/addon-fit';
import { Terminal, type ITheme } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { resizeTerminal, sendInput, streamUrl } from '../../api/sessions';
import { useEventStream } from '../../hooks/useEventStream';
import { useThemeChange } from '../../hooks/useTheme';
import { copy } from '../../lib/clipboard';
import { Loading } from '../common/Spinner';

declare global {
  interface Window {
    /** To look into from the console (and from the tests). */
    term?: Terminal;
  }
}

// The terminal wears the page's colours, by day and by night.
function palette(): ITheme {
  const v = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return { background: v('--panel'), foreground: v('--ink'), cursor: v('--lamp'), cursorAccent: v('--panel'), selectionBackground: v('--link') + '55' };
}

/** What is typed goes to the session one POST at a time, batching what was typed meanwhile:
 *  parallel requests could arrive reordered. */
function typist(session: string): (data: string) => void {
  let pending = '', sending = false;
  async function flush(): Promise<void> {
    if (sending || !pending) return;
    sending = true;
    const data = pending;
    pending = '';
    try {
      await sendInput(session, data);
    } catch { /* the server is away: what was typed is lost, as on a dead line */ }
    sending = false;
    void flush();
  }
  return data => {
    pending += data;
    void flush();
  };
}

// Copy and paste as in other terminals on the web: Ctrl+C copies when there is a selection (and
// interrupts as usual without one), Ctrl+Shift+C always copies. When the program takes the mouse
// (an agent's TUI does), Shift+drag still selects.
function clipboardKeys(term: Terminal): (e: KeyboardEvent) => boolean {
  return e => {
    const command = (e.ctrlKey || e.metaKey) && !e.altKey;
    // Ctrl+V pastes like Ctrl+Shift+V: left to the browser, whose paste the terminal takes in
    // (bracketed and all), instead of going on to the program as ^V.
    if (command && e.code === 'KeyV') return false;
    if (e.type !== 'keydown' || !command || e.code !== 'KeyC' || !(e.shiftKey || term.hasSelection())) return true;
    e.preventDefault();
    if (term.hasSelection()) {  // copied, then let go: the next Ctrl+C is an interrupt again
      void copy(term.getSelection()).then(() => term.focus());
      term.clearSelection();
    }
    return false;  // not to the program
  };
}

interface Props {
  /** The session whose pty this is. */
  session: string;
  /** Its program exited. */
  onExit: () => void;
}

export function TerminalScreen({ session, onExit }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const [connected, setConnected] = useState(false);

  // The pty is as large as the terminal on the page.
  const resize = useCallback(() => {
    const t = term.current;
    if (!t) return;
    fit.current?.fit();
    void resizeTerminal(session, t.cols, t.rows).catch(() => {});
  }, [session]);

  useEffect(() => {
    const t = new Terminal({
      fontSize: 13, cursorBlink: true, fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      theme: palette(), minimumContrastRatio: 4.5,
    });
    const fitting = new FitAddon();
    t.loadAddon(fitting);
    t.open(box.current!);
    t.onData(typist(session));
    t.attachCustomKeyEventHandler(clipboardKeys(t));
    term.current = window.term = t;
    fit.current = fitting;
    const watch = new ResizeObserver(resize);
    watch.observe(box.current!);
    t.focus();
    return () => {
      watch.disconnect();
      t.dispose();
      term.current = fit.current = null;
    };
  }, [session, resize]);

  useThemeChange(useCallback(() => {
    if (term.current) term.current.options.theme = palette();
  }, []));

  const close = useEventStream(streamUrl(session), {
    // The stream starts with the scrollback again after a reconnect, so start clean each time.
    onOpen: () => {
      term.current?.reset();
      resize();
      setConnected(true);
    },
    onMessage: data => term.current?.write(Uint8Array.from(atob(data), c => c.charCodeAt(0))),
    events: {
      exit: () => {
        close();
        onExit();
      },
    },
  });

  return (
    <>
      <div id="term" ref={box} />
      <div id="wait" hidden={connected}><Loading text="Connecting to the terminal" /></div>
    </>
  );
}
