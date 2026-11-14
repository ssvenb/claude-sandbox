// A project's sandbox settings, its .claude-sandbox.json, as a form: each setting the kernel, an
// agent or a plugin declares (its manifest's "settings": type, label, default) gets a control of
// its type, each plugin a switch. A setting left unset falls through to the repo's .env, your
// shell, then its default; ↺ unsets one again. Whatever the form has no control for stays as it
// is, and the JSON view edits the whole file. run.sh reads it on the project's next session.
//
// The file being edited is a draft object; a control reads its value from a slot (where one value
// of the draft lives) and writes it back there. What is typed is the control's own until it parses
// (a number, JSON): a control holds its text, and is drawn anew only when its value is reset.
import {html, render, createContext, useContext, useState, useRef, useMemo, useEffect, useLayoutEffect, useUpdate} from '../lib/preact.js';
import {api, post, name} from '../lib/ui.js';

const clone = v => v === undefined ? undefined : JSON.parse(JSON.stringify(v));
const ON = [true, 1, '1', 'true'];
const pretty = v => JSON.stringify(v, null, 2);

// A slot is where one value lives: get() is undefined while unset, set(undefined) unsets it.
const slot = (obj, key) => ({
  get: () => obj()?.[key],
  set: v => { const o = obj(true); if (v === undefined) delete o[key]; else o[key] = v; },
});
// Values in .env are exported as strings, so a switch writes 1/0 there and reads either spelling.
const envSlot = (s, spec) => spec.type !== 'boolean' ? s
  : {get: () => s.get() === undefined ? undefined : ON.includes(s.get()), set: v => s.set(v === undefined ? v : v ? 1 : 0)};
const shownIn = (field, value, fields) => Object.entries(field.when || {}).every(([k, allowed]) =>
  allowed.includes(value?.[k] ?? fields.find(f => f.key === k)?.default));
const searchOf = spec => [spec.label, spec.key, spec.env, spec.description].join(' ').toLowerCase();

// Entries added and left empty are not saved; a list that held only those goes with them.
function tidy(v) {
  if (Array.isArray(v)) return v.filter(x => x !== '').map(tidy);
  if (v && typeof v === 'object')
    for (const [k, x] of Object.entries(v)) {
      v[k] = tidy(x);
      if (Array.isArray(x) && x.length && !v[k].length) delete v[k];
    }
  return v;
}

// What every control of the form shares: drawing the form again after a change, and the controls
// holding what is not yet a value (JSON that does not parse), which block Save.
const Form = createContext(null);
let uid = 0;
const useId = () => useMemo(() => 'f' + ++uid, []);
function useBad() {
  const form = useContext(Form), token = useMemo(() => ({}), []);
  const [bad, setBad] = useState(false);
  useEffect(() => () => form.mark(token, false), []);
  return [bad, b => { form.mark(token, b); setBad(b); }];
}

// One setting: its label, its control, its description; ↺ while it is set. With `head`, only its
// control and ↺ (a plugin's switch, on its card's head next to the name).
function Field({spec, slot: s, name: path, required, ariaLabel, head, hidden}) {
  const form = useContext(Form);
  const id = useId();
  const [gen, setGen] = useState(0);
  const kind = spec.type || 'string';
  const set = v => { s.set(v); form.changed(); };
  const reset = html`<button type="button" class=${'reset' + (s.get() === undefined ? ' hidden' : '')} title="Unset: use the default"
    aria-label=${'Reset ' + (spec.label || path)} onClick=${() => { s.set(undefined); setGen(g => g + 1); form.changed(); }}>↺ reset</button>`;
  const control = html`<${Control} key=${gen} kind=${kind} spec=${spec} slot=${s} name=${path} set=${set} id=${id} ariaLabel=${ariaLabel}/>`;
  if (head) return html`<div class="control">${reset}<div class="control">${control}</div></div>`;
  const wide = ['list', 'map', 'object', 'json', 'text'].includes(kind);
  return html`<div class=${'field' + (kind === 'boolean' ? ' bool' : '') + (wide ? ' wide' : '') + (hidden ? ' hidden' : '')}>
    <div class="label"><label for=${id}>${spec.label || spec.key || spec.env}${spec.required || required ? html`<span class="req" title="Required">*</span>` : ''}</label>
      ${spec.env ? html`<code title="Set in the env block">${spec.env}</code>` : ''}${reset}</div>
    <div class="control">${control}</div>
    ${spec.description ? html`<p>${spec.description}</p>` : ''}
  </div>`;
}

