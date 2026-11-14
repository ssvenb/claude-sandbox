import { placeholder, type ControlProps } from '../Control';
import { useBad } from '../FormContext';

/** A whole number, within the setting's bounds; anything else is marked, and not written. */
export function IntegerControl({ spec, slot, name, set, id }: ControlProps) {
  const [bad, setBad] = useBad();
  const v = slot.get();
  return (
    <input id={id} name={name} type="number" step="1" placeholder={placeholder(spec)} defaultValue={typeof v === 'number' || typeof v === 'string' ? v : ''}
      min={spec.min} max={spec.max} className={bad ? 'bad' : undefined}
      onChange={e => {
        const input = e.target, ok = input.value === '' || input.validity.valid;
        setBad(!ok);
        if (ok) set(input.value === '' ? undefined : Number(input.value));
      }} />
  );
}
