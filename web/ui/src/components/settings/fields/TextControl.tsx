import { placeholder, type ControlProps } from '../Control';

/** Text over several lines. */
export function TextControl({ spec, slot, name, set, id }: ControlProps) {
  const v = slot.get();
  return (
    <textarea id={id} name={name} placeholder={placeholder(spec)} defaultValue={Array.isArray(v) ? v.join('\n') : String(v ?? '')}
      onChange={e => set(e.target.value === '' ? undefined : e.target.value)} />
  );
}
