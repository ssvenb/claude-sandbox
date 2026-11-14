// A session's conversation: the header says which and how it is doing, the column is what was said
// and done, the dock at the bottom is where the next message is written. The dock is there from the
// first moment, while the sandbox still starts.
//
// The session comes as events on /api/sessions/<id>/events (a snapshot of everything so far, then
// one event at a time). They are kept here as records, a column of them; each record carries a
// version that goes up whenever it, or anything inside it, changes, so drawing the page again
// redraws only what changed.
import {html, render, Component, useState, useRef, useLayoutEffect} from '../lib/preact.js';
import {api, post, name, titled, SHORT, ICON, Spin, Spinner, BusyButton, ThemeSwitch, FAVICON, setFavicon,
        Chip, here, usePasted, Tray, Shots} from '../lib/ui.js';
import {markdown} from './markdown.js';
import {verb, what, given, Steps} from './tools.js';

const id = location.hash.slice(1);
setFavicon(FAVICON.starting);

// ---- the session, as its events left it ------------------------------------------------------

let session = null, info = {}, status = 'starting', ready = false, over = null, gone = false;
let log = [], blocks = new Map(), tools = new Map(), asks = new Map(), users = new Map(), boot = null;
let todos = null, tasks = [], items = [];  // items: what the project's plugins tie to this run (its pull request)
let chosen = {};  // a model or effort picked here, until the agent says it took it
let halting = false;
let follow = true;  // keep the newest line in view, until the reader scrolls up
let uid = 0;

// Something in a record changed: it, and whatever holds it, draw again.
const touch = r => { for (; r; r = r.up) r.v++; };
const record = (kind, fields) => ({kind, key: ++uid, v: 0, up: null, ...fields});
// Where an event's record goes: inside the subagent call it belongs to, else at the column's end.
function place(r, parent) {
  const t = tools.get(parent);
  r.up = t || null;
  (t ? t.kids : log).push(r);
  touch(t);
  return r;
}

function bootLine(text) {
  boot ??= {text: '', last: ''};
  if (text) {
    boot.text += text + '\n';
    boot.last = text.split('\n').filter(Boolean).pop() || '';
  }
}

function user(e) {
  const r = place(record('you', {text: e.text, images: e.images, queued: !!e.queued}));
  if (e.id) users.set(e.id, r);
  if (session && !session.title) session.title = e.text.replace(/\s+/g, ' ').slice(0, 140) || 'Image';  // it is called what it was first asked
  follow = true;
}
function sent(e) {
  const r = users.get(e.id);
  if (r) { r.queued = false; touch(r); }
}

// A block streams until its whole text comes, or until anything else does: not every block gets
// its whole text sent (thinking may come only as a stream), and it must not turn for ever.
function settleBlocks(except) {
  for (const b of blocks.values()) if (b.streaming && b !== except) { b.streaming = false; touch(b); }
}
function block(e, streaming) {
  let b = blocks.get(e.id);
  if (!b) blocks.set(e.id, b = place(record(e.kind === 'thinking' ? 'think' : 'say', {text: ''}), e.parent));
  settleBlocks(b);
  b.text = streaming ? b.text + e.text : e.text;
  b.streaming = streaming;
  touch(b);
}

function tool(e) {
  let t = tools.get(e.id);
  if (!t) {
    const into = tools.get(e.parent)?.kids || log;
    let box = into[into.length - 1];
    if (box?.kind !== 'tools') box = place(record('tools', {list: []}), e.parent);
    t = record('tool', {up: box, kids: [], out: '', took: ''});
    box.list.push(t);
    tools.set(e.id, t);
  }
  Object.assign(t, {name: e.name ?? t.name, title: e.title ?? t.title, input: e.input ?? t.input, progress: ''});
  if (e.done !== undefined || e.output !== undefined) result(e);
  else touch(t);
}
function result(e) {
  const t = tools.get(e.id);
  if (!t) return;
  t.done = e.done ?? !e.partial;
  t.error = !!e.error;
  t.out = String(e.output ?? '').replace(/\s+$/, '');
  touch(t);
}
function progress(e) {
  const t = tools.get(e.id);
  if (!t || t.done) return;
  if (e.seconds) t.took = e.seconds >= 60 ? `${Math.floor(e.seconds / 60)} min ${e.seconds % 60} s` : `${e.seconds} s`;
  if (e.text) t.progress = e.text;
  touch(t);
}
const finish = (error = false) => { for (const t of tools.values()) if (!t.done) { t.done = true; t.error ||= error; touch(t); } };

