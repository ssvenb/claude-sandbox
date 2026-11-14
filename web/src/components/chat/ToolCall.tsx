import { memo } from 'react';
import type { ToolRecord } from '../../lib/transcript';
import { verb, what } from '../../lib/tools';
import { Spin } from '../common/Spinner';
import { Entries } from './Entries';
import { ToolInput } from './ToolInput';

interface Props {
  tool: ToolRecord;
  /** The record's version: it is drawn again only when this changed. */
  v: number;
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
      </summary>
      <div className="body">
        <div className="given"><ToolInput input={input} /></div>
        <div className="kids"><Entries list={t.kids} /></div>
        <div className="out">{t.out && <pre className={t.error ? 'err' : undefined}>{t.out}</pre>}</div>
      </div>
    </details>
  );
});
