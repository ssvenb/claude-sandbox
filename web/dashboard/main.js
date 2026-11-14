// The dashboard: on top, the first message of a new session; under it, on the left what is
// running, grouped by project, and on the right each project with what its plugins list. It polls
// /api/state (the sessions) every few seconds and /api/project (what each project's plugins
// describe, `run.sh --web`) every minute, and draws what it got.
import {html, render, Component, useState, useRef} from '../lib/preact.js';
import {api, post, name, titled, SAYS, ICON, BusyButton, ThemeSwitch, Mark, Chip, tip, here, usePasted, Tray} from '../lib/ui.js';
import {configure} from './settings.js';

window.name = 'sandbox-dashboard';  // where a chat's way back lands
let state = {projects: [], sessions: []}, loaded = false;
const plugins = {};  // project → what its plugins said about it

// What a project's plugins put on a run's session row: items they added there themselves, and
// items they tied to a run (a pull request on the run's branch), from their sections or listed
// for runs only (which show nowhere else).
const liveItems = s => (s.items || []).map(here);
const runItems = said => [...said.lists.flatMap(list => list.items), ...(said.run_items || [])]
  .filter(i => i.run_id).concat(said.session_items || []);

// ---- tabs ----------------------------------------------------------------------------------------

// The tabs this page opened, by name, so closing a session can close them too. A session's own
// page also closes itself (and the VS Code tab it opened) when told on `tabs`.
const opened = {}, tabs = new BroadcastChannel('sandbox-tabs');
// A session's tabs: its page, any item (its pull request) a plugin tied to its run, and those
// opened from it (a port it published while it ran, no longer listed once it is stopped).
const owned = {};
const tabNames = s => ['session-' + s.id, ...(owned[s.id] || []),
  ...Object.values(plugins).flatMap(runItems).filter(i => s.run_id && i.run_id === s.run_id)
    .concat(liveItems(s)).map(i => 'item-' + i.url)];
const closeTabs = s => tabNames(s).forEach(n => opened[n]?.close());
tabs.onmessage = e => closeTabs(e.data);

// A tab per thing, found again by its name: opened once, brought to the front after that. Always
// called inside the click, before any await, or the popup blocker eats the new tab.
function tab(tabName) {
  const w = window.open('', tabName);
  w?.focus();
  if (w) opened[tabName] = w;
  return w;
}
// Still empty, so ours to fill. Reading another site's tab (GitHub) throws: it is long filled.
const fresh = w => { try { return w.location.href === 'about:blank'; } catch { return false; } };

// One tab per listed item (a pull request, an issue). A plain click only: ctrl/middle-click still
// open a tab of their own, as on any link.
function item(e, i, s) {
  if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  const w = tab('item-' + i.url);
  if (s) (owned[s.id] ??= new Set()).add('item-' + i.url);
  // The tab keeps its opener (this page): cut off, Chromium moves it out of reach of both the
  // lookup by name and close(). GitHub could navigate this tab through it; it is your own login.
  if (w && fresh(w)) w.location.replace(i.url);
}

// A session's page: its chat, or the terminal of one that runs in a pty.
const page = s => (s.ui === 'chat' ? '/chat#' : '/session#') + s.id;
function show(s) {
  const w = tab('session-' + s.id);
  if (w && fresh(w)) w.location.replace(page(s));
}

// ---- what the buttons do -------------------------------------------------------------------------

async function start(project, kind, run_id, task, images) {
  const w = window.open('about:blank');  // its name is the session's id, which the server picks
  try {
    const s = await post('/api/sessions', JSON.stringify({project, kind, run_id, task, images}));
    if (w) { w.name = 'session-' + s.id; opened[w.name] = w; w.location.replace(page(s)); }
    refresh();
  } catch (e) { w?.close(); alert(e.message); }
}

// One terminal per project, a shell on this machine in its directory: brought to the front when
// its tab is open, and the server hands back the live one when the tab was closed.
async function terminal(project) {
  const w = tab('terminal-' + project);
  if (!w || !fresh(w)) return;
  try {
    const t = await post('/api/sessions', JSON.stringify({project, kind: 'shell'}));
    w.location.replace('/session#' + t.id);
  } catch (e) { w.close(); alert(e.message); }
}

// Stopping removes the container and keeps the session listed, its tab showing how it ended, so
// it can be read and resumed. Nothing else stops it: closing its tab, or the browser, does not.
async function stop(s) {
  if (!confirm(`Stop “${titled(s)}”?`)) return;
  await post(`/api/sessions/${s.id}/stop`).catch(e => alert(e.message));
  refresh();
}

