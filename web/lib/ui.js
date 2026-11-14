// What the dashboard, the chat and the terminal page share: talking to the server, what a session
// is called, icons, the day/night switch, a button that turns while it works, pasted pictures.
// Everything is drawn as Preact components (lib/preact.js): PR titles and what an agent writes are
// other people's text, and stay text.
import {html, useState, useRef, useEffect} from './preact.js';

export const $ = id => document.getElementById(id);
export const api = async (path, opts) => {
  const r = await fetch(path, opts), j = await r.json();
  if (!r.ok) throw new Error(j.error);
  return j;
};
export const post = (path, body) => api(path, {method: 'POST', body});
export const name = path => path.replace(/\/+$/, '').split('/').pop();
// What a session is called: what it was first asked, else its run.
export const label = s => s.kind === 'shell' ? 'terminal' : s.run_id + (s.kind === 'resume' ? ' (resumed)' : '');
export const titled = s => s.title || (s.kind === 'shell' ? 'Terminal' : 'Session ' + s.run_id);
export const SAYS = {starting: 'starting its sandbox', working: 'working', idle: 'idle, waiting for its next task',
                     question: 'waiting on your answer'};
export const SHORT = {starting: 'Starting', working: 'Working', idle: 'Idle', question: 'Needs you'};

// Icons are drawn, so they keep the colour of the button they are on. Their markup is ours, fixed
// here: the one place a string becomes markup.
const svg = (inner, viewBox = '0 0 20 20') => () =>
  html`<svg viewBox=${viewBox} aria-hidden="true" dangerouslySetInnerHTML=${{__html: inner}}></svg>`;
const stroke = (d, width = 2) => svg(`<path d="${d}" fill="none" stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`);
export const ICON = {
  plus: stroke('M10 4v12M4 10h12', 2.2),
  prompt: stroke('M4 6l4 4-4 4M10 15h6', 2.2),
  trash: stroke('M3.5 5.5h13M8 5.5V3.5h4v2M5.5 5.5l.8 11h7.4l.8-11M8.5 8.5v5M11.5 8.5v5'),
  play: svg('<path d="M6 4.2v11.6a.8.8 0 0 0 1.2.7l9.3-5.8a.8.8 0 0 0 0-1.4L7.2 3.5a.8.8 0 0 0-1.2.7z" fill="currentColor"/>'),
  stop: svg('<rect x="4.5" y="4.5" width="11" height="11" rx="2" fill="currentColor"/>'),
  vscode: svg('<path fill="currentColor" fill-rule="evenodd" d="M17 1.5 22 4v16l-5 2.5-9.4-8.6-4.3 3.3L2 16.5v-9l1.3-.7 4.3 3.3zm0 5.7L10.7 12l6.3 4.8z"/>', '0 0 24 24'),
  gear: svg('<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></g>', '0 0 24 24'),
  send: stroke('M10 16V4M4.5 9.5 10 4l5.5 5.5', 2.2),
  back: stroke('M11.5 4.5 6 10l5.5 5.5', 2.2),
  sun: svg('<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10" cy="10" r="3.4"/><path d="M10 2.2v2M10 15.8v2M2.2 10h2M15.8 10h2M4.5 4.5l1.4 1.4M14.1 14.1l1.4 1.4M4.5 15.5l1.4-1.4M14.1 5.9l1.4-1.4"/></g>'),
  moon: stroke('M16.5 11.8A7 7 0 0 1 8.2 3.5a7 7 0 1 0 8.3 8.3z', 1.8),
  auto: svg('<circle cx="10" cy="10" r="6.8" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10 3.2a6.8 6.8 0 0 1 0 13.6z" fill="currentColor"/>'),
};
export const Spinner = ({text = ''}) => html`<span class="loading" role="status"><span class="spin"></span>${text}</span>`;
export const Spin = () => html`<span class="spin"></span>`;

// A button that does something slow turns until it is done, and cannot be pressed twice. Its
// onClick may return a promise; whatever it opens in a new tab it opens before its first await.
export function BusyButton({onClick, class: cls = '', children, ...rest}) {
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const click = async e => {
    if (busy) return;
    setBusy(true);
    try { await onClick(e); } finally { if (alive.current) setBusy(false); }
  };
  return html`<button type="button" ...${rest} class=${(cls + (busy ? ' busy' : '')).trim() || undefined} disabled=${busy}
                      onClick=${click}>${children}</button>`;
}

// The switch between the browser's setting and a pinned day or night (the pin is set before the
// first paint by /theme.js).
export function ThemeSwitch() {
  const [now, setNow] = useState(() => document.documentElement.dataset.theme || 'auto');
  const pick = mode => {
    if (mode === 'auto') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = mode;
    try { mode === 'auto' ? localStorage.removeItem('theme') : localStorage.setItem('theme', mode); } catch {}
    setNow(mode);
    document.dispatchEvent(new Event('themechange'));
  };
  return html`<div class="theme" role="group" aria-label="Colours">
    ${[['auto', 'Follow the browser', ICON.auto], ['light', 'Day', ICON.sun], ['dark', 'Night', ICON.moon]].map(([mode, title, icon]) =>
      html`<button key=${mode} type="button" title=${title} aria-label=${title} aria-pressed=${String(now === mode)}
                   onClick=${() => pick(mode)}>${icon()}</button>`)}
  </div>`;
}

