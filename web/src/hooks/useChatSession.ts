// A chat session, live: its conversation as its events left it (lib/transcript.ts), fed from the
// server's stream; the session itself as the server lists it; and everything its page can do to it.
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { message } from '../api/client';
import type { Answers, StreamMessage } from '../api/events';
import * as server from '../api/sessions';
import type { AppState, Item, Picture, Upload } from '../api/types';
import { deleteAfterAsking, stopAfterAsking } from '../lib/sessionActions';
import { announceDeleted, onSessionDeleted, sessionTab } from '../lib/tabs';
import { Transcript } from '../lib/transcript';
import { useEventStream } from './useEventStream';
import { usePolling } from './usePolling';

export interface ChatSession {
  /** The conversation. It changes in place: `version` goes up whenever it did. */
  transcript: Transcript;
  version: number;
  /** What the project's plugins tie to this run (its pull request). */
  items: Item[];
  /** The session is no longer there. */
  gone: boolean;
  /** An interrupt is on its way. */
  halting: boolean;
  stop: () => Promise<void>;
  remove: () => Promise<void>;
  /** Opens the session's checkout in VS Code, in a tab that closes with the session. */
  openCode: () => Promise<void>;
  /** Starts the run again, in this tab. */
  resume: () => Promise<void>;
  interrupt: () => Promise<void>;
  answer: (ask: string, reply: { answers: Answers } | { cancel: true }) => void;
  /** Sends a message; throws when it could not be sent. */
  send: (text: string, images: Picture[], files: Upload[]) => Promise<unknown>;
  choose: (what: 'model' | 'effort', value: string) => void;
  stopTask: (task: string) => Promise<unknown>;
}

export function useChatSession(id: string): ChatSession {
  const [transcript] = useState(() => new Transcript());
  const [version, update] = useReducer((n: number) => n + 1, 0);
  const [items, setItems] = useState<Item[]>([]);
  const [gone, setGone] = useState(false);
  const [halting, setHalting] = useState(false);
  const described = useRef(false);
  const vsTab = useRef<Window | null>(null);  // the VS Code tab this page opened: closed with the session

  const leave = useCallback(() => {
    vsTab.current?.close();
    window.close();
  }, []);

  // The session as the server lists it now; no longer listed, it is gone and so is this tab.
  const poll = useCallback(async () => {
    const known: Pick<AppState, 'sessions'> = { sessions: transcript.session ? [transcript.session] : [] };
    const s = (await server.getState().catch(() => known)).sessions.find(s => s.id === id);
    if (s) transcript.session = s;
    else {
      setGone(true);
      leave();
    }
    update();
  }, [id, transcript, leave]);

  const describe = useCallback(async () => {
    const session = transcript.session;
    if (!session?.run_id) return;
    const said = await server.getProject(session.project).catch(() => null);
    if (!said) return;
    described.current = true;
    setItems([...(said.session_items ?? []), ...(said.run_items ?? []), ...(said.lists ?? []).flatMap(l => l.items)]
      .filter(i => i.run_id === session.run_id));
  }, [transcript]);

  const closeStream = useEventStream(server.eventsUrl(id), {
    onMessage: data => {
      const e = JSON.parse(data) as StreamMessage;
      if (e.type === 'snapshot') {
        transcript.restore(e);
        if (!described.current) void describe();
      } else transcript.handle(e);
      update();
      // Nothing more will come.
      if (e.type === 'exit' || (e.type === 'snapshot' && e.session.exit !== null)) closeStream();
    },
    onError: closed => { if (closed) void poll(); },
  });
  useEffect(() => { if (gone) closeStream(); }, [gone, closeStream]);
  usePolling(poll, 3000);
  usePolling(describe, 60000);

  // Deleted from another page (the dashboard): this tab goes with it.
  useEffect(() => onSessionDeleted(s => { if (s.id === id) leave(); }), [id, leave]);

  const interrupt = useCallback(async () => {
    setHalting(true);
    await server.interruptSession(id).catch(e => alert(message(e)));
    setHalting(false);
  }, [id]);

  const actions = useMemo(() => ({
    stop: async () => {
      if (transcript.session && await stopAfterAsking(transcript.session, 'Stop this session?')) await poll();
    },
    remove: async () => {
      const session = transcript.session;
      if (!session || !await deleteAfterAsking(session, 'Stop and delete this session?')) return;
      announceDeleted(session);
      leave();
      await poll();  // still here: this tab was not opened by the dashboard, so it may not close itself
    },
    openCode: async () => {
      const w = (vsTab.current = window.open('', 'code-' + transcript.session?.workspace));
      try {
        const { folder } = await server.openVscode(id);
        w?.location.replace('/vscode/?folder=' + encodeURIComponent(folder));
      } catch (e) {
        w?.close();
        alert(message(e));
      }
    },
    resume: async () => {
      const session = transcript.session;
      if (!session?.run_id) return;
      try {
        const s = await server.startSession({ project: session.project, kind: 'resume', run_id: session.run_id });
        window.name = sessionTab(s.id);
        location.hash = s.id;
        location.reload();
      } catch (e) {
        alert(message(e));
      }
    },
    answer: (ask: string, reply: { answers: Answers } | { cancel: true }) => {
      transcript.answered(ask, 'cancel' in reply ? null : reply.answers);
      update();
      server.sendAnswer(id, ask, reply).catch(e => alert(message(e)));
    },
    send: (text: string, images: Picture[], files: Upload[]) =>
      server.sendPrompt(id, text, images.length ? images : undefined, files.length ? files : undefined),
    choose: (what: 'model' | 'effort', value: string) => {
      transcript.chosen[what] = value;
      update();
      (what === 'model' ? server.chooseModel : server.chooseEffort)(id, value).catch(e => {
        delete transcript.chosen[what];
        update();
        alert(message(e));
      });
    },
    stopTask: (task: string) => server.stopTask(id, task),
  }), [id, transcript, poll, leave]);

  return { transcript, version, items, gone, halting, interrupt, ...actions };
}
