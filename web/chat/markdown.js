// What the agent writes, as markdown built into elements: never as HTML, since it is the agent's
// text (and other people's, quoted). The parser builds a small tree of {tag, props, kids}, which
// becomes Preact elements at the end, so a list can still take a nested list into its last item.
import {html, h, useState} from '../lib/preact.js';

const SAFE = /^(https?:|mailto:)/i;
const el = (tag, props = {}, ...kids) => ({tag, props, kids});

function inline(text, into) {
  // code spans first, then links, bold, italics, strikethrough, bare URLs
  const re = /(`+)([\s\S]*?)\1|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*([^\n]+?)\*\*|(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])|~~([^\n]+?)~~|(https?:\/\/[^\s<>)\]]+[^\s<>)\].,;:!?'"])/g;
  let last = 0, m;
  const add = k => into.kids.push(k);
  while ((m = re.exec(text))) {
    if (m.index > last) add(text.slice(last, m.index));
    last = re.lastIndex;
    if (m[1]) add(el('code', {}, m[2].trim()));
    else if (m[3]) {
      if (SAFE.test(m[4])) add(inline(m[3], el('a', {href: m[4], target: '_blank', rel: 'noopener noreferrer'})));
      else add(m[0]);
    } else if (m[5]) add(inline(m[5], el('strong')));
    else if (m[6] || m[7]) add(inline(m[6] || m[7], el('em')));
    else if (m[8]) add(inline(m[8], el('s')));
    else add(el('a', {href: m[9], target: '_blank', rel: 'noopener noreferrer'}, m[9]));
  }
  if (last < text.length) add(text.slice(last));
  return into;
}

export async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {  // no Clipboard API off localhost over plain http: the old way, through a textarea
    const area = Object.assign(document.createElement('textarea'), {value: text});
    document.body.append(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
}
function CodeBlock({text, lang}) {
  const [copied, setCopied] = useState(false);
  const click = async () => { await copy(text); setCopied(true); setTimeout(() => setCopied(false), 1200); };
  return html`<div class="code">${lang ? html`<span class="lang">${lang}</span>` : ''}
    <button type="button" class="copy" onClick=${click}>${copied ? 'Copied' : 'Copy'}</button><pre><code>${text}</code></pre></div>`;
}

const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const cells = line => line.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map(c => c.trim().replaceAll('\\|', '|'));
function blocks(text, into) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  let i = 0;
  const para = [];
  const flush = () => { if (para.length) into.kids.push(inline(para.join('\n'), el('p'))); para.length = 0; };
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if ((m = /^\s*(```+|~~~+)\s*([\w+#.-]*)/.exec(line))) {  // fenced code, to its closing fence or the end
      flush();
      const body = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith(m[1]); i++) body.push(lines[i]);
      i++;
      into.kids.push({component: CodeBlock, props: {text: body.join('\n'), lang: m[2]}});
    } else if (!line.trim()) { flush(); i++; }
    else if ((m = /^(#{1,6})\s+(.*?)\s*#*$/.exec(line))) { flush(); into.kids.push(inline(m[2], el('h' + Math.min(4, m[1].length)))); i++; }
    else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); into.kids.push(el('hr')); i++; }
    else if (/^\s*>/.test(line)) {
      flush();
      const body = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) body.push(lines[i].replace(/^\s*>\s?/, ''));
      into.kids.push(blocks(body.join('\n'), el('blockquote')));
    } else if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      flush();
      const head = cells(line), body = [];
      for (i += 2; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++) body.push(cells(lines[i]));
      into.kids.push(el('div', {class: 'scroller'}, el('table', {},
        el('thead', {}, el('tr', {}, ...head.map(c => inline(c, el('th'))))),
        el('tbody', {}, ...body.map(row => el('tr', {}, ...head.map((_, k) => inline(row[k] || '', el('td')))))))));
    } else if ((m = ITEM.exec(line))) {
      flush();
      i = list(lines, i, m[1].length, into);
    } else { para.push(line); i++; }
  }
  flush();
  return into;
}
// A list: its items at one indent, whatever is indented further belongs to the item above it.
function list(lines, i, indent, into) {
  const ordered = /\d/.test(ITEM.exec(lines[i])[2]);
  const node = el(ordered ? 'ol' : 'ul', ordered ? {start: parseInt(ITEM.exec(lines[i])[2], 10)} : {});
  while (i < lines.length) {
    const m = ITEM.exec(lines[i]);
    if (!m || m[1].length < indent || (m[1].length === indent && /\d/.test(m[2]) !== ordered)) break;
    if (m[1].length > indent) { i = list(lines, i, m[1].length, node.kids[node.kids.length - 1] || node); continue; }
    const body = [m[3]];
    for (i++; i < lines.length && lines[i].trim() && !ITEM.test(lines[i]) && !/^\s*(```|~~~)/.test(lines[i]); i++) body.push(lines[i].trim());
    const task = /^\[([ xX])\]\s+/.exec(body[0]);
    const li = el('li');
    if (task) { li.kids.push(el('input', {type: 'checkbox', checked: task[1] !== ' ', disabled: true}), ' '); body[0] = body[0].slice(task[0].length); }
    node.kids.push(inline(body.join('\n'), li));
    while (i < lines.length && !lines[i].trim() && i + 1 < lines.length && ITEM.test(lines[i + 1]) && ITEM.exec(lines[i + 1])[1].length >= indent) i++;
  }
  into.kids.push(node);
  return i;
}

const toVNode = n => typeof n === 'string' ? n
  : n.component ? h(n.component, n.props) : h(n.tag, n.props, ...n.kids.map(toVNode));

// markdown(text, {caret}): the elements, the last one blinking a caret while the text still
// streams in (unless it is code or a table, which have no line to end).
export function markdown(text, {caret = false} = {}) {
  const kids = blocks(text, el('div')).kids;
  const last = kids[kids.length - 1];
  if (caret && last && !last.component && !(last.props.class === 'scroller'))
    last.props = {...last.props, class: ((last.props.class || '') + ' caret').trim()};
  return kids.map(toVNode);
}
