import type { Json } from '../../../api/types';
import { placeholder, type ControlProps } from '../Control';
import { useBad } from '../FormContext';
import { pretty } from '../slots';

/** Any value, written as JSON; while it does not parse it is marked, and not written. */
export function JsonControl({ spec, slot, name, set, id }: ControlProps) {
  const [bad, setBad] = useBad();
  const v = slot.get();
  return (
    <textarea id={id} name={name} className={'json' + (bad ? ' bad' : '')} placeholder={placeholder(spec) || '{ }'} defaultValue={v === undefined ? '' : pretty(v)}
      onChange={e => {
        const text = e.target.value;
        if (!text.trim()) {
          setBad(false);
          return set(undefined);
        }
        let parsed: Json;
        try {
          parsed = JSON.parse(text) as Json;
        } catch {
          return setBad(true);
        }
        setBad(false);
        set(parsed);
      }} />
  );
}