// Deleting forgets the session (stopping it first if it still runs) and closes its tabs.
async function remove(s) {
  if (s.exit === null && !confirm(`Stop and delete “${titled(s)}”?`)) return;
  // What a plugin offers to tidy up with it (its run's open pull request: close it) is asked
  // about one by one, and done only on a yes.
  const {offers} = await api(`/api/sessions/${s.id}/offers`).catch(() => ({offers: []}));
  const tidy = offers.filter(o => confirm(o.ask)).map(o => o.url);
  const done = await post(`/api/sessions/${s.id}/delete`, JSON.stringify({tidy})).catch(e => alert(e.message));
  if (done?.failed?.length) alert('Not done:\n' + done.failed.join('\n'));
  closeTabs(s);
  tabs.postMessage(s);
  refresh();
}

// ---- the page ------------------------------------------------------------------------------------

// The first message of a new session (pictures pasted into it go along), and the project it is for.
function Starter({projects}) {
  const text = useRef(), pick = useRef();
  const [busy, setBusy] = useState(false);
  const pictures = usePasted();
  const grow = () => { const el = text.current; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, innerHeight * .3) + 'px'; };
  const submit = async e => {
    e.preventDefault();
    if (busy) return;
    const task = text.current.value.trim(), images = pictures.take();
    text.current.value = '';
    grow();
    setBusy(true);
    try { await start(projects.length > 1 ? pick.current.value : projects[0], 'run', undefined, task || undefined, images.length ? images : undefined); }
    finally { setBusy(false); }
  };
  return html`<form class="starter" onSubmit=${submit}>
    <div class="field"><${Tray} pictures=${pictures} onRemoved=${() => text.current.focus()}/>
      <textarea ref=${text} rows="1" name="task" placeholder="What should an agent work on?" aria-label="First message of a new session"
        onInput=${grow} onPaste=${pictures.onPaste}
        onKeyDown=${e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); e.target.form.requestSubmit(); } }}></textarea></div>
    ${projects.length > 1 ? html`<select ref=${pick} name="project" aria-label="Project">
      ${projects.map(p => html`<option key=${p} value=${p}>${name(p)}</option>`)}</select>` : ''}
    <button type="submit" class=${'primary' + (busy ? ' busy' : '')} disabled=${busy}>Start session</button>
  </form>`;
}

// An item on a session's row: opens in its own tab, as in a section.
const RunChip = ({i, s}) => html`<${Chip} i=${i} onClick=${e => item(e, i, s)}/>`;