// A tab's icon says what it is and how it is doing: the agent's lamp in the colour of what it does
// (amber working or starting, green idle, violet waiting on your answer), an empty ring once ended.
const tile = inner => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='#1b1d36'/>${inner}</svg>`)}`;
export const FAVICON = {
  shell: tile("<path d='M8 10l6 6-6 6' fill='none' stroke='#f2b84b' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/><path d='M17 23h7' stroke='#e6e4f2' stroke-width='3' stroke-linecap='round'/>"),
  working: tile("<circle cx='16' cy='16' r='10' fill='#f2b84b'/>"),
  starting: tile("<circle cx='16' cy='16' r='8' fill='none' stroke='#f2b84b' stroke-width='4' stroke-dasharray='30 21'/>"),
  idle: tile("<circle cx='16' cy='16' r='8' fill='#6fd3a2'/>"),
  question: tile("<circle cx='16' cy='16' r='10' fill='#c69cff'/>"),
  unlit: tile("<circle cx='16' cy='16' r='7' fill='none' stroke='#8c8fb3' stroke-width='3'/>"),
};
export const setFavicon = href => { const link = $('icon'); if (link && link.getAttribute('href') !== href) link.href = href; };

// A listed item (a pull request, an issue, a published port): its status mark and its tooltip.
export const Mark = ({i}) => i.status ? html`<span class=${'status ' + i.status} aria-label=${i.status_text || i.status}>
  ${{ok: '✓', fail: '✕', pending: '●', done: '⇥'}[i.status] || ''}</span>` : '';
export const tip = i => [(i.ref ? i.ref + ' ' : '') + (i.note ? i.note + ': ' : '') + i.title + (i.branch ? ` (${i.branch})` : ''),
  i.status_text].filter(Boolean).join('\n');
// What a plugin publishes for a running session (its servers' ports), to link from wherever this
// page was opened: `{host}` in its url is this page's own host name.
export const here = i => ({...i, url: i.url.replaceAll('{host}', location.hostname)});
// An item on a session's row: a chip with its mark and its ref, opening `url`.
export const Chip = ({i, onClick}) => html`<a class=${'chip ' + (i.status || '')} href=${i.url} target="_blank" rel="noopener"
  onClick=${onClick} title=${tip(i)}><${Mark} i=${i}/>${i.ref || i.title}</a>`;

// Pictures pasted into a message: kept in a tray over the field until it is sent, each with a
// button that takes it out again. `take()` hands them over (their type and their bytes in base64)
// and empties the tray. `onPaste` goes on the field; <Tray> draws what is held.
export const PICTURE = /^image\/(png|jpeg|gif|webp)$/;
export function usePasted(changed) {
  const [held, setHeld] = useState([]);
  const now = useRef(held);
  const put = all => { now.current = all; setHeld(all); };
  useEffect(() => { changed?.(); }, [held]);
  const add = file => new Promise(done => {
    if (file.size > 5 << 20) { alert('An image can be at most 5 MB.'); return done(); }
    if (now.current.length >= 8) return done();
    const reader = new FileReader();
    reader.onload = () => { put([...now.current, {type: file.type, data: String(reader.result).split(',')[1]}]); done(); };
    reader.onerror = () => done();
    reader.readAsDataURL(file);
  });
  const onPaste = e => {
    const files = [...(e.clipboardData?.files || [])].filter(f => PICTURE.test(f.type));
    if (!files.length) return;  // text: pasted as ever
    e.preventDefault();
    files.reduce((before, f) => before.then(() => add(f)), Promise.resolve());
  };
  return {held, onPaste, put, count: () => now.current.length,
          take: () => { const all = now.current; put([]); return all; },
          drop: p => put(now.current.filter(x => x !== p))};
}
export const Tray = ({pictures, id, onRemoved}) => html`<div class="shots" id=${id}>
  ${pictures.held.map(p => html`<span class="shot">
    <img src=${`data:${p.type};base64,${p.data}`} alt="Pasted image"/>
    <button type="button" aria-label="Remove image" title="Remove" onClick=${() => { pictures.drop(p); onRemoved?.(); }}>✕</button>
  </span>`)}</div>`;
// The pictures of a message that was sent, as it shows them.
export const Shots = ({images}) => html`<div class="shots">
  ${(images || []).filter(p => PICTURE.test(p.type) && /^[A-Za-z0-9+/=]+$/.test(p.data))
    .map(p => html`<img src=${`data:${p.type};base64,${p.data}`} alt="Image"/>`)}</div>`;
