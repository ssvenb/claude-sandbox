// A project's sandbox settings, its .claude-sandbox.json, as a form (SettingsCards) or as the
// whole file in JSON. A setting left unset falls through to the repo's .env, your shell, then its
// default. run.sh reads the file on the project's next session.
import { useMemo, useReducer, useRef, useState, type FormEvent } from 'react';
import { message } from '../../api/client';
import { saveConfig } from '../../api/sessions';
import type { Json, JsonObject, ProjectConfig } from '../../api/types';
import { projectName } from '../../lib/session';
import { FormContext, type FormHandle } from './FormContext';
import { SettingsCards } from './SettingsCards';
import { clone, isObject, pretty, tidy } from './slots';

interface Props {
  project: string;
  /** The file as it is, and what can be set in it. */
  declared: ProjectConfig;
  onClose: () => void;
  /** After the file was written. */
  onSaved: () => void;
}

type Mode = 'form' | 'json';

/** What the draft becomes as a file: entries left empty, and blocks and sections left without
 *  anything, are not written. */
function fileOf(draft: JsonObject): JsonObject {
  const next = tidy(clone(draft));
  const plugins = next.plugins;
  if (isObject(plugins))
    for (const [plugin, section] of Object.entries(plugins))
      if (isObject(section) && !Object.keys(section).length) delete plugins[plugin];
  for (const key of ['env', 'plugins']) {
    const block = next[key];
    if (isObject(block) && !Object.keys(block).length) delete next[key];
  }
  return next;
}

export function SettingsForm({ project, declared, onClose, onSaved }: Props) {
  const draft = useRef(clone(declared.config));
  const [mode, setMode] = useState<Mode>('form');
  const [gen, setGen] = useState(0);  // the body is drawn anew from the draft, after the other view
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [, changed] = useReducer((n: number) => n + 1, 0);
  const bad = useRef(new Set<object>());  // the controls holding what is not a value yet
  const area = useRef<HTMLTextAreaElement>(null), json = useRef('');
  const form = useMemo<FormHandle>(() => ({
    changed,
    mark: (token, isBad) => void (isBad ? bad.current.add(token) : bad.current.delete(token)),
  }), []);

  // What the file becomes, from whichever view is open.
  function result(): JsonObject {
    if (mode === 'json') {
      let parsed: Json;
      try {
        parsed = JSON.parse(area.current!.value) as Json;
      } catch (e) {
        throw new Error('Not valid JSON: ' + message(e));
      }
      if (!isObject(parsed)) throw new Error('The file must hold a JSON object');
      return parsed;
    }
    if (bad.current.size) throw new Error('Fix the fields marked red first');
    return fileOf(draft.current);
  }
  function switchTo(next: Mode) {
    if (next === mode) return;
    setError('');
    try {
      if (next === 'json') json.current = pretty(result());
      else {
        draft.current = result();
        bad.current.clear();
      }
    } catch (e) {
      return setError(message(e));
    }
    setGen(g => g + 1);
    setMode(next);
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await saveConfig(project, result());
      onClose();
      onSaved();  // what the plugins show now, or run.sh's complaint about the file
    } catch (err) {
      setError(message(err));
    }
  }

  return (
    <FormContext value={form}>
      <form onSubmit={save}>
        <header>
          <h2>{projectName(project)} settings</h2>
          <p>{declared.file + (declared.exists ? '' : ' (not there yet: saving creates it)')}</p>
          <div className="tools">
            <input type="search" placeholder="Filter settings and plugins…" aria-label="Filter" disabled={mode === 'json'}
              onChange={e => setQuery(e.target.value)} />
            <div className="modes" role="group" aria-label="View">
              <button type="button" aria-pressed={mode === 'form'} onClick={() => switchTo('form')}>Form</button>
              <button type="button" aria-pressed={mode === 'json'} onClick={() => switchTo('json')}>JSON</button>
            </div>
          </div>
        </header>
        {mode === 'json' ? (
          <div className="body" key={'json' + gen}>
            <textarea className="json" name="json" aria-label="The whole file, as JSON" spellCheck={false} style={{ minHeight: '50vh' }}
              defaultValue={json.current} ref={area} />
          </div>
        ) : (
          <div className="body" key={'form' + gen}>
            <SettingsCards declared={declared} draft={draft.current} query={query.trim().toLowerCase()} />
          </div>
        )}
        <footer>
          <p className="error" role="alert">{error}</p>
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary">Save</button>
        </footer>
      </form>
    </FormContext>
  );
}
