import { useLayoutEffect, useRef } from 'react';
import type { Boot as BootOutput } from '../../lib/transcript';
import { Spin } from '../common/Spinner';

interface Props {
  boot: BootOutput;
  ready: boolean;
  /** The sandbox ended before its agent was ready. */
  failed: boolean;
  /** The agent, once the sandbox is up and it starts. */
  agent?: string;
}

/** The sandbox starting: a turning ring, the step it is on, its whole output on request. */
export function Boot({ boot, ready, failed, agent }: Props) {
  const box = useRef<HTMLDetailsElement>(null), pre = useRef<HTMLPreElement>(null);
  useLayoutEffect(() => {
    if (box.current?.open && pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  });
  return (
    <details ref={box} className={'boot ' + (failed ? 'failed' : ready ? 'ok quiet' : 'starting')} open={failed || undefined}>
      <summary>
        <span className="mark">{failed ? '✕' : ready ? '✓' : <Spin />}</span>
        <span className="step">{failed ? 'Sandbox failed' : ready ? 'Sandbox ready' : agent ? 'Starting the agent' : 'Starting the sandbox'}</span>
        <span className="line">{ready ? '' : boot.last}</span>
      </summary>
      <pre ref={pre}>{boot.text}</pre>
    </details>
  );
}
