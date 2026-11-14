#!/usr/bin/env node
// Chat bridge (runs as 'node', started by launch.sh when the session is a web chat): Copilot CLI
// through the GitHub Copilot SDK instead of its TUI, speaking the sandbox's chat events on stdio
// (src/services/chat/chat-bridge.mjs). The SDK drives the same `copilot` runtime the terminal would, over
// JSON-RPC, with its sessions, tools, skills and slash commands; only the screen is ours.
import { execFileSync } from 'node:child_process';

const lib = process.env.SANDBOX_LIB || '/usr/local/lib/sandbox';
const { emit, clip, sdk, commands, executable, questions, images } = await import(`${lib}/chat-bridge.mjs`);

emit({ type: 'hello', agent: 'copilot' });
const { CopilotClient, RuntimeConnection, approveAll } = await sdk('@github/copilot-sdk');

const cwd = process.cwd();
// The same session launch.sh names for the TUI, so a run resumes in either.
const name = `sandbox-${process.env.RUN_ID}`;
const briefing = process.env.AGENT_PROMPT || '';
const asking = questions();
const fail = text => emit({ type: 'notice', level: 'error', text });

// ---- what Copilot says, as chat events --------------------------------------------------------

let context = null, turnStarted = 0, model = null, replaying = false;
const json = v => { try { return typeof v === 'string' ? JSON.parse(v) : v; } catch { return v; } };

function on(event) {
  const d = event.data || {}, parent = d.parentToolCallId || undefined;
  switch (event.type) {
    case 'user.message':
      if (replaying) emit({ type: 'user', text: d.content });
      break;
    case 'assistant.message_delta':
      emit({ type: 'delta', id: d.messageId, kind: 'text', text: d.deltaContent, parent });
      break;
    case 'assistant.message':
      if (d.content) emit({ type: 'text', id: d.messageId, kind: 'text', text: d.content, parent });
      break;
    case 'assistant.reasoning_delta':
      emit({ type: 'delta', id: d.reasoningId, kind: 'thinking', text: d.deltaContent });
      break;
    case 'assistant.reasoning':
      if (d.content) emit({ type: 'text', id: d.reasoningId, kind: 'thinking', text: d.content });
      break;
    case 'tool.execution_start':
      emit({ type: 'tool', id: d.toolCallId, name: d.toolName, title: d.toolTitle, input: json(d.arguments) ?? {}, parent });
      break;
    case 'tool.execution_partial_result':
      emit({ type: 'result', id: d.toolCallId, output: clip(d.partialOutput), partial: true });
      break;
    case 'tool.execution_complete':
      emit({ type: 'result', id: d.toolCallId, error: !d.success,
             output: clip(d.success ? d.result?.detailedContent ?? d.result?.content ?? '' : d.error?.message ?? 'The tool failed.') });
      break;
    case 'assistant.turn_start':
      if (!replaying) {
        turnStarted ||= Date.now();
        emit({ type: 'status', state: 'working' });
      }
      break;
    case 'session.idle':
      if (!replaying) {
        asking.drop();
        emit({ type: 'turn', duration: turnStarted ? Date.now() - turnStarted : undefined, context });
        turnStarted = 0;
        emit({ type: 'status', state: 'idle' });
      }
      break;
    case 'session.usage_info':
      context = { used: d.currentTokens, max: d.tokenLimit };
      break;
    case 'session.model_change':
      emit({ type: 'model', id: model = d.newModel });
      break;
    case 'session.todos_changed':
      if (!replaying) todos();
      break;
    case 'session.error':
      if (!replaying) fail(d.message);
      break;
    case 'session.warning':
      if (!replaying) emit({ type: 'notice', level: 'warning', text: d.message });
      break;
    case 'session.compaction_start':
      if (!replaying) emit({ type: 'notice', level: 'info', text: 'Compacting the conversation…' });
      break;
    case 'session.compaction_complete':
      if (!replaying) emit({ type: 'notice', level: 'info', text: 'Conversation compacted.' });
      break;
    case 'commands.changed':
      if (!replaying) describe();
      break;
  }
}

async function todos() {
  try {
    const { rows } = await session.rpc.plan.readSqlTodos();
    emit({ type: 'todos', items: rows.map(r => ({ text: r.title || r.description || r.id,
      status: { in_progress: 'active', done: 'done', completed: 'done' }[r.status] || 'pending' })) });
  } catch {}
}

// ---- the session ------------------------------------------------------------------------------

const client = new CopilotClient({ connection: RuntimeConnection.forStdio({
  path: await executable(process.env.COPILOT_CLI_PATH || execFileSync('sh', ['-c', 'command -v copilot']).toString().trim()) }) });

