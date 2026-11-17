// A settings file — a project's (SettingsCards), your authentications (AuthCards) — as a form or as
// the whole file in JSON.
import { useMemo, useReducer, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { message } from '../../api/client';
import type { Json, JsonObject } from '../../api/types';
import { FormContext, type FormHandle } from './FormContext';
import { clone, isObject, pretty, tidy } from './slots';

interface Props {
  title: string;
  /** Where the file is, whether it is there yet, and what it holds. */
  file: string;
  exists: boolean;
  config: JsonObject;
  /** Writes the file. */
  save: (config: JsonObject) => Promise<unknown>;
  /** The form's cards, drawn from the draft they write into and the filter's text in lower case. */
  cards: (draft: JsonObject, query: string) => ReactNode;
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

export function SettingsForm({ title, file, exists, config, save: write, cards, onClose, onSaved }: Props) {
  const draft = useRef(clone(config));
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
      await write(result());
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
          <h2>{title}</h2>
          <p>{file + (exists ? '' : ' (not there yet: saving creates it)')}</p>
          <div className="tools">
            <input type="search" placeholder="Filter settings…" aria-label="Filter" disabled={mode === 'json'}
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
            {cards(draft.current, query.trim().toLowerCase())}
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
