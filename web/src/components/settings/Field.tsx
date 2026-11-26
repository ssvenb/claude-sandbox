import { useId } from 'react';
import type { JsonObject, SettingSpec } from '../../api/types';
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
  /** Only its control: a plugin's switch, on its card's head next to the name. */
  head?: boolean;
  /** Filtered out. It stays in the form, so what was typed in it is kept. */
  hidden?: boolean;
  parent?: () => JsonObject;
}

/** An ⓘ that shows `text` in a view of its own, over the form, until clicked away. */
export function Info({ text, about }: { text: string; about: string }) {
  const id = useId();
  return (
    <>
      <button type="button" className="info" popoverTarget={id} title="About this" aria-label={'About ' + about}>i</button>
      <div popover="auto" id={id} className="tip"><b>{about}</b><p>{text}</p></div>
    </>
  );
}

const WIDE = ['list', 'map', 'object', 'json', 'text'];

/** One setting: its label, its control, and its description behind an ⓘ. */
export function Field({ spec, slot, name, required, ariaLabel, head, hidden, parent }: FieldProps) {
  const form = useForm();
  const id = useId();
  const kind = spec.type ?? 'string';
  const set = (v: Value) => {
    slot.set(v);
    form.changed();
  };
  const control = <Control kind={kind} spec={spec} slot={slot} name={name} set={set} id={id} ariaLabel={ariaLabel} parent={parent} />;
  if (head) return <div className="control">{control}</div>;
  return (
    <div className={'field' + (WIDE.includes(kind) ? ' wide' : '') + (hidden ? ' hidden' : '')}>
      <div className="label">
        <label htmlFor={id}>
          {spec.label || spec.key || spec.env}
          {(spec.required || required) && <span className="req" title="Required">*</span>}
        </label>
        {spec.description && <Info text={spec.description} about={spec.label || spec.key || spec.env || name} />}
      </div>
      <div className="control">{control}</div>
    </div>
  );
}
