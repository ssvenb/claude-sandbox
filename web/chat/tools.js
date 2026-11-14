// A tool call, in a few words: what it is called, what it was about, an edit as a diff, a plan as
// its steps.
import {html} from '../lib/preact.js';
import {Spin} from '../lib/ui.js';

const VERBS = {bash: 'Run', shell: 'Run', powershell: 'Run', read: 'Read', view: 'Read', edit: 'Edit', multiedit: 'Edit', str_replace: 'Edit',
  str_replace_editor: 'Edit', write: 'Write', create: 'Write', grep: 'Search', glob: 'Find files', ls: 'List', webfetch: 'Fetch',
  web_fetch: 'Fetch', fetch: 'Fetch', websearch: 'Search the web', web_search: 'Search the web', task: 'Subagent', agent: 'Subagent',
  todowrite: 'Plan', update_todo: 'Plan', skill: 'Skill', askuserquestion: 'Ask', ask_user: 'Ask', exitplanmode: 'Propose plan',
  notebookedit: 'Edit notebook', toolsearch: 'Find tools', report_intent: 'Intent'};
export function verb(tool) {
  if (tool.title) return tool.title;
  const mcp = /^mcp__(.+?)__(.+)$/.exec(tool.name || '');
  if (mcp) return `${mcp[1]}: ${mcp[2].replaceAll('_', ' ')}`;
  return VERBS[String(tool.name).toLowerCase()] || String(tool.name);
}
export function what(input) {
  if (!input || typeof input !== 'object') return '';
  for (const key of ['command', 'file_path', 'notebook_path', 'pattern', 'query', 'url', 'path', 'skill', 'description', 'intent', 'prompt'])
    if (typeof input[key] === 'string' && input[key].trim())
      return input[key].trim().split('\n')[0] + (key === 'pattern' && input.path ? `  in ${input.path}` : '');
  const first = Object.values(input).find(v => typeof v === 'string' && v.trim());
  return first ? first.trim().split('\n')[0] : '';
}

// Lines that left and lines that came, in order, with a little of what stayed around them.
export function diff(before, after) {
  const a = before.replace(/\n$/, '').split('\n'), b = after.replace(/\n$/, '').split('\n');
  let rows;
  if (a.length * b.length > 250000) rows = [...a.map(t => ['del', t]), ...b.map(t => ['add', t])];
  else {
    const lcs = Array.from({length: a.length + 1}, () => new Uint16Array(b.length + 1));
    for (let x = a.length - 1; x >= 0; x--)
      for (let y = b.length - 1; y >= 0; y--)
        lcs[x][y] = a[x] === b[y] ? lcs[x + 1][y + 1] + 1 : Math.max(lcs[x + 1][y], lcs[x][y + 1]);
    rows = [];
    let x = 0, y = 0;
    while (x < a.length || y < b.length) {
      if (x < a.length && y < b.length && a[x] === b[y]) { rows.push(['same', a[x]]); x++; y++; }
      else if (y >= b.length || (x < a.length && lcs[x + 1][y] >= lcs[x][y + 1])) rows.push(['del', a[x++]]);
      else rows.push(['add', b[y++]]);
    }
  }
  const keep = rows.map((r, k) => r[0] !== 'same' || rows.slice(Math.max(0, k - 2), k + 3).some(n => n[0] !== 'same'));
  const spans = [];
  rows.forEach((r, k) => {
    if (keep[k]) spans.push(html`<span class=${r[0]}>${r[1] || ' '}</span>`);
    else if (keep[k - 1] !== false) spans.push(html`<span class="gap">  ⋯</span>`);
  });
  return html`<pre class="diff">${spans}</pre>`;
}

export const Steps = ({items}) => html`<ul class="steps">${items.map(t => html`<li class=${t.status}>
  <span class="box">${t.status === 'done' ? '✓' : t.status === 'active' ? html`<${Spin}/>` : '○'}</span><span>${t.text}</span></li>`)}</ul>`;
export const todoItems = input => (input?.todos || []).map(t => ({text: t.content || t.title || '',
  status: {in_progress: 'active', completed: 'done', done: 'done'}[t.status] || 'pending'}));

// What went in, drawn once per input: an edit as a diff, a file written, a command behind its
// prompt, a subagent's prompt, else the input itself.
export function given(i) {
  if (!i || typeof i !== 'object') return null;
  const before = i.old_string ?? i.old_str, after = i.new_string ?? i.new_str, written = i.content ?? i.file_text;
  if (i.todos) return html`<${Steps} items=${todoItems(i)}/>`;
  if (typeof before === 'string' && typeof after === 'string') return diff(before, after);
  if (typeof written === 'string' && (i.file_path || i.path)) return html`<pre>${written}</pre>`;
  if (typeof i.command === 'string') return html`<pre class="cmd">${i.command}</pre>`;
  if (typeof i.prompt === 'string') return html`<pre>${i.prompt}</pre>`;
  if (Object.keys(i).length) return html`<pre>${JSON.stringify(i, null, 2)}</pre>`;
  return null;
}