function ask(e) {
  const a = place(record('ask', {e, picked: e.questions.map(() => new Set()), other: e.questions.map(() => ''), sending: false}));
  asks.set(e.id, a);
  if (e.done || e.answers !== undefined) return settled(a, e.answers);
  follow = true;
}
function settled(a, answers) { a.settled = true; a.answers = answers; touch(a); }

function turn(e) {
  const parts = [];
  if (e.duration) parts.push(e.duration >= 60000 ? `${Math.floor(e.duration / 60000)} min ${Math.round(e.duration % 60000 / 1000)} s` : `${Math.max(1, Math.round(e.duration / 1000))} s`);
  if (typeof e.cost === 'number') parts.push(`$${e.cost.toFixed(2)}`);
  if (e.context?.max) parts.push(`${Math.round(100 * e.context.used / e.context.max)}% context`);
  if (e.error) place(record('note', {level: 'error', text: e.error}));
  if (parts.length) place(record('turn', {text: parts.join(' · ')}));
  finish();  // nothing still runs once the turn is over
}

function ended(e) {
  over = e.code;
  finish(true);
  place(record('over', {code: e.code, runId: session?.run_id}));
}

function handle(e) {
  switch (e.type) {
    case 'boot': bootLine(e.text); break;
    case 'hello': info.agent = e.agent; break;
    case 'ready': Object.assign(info, e); ready = true; break;
    case 'user': user(e); break;
    case 'sent': sent(e); break;
    case 'text': block(e, false); break;
    case 'delta': block(e, true); break;
    case 'tool': settleBlocks(); tool(e); break;
    case 'result': result(e); break;
    case 'progress': progress(e); break;
    case 'ask': settleBlocks(); ask(e); break;
    case 'asked': { const a = asks.get(e.id); if (a && !a.settled) settled(a, a.e.answers); break; }
    case 'turn': settleBlocks(); turn(e); break;
    case 'notice': place(record('note', {level: e.level || 'info', text: e.text})); break;
    case 'status': status = e.state; if (status !== 'working') settleBlocks(); break;
    case 'model': info.model = e.id; delete chosen.model; break;
    case 'effort': info.effort = e.level; delete chosen.effort; break;
    case 'todos': todos = e.items; break;
    case 'tasks': tasks = e.items || []; break;
    case 'exit': tasks = []; settleBlocks(); ended(e); break;
  }
}

// The whole session from nothing: on opening the page, and again whenever the stream reconnects.
function restore(snap) {
  log = []; blocks = new Map(); tools = new Map(); asks = new Map(); users = new Map(); boot = null; over = null;
  session = snap.session; info = {...snap.info}; ready = snap.ready; status = snap.status;
  bootLine('');
  for (const e of snap.events) handle(e);
  for (const b of blocks.values()) b.streaming = false;
  todos = snap.todos;
  tasks = snap.tasks || [];
  follow = true;
  update();
  requestAnimationFrame(settle);
}

// ---- talking to the server --------------------------------------------------------------------

const tabs = new BroadcastChannel('sandbox-tabs');
let vsTab = null;  // the VS Code tab this page opened: closed with the session
const leave = () => { vsTab?.close(); window.close(); };
tabs.onmessage = e => { if (e.data.id === id) leave(); };

