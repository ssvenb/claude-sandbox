#!/usr/bin/env node
// Chat bridge (runs as 'node', started by launch.sh when the session is a web chat): Claude Code
// through the Claude Agent SDK instead of its TUI, speaking the sandbox's chat events on stdio
// (src/services/chat/chat-bridge.mjs). The SDK drives the same `claude` binary the terminal would, with the
// same settings, hooks, MCP servers, skills and slash commands; only the screen is ours.
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';

const lib = process.env.SANDBOX_LIB || '/usr/local/lib/sandbox';
const { emit, clip, sdk, commands, executable, questions, images, attach } = await import(`${lib}/chat-bridge.mjs`);

process.removeAllListeners('warning');  // the SDK's note that bypass mode skips canUseTool for all but the two tools consult() handles
emit({ type: 'hello', agent: 'claude' });
const { query, getSessionMessages } = await sdk('@anthropic-ai/claude-agent-sdk');

const cwd = process.cwd();
// The same conversation id launch.sh gives the TUI, so a run resumes in either.
const session = `5a4db0c0-0000-4000-8000-000000${process.env.RUN_ID}`;
const home = process.env.CLAUDE_CONFIG_DIR || `${process.env.HOME}/.claude`;
const resumed = process.env.RESUME === '1' && existsSync(`${home}/projects/${cwd.replace(/[^A-Za-z0-9]/g, '-')}/${session}.jsonl`);
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];

// ---- what Claude says, as chat events --------------------------------------------------------

const blockText = content => typeof content === 'string' ? content
  : (content || []).map(b => b.type === 'text' ? b.text : b.type === 'image' ? '[image]' : '').join('\n');

function todos(input) {
  const items = (input?.todos || []).map(t => ({
    text: t.status === 'in_progress' && t.activeForm ? t.activeForm : t.content,
    status: { in_progress: 'active', completed: 'done' }[t.status] || 'pending' }));
  emit({ type: 'todos', items });
}

// A user-role message: the user's own text, or what tools returned.
function fromUser(message, parent, replay) {
  const content = message?.content;
  if (typeof content === 'string' || !Array.isArray(content)) {
    if (replay) userText(String(content ?? ''));
    return;
  }
  // The pictures pasted into it go with its first text, as they were sent; alone when it had none.
  let pictures = !replay || parent ? [] : images({ images: content.filter(b => b.type === 'image' && b.source?.type === 'base64')
    .map(b => ({ type: b.source.media_type, data: b.source.data })) });
  for (const block of content) {
    if (block.type === 'tool_result')
      emit({ type: 'result', id: block.tool_use_id, output: clip(blockText(block.content)), error: !!block.is_error });
    else if (block.type === 'text' && replay && !parent && userText(block.text, pictures))
      pictures = [];
  }
  if (pictures.length) emit({ type: 'user', text: '', images: pictures });
}

// Claude Code wraps what it adds to a transcript in tags; only a command and plain text are the user's.
// Says whether it was the user's, and so shown.
function userText(text, pictures = []) {
  const command = /<command-name>([^<]*)<\/command-name>(?:[\s\S]*<command-args>([^<]*)<\/command-args>)?/.exec(text);
  if (command) return emit({ type: 'user', text: `${command[1]} ${command[2] || ''}`.trim() });
  if (!text.trim() || /^\s*<[a-z-]+>/.test(text) || text.startsWith('Caveat:')) return false;
  return emit({ type: 'user', text, ...(pictures.length && { images: pictures }) });
}

function fromAssistant(message, parent, ids) {
  for (const block of message?.content || []) {
    if (block.type === 'text' && block.text)
      emit({ type: 'text', id: ids(block.type), kind: 'text', text: block.text, parent });
    else if (block.type === 'thinking' && block.thinking)
      emit({ type: 'text', id: ids(block.type), kind: 'thinking', text: block.thinking, parent });
    else if (block.type === 'tool_use') {
      emit({ type: 'tool', id: block.id, name: block.name, input: block.input, parent });
      if (block.name === 'TodoWrite' && !parent) todos(block.input);
    }
  }
}

// ---- a resumed run: its conversation so far ---------------------------------------------------

