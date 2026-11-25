// The settings form is a card per part (the sandbox, an agent, a plugin), its settings in it. The
// filter keeps the cards, or the settings of a card, that mention what it is given.
import type { ReactNode } from 'react';
import type { SettingSpec } from '../../api/types';
import type { FieldProps } from './Field';

export interface CardSpec {
  key: string;
  title: string;
  description?: string;
  fields: FieldProps[];
  /** On the card's head, right of its title: a plugin's switch. */
  right?: ReactNode;
  /** Under its fields. */
  after?: ReactNode;
  /** Unfolded when the form opens. */
  open?: boolean;
  /** Switched off: dimmed, its settings not shown. */
  off?: boolean;
  /** Cards under it, folded with it: the agents', an agent's own plugins. */
  cards?: CardSpec[];
  /** A heading over those cards. */
  cardsTitle?: string;
  /** More for the filter to find the card by. */
  more?: string;
}

const searchOf = (spec: SettingSpec): string => [spec.label, spec.key, spec.env, spec.description].join(' ').toLowerCase();

/** What of a card the filter `q` (in lower case) keeps: nothing of it, or which of its fields (and
 *  cards); `hit`, the card itself matches, so all of it is kept. */
export function filtered(card: CardSpec, q: string): { hidden: boolean; hit: boolean; hiddenFields: boolean[] } {
  const hit = !q || ([card.title, card.description].join(' ').toLowerCase() + (card.more ?? '')).includes(q);
  const hits = card.fields.map(f => searchOf(f.spec).includes(q));
  const inner = (card.cards ?? []).some(c => !filtered(c, q).hidden);
  return { hidden: !hit && !hits.some(Boolean) && !inner, hit, hiddenFields: hits.map(found => !!q && !hit && !found) };
}