function Control({kind, spec, slot: s, name: path, set, id, ariaLabel}) {
  const [bad, setBad] = useBad();
  const v = s.get();
  const ph = spec.default !== undefined && !['boolean', 'enum'].includes(kind) ? String(spec.default) : spec.placeholder || '';
  const cls = (...names) => names.concat(bad ? ['bad'] : []).filter(Boolean).join(' ') || undefined;
  switch (kind) {
    case 'boolean': {
      const on = v === undefined ? !!spec.default : !!v;
      return html`${v === undefined ? html`<span class="default">default</span>` : ''}
        <button type="button" id=${id} name=${path} role="switch" aria-label=${ariaLabel || spec.label} class=${'switch' + (v === undefined ? ' unset' : '')}
          aria-checked=${String(on)} title=${v === undefined ? `Default: ${on ? 'on' : 'off'}` : on ? 'On' : 'Off'} onClick=${() => set(!on)}></button>`;
    }
    case 'enum':
      return html`<select id=${id} name=${path} value=${v === undefined ? '' : String(v)} onChange=${e => set(e.target.value === '' ? undefined : e.target.value)}>
        <option value="">${spec.default !== undefined ? `Default (${spec.default})` : '—'}</option>
        ${spec.choices.map(c => html`<option value=${c}>${String(c)}</option>`)}</select>`;
    case 'integer':
      return html`<input id=${id} name=${path} type="number" step="1" placeholder=${ph} defaultValue=${v ?? ''} min=${spec.min} max=${spec.max}
        class=${cls()} onInput=${e => { const inp = e.target, ok = inp.value === '' || inp.validity.valid; setBad(!ok);
                                         if (ok) set(inp.value === '' ? undefined : Number(inp.value)); }}/>`;
    case 'text':
      return html`<textarea id=${id} name=${path} placeholder=${ph} defaultValue=${Array.isArray(v) ? v.join('\n') : v ?? ''}
        onInput=${e => set(e.target.value === '' ? undefined : e.target.value)}></textarea>`;
    case 'json':
      return html`<textarea id=${id} name=${path} class=${cls('json')} placeholder=${ph || '{ }'} defaultValue=${v === undefined ? '' : pretty(v)}
        onInput=${e => {
          const text = e.target.value;
          if (!text.trim()) { setBad(false); return set(undefined); }
          let parsed;
          try { parsed = JSON.parse(text); } catch { return setBad(true); }
          setBad(false);
          set(parsed);
        }}></textarea>`;
    case 'list': return html`<${List} spec=${spec} slot=${s} name=${path} set=${set} id=${id}/>`;
    case 'map': return html`<${Pairs} spec=${spec} slot=${s} name=${path} set=${set} id=${id}/>`;
    case 'object': return html`<${Fields} spec=${spec} slot=${s} name=${path} set=${set} id=${id}/>`;
    default:  // string, path
      return html`<input id=${id} name=${path} type=${spec.secret ? 'password' : 'text'} placeholder=${ph} defaultValue=${v ?? ''}
        autocomplete="off" spellcheck=${false} class=${cls(spec.monospace || kind === 'path' ? 'mono' : '')}
        onInput=${e => { setBad(!!spec.pattern && !new RegExp(`^(?:${spec.pattern})$`).test(e.target.value));
                         set(e.target.value === '' ? undefined : e.target.value); }}/>`;
  }
}

// A new entry's first input is focused once it is drawn.
function useFocusNew(box) {
  const pending = useRef(false);
  useLayoutEffect(() => {
    if (!pending.current) return;
    pending.current = false;
    box.current.lastElementChild.previousElementSibling?.querySelector('input, select')?.focus();
  });
  return () => { pending.current = true; };
}

