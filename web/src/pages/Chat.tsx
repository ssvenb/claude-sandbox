// A session's conversation: the header says which and how it is doing, the column is what was said
// and done, the dock at the bottom is where the next message is written. The dock is there from the
// first moment, while the sandbox still starts.
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { BackgroundTasks } from '../components/chat/BackgroundTasks';
import { Boot } from '../components/chat/Boot';
import { ChatContext, type ChatActions } from '../components/chat/ChatContext';
import { ChatHeader } from '../components/chat/ChatHeader';
import { Composer } from '../components/chat/Composer';
import { Entries } from '../components/chat/Entries';
import { Plan } from '../components/chat/Plan';
import { Gone } from '../components/common/Gone';
import { useChatSession } from '../hooks/useChatSession';
import { useFollowScroll } from '../hooks/useFollowScroll';
import { useTabIdentity } from '../hooks/useTabIdentity';
import { here } from '../lib/items';
import { projectName, sessionIdFromLocation, titled } from '../lib/session';

export default function Chat() {
  const id = useMemo(sessionIdFromLocation, []);
  const chat = useChatSession(id);
  const { transcript: t, gone, halting, interrupt } = chat;
  const { session, info, boot, ready, over } = t;
  const state = over !== null ? null : t.status;
  const working = state === 'working';

  useTabIdentity(session && `${titled(session)} · ${projectName(session.project)}`, !session ? 'starting' : state ?? 'unlit');

  // The column keeps its newest line in view, until the reader scrolls up.
  const scroller = useRef<HTMLElement>(null), log = useRef<HTMLDivElement>(null);
  const { onScroll, settle, follow } = useFollowScroll(scroller, log);
  useLayoutEffect(() => {
    if (t.wantsFollow) {
      t.wantsFollow = false;
      follow();
    }
    settle();
  });

  // Esc interrupts, as in the terminal (unless it closed the commands' menu).
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented && working && !halting) void interrupt();
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [working, halting, interrupt]);

  // Another session in this tab (a resumed run, a pasted link): start over on it.
  useEffect(() => {
    const reload = () => location.reload();
    addEventListener('hashchange', reload);
    return () => removeEventListener('hashchange', reload);
  }, []);

  const { answer, resume, stopTask } = chat;
  const actions = useMemo<ChatActions>(() => ({ answer, resume, stopTask }), [answer, resume, stopTask]);
  const chips = [...chat.items, ...(session?.items ?? []).map(here)];

  return (
    <ChatContext value={actions}>
      <ChatHeader session={session} gone={gone} info={info} state={state} items={chips}
        onStop={chat.stop} onDelete={chat.remove} onCode={chat.openCode} />
      <Gone id="gone" hidden={!gone} />
      <main id="scroll" hidden={gone} ref={scroller} onScroll={onScroll}>
        <div className="column">
          <div id="log" aria-live="polite" ref={log}>
            {boot && <Boot boot={boot} ready={ready} failed={over !== null && !ready} agent={info.agent} />}
            <Entries list={t.log} />
          </div>
        </div>
      </main>
      <footer id="dock" hidden={gone}>
        <div className="column">
          <BackgroundTasks tasks={t.tasks} />
          <Plan items={t.todos} />
          <Composer session={id} info={info} model={t.chosen.model ?? info.model} effort={t.chosen.effort ?? info.effort}
            ready={ready} ended={over !== null} working={working} halting={halting}
            onSend={chat.send} onInterrupt={interrupt} onModel={m => chat.choose('model', m)} onEffort={l => chat.choose('effort', l)} />
        </div>
      </footer>
    </ChatContext>
  );
}
