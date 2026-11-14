import { useRef, useState, type KeyboardEvent } from 'react';
import type { Answers } from '../../api/events';
import type { AskRecord } from '../../lib/transcript';
import { useChatActions } from './ChatContext';
import { Markdown } from './Markdown';

/** A question the agent asked, and what was answered. */
function SettledQuestion({ ask }: { ask: AskRecord }) {
  return (
    <div className="ask settled">
      {ask.e.questions.map((q, k) => (
        <div key={k}>
          {q.question + ' '}
          <span className="said">{ask.answers === null ? 'Dismissed' : ask.answers?.[q.question] || ''}</span>
        </div>
      ))}
    </div>
  );
}

/** A question the agent waits on. One question with one choice answers on the click; anything
 *  more is collected and sent together. */
function OpenQuestion({ ask }: { ask: AskRecord }) {
  const { answer } = useChatActions();
  const { id, questions } = ask.e;
  const [picked, setPicked] = useState<ReadonlySet<string>[]>(() => questions.map(() => new Set()));
  const other = useRef(questions.map(() => ''));  // what was written in each question's own field
  const [sending, setSending] = useState(false);
  const single = questions.length === 1 && !questions[0]!.multi;

  const answers = (from: ReadonlySet<string>[]): Answers =>
    Object.fromEntries(questions.map((q, k) => {
      const own = other.current[k]!.trim();
      return [q.question, [...from[k]!, ...(own ? [own] : [])].join(', ')];
    }));
  const send = (reply: { answers: Answers } | { cancel: true }) => {
    setSending(true);
    answer(id, reply);
  };
  const withPicked = (k: number, set: ReadonlySet<string>) => picked.map((old, at) => (at === k ? set : old));
  const pick = (k: number, label: string) => {
    if (single) return send({ answers: answers(withPicked(k, new Set([label]))) });
    const on = picked[k]!.has(label);
    const set = new Set(questions[k]!.multi ? picked[k] : []);
    if (on) set.delete(label);
    else set.add(label);
    setPicked(withPicked(k, set));
  };
  const own = (e: KeyboardEvent<HTMLInputElement>, k: number) => {
    if (e.key !== 'Enter' || !e.currentTarget.value.trim()) return;
    e.preventDefault();
    send({ answers: answers(single ? withPicked(k, new Set()) : picked) });
  };

  return (
    <div className="ask">
      {questions.map((q, k) => (
        <div className="q" key={k}>
          {q.header && <small>{q.header}</small>}
          <b>{q.question}</b>
          {q.plan && <div className="plan say"><Markdown text={q.plan} /></div>}
          <div className="options">
            {q.options.map(o => (
              <button key={o.label} type="button" aria-pressed={picked[k]!.has(o.label)} disabled={sending} onClick={() => pick(k, o.label)}>
                <b>{o.label}</b>
                {o.description && <span>{o.description}</span>}
              </button>
            ))}
          </div>
          <div className="other">
            <input type="text" placeholder={q.options.length ? 'Something else…' : 'Your answer…'} aria-label="Your own answer"
              disabled={sending} onChange={e => { other.current[k] = e.target.value; }} onKeyDown={e => own(e, k)} />
          </div>
        </div>
      ))}
      <div className="row">
        <button type="button" disabled={sending} onClick={() => send({ cancel: true })}>Dismiss</button>
        {!single && <button type="button" className="primary" disabled={sending} onClick={() => send({ answers: answers(picked) })}>Send answers</button>}
      </div>
    </div>
  );
}

export const Question = ({ ask }: { ask: AskRecord }) => (ask.settled ? <SettledQuestion ask={ask} /> : <OpenQuestion ask={ask} />);
