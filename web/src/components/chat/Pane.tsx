import { useRef, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import type { PaneState } from '../../hooks/usePane';
import type { IconName } from '../common/Icon';
import { Icon } from '../common/Icon';

type Side = 'left' | 'right';

interface Props {
  side: Side;
  /** What it holds, as its buttons name it: "changed files". */
  what: string;
  pane: PaneState;
  children: ReactNode;
}

/** A panel beside the chat on a desk: as wide as the reader drags its edge (or moves it with the
 *  arrow keys: a window splitter, as the ARIA practices describe one), and put away from its
 *  button in the header. On a smaller screen it is no box at all: what it holds is a popover. */
export function Pane({ side, what, pane, children }: Props) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  const out = side === 'left' ? 1 : -1;  // the way its edge moves to widen it
  const to = (width: number) => pane.resize(Math.min(pane.max, Math.max(pane.min, width)));

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();  // no text is selected on the way
    e.currentTarget.setPointerCapture(e.pointerId);
    e.currentTarget.focus();
    drag.current = { x: e.clientX, width: pane.width };
    document.documentElement.classList.add('resizing');
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (drag.current) to(drag.current.width + out * (e.clientX - drag.current.x));
  };
  const up = () => {
    drag.current = null;
    document.documentElement.classList.remove('resizing');
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 16;
    if (e.key === 'ArrowLeft') to(pane.width - out * step);
    else if (e.key === 'ArrowRight') to(pane.width + out * step);
    else if (e.key === 'Home') to(pane.min);
    else if (e.key === 'End') to(pane.max);
    else if (e.key === 'Enter') {
      pane.toggle();
      document.getElementById(`toggle-${side}`)?.focus();  // the edge goes with the panel: its button brings both back
    } else return;
    e.preventDefault();
  };

  return (
    <div id={`pane-${side}`} className={`pane ${side}${pane.shut ? ' shut' : ''}`} style={{ '--pane': `${pane.width}px` } as CSSProperties}>
      {children}
      <div className="splitter" role="separator" tabIndex={0} aria-orientation="vertical" aria-controls={`pane-${side}`}
        aria-label={`Width of the ${what}`} aria-valuenow={pane.width} aria-valuemin={pane.min} aria-valuemax={pane.max}
        aria-valuetext={`${pane.width} pixels`} title="Drag to resize, double-click to reset"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onDoubleClick={pane.reset} onKeyDown={key} />
    </div>
  );
}

/** The header's button that puts a panel away and brings it back, on a desk. */
export function PaneToggle({ side, what, pane }: Omit<Props, 'children'>) {
  const label = `${pane.shut ? 'Show' : 'Hide'} ${what}`;
  return (
    <button id={`toggle-${side}`} className={`icon pane-toggle ${side}`} aria-expanded={!pane.shut} aria-controls={`pane-${side}`}
      aria-label={label} title={label} onClick={pane.toggle}>
      <Icon name={`panel${side === 'left' ? 'Left' : 'Right'}` satisfies IconName} />
    </button>
  );
}
