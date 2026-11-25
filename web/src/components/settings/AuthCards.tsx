// The sandbox's own settings: the projects (added and deleted at once, each a file of its own), and
// your authentications, the file this form edits.
import { useMemo, useRef, useState } from 'react';
import { message } from '../../api/client';
import { addProject, deleteProject } from '../../api/sessions';
import type { AuthConfig, Json, JsonObject, SettingSpec } from '../../api/types';
import { BusyButton } from '../common/BusyButton';
import { Card } from './Card';
import { useForm } from './FormContext';
import { isObject, type Slot } from './slots';

interface Props {
  auth: AuthConfig;
  projects: string[];
  /** The file as it is being edited: name → entry. */
  draft: JsonObject;
  query: string;
  /** A project was added or deleted. */
  onChanged: () => void;
}

/** An entry as a form: its name, its type, and the fields of that type. */
function entrySpec(types: AuthConfig['types']): SettingSpec {
  const fields = new Map<string, { of: string[]; requiredIn: number }>();
  for (const [type, { required, optional }] of Object.entries(types))
    for (const f of [...required, ...optional]) {
      const seen = fields.get(f) ?? { of: [], requiredIn: 0 };
      seen.of.push(type);
      if (required.includes(f)) seen.requiredIn++;
      fields.set(f, seen);
    }
  return {
    type: 'object', title: 'name', groupBy: 'type', fields: [
      { key: 'name', label: 'Name', required: true, monospace: true },
      { key: 'type', type: 'enum', label: 'Type', required: true, choices: Object.keys(types) },
      ...[...fields].map(([key, { of, requiredIn }]): SettingSpec => ({
        key, label: key, type: key.endsWith('File') ? 'path' : 'string', monospace: true,
        required: requiredIn === of.length, when: { type: of },
      })),
    ],
  };
}

export function AuthCards({ auth, projects, draft, query, onChanged }: Props) {
  const form = useForm();
  const token = useMemo(() => ({}), []);
  // The entries as a list while they are edited: one just added has no name yet, so no place in the file.
  const rows = useRef<JsonObject[]>(Object.entries(draft).map(([name, e]) => ({ name, ...(isObject(e) ? e : {}) })));
  const entries: Slot = {
    get: () => (rows.current.length ? rows.current : undefined),
    set: v => {
      rows.current = (v as JsonObject[] | undefined) ?? [];
      for (const k of Object.keys(draft)) delete draft[k];
      let twice = false;
      for (const { name, ...e } of rows.current) {
        if (typeof name !== 'string' || !name) continue;
        twice ||= name in draft;
        draft[name] = e as Json;
      }
      form.mark(token, twice);  // two of one name: one would be lost
    },
  };

  const [listed, setListed] = useState(projects);
  const [error, setError] = useState('');
  const name = useRef<HTMLInputElement>(null), repo = useRef<HTMLInputElement>(null);
  const act = async (what: () => Promise<unknown>, after: (l: string[]) => string[]) => {
    setError('');
    try {
      await what();
      setListed(after);
      onChanged();
      return true;
    } catch (e) {
      setError(message(e));
      return false;
    }
  };
  const add = async () => {
    const n = name.current!.value.trim(), r = repo.current!.value.trim();
    if (await act(() => addProject(n, r), l => [...l, n].sort()) && name.current) name.current.value = repo.current!.value = '';
  };
  const remove = (p: string) =>
    confirm(`Delete the project ${p}? Its file goes; its repo stays where it is.`) && act(() => deleteProject(p), l => l.filter(x => x !== p));

  return (
    <div className="stack">
      <Card query={query} card={{
        key: 'projects', title: 'Projects', open: true, fields: [],
        description: 'A file each in the projects folder. Added and deleted at once; its own settings are behind its gear.',
        more: ' ' + listed.join(' ').toLowerCase(),
        after: <>
          <div className="entries">
            <div className="entry">
              <input ref={name} className="key mono" name="new-project.name" placeholder="name" aria-label="New project's name" spellCheck={false} />
              <input ref={repo} className="mono" name="new-project.repo" placeholder="~/code/my-app or a git URL" aria-label="New project's repo" spellCheck={false} />
              <BusyButton className="add" onClick={add}>+ Add</BusyButton>
            </div>
            <p className="error" role="alert">{error}</p>
            {listed.map(p => (
              <div className="entry" key={p}>
                <span className="mono">{p}</span>
                <BusyButton className="remove" title="Delete" aria-label={'Delete project ' + p} onClick={() => remove(p)}>✕</BusyButton>
              </div>
            ))}
          </div>
        </>,
      }} />
      <Card query={query} card={{
        key: 'auth', title: 'Authentications', open: true,
        description: 'Every identity, key and token a sandbox may use, each under a name; projects and plugins only name one. Saved readable by you alone; a saved key, token or client secret is never shown again, and kept while you leave it as it is.',
        more: ' ' + Object.keys(draft).join(' ').toLowerCase(),
        fields: [{ spec: { type: 'list', label: 'Entries', items: entrySpec(auth.types) }, slot: entries, name: 'auth' }],
      }} />
    </div>
  );
}
