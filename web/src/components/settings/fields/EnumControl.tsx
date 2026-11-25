import type { ControlProps } from '../Control';

/** One of a few choices, its default picked while unset (and picking it unsets it again); without
 *  a default, a first entry leaves it unset. */
export function EnumControl({ spec, slot, name, set, id }: ControlProps) {
  const v = slot.get(), def = spec.default === undefined ? '' : String(spec.default);
  return (
    <select id={id} name={name} value={v === undefined ? def : String(v)} onChange={e => set(e.target.value === def ? undefined : e.target.value)}>
      {def === '' && <option value="">—</option>}
      {(spec.choices ?? []).map(c => <option key={c} value={c}>{String(c)}</option>)}
    </select>
  );
}
