import { useId, useRef, useState } from 'react';
import type { Json, SettingSpec } from '../../../api/types';
import type { ControlProps } from '../Control';
import { isObject, type Slot, type Value } from '../slots';
import { ObjectFields } from './ObjectControl';
import { useFocusNew } from './useFocusNew';

/** A list of a few choices: a chip to tick for each. */
function ChoiceChips({ items, name, id, list, put }: { items: SettingSpec; name: string; id?: string; list: () => Json[]; put: (a: Json[]) => void }) {
  return (
    <div className="chips" id={id} role="group">
      {(items.choices ?? []).map(c => (
        <label key={c}>
          <input type="checkbox" name={`${name}.${c}`} checked={list().includes(c)}
            onChange={e => put(e.target.checked ? [...list(), c] : list().filter(x => x !== c))} />
          {String(c)}
        </label>
      ))}
    </div>
  );
}

/** An object in a list: its name (and the choice it was given first: an auth's type) on a row to
 *  click, its fields folded under it. A new one, nameless yet, starts unfolded. */
function Item({ items, v, i, slot, name, drop }: { items: SettingSpec; v: Json; i: number; slot: Slot; name: string; drop: () => void }) {
  const o = isObject(v) ? v : {};
  const named = items.title ? o[items.title] : undefined;
  const title = named ? String(named) : `#${i + 1}`;
  const kind = items.fields?.find(f => f.type === 'enum' && f.key && typeof o[f.key] === 'string');
  const [open, setOpen] = useState(!named);
  const body = useId();
  return (
    <div className={'item' + (open ? ' open' : '')}>
      <div className="head">
        <button type="button" className="toggle" aria-expanded={open} aria-controls={body} onClick={() => setOpen(!open)}>
          <span className="chev" aria-hidden="true" />
          <b>{title}</b>
          {kind && <span className="count">{String(o[kind.key!])}</span>}
        </button>
        <button type="button" className="remove" title="Remove" aria-label={`Remove ${title}`} onClick={drop}>✕</button>
      </div>
      <div className="fold" id={body} inert={!open}>
        <div>
          <ObjectFields spec={items} slot={slot} name={`${name}.${i}`} set={(x: Value) => slot.set(x ?? {})} keepEmpty />
        </div>
      </div>
    </div>
  );
}

/** A list: a row per entry with its own remove button, objects as cards; a list of a few choices
 *  is a set of chips to tick. */
export function ListControl({ spec, slot, name, set, id }: ControlProps) {
  const items: SettingSpec = spec.items ?? { type: 'string' };
  const box = useRef<HTMLDivElement>(null);
  const [gen, setGen] = useState(0);  // an entry removed: the rows are drawn anew
  const focusNew = useFocusNew(box);
  const list = (): Json[] => (slot.get() as Json[] | undefined) ?? [];
  const put = (a: Json[]) => set(a.length ? a : undefined);
  if (items.type === 'enum') return <ChoiceChips items={items} name={name} id={id} list={list} put={put} />;

  const at = (i: number): Slot => ({
    get: () => list()[i],
    set: v => { const a = [...list()]; a[i] = v as Json; put(a); },
  });
  const drop = (i: number) => () => {
    const a = [...list()];
    a.splice(i, 1);
    setGen(g => g + 1);
    put(a);
  };
  // A new entry starts empty (left out when saved while still empty), its first input focused.
  const add = () => {
    focusNew();
    set([...list(), items.type === 'object' ? {} : '']);
  };
  return (
    <div className="entries" ref={box}>
      {list().map((v, i) => {
        const key = gen + '.' + i, first = i === 0 ? id : undefined;
        if (items.type === 'object') return <Item key={key} items={items} v={v} i={i} slot={at(i)} name={name} drop={drop(i)} />;
        return (
          <div className="entry" key={key}>
            <input name={`${name}.${i}`} defaultValue={String(v ?? '')} placeholder={items.placeholder || ''} autoComplete="off" spellCheck={false}
              className={items.monospace ? 'mono' : undefined} id={first}
              onChange={e => at(i).set(items.type === 'integer' ? Number(e.target.value) : e.target.value)} />
            <button type="button" className="remove" title="Remove" aria-label={'Remove ' + (v ? String(v) : 'entry')} onClick={drop(i)}>✕</button>
          </div>
        );
      })}
      <button type="button" className="add" onClick={add}>+ Add</button>
    </div>
  );
}