// A list of enums is a set of chips to tick; any other list a row per entry, objects as cards.
function List({spec, slot: s, name: path, set, id}) {
  const items = spec.items || {type: 'string'};
  const box = useRef();
  const [gen, setGen] = useState(0);  // an entry removed: the rows are drawn anew
  const focusNew = useFocusNew(box);
  const arr = () => s.get() || [];
  const put = a => set(a.length ? a : undefined);
  if (items.type === 'enum')
    return html`<div class="chips" id=${id} role="group">${items.choices.map(c => html`<label>
      <input type="checkbox" name=${`${path}.${c}`} checked=${arr().includes(c)}
        onChange=${e => put(e.target.checked ? [...arr(), c] : arr().filter(x => x !== c))}/>${String(c)}</label>`)}</div>`;
  const at = i => ({get: () => arr()[i], set: v => { const a = [...arr()]; a[i] = v; put(a); }});
  const drop = i => () => { const a = [...arr()]; a.splice(i, 1); setGen(g => g + 1); put(a); };
  const rows = arr().map((v, i) => {
    if (items.type === 'object') {
      const title = (items.title && v?.[items.title]) || `#${i + 1}`;
      return html`<div class="item" key=${gen + '.' + i}><div class="row"><b>${title}</b>
          <button type="button" class="remove" title="Remove" aria-label=${`Remove ${title}`} onClick=${drop(i)}>✕</button></div>
        <${Fields} spec=${{...items, label: undefined}} slot=${at(i)} name=${`${path}.${i}`} set=${v2 => at(i).set(v2 ?? {})}
          id=${i === 0 ? id : undefined} bare/></div>`;
    }
    return html`<div class="entry" key=${gen + '.' + i}>
      <input name=${`${path}.${i}`} defaultValue=${v ?? ''} placeholder=${items.placeholder || ''} autocomplete="off" spellcheck=${false}
        class=${items.monospace ? 'mono' : undefined} id=${i === 0 ? id : undefined}
        onInput=${e => at(i).set(items.type === 'integer' ? Number(e.target.value) : e.target.value)}/>
      <button type="button" class="remove" title="Remove" aria-label=${'Remove ' + (v || 'entry')} onClick=${drop(i)}>✕</button></div>`;
  });
  // A new entry starts empty (left out when saved while still empty), its first input focused.
  return html`<div class="entries" ref=${box}>${rows}
    <button type="button" class="add" onClick=${() => { focusNew(); set([...arr(), items.type === 'object' ? {} : '']); }}>+ Add</button></div>`;
}

// Name → value pairs (environment variables): a row each. A pair with no name yet is not written,
// but keeps its row until it gets one.
function Pairs({spec, slot: s, name: path, set, id}) {
  const pairs = useMemo(() => Object.entries(s.get() || {}), []);
  const box = useRef();
  const [gen, setGen] = useState(0);
  const focusNew = useFocusNew(box);
  const write = () => {
    const o = {};
    for (const [k, v] of pairs) if (k !== '') o[k] = v;
    set(Object.keys(o).length ? o : undefined);
  };
  return html`<div class="entries" ref=${box}>
    ${pairs.map((pair, i) => html`<div class="entry" key=${gen + '.' + i}>
      <input class="key mono" name=${`${path}.${i}.key`} defaultValue=${pair[0]} placeholder=${spec.placeholder || 'NAME'} aria-label="Name"
        spellcheck=${false} id=${i === 0 ? id : undefined} onInput=${e => { pair[0] = e.target.value; write(); }}/>
      <input class="mono" name=${`${path}.${i}.value`} defaultValue=${String(pair[1])} placeholder="value" aria-label="Value"
        spellcheck=${false} onInput=${e => { pair[1] = e.target.value; write(); }}/>
      <button type="button" class="remove" title="Remove" aria-label=${'Remove ' + (pair[0] || 'entry')}
        onClick=${() => { pairs.splice(i, 1); setGen(g => g + 1); write(); }}>✕</button></div>`)}
    <button type="button" class="add" onClick=${() => { pairs.push(['', '']); focusNew(); setGen(g => g + 1); }}>+ Add</button></div>`;
}

// An object: its fields, those whose `when` does not match its other values left out.
function Fields({spec, slot: s, name: path, set, id, bare}) {
  const fields = spec.fields || [];
  const v = s.get();
  const box = html`<div class="fields">${fields.filter(f => shownIn(f, v, fields)).map(f => {
    const fs = {get: () => s.get()?.[f.key],
                set: x => { const o = {...(s.get() || {})}; if (x === undefined) delete o[f.key]; else o[f.key] = x;
                            set(Object.keys(o).length || bare ? o : undefined); }};
    return html`<${Field} key=${f.key} spec=${f} slot=${fs} name=${`${path}.${f.key}`}/>`;
  })}</div>`;
  return bare ? box : html`<fieldset class="object" id=${id}>${box}</fieldset>`;
}