async function stop() {
  if (!confirm('Stop this session?')) return;
  await post(`/api/sessions/${id}/stop`).catch(e => alert(e.message));
  poll();
}
async function remove() {
  if (session.exit === null && !confirm('Stop and delete this session?')) return;
  // What a plugin offers to tidy up with it (its run's open pull request: close it) is asked
  // about one by one, and done only on a yes.
  const {offers} = await api(`/api/sessions/${id}/offers`).catch(() => ({offers: []}));
  const tidy = offers.filter(o => confirm(o.ask)).map(o => o.url);
  const done = await post(`/api/sessions/${id}/delete`, JSON.stringify({tidy})).catch(e => alert(e.message));
  if (done?.failed?.length) alert('Not done:\n' + done.failed.join('\n'));
  tabs.postMessage(session);
  leave();
  poll();  // still here: this tab was not opened by the dashboard, so it may not close itself
}
async function code() {
  const w = vsTab = window.open('', 'code-' + session.workspace);
  try {
    const v = await post('/api/vscode', JSON.stringify({session: id}));
    if (w) w.location.replace('/vscode/?folder=' + encodeURIComponent(v.folder));
  } catch (e) { w?.close(); alert(e.message); }
}
async function resume() {
  try {
    const s = await post('/api/sessions', JSON.stringify({project: session.project, kind: 'resume', run_id: session.run_id}));
    window.name = 'session-' + s.id;
    location.hash = s.id;
    location.reload();
  } catch (e) { alert(e.message); }
}
async function interrupt() {
  if (halting) return;
  halting = true;
  update();
  await post(`/api/sessions/${id}/interrupt`).catch(e => alert(e.message));
  halting = false;
  update();
}
async function reply(a, body) {
  a.e.answers = body.cancel ? null : body.answers;  // shown in the question's place once it is settled
  a.sending = true;
  touch(a);
  update();
  await post(`/api/sessions/${id}/answer`, JSON.stringify({id: a.e.id, ...body})).catch(err => alert(err.message));
}

async function poll() {
  const s = (await api('/api/state').catch(() => ({sessions: [session].filter(Boolean)}))).sessions.find(s => s.id === id);
  if (!s) {
    gone = true;
    es.close();
    leave();
  } else session = s;
  update();
}
async function describe() {
  if (!session?.run_id) return;
  const said = await api('/api/project?project=' + encodeURIComponent(session.project)).catch(() => null);
  if (!said) return;
  items = [...(said.session_items || []), ...(said.run_items || []), ...(said.lists || []).flatMap(l => l.items)]
    .filter(i => i.run_id === session.run_id);
  update();
}

// ---- the column -------------------------------------------------------------------------------

let scroller = null;
const settle = () => { if (follow && scroller) scroller.scrollTop = scroller.scrollHeight; };

function Boot() {
  const failed = over !== null && !ready;
  const box = useRef(), pre = useRef();
  useLayoutEffect(() => { if (box.current.open) pre.current.scrollTop = pre.current.scrollHeight; });
  return html`<details ref=${box} class=${'boot ' + (failed ? 'failed' : ready ? 'ok quiet' : 'starting')} open=${failed || undefined}>
    <summary><span class="mark">${failed ? '✕' : ready ? '✓' : html`<${Spin}/>`}</span>
      <span class="step">${failed ? 'Sandbox failed' : ready ? 'Sandbox ready' : info.agent ? 'Starting the agent' : 'Starting the sandbox'}</span>
      <span class="line">${ready ? '' : boot.last}</span></summary>
    <pre ref=${pre}>${boot.text}</pre></details>`;
}

// What went in to a tool call, drawn again only for a new input (a diff can be costly).
class Given extends Component {
  shouldComponentUpdate(next) { return next.input !== this.props.input; }
  render({input}) { return given(input); }
}

