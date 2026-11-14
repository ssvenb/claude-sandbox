import { useRef, useState } from 'react';
import type { Json, JsonObject } from '../../../api/types';
import type { ControlProps } from '../Control';
import { isObject } from '../slots';
import { useFocusNew } from './useFocusNew';

/** Name → value pairs (environment variables): a row each. A pair with no name yet is not
 *  written, but keeps its row until it gets one. */
export function MapControl({ spec, slot, name, set, id }: ControlProps) {
  const [pairs] = useState<[string, Json][]>(() => {
    const held = slot.get();
    return Object.entries(isObject(held) ? held : {});
  });
  const box = useRef<HTMLDivElement>(null);
  const [gen, setGen] = useState(0);  // a row added or removed: the rows are drawn anew
  const focusNew = useFocusNew(box);
  const write = () => {
    const o: JsonObject = {};
    for (const [k, v] of pairs) if (k !== '') o[k] = v;
    set(Object.keys(o).length ? o : undefined);
  };
  return (
    <div className="entries" ref={box}>
      {pairs.map((pair, i) => (
        <div className="entry" key={gen + '.' + i}>
          <input className="key mono" name={`${name}.${i}.key`} defaultValue={pair[0]} placeholder={spec.placeholder || 'NAME'} aria-label="Name"
            spellCheck={false} id={i === 0 ? id : undefined} onChange={e => { pair[0] = e.target.value; write(); }} />
          <input className="mono" name={`${name}.${i}.value`} defaultValue={String(pair[1])} placeholder="value" aria-label="Value"
            spellCheck={false} onChange={e => { pair[1] = e.target.value; write(); }} />
          <button type="button" className="remove" title="Remove" aria-label={'Remove ' + (pair[0] || 'entry')}
            onClick={() => { pairs.splice(i, 1); setGen(g => g + 1); write(); }}>✕</button>
        </div>
      ))}
      <button type="button" className="add" onClick={() => { pairs.push(['', '']); focusNew(); setGen(g => g + 1); }}>+ Add</button>
    </div>
  );
}
