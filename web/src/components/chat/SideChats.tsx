import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { message } from '../../api/client';
import { useAutoGrow } from '../../hooks/useAutoGrow';
import { useFollowScroll } from '../../hooks/useFollowScroll';
import type { Transcript } from '../../lib/transcript';
import { Icon } from '../common/Icon';
import { Entries, Thinking } from './Entries';

interface Props {
  /** The session's side chats, by id (lib/transcript.ts). */
  sides: Map<string, Transcript>;
  /** The agent is up and takes questions; the session is over and takes none. */
  ready: boolean;
  ended: boolean;
  /** Asks in a side chat (a new one for null) and says which it was; throws when it could not be sent. */
  onAsk: (side: string | null, text: string) => Promise<string>;
  onClose: (side: string) => void;
  onInterrupt: (side: string) => void;
}

const NEW = 'new';  // the tab of a side chat not asked anything yet: it is not one until it is
const touchScreen = matchMedia('(pointer: coarse)').matches;  // a soft keyboard's Enter is a new line; the button sends

/** Questions about the conversation, asked beside it while the agent works on: each side chat a
 *  tab, with what was asked and answered in it and a field for the next question. Beside the chat
 *  on a desk, a popover from the header's button on a smaller screen. */
export function SideChats({ sides, ready, ended, onAsk, onClose, onInterrupt }: Props) {
  const ids = [...sides.keys()];
  const [picked, setPicked] = useState<string | null>(null);
  // The tab in view: the one picked while it is there, else the newest; none yet, the new one.
  const active = picked === NEW ? null : picked !== null && sides.has(picked) ? picked : ids.at(-1) ?? null;
  const chat = active === null ? null : sides.get(active)!;
  const working = chat?.status === 'working';
  // Not every answer thinks first: while its turn runs and nothing on the page moves, it says it is at it.
  const last = chat?.log.at(-1);
  const moving = last && ('streaming' in last ? last.streaming : last.kind === 'tools' && last.list.some(t => !t.done));

  const input = useRef<HTMLTextAreaElement>(null), form = useRef<HTMLFormElement>(null);
  const scroller = useRef<HTMLDivElement>(null), log = useRef<HTMLDivElement>(null);
  const grow = useAutoGrow(input, 0.3);
  const { onScroll, settle, follow } = useFollowScroll(scroller, log);
  const shown = useRef(active);
  useLayoutEffect(() => {
    if (chat?.wantsFollow || shown.current !== active) follow();
    if (chat) chat.wantsFollow = false;
    shown.current = active;
    settle();
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const el = input.current!, text = el.value;
    if (!text.trim() || ended || !ready) return;
    el.value = '';
    grow();
    try {
      const id = await onAsk(active, text);
      if (active === null) setPicked(id);
    } catch (err) {  // not sent: back in the field, to try again
      el.value = text;
      grow();
      alert(message(err));
    }
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !touchScreen) {
      e.preventDefault();
      form.current!.requestSubmit();
    } else if (e.key === 'Escape' && working) {  // this chat's turn, not the agent's in the conversation
      e.preventDefault();
      onInterrupt(active!);
    }
  };
  // Left and right walk the tabs, as in any row of them.
  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const tabs = [...e.currentTarget.querySelectorAll<HTMLElement>('[role=tab]')], at = tabs.indexOf(document.activeElement as HTMLElement);
    if (at < 0 || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
    e.preventDefault();
    const next = tabs[(at + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]!;
    next.focus();
    next.click();
  };

  const tabs = [...ids.map(id => ({ id, title: sides.get(id)!.title || 'Side chat', lamp: sides.get(id)!.status === 'working' })),
    ...(active === null && ids.length ? [{ id: NEW, title: 'New question', lamp: false }] : [])];
  const on = active ?? NEW;
  return (
    <aside id="sidechat" className="side" popover="auto" aria-label="Side chats">
      <div className="head">
        {tabs.length ? (
          <div className="tabs" role="tablist" aria-label="Side chats" onKeyDown={onTabKey}>
            {tabs.map(t => (
              <span key={t.id} className={'tab' + (t.id === on ? ' on' : '')}>
                <button role="tab" id={`side-tab-${t.id}`} aria-selected={t.id === on} aria-controls="side-thread"
                  tabIndex={t.id === on ? 0 : -1} title={t.title} onClick={() => setPicked(t.id)}>
                  {t.lamp && <span className="lamp working" />}
                  <span>{t.title}</span>
                </button>
                <button className="shut" aria-label={`Close “${t.title}”`} title="Close"
                  onClick={() => (t.id === NEW ? setPicked(null) : onClose(t.id))}>
                  <Icon name="close" />
                </button>
              </span>
            ))}
          </div>
        ) : <b>Side chat</b>}
        {ids.length > 0 && (
          <button className="icon" aria-label="New side chat" title="New side chat" disabled={active === null}
            onClick={() => { setPicked(NEW); input.current?.focus(); }}>
            <Icon name="plus" />
          </button>
        )}
      </div>
      <div id="side-thread" className="thread" role="tabpanel" aria-labelledby={tabs.length ? `side-tab-${on}` : undefined}
        ref={scroller} onScroll={onScroll}>
        <div className="log" aria-live="polite" ref={log}>
          {chat && <Entries list={chat.log} />}
          {working && !moving && <Thinking streaming />}
        </div>
      </div>
      <form className="composer" ref={form} onSubmit={submit}>
        <textarea ref={input} rows={1} aria-label="Question for the side chat" autoComplete="off" disabled={ended || !ready}
          placeholder={ended ? 'Session ended' : ready ? 'Ask about this conversation' : 'Waiting for the agent'}
          onChange={grow} onKeyDown={onKeyDown} />
        <div className="bar">
          <span className="hint" />
          <button className="round halt" type="button" title="Interrupt (Esc)" aria-label="Interrupt the side chat"
            hidden={!working} onClick={() => onInterrupt(active!)}>
            <Icon name="stop" />
          </button>
          <button className="round primary" type="submit" aria-label="Ask" disabled={ended || !ready}>
            <Icon name="send" />
          </button>
        </div>
      </form>
    </aside>
  );
}
