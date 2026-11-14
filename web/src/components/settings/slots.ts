// The file being edited is a draft object; a control reads its value from a slot (where one value
// of the draft lives) and writes it back there.
import type { Json, JsonObject, SettingSpec } from '../../api/types';

export type Value = Json | undefined;

/** Where one value lives: get() is undefined while unset, set(undefined) unsets it. */
export interface Slot {
  get: () => Value;
  set: (v: Value) => void;
}

/** The object a slot's value is in; asked with `create`, it is made if it is not there yet. */
export type Holder = (create?: boolean) => JsonObject | undefined;

export const slot = (obj: Holder, key: string): Slot => ({
  get: () => obj()?.[key],
  set: v => {
    const o = obj(true)!;
    if (v === undefined) delete o[key];
    else o[key] = v;
  },
});

export const ON: Value[] = [true, 1, '1', 'true'];

/** Values in .env are exported as strings, so a switch writes 1/0 there and reads either spelling. */
export const envSlot = (s: Slot, spec: SettingSpec): Slot =>
  spec.type !== 'boolean' ? s : {
    get: () => (s.get() === undefined ? undefined : ON.includes(s.get())),
    set: v => s.set(v === undefined ? v : v ? 1 : 0),
  };

export const clone = <T extends Value>(v: T): T => (v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T));
export const pretty = (v: Value): string => JSON.stringify(v, null, 2);
export const isObject = (v: Value): v is JsonObject => !!v && typeof v === 'object' && !Array.isArray(v);

/** Whether an object's field shows: its `when` matches the object's other values. */
export const shownIn = (field: SettingSpec, value: Value, fields: SettingSpec[]): boolean =>
  Object.entries(field.when ?? {}).every(([k, allowed]) =>
    allowed.includes(((isObject(value) ? value[k] : undefined) ?? fields.find(f => f.key === k)?.default) as Json));

/** Entries added and left empty are not saved; a list that held only those goes with them. */
export function tidy<T extends Value>(v: T): T {
  if (Array.isArray(v)) return v.filter(x => x !== '').map(tidy) as T;
  if (isObject(v)) {
    for (const [k, x] of Object.entries(v)) {
      const kept = (v[k] = tidy(x));
      if (Array.isArray(x) && x.length && Array.isArray(kept) && !kept.length) delete v[k];
    }
  }
  return v;
}