// A record, drawn again only when its version changed.
class Entry extends Component {
  shouldComponentUpdate(next) { return next.v !== this.props.v || next.r !== this.props.r; }
  render({r}) {
    switch (r.kind) {
      case 'you': return html`<div class=${'you' + (r.queued ? ' queued' : '')}>${r.images?.length ? html`<${Shots} images=${r.images}/>` : ''}${r.text}</div>`;
      case 'say': return html`<div class="say">${markdown(r.text, {caret: r.streaming})}</div>`;
      case 'think': return html`<div class="think">${r.streaming ? html`<${Spin}/>` : ''}${r.streaming ? 'Thinking' : 'Thought'}</div>`;
      case 'tools': return html`<div class="tools">${r.list.map(t => html`<${Entry} key=${t.key} r=${t} v=${t.v}/>`)}</div>`;
      case 'tool': return html`<${Tool} t=${r}/>`;
      case 'ask': return html`<${Ask} a=${r}/>`;
      case 'turn': return html`<div class="turn">${r.text}</div>`;
      case 'note': return html`<div class=${'note ' + r.level}>${r.text}</div>`;
      case 'over': return html`<div class="over"><b>Session ended</b><span>${r.code ? `Exit status ${r.code}` : ''}</span>
        ${r.runId ? html`<${BusyButton} class="primary" onClick=${resume}>Resume</${BusyButton}>` : ''}</div>`;
    }
    return null;
  }
}
const Entries = ({list}) => list.map(r => html`<${Entry} key=${r.key} r=${r} v=${r.v}/>`);

// What it did: one line per tool call; open a line for what went in and what came back.
function Tool({t}) {
  const i = t.input;
  return html`<details class=${'tool ' + (t.done ? (t.error ? 'failed' : 'done') : 'running')}>
    <summary><span class="mark">${t.done ? (t.error ? '✕' : '✓') : html`<${Spin}/>`}</span><span class="verb">${verb(t)}</span>
      <span class="what" title=${typeof i?.description === 'string' ? i.description : undefined}>${t.progress || what(i)}</span>
      <span class="took">${t.done ? '' : t.took}</span></summary>
    <div class="body"><div class="given"><${Given} input=${i}/></div><div class="kids"><${Entries} list=${t.kids}/></div>
      <div class="out">${t.out ? html`<pre class=${t.error ? 'err' : undefined}>${t.out}</pre>` : ''}</div></div></details>`;
}

// A question it waits on. One question with one choice answers on the click; anything more is
// collected and sent together.
function Ask({a}) {
  const {e} = a;
  if (a.settled) return html`<div class="ask settled">${e.questions.map(q => html`<div>${q.question + ' '}
    <span class="said">${a.answers === null ? 'Dismissed' : a.answers?.[q.question] || ''}</span></div>`)}</div>`;
  const single = e.questions.length === 1 && !e.questions[0].multi;
  const answers = () => Object.fromEntries(e.questions.map((q, k) =>
    [q.question, [...a.picked[k], ...(a.other[k].trim() ? [a.other[k].trim()] : [])].join(', ')]));
  const pick = (q, k, o) => {
    if (single) { a.picked[k] = new Set([o.label]); return reply(a, {answers: answers()}); }
    const set = a.picked[k], on = set.has(o.label);
    if (!q.multi) set.clear();
    on ? set.delete(o.label) : set.add(o.label);
    touch(a);
    update();
  };
  const own = (ev, k) => {
    if (ev.key === 'Enter' && ev.target.value.trim()) { ev.preventDefault(); if (single) a.picked[k].clear(); reply(a, {answers: answers()}); }
  };
  return html`<div class="ask">
    ${e.questions.map((q, k) => html`<div class="q">${q.header ? html`<small>${q.header}</small>` : ''}<b>${q.question}</b>
      ${q.plan ? html`<div class="plan say">${markdown(q.plan)}</div>` : ''}
      <div class="options">${q.options.map(o => html`<button type="button" aria-pressed=${String(a.picked[k].has(o.label))}
        disabled=${a.sending} onClick=${() => pick(q, k, o)}><b>${o.label}</b>${o.description ? html`<span>${o.description}</span>` : ''}</button>`)}</div>
      <div class="other"><input type="text" placeholder=${q.options.length ? 'Something else…' : 'Your answer…'} aria-label="Your own answer"
        disabled=${a.sending} onInput=${ev => { a.other[k] = ev.target.value; }} onKeyDown=${ev => own(ev, k)}/></div></div>`)}
    <div class="row"><button type="button" disabled=${a.sending} onClick=${() => reply(a, {cancel: true})}>Dismiss</button>
      ${single ? '' : html`<button type="button" class="primary" disabled=${a.sending} onClick=${() => reply(a, {answers: answers()})}>Send answers</button>`}</div>
  </div>`;
}

