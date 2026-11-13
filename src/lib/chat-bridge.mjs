// What every agent's chat bridge (agents/<name>/chat.mjs) shares: the wire between the bridge, in
// the container, and web/server.py on the host. It is the container's own stdio (`docker run -i`):
//
//   bridge → host   one JSON object per line on stdout, each line led by an ASCII record separator
//                   (RS, 0x1e). Anything else on stdout is boot output, which the host shows as such.
//   host → bridge   one JSON object per line on stdin.
//
// The events are the same for every agent, so the page that draws them knows none of them:
//
//   hello      {agent}                           the bridge runs; its SDK is starting the agent
//   ready      {agent, version, model, models: [{id, name, description}],
//               commands: [{name, description, hint}], effort, efforts: [..]}
//   user       {text, images: [{type, data}]}    a message of the user's, replayed from a resumed run
//   text       {id, text, kind, parent}          a whole block; kind is "text" or "thinking"
//   delta      {id, text, kind, parent}          more of that block, as it streams
//   tool       {id, name, input, parent}         a tool call (sent again once its input is complete)
//   result     {id, output, error}               what the tool returned
//   status     {state}                           working, idle or question
//   turn       {cost, duration, context: {used, max}, error}   a turn ended
//   ask        {id, questions: [{question, header, multi, options: [{label, description}]}]}
//   asked      {id}                              that question is settled
//   todos      {items: [{text, status}]}         the agent's plan; status is pending, active or done
//   tasks      {items: [{id, kind, text, note}]} what runs in the background right now, all of it
//                                                each time (a bridge whose agent has none sends none)
//   model      {id}, effort {level}              what the next turn runs on
//   notice     {level, text}                     info, warning or error
//
// and the commands: prompt {text, images: [{type, data}]}, interrupt {}, answer {id, answers |
// cancel}, model {id}, effort {level}, task {id} (stop that background task). An image is its
// media type and its bytes in base64.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline';

export const emit = event => process.stdout.write('\x1e' + JSON.stringify(event) + '\n');

// Tool output can be megabytes (a log, a minified file): the page gets its head and its tail.
export function clip(text, max = 16000) {
  text = String(text ?? '');
  if (text.length <= max) return text;
  const half = max >> 1;
  return `${text.slice(0, half)}\n… ${text.length - max} characters left out …\n${text.slice(-half)}`;
}

// The pictures pasted into a prompt: only what is one, by its type and its bytes.
export const images = command => (Array.isArray(command.images) ? command.images : []).filter(p =>
  p && /^image\/(png|jpeg|gif|webp)$/.test(p.type) && typeof p.data === 'string' && /^[A-Za-z0-9+/]+=*$/.test(p.data))
  .map(p => ({ type: p.type, data: p.data }));

// The agent's SDK, from where its install.sh put it (outside any project, so not on a resolve path).
export async function sdk(name) {
  const dir = process.env.AGENT_SDK_DIR || '/opt/agent-sdk';
  const found = createRequire(dir + '/').resolve(name);
  return import(pathToFileURL(found).href);
}

// Calls `handle` with each command the host sends; resolves when the host hangs up.
export function commands(handle) {
  return new Promise(resolve => {
    const lines = createInterface({ input: process.stdin });
    lines.on('line', line => {
      let command;
      try { command = JSON.parse(line); } catch { return; }
      if (command && typeof command === 'object')
        Promise.resolve().then(() => handle(command)).catch(e => emit({ type: 'notice', level: 'error', text: String(e?.message || e) }));
    });
    lines.on('close', resolve);
  });
}

// $AGENT_LAUNCH_CMD may be a wrapper with arguments; an SDK wants one executable to start.
export async function executable(fallback) {
  const cmd = (process.env.AGENT_LAUNCH_CMD || '').trim();
  if (!cmd) return fallback;
  if (!/\s/.test(cmd)) return cmd;
  const { mkdtempSync, writeFileSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const path = mkdtempSync(tmpdir() + '/agent-launch-') + '/agent';
  writeFileSync(path, `#!/bin/sh\nexec ${cmd} "$@"\n`, { mode: 0o700 });
  return path;
}

// Questions wait here until the host answers them (or the agent stops waiting).
export function questions() {
  const open = new Map();
  let next = 0;
  return {
    ask(questions, signal) {
      const id = 'q' + ++next;
      emit({ type: 'ask', id, questions });
      emit({ type: 'status', state: 'question' });
      return new Promise(resolve => {
        const settle = answer => {
          if (!open.delete(id)) return;
          emit({ type: 'asked', id });
          emit({ type: 'status', state: 'working' });
          resolve(answer);
        };
        open.set(id, settle);
        signal?.addEventListener('abort', () => settle(null));
      });
    },
    answer(command) {
      open.get(command.id)?.(command.cancel ? null : command.answers || {});
    },
    drop() {
      for (const settle of [...open.values()]) settle(null);
    },
  };
}