let n = 0;
const fresh = () => 'b' + ++n;
if (resumed) {
  try {
    for (const m of await getSessionMessages(session, { dir: cwd })) {
      if (m.type === 'user') fromUser(m.message, m.parent_tool_use_id, true);
      else if (m.type === 'assistant') fromAssistant(m.message, m.parent_tool_use_id || undefined, fresh);
    }
  } catch (e) {
    emit({ type: 'notice', level: 'warning', text: `The earlier conversation could not be read: ${e.message}` });
  }
}

// ---- the live session -------------------------------------------------------------------------

// Prompts wait in `inbox` until the SDK asks for the next one; it keeps asking while Claude works,
// so a prompt sent mid-turn is Claude Code's to queue, as in the terminal.
const inbox = [];
let wake = null, closed = false;
async function* prompts() {
  while (true) {
    while (inbox.length) yield inbox.shift();
    if (closed) return;
    await new Promise(resolve => { wake = resolve; });
  }
}
const push = (text, pictures) => {
  const content = !pictures.length ? text : [
    ...pictures.map(p => ({ type: 'image', source: { type: 'base64', media_type: p.type, data: p.data } })),
    ...(text ? [{ type: 'text', text }] : [])];
  inbox.push({ type: 'user', message: { role: 'user', content }, parent_tool_use_id: null });
  wake?.();
};

// A turn the API failed (overloaded, down, rate-limited) after Claude Code's own retries is tried
// again every couple of minutes until it answers; the user's next prompt or a stop ends that.
const RETRYABLE = ['server_error', 'rate_limit', 'unknown'];
const retryIn = (Number(process.env.API_RETRY_SECONDS) || 120) * 1000;
let failed = false, retry = null;
const giveUp = () => { clearTimeout(retry); retry = null; failed = false; };
function retryLater() {
  emit({ type: 'notice', level: 'warning', text: `The API is unreachable; trying again in ${Math.round(retryIn / 60000) || 1} minute(s).` });
  retry = setTimeout(() => {
    retry = null;
    emit({ type: 'status', state: 'working' });
    // In a tag, so a resumed run's replay does not show it as the user's.
    push('<api-retry>The API was unreachable and your last turn ended early; carry on where you left off.</api-retry>', []);
  }, retryIn);
}

const asking = questions();
const claude = await executable(process.env.CLAUDE_BIN || execFileSync('sh', ['-c', 'command -v claude']).toString().trim());
const briefing = process.env.AGENT_PROMPT || '';

async function consult(name, input, { signal }) {
  if (name === 'AskUserQuestion') {
    const answers = await asking.ask((input.questions || []).map(x => ({
      question: x.question, header: x.header, multi: !!x.multiSelect,
      options: (x.options || []).map(o => ({ label: o.label, description: o.description })) })), signal);
    if (!answers) return { behavior: 'deny', message: 'The user dismissed the question without answering.' };
    return { behavior: 'allow', updatedInput: { ...input, answers } };
  }
  if (name === 'ExitPlanMode') {
    const answers = await asking.ask([{ question: 'Go ahead with this plan?', header: 'Plan', plan: input.plan, multi: false,
      options: [{ label: 'Go ahead', description: 'Start working on it.' },
                { label: 'Keep planning', description: 'Stay in plan mode; say what to change.' }] }], signal);
    const said = answers && Object.values(answers)[0];
    if (said === 'Go ahead') return { behavior: 'allow', updatedInput: input };
    return { behavior: 'deny', message: said && said !== 'Keep planning' ? `The user wants changes to the plan: ${said}` : 'The user wants to keep planning.' };
  }
  return { behavior: 'allow', updatedInput: input };
}

