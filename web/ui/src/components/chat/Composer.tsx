import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { message } from '../../api/client';
import type { AgentInfo, Command } from '../../api/events';
import type { Picture } from '../../api/types';
import { useAutoGrow } from '../../hooks/useAutoGrow';
import { usePastedImages } from '../../hooks/usePastedImages';
import { Icon } from '../common/Icon';
import { ImageTray } from '../common/Pictures';
import { CommandMenu } from './CommandMenu';
import { EffortPicker, ModelPicker } from './Pickers';

interface Props {
  /** The session the message is for: a message not yet sent is kept under it. */
  session: string;
  /** What the agent said it has: its commands, its models. */
  info: AgentInfo;
  /** The model and effort to show: what was picked here, else what the agent uses. */
  model?: string;
  effort?: string;
  /** The agent is up: with no command to offer before that, the menu waits. */
  ready: boolean;
  /** The session is over: nothing more to send. */
  ended: boolean;
  working: boolean;
  /** An interrupt is on its way. */
  halting: boolean;
  /** Sends a message; throws when it could not be sent. */
  onSend: (text: string, images: Picture[]) => Promise<unknown>;
  onInterrupt: () => void;
  onModel: (id: string) => void;
  onEffort: (level: string) => void;
}

const touchScreen = matchMedia('(pointer: coarse)').matches;  // a soft keyboard's Enter is a new line; the button sends

// What was written and not sent survives a reload of the tab.
const draft = (session: string) => ({
  get: (): string => { try { return sessionStorage.getItem('draft-' + session) || ''; } catch { return ''; } },
  set: (text: string): void => {
    try {
      if (text) sessionStorage.setItem('draft-' + session, text);
      else sessionStorage.removeItem('draft-' + session);
    } catch { /* no storage: nothing kept */ }
  },
});

/** The agent's commands that go with what is typed after the slash: what begins with it first,
 *  else as the agent lists them. */
function matching(commands: Command[], typed: string): Command[] {
  const lower = typed.toLowerCase(), starts = (c: Command) => Number(c.name.toLowerCase().startsWith(lower));
  return commands.filter(c => c.name.toLowerCase().includes(lower)).sort((a, b) => starts(b) - starts(a)).slice(0, 40);
}

/** Where the next message is written: the field, pasted pictures over it, the agent's commands
 *  as a slash is typed, its model and effort, and the buttons that send and interrupt. */
export function Composer({ session, info, model, effort, ready, ended, working, halting, onSend, onInterrupt, onModel, onEffort }: Props) {
  const input = useRef<HTMLTextAreaElement>(null), form = useRef<HTMLFormElement>(null);
  const pictures = usePastedImages();
  const [typed, setTyped] = useState<string | null>(null);  // the name after a lone slash, while that is all there is
  const [closed, setClosed] = useState(false);
  const [picked, setPicked] = useState(0);
  const grow = useAutoGrow(input, 0.4);
  const kept = draft(session);

  useLayoutEffect(() => {
    const el = input.current!;
    el.value = draft(session).get();
    grow();
    el.focus();
  }, [session, grow]);

  const offered = typed === null || closed ? [] : matching(info.commands ?? [], typed);
  const waiting = typed !== null && !closed && !ready && !offered.length;
  const at = Math.min(picked, Math.max(0, offered.length - 1));

  const choose = (c: Command) => {
    input.current!.value = `/${c.name} `;
    setClosed(true);
    grow();
    input.current!.focus();
  };
  const onChange = () => {
    const text = input.current!.value;
    grow();
    setPicked(0);
    setClosed(false);
    setTyped(/^\/(\S*)$/.exec(text)?.[1] ?? null);
    kept.set(text);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const on = offered[at];
    if (on) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        return setPicked((at + (e.key === 'ArrowDown' ? 1 : offered.length - 1)) % offered.length);
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && `/${on.name}` !== input.current!.value)) {
        e.preventDefault();
        return choose(on);
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        return setClosed(true);
      }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !touchScreen) {
      e.preventDefault();
      form.current!.requestSubmit();
    }
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const el = input.current!, text = el.value;
    if (!(text.trim() || pictures.count()) || ended) return;
    const images = pictures.take();
    el.value = '';
    kept.set('');
    setClosed(true);
    grow();
    try {
      await onSend(text, images);
    } catch (err) {  // not sent: back in the field, to try again
      el.value = text;
      pictures.put(images);
      grow();
      alert(message(err));
    }
  };

  return (
    <form className="composer" id="composer" ref={form} onSubmit={submit}>
      <CommandMenu offered={offered} at={at} waiting={waiting} onChoose={choose} />
      <ImageTray pictures={pictures} id="shots" onRemoved={() => input.current?.focus()} />
      <textarea id="input" ref={input} rows={1} aria-label="Message to the agent" autoComplete="off" disabled={ended}
        placeholder={ended ? 'Session ended' : 'Message'} onChange={onChange} onKeyDown={onKeyDown} onPaste={pictures.onPaste} />
      <div className="bar">
        <ModelPicker models={info.models ?? []} model={model} onChoose={onModel} />
        <EffortPicker efforts={info.efforts ?? []} effort={effort} onChoose={onEffort} />
        <span className="hint" />
        <button className={'round halt' + (halting ? ' busy' : '')} id="halt" type="button" title="Interrupt (Esc)" aria-label="Interrupt"
          hidden={!working} disabled={halting} onClick={onInterrupt}>
          <Icon name="stop" />
        </button>
        <button className="round primary" id="send" type="submit" aria-label="Send" disabled={ended}>
          <Icon name="send" />
        </button>
      </div>
    </form>
  );
}
