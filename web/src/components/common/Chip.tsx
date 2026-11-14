import type { MouseEvent } from 'react';
import type { Item, ItemStatus } from '../../api/types';
import { tip } from '../../lib/items';

const MARKS: Record<ItemStatus, string> = { ok: '✓', fail: '✕', pending: '●', done: '⇥' };

/** A listed item's status mark (its CI, merged), spelled out for a screen reader. */
export function StatusMark({ item }: { item: Item }) {
  if (!item.status) return null;
  return (
    <span className={'status ' + item.status} aria-label={item.status_text || item.status}>
      {MARKS[item.status] ?? ''}
    </span>
  );
}

interface Props {
  item: Item;
  onClick?: (e: MouseEvent<HTMLAnchorElement>) => void;
}

/** An item on a session's row (its pull request, a port it serves): its mark and its ref, opening its url. */
export function Chip({ item, onClick }: Props) {
  return (
    <a className={('chip ' + (item.status ?? '')).trim()} href={item.url} target="_blank" rel="noopener" onClick={onClick} title={tip(item)}>
      <StatusMark item={item} />
      {item.ref || item.title}
    </a>
  );
}
