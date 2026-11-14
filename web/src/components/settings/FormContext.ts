import { createContext, useContext, useEffect, useMemo, useState } from 'react';

/** What every control of the settings form shares. */
export interface FormHandle {
  /** A value of the draft changed: the form is drawn again. */
  changed: () => void;
  /** A control holds, or no longer holds, what is not a value yet (JSON that does not parse): such block Save. */
  mark: (token: object, bad: boolean) => void;
}

export const FormContext = createContext<FormHandle | null>(null);

export function useForm(): FormHandle {
  const form = useContext(FormContext);
  if (!form) throw new Error('not inside the settings form');
  return form;
}

/** Whether a control holds something that is not a value yet, and how to say so. */
export function useBad(): [boolean, (bad: boolean) => void] {
  const form = useForm();
  const token = useMemo(() => ({}), []);
  const [bad, setBad] = useState(false);
  useEffect(() => () => form.mark(token, false), [form, token]);
  return [bad, b => { form.mark(token, b); setBad(b); }];
}