const q = query({
  prompt: prompts(),
  options: {
    cwd,
    pathToClaudeCodeExecutable: claude,
    // The sandbox is the boundary, not the prompts: as `claude --dangerously-skip-permissions`.
    permissionMode: 'bypassPermissions',
    allowDangerouslySkipPermissions: true,
    includePartialMessages: true,
    agentProgressSummaries: true,
    effort: EFFORTS.includes(process.env.CLAUDE_EFFORT) ? process.env.CLAUDE_EFFORT : 'medium',
    systemPrompt: { type: 'preset', preset: 'claude_code', ...(briefing && { append: briefing }) },
    ...(resumed ? { resume: session } : { sessionId: session }),
    stderr: text => process.stderr.write(text),
    // Claude Code says when a turn is over (session_state_changed) only when asked to.
    env: { ...process.env, CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS: '1' },
    // Asked only for the two tools that exist to consult a person, which Claude Code holds for
    // an answer even with every permission granted: a question with choices, a plan to approve.
    canUseTool: consult,
  },
});

// What it can do, for the page's pickers: its commands and skills, its models.
let model = null;
async function describe(version) {
  const init = await q.initializationResult();
  emit({
    type: 'ready', agent: 'claude', version: version || init.claude_code_version, model,
    effort: EFFORTS.includes(process.env.CLAUDE_EFFORT) ? process.env.CLAUDE_EFFORT : 'medium', efforts: EFFORTS,
    account: init.account?.email || init.account?.organization || '',
    models: (init.models || []).map(m => ({ id: m.value, name: m.displayName, description: m.description })),
    commands: (init.commands || []).map(c => ({ name: c.name, description: c.description, hint: c.argumentHint || '' })),
  });
}
// The handshake answers before the first prompt, so the page has the pickers while Claude is idle.
let described = describe().catch(e => emit({ type: 'notice', level: 'error', text: `Claude Code did not start: ${e.message}` }));

const done = commands(async c => {
  if (c.type === 'prompt' && typeof c.text === 'string') {
    giveUp();
    emit({ type: 'status', state: 'working' });
    push(await attach(c), images(c));
  } else if (c.type === 'interrupt') {
    giveUp();
    asking.drop();
    await q.interrupt();
  } else if (c.type === 'answer') {
    asking.answer(c);
  } else if (c.type === 'task' && typeof c.id === 'string') {
    await q.stopTask(c.id);  // a background task, stopped: the list says so once it is gone
  } else if (c.type === 'model' && typeof c.id === 'string') {
    await q.setModel(c.id);
    emit({ type: 'model', id: c.id });
  } else if (c.type === 'effort' && EFFORTS.includes(c.level)) {
    await q.applyFlagSettings({ effortLevel: c.level });
    emit({ type: 'effort', level: c.level });
  }
}).then(() => { giveUp(); closed = true; wake?.(); });

// Streamed blocks are named after their place in their message, so the whole block that follows
// (one assistant message per block) lands on the text already on the page.
const streamed = new Map();  // message id → [{type, id, used}]
let streaming = null;        // the message id whose blocks are arriving
const blocks = new Map();    // index in that message → block id

function fromStream(event, parent) {
  if (event.type === 'message_start') {
    streaming = event.message.id;
    streamed.set(streaming, []);
    blocks.clear();
  } else if (event.type === 'content_block_start') {
    const b = event.content_block;
    if (b.type === 'tool_use') return emit({ type: 'tool', id: b.id, name: b.name, input: null, parent });
    if (b.type !== 'text' && b.type !== 'thinking') return;
    const id = fresh();
    blocks.set(event.index, id);
    streamed.get(streaming)?.push({ type: b.type, id });
  } else if (event.type === 'content_block_delta') {
    const id = blocks.get(event.index), d = event.delta;
    if (!id) return;
    if (d.type === 'text_delta') emit({ type: 'delta', id, kind: 'text', text: d.text, parent });
    else if (d.type === 'thinking_delta') emit({ type: 'delta', id, kind: 'thinking', text: d.thinking, parent });
  }
}
const idsOf = message => type => {
  const hit = (streamed.get(message?.id) || []).find(b => b.type === type && !b.used);
  if (!hit) return fresh();
  hit.used = true;
  return hit.id;
};