// A running session as a window: what it was asked and what it is at right now. How it is doing
// is its colour (its class), spelled out only for a screen reader.
function Window({s, items}) {
  const doing = s.status === 'starting' ? html`<div class="doing">${s.waiting ? `${s.waiting} message${s.waiting > 1 ? 's' : ''} waiting` : ''}</div>`
    : s.status === 'working' && s.activity ? html`<div class="doing tool">${s.activity}</div>`
    : html`<div class="doing">${(s.said || '').replace(/[#*`>|]/g, '').replace(/\s+/g, ' ').slice(0, 180)}</div>`;
  return html`<article class=${'window ' + s.status} aria-label=${`${titled(s)}: ${SAYS[s.status]}`}>
    <div class="name"><button class="open" onClick=${() => show(s)} title=${s.title || ''}>${titled(s)}</button>
      <button class="icon stop" onClick=${() => stop(s)} aria-label="Stop session" title="Stop">${ICON.stop()}</button></div>
    ${doing}
    <div class="chips">${items.map(i => html`<${RunChip} i=${i} s=${s}/>`)}</div>
  </article>`;
}

// Lists a plugin made, and a section for each run item that names one (a run's open pull request).
const sections = said => {
  const lists = said.lists.map(list => ({title: list.title, items: [...list.items]}));
  for (const i of said.run_items || []) {
    if (!i.run_id || !i.section) continue;
    let list = lists.find(l => l.title === i.section);
    if (!list) lists.push(list = {title: i.section, items: []});
    list.items.push(i);
  }
  return lists;
};

// A project: its buttons, and what its plugins list (issues, …): the page only draws it. An item
// a plugin tied to a run is on that run's session instead, while one is listed; with none, it
// offers to resume the run. Items listed for runs only (pull requests) show for their run alone:
// with no session of it listed, under the section they name (an open pull request), else nowhere.
// Its ended sessions are at the foot of its panel.
function Project({path, said, holder, tiedTo, ended, live}) {
  return html`<section class="project">
    <div class="head"><h3 title=${path}>${name(path)}${said?.agent ? html`<small>${said.agent}</small>` : ''}</h3>
      <${BusyButton} class="glyph" onClick=${() => configure(path, () => load(path))} title="Settings" aria-label="Settings">${ICON.gear()}</${BusyButton}>
      <${BusyButton} class="glyph" onClick=${() => terminal(path)} title="Terminal" aria-label="Terminal">${ICON.prompt()}</${BusyButton}>
      <${BusyButton} class="glyph primary" onClick=${() => start(path, 'run')} title="New session" aria-label="New session">${ICON.plus()}</${BusyButton}></div>
    <div class="notes">${said ? said.notes.map(note => html`<p>${note}</p>`) : html`<p class="loading"><span class="spin"></span>Loading</p>`}</div>
    ${(said ? sections(said) : []).map(list => {
      const items = list.items.filter(i => !(i.run_id && holder(path, i.run_id)));
      if (!items.length) return null;  // a list with nothing on it (no open issue) is not shown
      return html`<h4>${list.title}<span class="count">${String(items.length)}</span></h4>
        <ul>${items.map(i => html`<li>
          <a href=${i.url} target="_blank" rel="noopener" onClick=${e => item(e, i)} title=${tip(i)}><${Mark} i=${i}/>
            ${i.ref ? html`<span class="num">${i.ref}</span>` : ''}${i.note ? html`<span class="draft">${i.note + ': '}</span>` : ''}${i.title}</a>
          ${i.run_id ? html`<${BusyButton} onClick=${() => start(path, 'resume', i.run_id)}>Resume</${BusyButton}>` : ''}
          ${i.start ? html`<${BusyButton} onClick=${() => start(path, 'run', undefined, i.start.task)} title=${i.start.task}>${i.start.label}</${BusyButton}>` : ''}
        </li>`)}</ul>`;
    })}
    ${ended.length ? html`<ul class="ended">${ended.map(s => html`<li key=${s.id}>
      <button class="session" onClick=${() => show(s)} title=${s.title || ''}><span class="lamp"></span><span class="name">${titled(s)}</span></button>
      ${tiedTo(s).map(i => html`<${RunChip} i=${i} s=${s}/>`)}
      ${s.run_id && !live(s.run_id) ? html`<${BusyButton} class="icon play" onClick=${() => start(path, 'resume', s.run_id)} aria-label="Resume session" title="Resume">${ICON.play()}</${BusyButton}>` : ''}
      <button class="icon" onClick=${() => remove(s)} aria-label="Delete session" title="Delete">${ICON.trash()}</button>
    </li>`)}</ul>` : ''}
  </section>`;
}

const URGENCY = {question: 0, working: 1, starting: 2, idle: 3};

class Board extends Component {
  render() {
    if (!loaded) return html`<p class="loading"><span class="spin"></span>Reading your projects</p>`;
    const agents = state.sessions.filter(s => s.kind !== 'shell');  // terminals are not sessions
    const live = id => state.sessions.find(s => s.run_id === id && s.exit === null);
    // The one session of a run that carries its items: the live one, else the latest.
    const holder = (path, id) => {
      const of = agents.filter(s => s.project === path && s.run_id === id);
      return of.find(s => s.exit === null) || of.pop();
    };
    const tiedTo = s => {
      const said = plugins[s.project];
      return (s.run_id && said && holder(s.project, s.run_id) === s ? runItems(said).filter(i => i.run_id === s.run_id) : []).concat(liveItems(s));
    };
    // The left: each project's running sessions (the ones waiting on you first).
    const groups = state.projects.map(path => {
      const running = agents.filter(s => s.project === path && s.exit === null)
        .sort((a, b) => URGENCY[a.status] - URGENCY[b.status] || b.started - a.started);
      if (!running.length) return null;
      return html`<div class="group" key=${path}><h3 title=${path}>${name(path)}</h3>
        <div class="windows">${running.map(s => html`<${Window} key=${s.id} s=${s} items=${tiedTo(s)}/>`)}</div></div>`;
    }).filter(Boolean);
    const projects = state.projects.map(path => html`<${Project} key=${path} path=${path} said=${plugins[path]} holder=${holder}
      tiedTo=${tiedTo} live=${live} ended=${agents.filter(s => s.project === path && s.exit !== null).reverse()}/>`);
    return html`
      <div class="top">${state.projects.length ? html`<${Starter} projects=${state.projects}/>` : html`<div class="starter"></div>`}<${ThemeSwitch}/></div>
      ${state.projects.length ? html`<div class=${'board' + (groups.length ? '' : ' quiet')}>
          ${groups.length ? html`<div class="running"><h2 class="band">Running now</h2>${groups}</div>` : ''}
          <aside class="projects"><h2 class="band">Projects</h2>${projects}</aside></div>`
        : html`<div class="empty"><b>No projects yet</b>List the directories of the repos your agents work on, one per line, in ${state.projects_file}.</div>`}`;
  }
}
const root = document.getElementById('board');
const draw = () => render(html`<${Board}/>`, root);

async function load(path) {
  plugins[path] = await api('/api/project?project=' + encodeURIComponent(path)).catch(e => ({lists: [], notes: [e.message]}));
  draw();
}

async function refresh() {
  const before = state.projects.join();
  state = await api('/api/state');
  loaded = true;
  if (state.projects.join() !== before) state.projects.forEach(load);
  draw();
}

root.replaceChildren();
draw();
// To look into from the console: what the page drew from, and a way to draw it again.
window.dashboard = {get state() { return state; }, plugins, render: draw};
refresh();
setInterval(refresh, 3000);
setInterval(() => state.projects.forEach(load), 60000);