function Settings({path, got, close, saved}) {
  const draft = useRef(clone(got.config));
  const [mode, setMode] = useState('form');
  const [gen, setGen] = useState(0);  // the body drawn anew from the draft, after the JSON view
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const changed = useUpdate();
  const bad = useRef(new Set());
  const area = useRef(), json = useRef('');
  const form = useMemo(() => ({changed, mark: (token, b) => { b ? bad.current.add(token) : bad.current.delete(token); }}), []);

  const env = create => { const d = draft.current; if (create && !d.env) d.env = {}; return d.env; };
  const section = plugin => create => {
    const d = draft.current;
    if (create) { d.plugins ??= {}; d.plugins[plugin] ??= {}; }
    return d.plugins?.[plugin];
  };

  // What the file becomes: empty blocks and sections left out.
  function result() {
    if (mode === 'json') {
      let v;
      try { v = JSON.parse(area.current.value); } catch (e) { throw new Error('Not valid JSON: ' + e.message); }
      if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('The file must hold a JSON object');
      return v;
    }
    if (bad.current.size) throw new Error('Fix the fields marked red first');
    const next = tidy(clone(draft.current));
    for (const [plugin, sec] of Object.entries(next.plugins || {}))
      if (sec && typeof sec === 'object' && !Object.keys(sec).length) delete next.plugins[plugin];
    for (const key of ['env', 'plugins'])
      if (next[key] && !Object.keys(next[key]).length) delete next[key];
    return next;
  }
  function switchTo(next) {
    if (next === mode) return;
    setError('');
    try {
      if (next === 'json') json.current = pretty(result());
      else { draft.current = result(); bad.current.clear(); }
    } catch (e) { return setError(e.message); }
    setGen(g => g + 1);
    setMode(next);
  }
  async function save(e) {
    e.preventDefault();
    setError('');
    try {
      await post('/api/config', JSON.stringify({project: path, config: result()}));
      close();
      saved();  // what the plugins show now, or run.sh's complaint about the file
    } catch (err) { setError(err.message); }
  }

  // A card per part (the sandbox, an agent, a plugin), its settings in it. The filter keeps the
  // cards, or the settings of a card, that mention what it is given.
  const q = query.trim().toLowerCase();
  const field = (spec, s, path, extra = {}) => ({spec, draw: hidden =>
    html`<${Field} key=${path} spec=${spec} slot=${s} name=${path} hidden=${hidden} ...${extra}/>`});
  const envField = (spec, extra) => field(spec, envSlot(slot(env, spec.env), spec), 'env.' + spec.env, extra);
  const card = ({key, title, description, tag = '', fields, right = '', after = '', off = false, more = ''}) => {
    const hit = !q || ([title, description, tag].join(' ').toLowerCase() + more).includes(q);
    const hits = fields.map(f => searchOf(f.spec).includes(q));
    const hidden = !hit && !hits.some(Boolean);
    return {hidden, node: html`<div key=${key} class=${'card' + (off ? ' off' : '') + (hidden ? ' hidden' : '')}>
      <div class="row"><b>${title}${tag ? html`<span class="agent">${tag}</span>` : ''}</b>${right}</div>
      ${description ? html`<p>${description}</p>` : ''}
      <div class=${'fields' + (off ? ' hidden' : '')}>${fields.map((f, k) => f.draw(!!q && !hit && !hits[k]))}</div>${after}</div>`};
  };
  const group = (title, cards) => [html`<h4 key=${'h-' + title} class=${cards.every(c => c.hidden) ? 'hidden' : undefined}>${title}</h4>`,
                                   ...cards.map(c => c.node)];

  function body() {
    const d = draft.current;
    const declaredEnv = new Set([...got.kernel.settings, ...got.agents.flatMap(a => a.settings),
                                 ...got.plugins.flatMap(p => p.settings)].filter(s => s.env).map(s => s.env));
    // env keys nobody declares: a plain name → value list, so nothing in the file goes missing.
    const others = {get: () => { const o = Object.fromEntries(Object.entries(d.env || {}).filter(([k]) => !declaredEnv.has(k)));
                                 return Object.keys(o).length ? o : undefined; },
                    set: v => { for (const k of Object.keys(d.env || {})) if (!declaredEnv.has(k)) delete d.env[k];
                                if (v) Object.assign(env(true), v); }};
    const agentNow = d.env?.AGENT ?? got.kernel.settings.find(s => s.env === 'AGENT')?.default;
    const sandbox = [
      card({key: 'general', title: 'General', description: got.kernel.description, fields: got.kernel.settings.map(s => envField(s))}),
      ...got.agents.map(a => card({key: 'agent-' + a.name, title: a.name + ' agent', description: a.description,
                                   fields: a.settings.map(s => envField(s)), tag: a.name === agentNow ? 'selected' : ''})),
      card({key: 'other', title: 'Other variables', description: 'Further sandbox settings for the env block, by name (see .env.example).',
            fields: [field({type: 'map', label: 'Variables', placeholder: 'NAME'}, others, 'env-other')]}),
    ];
    const plugins = got.plugins.map(p => {
      const sec = section(p.name);
      const enabled = {get: () => { const e = sec()?.enabled; return e === undefined ? undefined : ON.includes(e); },
                       set: v => { if (v === undefined) { if (sec()) delete sec().enabled; } else sec(true).enabled = v; }};
      const on = enabled.get() ?? p.defaultEnabled;
      const declaredKeys = new Set(['enabled', ...p.settings.filter(s => s.key).map(s => s.key)]);
      const kept = Object.keys(sec() || {}).filter(k => !declaredKeys.has(k));
      return card({key: 'plugin-' + p.name, title: p.name, description: p.description, off: !on,
        tag: p.requiredAgent ? p.requiredAgent + ' only' : '',
        more: ' ' + p.settings.map(s => [s.label, s.key, s.env].join(' ')).join(' ').toLowerCase(),
        right: html`<${Field} key=${'enabled-' + p.name} spec=${{type: 'boolean', label: 'Enabled', default: p.defaultEnabled}} slot=${enabled}
                      name=${'enabled-' + p.name} ariaLabel=${p.name + ' enabled'} head/>`,
        fields: p.settings.map(spec => spec.env
          ? envField(spec, {required: spec.required || (p.requiredEnv || []).includes(spec.env)})
          : field(spec, slot(sec, spec.key), `plugins.${p.name}.${spec.key}`)),
        after: kept.length ? html`<p class="kept">Also holds ${kept.join(', ')}: kept as is (edit it in the JSON view).</p>` : ''});
    });
    return [html`<p key="intro">Unset settings come from the repo's .env or your shell, else their default. ↺ reset unsets one again.</p>`,
            ...group('Sandbox', sandbox), ...group('Plugins', plugins)];
  }

  return html`<${Form.Provider} value=${form}><form onSubmit=${save}>
    <header><h2>${name(path)} settings</h2>
      <p>${got.file + (got.exists ? '' : ' (not there yet: saving creates it)')}</p>
      <div class="tools">
        <input type="search" placeholder="Filter settings and plugins…" aria-label="Filter" disabled=${mode === 'json'}
          onInput=${e => setQuery(e.target.value)}/>
        <div class="modes" role="group" aria-label="View">
          <button type="button" aria-pressed=${String(mode === 'form')} onClick=${() => switchTo('form')}>Form</button>
          <button type="button" aria-pressed=${String(mode === 'json')} onClick=${() => switchTo('json')}>JSON</button>
        </div></div></header>
    ${mode === 'json'
      ? html`<div class="body" key=${'json' + gen}><textarea class="json" name="json" aria-label="The whole file, as JSON" spellcheck=${false}
               style="min-height: 50vh" defaultValue=${json.current} ref=${area}></textarea></div>`
      : html`<div class="body" key=${'form' + gen}>${body()}</div>`}
    <footer><p class="error" role="alert">${error}</p>
      <button type="button" onClick=${close}>Cancel</button>
      <button type="submit" class="primary">Save</button></footer>
  </form></${Form.Provider}>`;
}

// Opens the settings of the project at `path` in the page's <dialog>; `saved` runs once they are.
let opened = 0;
export async function configure(path, saved) {
  const dialog = document.getElementById('config');
  let got;
  try { got = await api('/api/config?project=' + encodeURIComponent(path)); }
  catch (e) { return alert(e.message); }
  render(html`<${Settings} key=${++opened} path=${path} got=${got} close=${() => dialog.close()} saved=${saved}/>`, dialog);
  dialog.showModal();
  dialog.querySelector('input[type=search]').focus();
}