async function turnEnded(m) {
  const turn = { type: 'turn', cost: m.total_cost_usd, duration: m.duration_ms };
  if (m.subtype !== 'success') turn.error = (m.errors || []).join('\n') || m.subtype.replace(/_/g, ' ');
  else if (m.is_error) turn.error = m.result;
  try {
    const usage = await q.getContextUsage();
    turn.context = { used: usage.totalTokens, max: usage.maxTokens };
  } catch {}
  emit(turn);
  if (failed && !closed) retryLater();
  failed = false;
  if (!stateful) emit({ type: 'status', state: 'idle' });  // a Claude Code that does not say so itself
}

// What runs in the background (a shell command sent there, a subagent, a monitor), as Claude Code's
// own task list shows it: the whole set each time it changes, each task with its latest line.
const KINDS = { local_bash: 'shell', local_agent: 'agent', local_workflow: 'workflow', mcp_task: 'tool' };
let running = [];
const lines = new Map();  // task id → the last thing it said it was doing
function background() {
  for (const id of [...lines.keys()]) if (!running.some(t => t.task_id === id)) lines.delete(id);
  emit({ type: 'tasks', items: running.map(t => ({
    id: t.task_id, kind: KINDS[t.task_type] || String(t.task_type || 'task').replace(/^local_/, ''),
    text: t.description || t.subagent_type || '', ...(lines.has(t.task_id) && { note: lines.get(t.task_id) }) })) });
}

let code = 0, stateful = false;  // stateful: it reports its own state
try {
  for await (const m of q) {
    const parent = m.parent_tool_use_id || undefined;
    if (m.type === 'stream_event') fromStream(m.event, parent);
    else if (m.type === 'assistant') {
      fromAssistant(m.message, parent, idsOf(m.message));
      if (m.error) emit({ type: 'notice', level: 'error', text: `Claude could not answer (${String(m.error).replace(/_/g, ' ')}).` });
      if (m.error && !parent && RETRYABLE.includes(m.error)) failed = true;
    } else if (m.type === 'user') fromUser(m.message, parent, false);
    else if (m.type === 'result') await turnEnded(m);
    else if (m.type === 'tool_progress' && m.elapsed_time_seconds >= 5)
      emit({ type: 'progress', id: m.tool_use_id, seconds: Math.round(m.elapsed_time_seconds) });
    else if (m.type === 'system') {
      if (m.subtype === 'init') {
        if (m.model !== model) emit({ type: 'model', id: model = m.model });
        await described;
      } else if (m.subtype === 'session_state_changed') {
        stateful = true;
        emit({ type: 'status', state: { idle: 'idle', running: 'working', requires_action: 'question' }[m.state] });
      }
      else if (m.subtype === 'status' && m.status === 'compacting')
        emit({ type: 'notice', level: 'info', text: 'Compacting the conversation…' });
      else if (m.subtype === 'compact_boundary')
        emit({ type: 'notice', level: 'info', text: `Conversation compacted (${m.compact_metadata.trigger}), from ${m.compact_metadata.pre_tokens.toLocaleString('en')} tokens.` });
      else if (m.subtype === 'api_retry')
        emit({ type: 'notice', level: 'warning', text: `The API did not answer (${m.error_status ?? 'no response'}); retry ${m.attempt} of ${m.max_retries}.` });
      else if (m.subtype === 'local_command_output' && m.content)
        emit({ type: 'text', id: fresh(), kind: 'text', text: m.content });
      else if (m.subtype === 'informational' && m.content && m.level !== 'suggestion')
        emit({ type: 'notice', level: m.level === 'warning' ? 'warning' : 'info', text: m.content });
      else if (m.subtype === 'background_tasks_changed') {
        running = (m.tasks || []).filter(t => !t.ambient);  // housekeeping is not work
        background();
      } else if (m.subtype === 'task_progress' && m.summary) {
        if (m.tool_use_id) emit({ type: 'progress', id: m.tool_use_id, text: m.summary });
        if (running.some(t => t.task_id === m.task_id) && lines.get(m.task_id) !== m.summary) {
          lines.set(m.task_id, m.summary);
          background();
        }
      }
      else if (m.subtype === 'commands_changed')
        described = describe().catch(() => {});
    }
  }
} catch (e) {
  emit({ type: 'notice', level: 'error', text: `Claude Code stopped: ${e.message}` });
  code = 1;
}
emit({ type: 'status', state: 'idle' });
process.exit(code);
