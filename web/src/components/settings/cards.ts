// The settings form is a card per part (the sandbox, an agent, a plugin), its settings in it. The
// filter keeps the cards, or the settings of a card, that mention what it is given.
import type { ReactNode } from 'react';
import type { SettingSpec } from '../../api/types';
import type { FieldProps } from './Field';

export interface CardSpec {
  key: string;
  title: string;
  description?: string;
  /** A word beside the title: `selected`, `claude only`. */
  tag?: string;
  fields: FieldProps[];
  /** On the card's head, right of its title: a plugin's switch. */
  right?: ReactNode;
  /** Under its fields. */
  after?: ReactNode;
  /** Switched off: dimmed, its settings not shown. */
  off?: boolean;
  /** More for the filter to find the card by. */
  more?: string;
}

const searchOf = (spec: SettingSpec): string => [spec.label, spec.key, spec.env, spec.description].join(' ').toLowerCase();

/** What of a card the filter `q` (in lower case) keeps: nothing of it, or which of its fields. */
export function filtered(card: CardSpec, q: string): { hidden: boolean; hiddenFields: boolean[] } {
  const hit = !q || ([card.title, card.description, card.tag ?? ''].join(' ').toLowerCase() + (card.more ?? '')).includes(q);
  const hits = card.fields.map(f => searchOf(f.spec).includes(q));
  return { hidden: !hit && !hits.some(Boolean), hiddenFields: hits.map(found => !!q && !hit && !found) };
}
