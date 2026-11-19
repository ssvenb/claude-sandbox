// A session's conversation: the header says which and how it is doing, the column is what was said
// and done, the dock at the bottom is where the next message is written. The dock is there from the
// first moment, while the sandbox still starts. On a desk the chat has a panel on either side: on
// the left what the project's plugins show (the files the run changed), on the right its side
// chats; each as wide as the reader makes it, and put away from its button in the header.
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { BackgroundTasks } from '../components/chat/BackgroundTasks';
import { Boot } from '../components/chat/Boot';
import { ChatContext, type ChatActions } from '../components/chat/ChatContext';
import { ChatHeader } from '../components/chat/ChatHeader';
import { Composer } from '../components/chat/Composer';
import { Entries } from '../components/chat/Entries';
import { Pane, PaneToggle } from '../components/chat/Pane';
import { Plan } from '../components/chat/Plan';
import { SideChats } from '../components/chat/SideChats';
import { Icon } from '../components/common/Icon';
import { Gone } from '../components/common/Gone';
import { useChatSession } from '../hooks/useChatSession';
import { useFollowScroll } from '../hooks/useFollowScroll';
import { usePane } from '../hooks/usePane';
import { useTabIdentity } from '../hooks/useTabIdentity';
import { here } from '../lib/items';
import { projectName, sessionIdFromLocation, titled } from '../lib/session';
import { PLUGINS } from '../plugins';

export default function Chat() {
  const id = useMemo(sessionIdFromLocation, []);
  const chat = useChatSession(id);
  const { transcript: t, gone, halting, interrupt } = chat;
  const { session, info, boot, ready, over } = t;
  const state = over !== null ? null : t.status;
  const working = state === 'working';

  // As on the dashboard's cards: idle with background tasks still running counts as working.
  const lamp = state === 'idle' && t.tasks.length ? 'working' : state;
  useTabIdentity(session && `${titled(session)} · ${projectName(session.project)}`, !session ? 'starting' : lamp ?? 'unlit');

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

  // What the project's plugins add to the page. Every plugin's hook is called on every draw, in
  // the same order: with the session only where its project enables that plugin.
  const parts = PLUGINS.map(p => {
    const enabled = session && !gone && session.plugins?.includes(p.name);
    return { name: p.name, ...p.useChat?.(enabled ? session : null) };
  });
  const slot = (part: 'bar' | 'actions' | 'aside') => parts.map(p => <Fragment key={p.name}>{p[part]}</Fragment>);

  const { answer, resume, stopTask } = chat;
  const actions = useMemo<ChatActions>(() => ({ answer, resume, stopTask }), [answer, resume, stopTask]);
  const chips = [...chat.items, ...(session?.items ?? []).map(here)];

  const left = usePane('left', 300, 200, 560), right = usePane('right', 380, 280, 720);
  // Side chats are there from the first moment, like the dock; gone once the agent says it takes none.
  const sided = !!session && !gone && !(ready && !info.sides);
  const asking = [...t.sides.values()].filter(s => s.status === 'working').length;

  return (
    <ChatContext value={actions}>
      <ChatHeader session={session} gone={gone} info={info} state={state} items={chips}
        bar={slot('bar')} actions={slot('actions')} onStop={chat.stop} onDelete={chat.remove}
        start={<PaneToggle side="left" what="changed files" pane={left} />}
        end={sided && (
          <>
            <button className="icon side-toggle" popoverTarget="sidechat" aria-label="Side chats" title="Side chats">
              <Icon name="aside" />{asking > 0 && <span className="lamp working" />}
            </button>
            <PaneToggle side="right" what="side chats" pane={right} />
          </>
        )} />
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
      <Pane side="left" what="changed files" pane={left}>{slot('aside')}</Pane>
      {sided && (
        <Pane side="right" what="side chats" pane={right}>
          <SideChats sides={t.sides} ready={ready} ended={over !== null}
            onAsk={chat.askSide} onClose={chat.closeSide} onInterrupt={chat.interruptSide} />
        </Pane>
      )}
    </ChatContext>
  );
}
