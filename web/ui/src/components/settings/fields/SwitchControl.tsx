import type { ControlProps } from '../Control';

/** A switch: on is lit; while it only shows the default, it is drawn hollow. */
export function SwitchControl({ spec, slot, name, set, id, ariaLabel }: ControlProps) {
  const v = slot.get();
  const on = v === undefined ? !!spec.default : !!v;
  return (
    <>
      {v === undefined && <span className="default">default</span>}
      <button type="button" id={id} name={name} role="switch" aria-label={ariaLabel || spec.label} aria-checked={on}
        className={'switch' + (v === undefined ? ' unset' : '')}
        title={v === undefined ? `Default: ${on ? 'on' : 'off'}` : on ? 'On' : 'Off'} onClick={() => set(!on)} />
    </>
  );
}
