import type { ControlProps } from '../Control';

/** One of a few choices; the first entry leaves it unset. */
export function EnumControl({ spec, slot, name, set, id }: ControlProps) {
  const v = slot.get();
  return (
    <select id={id} name={name} value={v === undefined ? '' : String(v)} onChange={e => set(e.target.value === '' ? undefined : e.target.value)}>
      <option value="">{spec.default !== undefined ? `Default (${String(spec.default)})` : '—'}</option>
      {(spec.choices ?? []).map(c => <option key={c} value={c}>{String(c)}</option>)}
    </select>
  );
}
