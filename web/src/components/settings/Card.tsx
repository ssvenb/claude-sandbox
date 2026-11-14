import { filtered, type CardSpec } from './cards';
import { Field } from './Field';

/** A part of the sandbox (the sandbox itself, an agent, a plugin) and its settings. */
export function Card({ card, query }: { card: CardSpec; query: string }) {
  const { hidden, hiddenFields } = filtered(card, query);
  return (
    <div className={'card' + (card.off ? ' off' : '') + (hidden ? ' hidden' : '')}>
      <div className="row">
        <b>{card.title}{card.tag && <span className="agent">{card.tag}</span>}</b>
        {card.right}
      </div>
      {card.description && <p>{card.description}</p>}
      <div className={'fields' + (card.off ? ' hidden' : '')}>
        {card.fields.map((field, k) => <Field key={field.name} {...field} hidden={hiddenFields[k]} />)}
      </div>
      {card.after}
    </div>
  );
}

/** Cards under a heading, which goes when the filter keeps none of them. */
export function CardGroup({ title, cards, query }: { title: string; cards: CardSpec[]; query: string }) {
  return (
    <>
      <h4 className={cards.every(card => filtered(card, query).hidden) ? 'hidden' : undefined}>{title}</h4>
      {cards.map(card => <Card key={card.key} card={card} query={query} />)}
    </>
  );
}
