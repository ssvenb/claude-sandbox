// What the dashboard, the chat and the terminal page share. Loaded in <head>, so the theme is set
// before anything is painted.
(() => {
  let pinned = null;
  try { pinned = localStorage.getItem('theme'); } catch {}
  if (pinned === 'light' || pinned === 'dark') document.documentElement.dataset.theme = pinned;
})();

const $ = id => document.getElementById(id);
// Everything is built with textContent, never innerHTML: PR titles and what an agent writes are
// other people's text.
const h = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids.filter(k => k !== null && k !== undefined && k !== false));
  return e;
};
const api = async (path, opts) => {
  const r = await fetch(path, opts), j = await r.json();
  if (!r.ok) throw new Error(j.error);
  return j;
};
const post = (path, body) => api(path, {method: 'POST', body});
const name = path => path.replace(/\/+$/, '').split('/').pop();
// What a session is called: what it was first asked, else its run.
const label = s => s.kind === 'shell' ? 'terminal' : s.run_id + (s.kind === 'resume' ? ' (resumed)' : '');
const titled = s => s.title || (s.kind === 'shell' ? 'Terminal' : 'Session ' + s.run_id);
const SAYS = {starting: 'starting its sandbox', working: 'working', idle: 'idle, waiting for its next task',
              question: 'waiting on your answer'};
const SHORT = {starting: 'Starting', working: 'Working', idle: 'Idle', question: 'Needs you'};

// Icons are drawn, so they keep the colour of the button they are on.
const svg = (inner, viewBox = '0 0 20 20') => {
  const e = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  e.setAttribute('viewBox', viewBox);
  e.setAttribute('aria-hidden', 'true');
  e.innerHTML = inner;
  return e;
};
const stroke = (d, width = 2) => svg(`<path d="${d}" fill="none" stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`);
const ICON = {
  plus: () => stroke('M10 4v12M4 10h12', 2.2),
  prompt: () => stroke('M4 6l4 4-4 4M10 15h6', 2.2),
  trash: () => stroke('M3.5 5.5h13M8 5.5V3.5h4v2M5.5 5.5l.8 11h7.4l.8-11M8.5 8.5v5M11.5 8.5v5'),
  play: () => svg('<path d="M6 4.2v11.6a.8.8 0 0 0 1.2.7l9.3-5.8a.8.8 0 0 0 0-1.4L7.2 3.5a.8.8 0 0 0-1.2.7z" fill="currentColor"/>'),
  stop: () => svg('<rect x="4.5" y="4.5" width="11" height="11" rx="2" fill="currentColor"/>'),
  vscode: () => svg('<path fill="currentColor" fill-rule="evenodd" d="M17 1.5 22 4v16l-5 2.5-9.4-8.6-4.3 3.3L2 16.5v-9l1.3-.7 4.3 3.3zm0 5.7L10.7 12l6.3 4.8z"/>', '0 0 24 24'),
  gear: () => svg('<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></g>', '0 0 24 24'),
  send: () => stroke('M10 16V4M4.5 9.5 10 4l5.5 5.5', 2.2),
  back: () => stroke('M11.5 4.5 6 10l5.5 5.5', 2.2),
  chevron: () => stroke('M7.5 5 12.5 10l-5 5', 2),
  sun: () => svg('<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10" cy="10" r="3.4"/><path d="M10 2.2v2M10 15.8v2M2.2 10h2M15.8 10h2M4.5 4.5l1.4 1.4M14.1 14.1l1.4 1.4M4.5 15.5l1.4-1.4M14.1 5.9l1.4-1.4"/></g>'),
  moon: () => stroke('M16.5 11.8A7 7 0 0 1 8.2 3.5a7 7 0 1 0 8.3 8.3z', 1.8),
  auto: () => svg('<circle cx="10" cy="10" r="6.8" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10 3.2a6.8 6.8 0 0 1 0 13.6z" fill="currentColor"/>'),
};
const spinner = (text = '') => h('span', {className: 'loading', role: 'status'}, h('span', {className: 'spin'}), text);

// A button that does something slow turns until it is done, and cannot be pressed twice.
async function busy(button, work) {
  if (!button) return work();
  button.classList.add('busy');
  button.disabled = true;
  try { return await work(); }
  finally { button.classList.remove('busy'); button.disabled = false; }
}

// The switch between the browser's setting and a pinned day or night.
function themeSwitch() {
  const now = () => document.documentElement.dataset.theme || 'auto';
  const box = h('div', {className: 'theme', role: 'group', ariaLabel: 'Colours'});
  const draw = () => box.replaceChildren(...[['auto', 'Follow the browser', ICON.auto], ['light', 'Day', ICON.sun], ['dark', 'Night', ICON.moon]]
    .map(([mode, title, icon]) => h('button', {type: 'button', title, ariaLabel: title, ariaPressed: String(now() === mode), onclick: () => {
      if (mode === 'auto') delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = mode;
      try { mode === 'auto' ? localStorage.removeItem('theme') : localStorage.setItem('theme', mode); } catch {}
      draw();
      document.dispatchEvent(new Event('themechange'));
    }}, icon())));
  draw();
  return box;
}

// A tab's icon says what it is and how it is doing: the agent's lamp in the colour of what it does
// (amber working or starting, green idle, violet waiting on your answer), an empty ring once ended.
const tile = inner => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='#1b1d36'/>${inner}</svg>`)}`;
const FAVICON = {
  shell: tile("<path d='M8 10l6 6-6 6' fill='none' stroke='#f2b84b' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/><path d='M17 23h7' stroke='#e6e4f2' stroke-width='3' stroke-linecap='round'/>"),
  working: tile("<circle cx='16' cy='16' r='10' fill='#f2b84b'/>"),
  starting: tile("<circle cx='16' cy='16' r='8' fill='none' stroke='#f2b84b' stroke-width='4' stroke-dasharray='30 21'/>"),
  idle: tile("<circle cx='16' cy='16' r='8' fill='#6fd3a2'/>"),
  question: tile("<circle cx='16' cy='16' r='10' fill='#c69cff'/>"),
  unlit: tile("<circle cx='16' cy='16' r='7' fill='none' stroke='#8c8fb3' stroke-width='3'/>"),
};

const mark = i => i.status ? h('span', {className: 'status ' + i.status, ariaLabel: i.status_text || i.status},
  {ok: '✓', fail: '✕', pending: '●', done: '⇥'}[i.status] || '') : '';
const tip = i => [(i.ref ? i.ref + ' ' : '') + (i.note ? i.note + ': ' : '') + i.title + (i.branch ? ` (${i.branch})` : ''),
  i.status_text].filter(Boolean).join('\n');
// What a plugin publishes for a running session (its servers' ports), to link from wherever this
// page was opened: `{host}` in its url is this page's own host name.
const here = i => ({...i, url: i.url.replaceAll('{host}', location.hostname)});
