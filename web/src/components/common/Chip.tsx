import type { MouseEvent } from 'react';
import type { Item, ItemStatus } from '../../api/types';
import { tip } from '../../lib/items';
import { Icon } from './Icon';

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

/** An item on a session's row (its pull request, a port it serves): its mark and its ref, opening its url.
 *  A server it runs is a button to open: its lamp lit once it answers, with the arrow of a link that leaves the page. */
export function Chip({ item, onClick }: Props) {
  const live = item.port !== undefined;
  return (
    <a className={['chip', item.status, live && 'live'].filter(Boolean).join(' ')} href={item.url} target="_blank" rel="noopener"
      onClick={onClick} title={tip(item)}>
      {live ? <span className={item.up ? 'lamp live up' : 'lamp live'} aria-label={item.up ? 'up' : 'starting'} /> : <StatusMark item={item} />}
      {item.ref || item.title}
      {live && <Icon name="open" />}
    </a>
  );
}
