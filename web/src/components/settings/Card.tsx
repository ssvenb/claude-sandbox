import { useId, useState, type ReactNode } from 'react';
import { filtered, type CardSpec } from './cards';
import { Field, Info } from './Field';

/** A part of the sandbox (the sandbox itself, an agent, a plugin): its head, a row to click, and
 *  under it its settings (or cards of its own: the agents), folded away until asked for (or while
 *  the filter is set). Its description is behind an ⓘ while it is open. Folded, they
 *  stay in the form, so what was typed in them is kept. */
export function Card({ card, query }: { card: CardSpec; query: string }) {
  const { hidden, hit, hiddenFields } = filtered(card, query);
  const [open, setOpen] = useState(!!card.open);
  const shown = open || !!query;
  const body = useId();
  const set = card.fields.filter(f => f.slot.get() !== undefined).length;
  const summary = card.summary ?? (set ? set + ' set' : '');
  return (
    <section data-card={card.key} className={['card', card.off && 'off', shown && 'open', hidden && 'hidden'].filter(Boolean).join(' ')}>
      <div className="head">
        <button type="button" className="toggle" aria-expanded={shown} aria-controls={body} onClick={() => setOpen(!shown)}>
          <span className="chev" aria-hidden="true" />
          <b>{card.title}{card.tag && <span className="agent">{card.tag}</span>}</b>
          {summary && <span className="count">{summary}</span>}
        </button>
        {shown && card.description && <Info text={card.description} about={card.title} />}
        {card.right}
      </div>
      <div className="fold" id={body} inert={!shown}>
        <div><div className="inner">
          <div className={'fields' + (card.off ? ' hidden' : '')}>
            {card.fields.map((field, k) => <Field key={field.name} {...field} hidden={hiddenFields[k]} />)}
          </div>
          {card.after}
          {!!card.cards?.length && card.cardsTitle && <h5 className="sub">{card.cardsTitle}</h5>}
          {!!card.cards?.length && <div className="stack">{card.cards.map(c => <Card key={c.key} card={c} query={hit ? '' : query} />)}</div>}
        </div></div>
      </div>
    </section>
  );
}

/** Cards under a heading (and what it offers: the plugins' Reset all), which goes when the filter keeps none of them. */
export function CardGroup({ title, cards, query, action }: { title: string; cards: CardSpec[]; query: string; action?: ReactNode }) {
  return (
    <>
      <h4 className={cards.every(card => filtered(card, query).hidden) ? 'hidden' : undefined}>{title}{action}</h4>
      <div className="stack">
        {cards.map(card => <Card key={card.key} card={card} query={query} />)}
      </div>
    </>
  );
}
