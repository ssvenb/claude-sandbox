import { useLayoutEffect, useRef } from 'react';
import type { Command } from '../../api/events';
import { Loading } from '../common/Spinner';

interface Props {
  /** The commands on offer, the best match first. */
  offered: Command[];
  /** Which of them the arrow keys are on. */
  at: number;
  /** A slash was typed before the agent said what its commands are. */
  waiting: boolean;
  onChoose: (command: Command) => void;
}

/** The agent's slash commands and skills, offered over the field while a name is typed. */
export function CommandMenu({ offered, at, waiting, onChoose }: Props) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    box.current?.querySelector('[aria-selected=true]')?.scrollIntoView({ block: 'nearest' });
  });
  return (
    <div id="menu" role="listbox" ref={box} hidden={!offered.length && !waiting}>
      {waiting ? <Loading /> : offered.map((c, k) => (
        // On mousedown, and kept from taking the focus: the field keeps it.
        <button key={c.name} type="button" role="option" aria-selected={k === at} onMouseDown={e => { e.preventDefault(); onChoose(c); }}>
          <b>/{c.name}</b>
          {c.hint && <i>{c.hint}</i>}
          <span>{c.description || ''}</span>
        </button>
      ))}
    </div>
  );
}
