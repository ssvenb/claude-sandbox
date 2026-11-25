import type { ControlProps } from '../Control';

/** A switch: on is lit. Switched to its default, it is unset again. */
export function SwitchControl({ spec, slot, name, set, id, ariaLabel }: ControlProps) {
  const v = slot.get();
  const on = v === undefined ? !!spec.default : !!v;
  return (
    <button type="button" id={id} name={name} role="switch" aria-label={ariaLabel || spec.label} aria-checked={on}
      className="switch" title={on ? 'On' : 'Off'} onClick={() => set(!on === !!spec.default ? undefined : !on)} />
  );
}
