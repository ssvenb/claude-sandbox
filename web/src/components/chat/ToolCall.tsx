import { memo, useState, type MouseEvent } from 'react';
import { message } from '../../api/client';
import type { ToolRecord } from '../../lib/transcript';
import { verb, what } from '../../lib/tools';
import { Icon } from '../common/Icon';
import { Spin } from '../common/Spinner';
import { useChatActions } from './ChatContext';
import { Entries } from './Entries';
import { ToolInput } from './ToolInput';

interface Props {
  tool: ToolRecord;
  /** The record's version: it is drawn again only when this changed. */
  v: number;
}

/** What a call the turn waits on can do instead: go on in the background, or stop. As the terminal's
 *  Ctrl+B. A click here is not the line's: it does not open it. */
function Hold({ call, task }: { call: string; task: string }) {
  const { background, stopTask } = useChatActions();
  const [busy, setBusy] = useState<'background' | 'stop' | null>(null);
  const act = (what: 'background' | 'stop') => (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setBusy(what);
    (what === 'background' ? background(call) : stopTask(task)).catch(err => {
      setBusy(null);
      alert(message(err));
    });
  };
  return (
    <span className="hold" role="group" aria-label="While it runs">
      <button type="button" className={'pill' + (busy === 'background' ? ' busy' : '')} disabled={!!busy}
        aria-label="Run in the background" title="Run in the background: the agent goes on, this keeps running" onClick={act('background')}>
        <Icon name="tray" /><span>Background</span>
      </button>
      <button type="button" className={'pill stop' + (busy === 'stop' ? ' busy' : '')} disabled={!!busy}
        aria-label="Stop it" title="Stop this one; the agent goes on" onClick={act('stop')}>
        <Icon name="stop" /><span>Stop</span>
      </button>
    </span>
  );
}

/** What the agent did, one line per tool call; open the line for what went in and what came back. */
export const ToolCall = memo(function ToolCall({ tool: t }: Props) {
  const input = t.input;
  const description = typeof input?.description === 'string' ? input.description : undefined;
  return (
    <details className={'tool ' + (t.done ? (t.error ? 'failed' : 'done') : 'running')}>
      <summary>
        <span className="mark">{t.done ? (t.error ? '✕' : '✓') : <Spin />}</span>
        <span className="verb">{verb(t)}</span>
        <span className="what" title={description}>{t.progress || what(input)}</span>
        <span className="took">{t.done ? '' : t.took}</span>
        {!t.done && t.task && <Hold call={t.call} task={t.task} />}
      </summary>
      <div className="body">
        <div className="given"><ToolInput input={input} /></div>
        <div className="kids"><Entries list={t.kids} /></div>
        <div className="out">{t.out && <pre className={t.error ? 'err' : undefined}>{t.out}</pre>}</div>
      </div>
    </details>
  );
});