// ---- the dock: background tasks, plan, composer -----------------------------------------------

// What the agent runs in the background, as its own task list has it: a line each, and a button
// that stops it (turning until the list comes without it).
function TaskRow({t}) {
  const [stopping, setStopping] = useState(false);
  const halt = () => {
    setStopping(true);
    post(`/api/sessions/${id}/task`, JSON.stringify({id: t.id})).catch(e => { setStopping(false); alert(e.message); });
  };
  return html`<li><span class="kind">${t.kind || 'task'}</span><span class="text" title=${t.text || ''}>${t.text || ''}</span>
    <span class="at" title=${t.note || ''}>${t.note || ''}</span>
    <button type="button" class=${'icon stop' + (stopping ? ' busy' : '')} disabled=${stopping} aria-label="Stop task" title="Stop" onClick=${halt}>${ICON.stop()}</button></li>`;
}
const Tasks = ({items}) => html`<details id="tasks" hidden=${!items.length}>${items.length ? html`
  <summary><${Spin}/><b>Background</b><span>${items.map(t => t.text).filter(Boolean).join(' · ')}</span><i>${items.length} running</i></summary>
  <ul>${items.map(t => html`<${TaskRow} key=${t.id} t=${t}/>`)}</ul>` : ''}</details>`;

function Plan({items}) {
  if (!items?.length) return html`<details id="plan" hidden></details>`;
  const done = items.filter(t => t.status === 'done').length, now = items.find(t => t.status === 'active') || items.find(t => t.status === 'pending');
  return html`<details id="plan"><summary><b>Plan</b><span>${done === items.length ? 'All done' : now?.text || ''}</span>
    <i>${done} of ${items.length}</i></summary><${Steps} items=${items}/></details>`;
}

const touchScreen = matchMedia('(pointer: coarse)').matches;  // a soft keyboard's Enter is a new line; the button sends
const draft = {get: () => { try { return sessionStorage.getItem('draft-' + id) || ''; } catch { return ''; } },
               set: v => { try { v ? sessionStorage.setItem('draft-' + id, v) : sessionStorage.removeItem('draft-' + id); } catch {} }};

