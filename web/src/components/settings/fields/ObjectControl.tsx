import type { JsonObject } from '../../../api/types';
import type { ControlProps } from '../Control';
import { Field } from '../Field';
import { isObject, shownIn, type Slot } from '../slots';

interface FieldsProps extends Pick<ControlProps, 'spec' | 'slot' | 'name' | 'set'> {
  /** An object left without a value stays, as `{}` (an entry of a list), instead of being unset. */
  keepEmpty?: boolean;
}

/** An object's fields, those whose `when` does not match its other values left out. */
export function ObjectFields({ spec, slot, name, set, keepEmpty }: FieldsProps) {
  const fields = spec.fields ?? [];
  const held = (): JsonObject => { const v = slot.get(); return isObject(v) ? v : {}; };
  const value = slot.get();
  return (
    <div className="fields">
      {fields.filter(f => shownIn(f, value, fields)).map(f => {
        const key = f.key!;
        const inner: Slot = {
          get: () => held()[key],
          set: x => {
            const o = { ...held() };
            if (x === undefined) delete o[key];
            else o[key] = x;
            set(Object.keys(o).length || keepEmpty ? o : undefined);
          },
        };
        return <Field key={key} spec={f} slot={inner} name={`${name}.${key}`} />;
      })}
    </div>
  );
}

/** An object: its fields, in a frame. */
export function ObjectControl({ spec, slot, name, set, id }: ControlProps) {
  return (
    <fieldset className="object" id={id}>
      <ObjectFields spec={spec} slot={slot} name={name} set={set} />
    </fieldset>
  );
}
