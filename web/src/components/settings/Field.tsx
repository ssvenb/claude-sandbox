import { useId, useState } from 'react';
import type { SettingSpec } from '../../api/types';
import { Control } from './Control';
import { useForm } from './FormContext';
import type { Slot, Value } from './slots';

export interface FieldProps {
  spec: SettingSpec;
  slot: Slot;
  /** Where the value is in the file (`plugins.kvm.briefing`): the control's name. */
  name: string;
  required?: boolean;
  ariaLabel?: string;
  /** Only its control and its reset: a plugin's switch, on its card's head next to the name. */
  head?: boolean;
  /** Filtered out. It stays in the form, so what was typed in it is kept. */
  hidden?: boolean;
}

const WIDE = ['list', 'map', 'object', 'json', 'text'];

/** One setting: its label, its control, its description, and a reset while it is set. */
export function Field({ spec, slot, name, required, ariaLabel, head, hidden }: FieldProps) {
  const form = useForm();
  const id = useId();
  const [gen, setGen] = useState(0);  // a control holds what was typed: reset, it is drawn anew
  const kind = spec.type ?? 'string';
  const set = (v: Value) => {
    slot.set(v);
    form.changed();
  };
  const unset = () => {
    slot.set(undefined);
    setGen(g => g + 1);
    form.changed();
  };
  const reset = (
    <button type="button" className={'reset' + (slot.get() === undefined ? ' hidden' : '')} title="Unset: use the default"
      aria-label={'Reset ' + (spec.label || name)} onClick={unset}>
      ↺ reset
    </button>
  );
  const control = <Control key={gen} kind={kind} spec={spec} slot={slot} name={name} set={set} id={id} ariaLabel={ariaLabel} />;
  if (head) return <div className="control">{reset}<div className="control">{control}</div></div>;
  return (
    <div className={'field' + (kind === 'boolean' ? ' bool' : '') + (WIDE.includes(kind) ? ' wide' : '') + (hidden ? ' hidden' : '')}>
      <div className="label">
        <label htmlFor={id}>
          {spec.label || spec.key || spec.env}
          {(spec.required || required) && <span className="req" title="Required">*</span>}
        </label>
        {spec.env && <code title="Set in the env block">{spec.env}</code>}
        {reset}
      </div>
      <div className="control">{control}</div>
      {spec.description && <p>{spec.description}</p>}
    </div>
  );
}