function Composer() {
  const input = useRef(), form = useRef(), menuBox = useRef();
  const pictures = usePasted(() => settle());
  const [typed, setTyped] = useState(null);  // the name after a lone slash, while that is all there is
  const [closed, setClosed] = useState(false);
  const [picked, setPicked] = useState(0);
  const grow = () => { const el = input.current; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, innerHeight * .4) + 'px'; };
  useLayoutEffect(() => { input.current.value = draft.get(); grow(); input.current.focus(); }, []);

  // Its slash commands and skills, offered while the message is still just a slash and a name:
  // what begins with it first, else as the agent lists them.
  const lower = typed?.toLowerCase(), starts = c => c.name.toLowerCase().startsWith(lower);
  const offered = typed === null || closed ? [] : (info.commands || []).filter(c => c.name.toLowerCase().includes(lower))
    .sort((a, b) => starts(b) - starts(a)).slice(0, 40);
  const waiting = typed !== null && !closed && !ready && !offered.length;
  const at = Math.min(picked, Math.max(0, offered.length - 1));
  useLayoutEffect(() => { menuBox.current.querySelector('[aria-selected=true]')?.scrollIntoView({block: 'nearest'}); });
  const choose = c => {
    input.current.value = `/${c.name} `;
    setClosed(true);
    grow();
    input.current.focus();
  };
  const onInput = () => {
    grow();
    setPicked(0);
    setClosed(false);
    const m = /^\/(\S*)$/.exec(input.current.value);
    setTyped(m ? m[1] : null);
    draft.set(input.current.value);
  };
  const onKeyDown = e => {
    if (offered.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); return setPicked((at + (e.key === 'ArrowDown' ? 1 : offered.length - 1)) % offered.length); }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && `/${offered[at].name}` !== input.current.value)) { e.preventDefault(); return choose(offered[at]); }
      if (e.key === 'Escape') { e.preventDefault(); return setClosed(true); }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !touchScreen) { e.preventDefault(); form.current.requestSubmit(); }
  };
  const submit = async e => {
    e.preventDefault();
    const el = input.current, text = el.value;
    if (!(text.trim() || pictures.count()) || over !== null) return;
    const images = pictures.take();
    el.value = '';
    draft.set('');
    setClosed(true);
    grow();
    try { await post(`/api/sessions/${id}/prompt`, JSON.stringify({text, images: images.length ? images : undefined})); }
    catch (err) { el.value = text; pictures.put(images); grow(); alert(err.message); }
  };

  const models = info.models || [], efforts = info.efforts || [];
  const model = chosen.model ?? info.model, effort = chosen.effort ?? info.effort;
  const known = models.some(m => m.id === model);
  const choice = (what, value, body) => {
    chosen[what] = value;
    update();
    post(`/api/sessions/${id}/${what}`, JSON.stringify(body)).catch(e => { delete chosen[what]; update(); alert(e.message); });
  };
  const working = over === null && status === 'working';
  return html`<form class="composer" id="composer" ref=${form} onSubmit=${submit}>
    <div id="menu" role="listbox" ref=${menuBox} hidden=${!offered.length && !waiting}>
      ${waiting ? html`<${Spinner}/>` : offered.map((c, k) => html`<button key=${c.name} type="button" role="option" aria-selected=${String(k === at)}
        onMouseDown=${ev => { ev.preventDefault(); choose(c); }}><b>/${c.name}</b>${c.hint ? html`<i>${c.hint}</i>` : ''}<span>${c.description || ''}</span></button>`)}
    </div>
    <${Tray} pictures=${pictures} id="shots" onRemoved=${() => input.current.focus()}/>
    <textarea id="input" ref=${input} rows="1" aria-label="Message to the agent" autocomplete="off" disabled=${over !== null}
      placeholder=${over !== null ? 'Session ended' : 'Message'} onInput=${onInput} onKeyDown=${onKeyDown} onPaste=${pictures.onPaste}></textarea>
    <div class="bar">
      <select id="model" aria-label="Model" hidden=${!models.length} value=${models.length ? model || models[0].id : undefined}
        onChange=${e => choice('model', e.target.value, {id: e.target.value})}>
        ${known || !model ? '' : html`<option value=${model}>${model}</option>`}
        ${models.map(m => html`<option value=${m.id} title=${m.description || ''}>${m.name === m.id || !m.description ? m.name : `${m.name} (${m.description.split(' · ')[0]})`}</option>`)}
      </select>
      <select id="effort" aria-label="Reasoning effort" hidden=${!efforts.length} value=${efforts.length ? effort || efforts[0] : undefined}
        onChange=${e => choice('effort', e.target.value, {level: e.target.value})}>
        ${efforts.map(l => html`<option value=${l}>${l} effort</option>`)}
      </select>
      <span class="hint"></span>
      <button class=${'round halt' + (halting ? ' busy' : '')} id="halt" type="button" title="Interrupt (Esc)" aria-label="Interrupt"
        hidden=${!working} disabled=${halting} onClick=${interrupt}>${ICON.stop()}</button>
      <button class="round primary" id="send" type="submit" aria-label="Send" disabled=${over !== null}>${ICON.send()}</button>
    </div>
  </form>`;
}