const config = {
  streaming: true,
  workingDirectory: cwd,
  // The briefing is context, not a task: it belongs in the system prompt, where it costs no turn.
  ...(briefing && { systemMessage: { mode: 'append', content: briefing } }),
  // The sandbox is the boundary, not the prompts: as `copilot --allow-all`.
  onPermissionRequest: approveAll,
  onUserInputRequest: async request => {
    const choices = request.choices || [];
    const answers = await asking.ask([{ question: request.question, header: '', multi: false,
      freeform: request.allowFreeform !== false, options: choices.map(label => ({ label, description: '' })) }]);
    const answer = answers ? String(Object.values(answers)[0] ?? '') : 'The user dismissed the question without answering.';
    return { answer, wasFreeform: !choices.includes(answer) };
  },
  onExitPlanModeRequest: async request => {
    const answers = await asking.ask([{ question: request.summary || 'Go ahead with this plan?', header: 'Plan',
      plan: request.planContent, multi: false, freeform: true,
      options: (request.actions || []).map(label => ({ label, description: label === request.recommendedAction ? 'Recommended' : '' })) }]);
    const said = answers && String(Object.values(answers)[0] ?? '');
    if (said && (request.actions || []).includes(said)) return { approved: true, selectedAction: said };
    return { approved: false, ...(said && { feedback: said }) };
  },
  onEvent: on,
};

let session;
try {
  await client.start();
  if (process.env.RESUME === '1') {
    try {
      replaying = true;  // its history arrives through getEvents below, not as live events
      session = await client.resumeSession(name, config);
      for (const event of await session.getEvents()) on(event);
    } catch {
      session = null;  // no session by that name: the run starts a new conversation
    }
    replaying = false;
  }
  session ||= await client.createSession({ ...config, sessionId: name, name });
} catch (e) {
  fail(`Copilot CLI did not start: ${e.message}`);
  process.exit(1);
}

// What it can do, for the page's pickers: its commands and skills, its models.
async function describe() {
  const [status, models, list, current] = await Promise.all([
    client.getStatus().catch(() => ({})),
    client.listModels().catch(e => (fail(`Copilot's models could not be listed: ${e.message}`), [])),
    session.rpc.commands.list({ includeBuiltins: true, includeSkills: true }).catch(() => ({ commands: [] })),
    session.rpc.model.getCurrent().catch(() => ({})),
  ]);
  model = current.modelId || model;
  const info = models.find(m => m.id === model);
  emit({
    type: 'ready', agent: 'copilot', version: status.version, model,
    effort: current.reasoningEffort || info?.defaultReasoningEffort || '', efforts: info?.supportedReasoningEfforts || [],
    models: models.map(m => ({ id: m.id, name: m.name, description: m.billing?.multiplier != null ? `${m.billing.multiplier}× premium requests` : '',
                               efforts: m.supportedReasoningEfforts || [] })),
    commands: (list.commands || []).map(c => ({ name: c.name, description: c.description, hint: c.input?.hint || '' })),
  });
}
await describe();
emit({ type: 'status', state: 'idle' });

// A slash command is the runtime's to run; what it answers decides what happens next.
async function slash(text) {
  const [, command, input = ''] = /^\/(\S+)\s*([\s\S]*)$/.exec(text);
  const done = await session.rpc.commands.invoke({ name: command, ...(input && { input }) });
  if (done.kind === 'text') emit({ type: 'text', id: `c${Date.now()}`, kind: 'text', text: done.markdown ? done.text : '```\n' + done.text + '\n```' });
  else if (done.kind === 'agent-prompt') await session.send({ prompt: done.prompt, displayPrompt: done.displayPrompt });
  else if (done.kind === 'completed') emit({ type: 'notice', level: 'info', text: done.message || `/${command} done.` });
  else if (done.kind === 'set-model' && done.model) await session.setModel(done.model);
  else emit({ type: 'notice', level: 'warning', text: `/${command} needs Copilot's terminal interface.` });
  if (done.kind !== 'agent-prompt') emit({ type: 'status', state: 'idle' });
}

await commands(async c => {
  if (c.type === 'prompt' && typeof c.text === 'string') {
    emit({ type: 'status', state: 'working' });
    turnStarted ||= Date.now();
    try {
      if (/^\/\S/.test(c.text)) await slash(c.text);
      else {
        const attachments = images(c).map((p, i) => ({ type: 'blob', data: p.data, mimeType: p.type, displayName: `image ${i + 1}` }));
        await session.send({ prompt: c.text, ...(attachments.length && { attachments }) });
      }
    } catch (e) {
      fail(e.message);
      emit({ type: 'status', state: 'idle' });
    }
  } else if (c.type === 'interrupt') {
    asking.drop();
    await session.abort();
  } else if (c.type === 'answer') {
    asking.answer(c);
  } else if (c.type === 'model' && typeof c.id === 'string') {
    await session.setModel(c.id);
    emit({ type: 'model', id: model = c.id });
  } else if (c.type === 'effort' && typeof c.level === 'string') {
    await session.rpc.model.setReasoningEffort({ reasoningEffort: c.level });
    emit({ type: 'effort', level: c.level });
  }
});

await session.disconnect().catch(() => {});
await client.stop().catch(() => {});
process.exit(0);
