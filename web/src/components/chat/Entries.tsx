import { memo } from 'react';
import type { Entry as Record, OverRecord, YouRecord } from '../../lib/transcript';
import { BusyButton } from '../common/BusyButton';
import { Icon } from '../common/Icon';
import { SentImages } from '../common/Pictures';
import { Spin } from '../common/Spinner';
import { useChatActions } from './ChatContext';
import { Markdown } from './Markdown';
import { Question } from './Question';
import { ToolCall } from './ToolCall';

/** What you said, with the pictures that went along. On its way to the server: faint, a ring
 *  turning under it. Could not be sent: marked, and why, with a way to send it again or change it.
 *  Still waiting for the sandbox: dashed. */
function UserMessage({ message: m }: { message: YouRecord }) {
  const { resend, edit } = useChatActions();
  const state = m.failed !== undefined ? 'failed' : m.sending ? 'sending' : m.queued ? 'queued' : '';
  return (
    <>
      <div className={'you' + (state && ' ' + state)}>
        {state === 'failed' && <span className="alert"><Icon name="alert" /></span>}
        {!!(m.images?.length || m.files?.length) && <SentImages images={m.images} files={m.files} />}
        {m.text}
      </div>
      {state === 'sending' && <div className="sent-state sending" role="status"><Spin />Sending…</div>}
      {state === 'failed' && (
        <div className="sent-state failed" role="alert">
          <span className="why"><b>Not sent</b>{m.failed && <> · {m.failed}</>}</span>
          <button type="button" className="pill" onClick={() => resend(m.nonce!)}><Icon name="retry" />Retry</button>
          <button type="button" className="pill quiet" onClick={() => edit(m.nonce!)}><Icon name="edit" />Edit</button>
        </div>
      )}
    </>
  );
}

/** What the agent wrote, a caret at its end while it still streams in. */
const AgentMessage = ({ text, streaming }: { text: string; streaming: boolean }) => (
  <div className={'say' + (streaming ? ' streaming' : '')}><Markdown text={text} /></div>
);

/** That it thought before it spoke: a line, turning while it does. What it thought is not shown. */
export const Thinking = ({ streaming }: { streaming: boolean }) => (
  <div className="think">{streaming && <Spin />}{streaming ? 'Thinking' : 'Thought'}</div>
);

/** The session is over: how it ended, and a way to take its run up again. */
function SessionOver({ over }: { over: OverRecord }) {
  const { resume } = useChatActions();
  return (
    <div className="over">
      <b>Session ended</b>
      <span>{over.code ? `Exit status ${over.code}` : ''}</span>
      {over.runId && <BusyButton className="primary" onClick={resume}>Resume</BusyButton>}
    </div>
  );
}

interface EntryProps {
  record: Record;
  /** The record's version: it is drawn again only when this changed. */
  v: number;
}

/** One record of the column, drawn as what it is. */
const Entry = memo(function Entry({ record: r }: EntryProps) {
  switch (r.kind) {
    case 'you': return <UserMessage message={r} />;
    case 'say': return <AgentMessage text={r.text} streaming={r.streaming} />;
    case 'think': return <Thinking streaming={r.streaming} />;
    case 'tools': return <div className="tools">{r.list.map(t => <ToolCall key={t.key} tool={t} v={t.v} />)}</div>;
    case 'ask': return <Question ask={r} />;
    case 'turn': return <div className="turn">{r.text}</div>;
    case 'note': return <div className={'note ' + r.level}>{r.text}</div>;
    case 'over': return <SessionOver over={r} />;
  }
});

/** The records of a column (the conversation, or what a subagent said and did), in order. */
export function Entries({ list }: { list: Record[] }) {
  return <>{list.map(r => <Entry key={r.key} record={r} v={r.v} />)}</>;
}