// ---- the header, and the page ------------------------------------------------------------------

function Bar() {
  if (gone) return html`<header id="bar"><a class="home" href="/" title="Dashboard" aria-label="Dashboard">${ICON.back()}</a>
    <div class="who"><b>No session</b></div></header>`;
  if (!session) return html`<header id="bar"></header>`;
  const state = over !== null ? null : status;
  const chips = [...items, ...(session.items || []).map(here)];
  return html`<header id="bar">
    <a class="home" href="/" target="sandbox-dashboard" title="Dashboard" aria-label="Dashboard">${ICON.back()}</a>
    <div class="who"><b title=${session.title || ''}>${titled(session)}</b>
      <span>${[name(session.project), session.run_id, info.agent && (info.model ? `${info.agent}, ${info.model}` : info.agent)].filter(Boolean).join(' / ')}</span></div>
    <div class="chips">${chips.map(i => html`<${Chip} i=${i}/>`)}</div>
    <span class=${'state ' + (state || 'ended')}><span class=${'lamp ' + (state || '')}></span>${state ? SHORT[state] : 'Ended'}</span>
    ${session.workspace ? html`<${BusyButton} class="icon vscode" onClick=${code} aria-label="VS Code" title="VS Code">${ICON.vscode()}</${BusyButton}>` : ''}
    ${state ? html`<button class="icon stop" onClick=${stop} aria-label="Stop session" title="Stop">${ICON.stop()}</button>` : ''}
    <button class="icon" onClick=${remove} aria-label="Delete session" title="Delete">${ICON.trash()}</button>
    <${ThemeSwitch}/>
  </header>`;
}

let app = null;
const update = () => app?.forceUpdate();

class Page extends Component {
  componentDidMount() {
    app = this;
    new ResizeObserver(settle).observe(document.getElementById('log'));
  }
  componentDidUpdate() {
    if (session) {
      const state = over !== null ? null : status;
      document.title = `${titled(session)} · ${name(session.project)}`;
      setFavicon(FAVICON[state || 'unlit']);
    }
    settle();
  }
  render() {
    return html`
      <${Bar}/>
      <div id="gone" hidden=${!gone}><div><b>Session gone</b><a href="/">Dashboard</a></div></div>
      <main id="scroll" hidden=${gone} ref=${el => { scroller = el; }}
            onScroll=${() => { follow = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80; }}>
        <div class="column"><div id="log" aria-live="polite">${boot ? html`<${Boot}/>` : ''}<${Entries} list=${log}/></div></div>
      </main>
      <footer id="dock" hidden=${gone}><div class="column">
        <${Tasks} items=${tasks}/>
        <${Plan} items=${todos}/>
        <${Composer}/>
      </div></footer>`;
  }
}

render(html`<${Page}/>`, document.body);

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !e.defaultPrevented && status === 'working' && over === null) interrupt();
});
// Another session in this tab (a resumed run, a pasted link): start over on it.
addEventListener('hashchange', () => location.reload());
const es = new EventSource(`/api/sessions/${id}/events`);
es.onmessage = m => {
  const e = JSON.parse(m.data);
  if (e.type === 'snapshot') { restore(e); if (!items.length) describe(); }
  else { handle(e); update(); }
  if (e.type === 'exit' || (e.type === 'snapshot' && e.session.exit !== null)) es.close();  // nothing more will come
};
es.onerror = () => { if (es.readyState === EventSource.CLOSED) poll(); };
setInterval(poll, 3000);
setInterval(describe, 60000);
