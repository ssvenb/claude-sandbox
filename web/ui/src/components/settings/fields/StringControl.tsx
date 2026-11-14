import { placeholder, type ControlProps } from '../Control';
import { useBad } from '../FormContext';

/** One line of text (a path in the monospace face, a secret hidden); emptied, it is unset. */
export function StringControl({ spec, slot, name, set, id, mono }: ControlProps & { mono?: boolean }) {
  const [bad, setBad] = useBad();
  const v = slot.get();
  const classes = [spec.monospace || mono ? 'mono' : '', bad ? 'bad' : ''].filter(Boolean).join(' ');
  return (
    <input id={id} name={name} type={spec.secret ? 'password' : 'text'} placeholder={placeholder(spec)} defaultValue={String(v ?? '')}
      autoComplete="off" spellCheck={false} className={classes || undefined}
      onChange={e => {
        setBad(!!spec.pattern && !new RegExp(`^(?:${spec.pattern})$`).test(e.target.value));
        set(e.target.value === '' ? undefined : e.target.value);
      }} />
  );
}
