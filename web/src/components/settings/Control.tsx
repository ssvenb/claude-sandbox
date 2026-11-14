import type { SettingSpec, SettingType } from '../../api/types';
import { EnumControl } from './fields/EnumControl';
import { IntegerControl } from './fields/IntegerControl';
import { JsonControl } from './fields/JsonControl';
import { ListControl } from './fields/ListControl';
import { MapControl } from './fields/MapControl';
import { ObjectControl } from './fields/ObjectControl';
import { StringControl } from './fields/StringControl';
import { SwitchControl } from './fields/SwitchControl';
import { TextControl } from './fields/TextControl';
import type { Slot, Value } from './slots';

/** What every kind of control is given. What is typed is the control's own until it is a value
 *  (a number, JSON that parses): it holds its text, and is drawn anew only when its value is reset. */
export interface ControlProps {
  spec: SettingSpec;
  slot: Slot;
  name: string;
  /** Writes the value, and has the form drawn again. */
  set: (v: Value) => void;
  id?: string;
  ariaLabel?: string;
}

/** What a field shows while it is empty: its default, else its own placeholder. */
export const placeholder = (spec: SettingSpec): string =>
  spec.default !== undefined && spec.default !== null ? String(spec.default) : spec.placeholder || '';

/** A setting's control, by its type. */
export function Control({ kind, ...props }: ControlProps & { kind: SettingType }) {
  switch (kind) {
    case 'boolean': return <SwitchControl {...props} />;
    case 'enum': return <EnumControl {...props} />;
    case 'integer': return <IntegerControl {...props} />;
    case 'text': return <TextControl {...props} />;
    case 'json': return <JsonControl {...props} />;
    case 'list': return <ListControl {...props} />;
    case 'map': return <MapControl {...props} />;
    case 'object': return <ObjectControl {...props} />;
    default: return <StringControl {...props} mono={kind === 'path'} />;
  }
}
