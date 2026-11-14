import { memo } from 'react';
import type { ToolInput as Input } from '../../api/events';
import { todoItems } from '../../lib/tools';
import { Diff } from './Diff';
import { Steps } from './Steps';

/** What went in to a tool call: an edit as a diff, a file written, a command behind its prompt,
 *  a subagent's prompt, a plan as its steps, else the input itself. Drawn again only for a new
 *  input (a diff can be costly). */
export const ToolInput = memo(function ToolInput({ input }: { input?: Input }) {
  if (!input || typeof input !== 'object') return null;
  const before = input.old_string ?? input.old_str, after = input.new_string ?? input.new_str;
  const written = input.content ?? input.file_text;
  if (input.todos) return <Steps items={todoItems(input)} />;
  if (typeof before === 'string' && typeof after === 'string') return <Diff before={before} after={after} />;
  if (typeof written === 'string' && (input.file_path || input.path)) return <pre>{written}</pre>;
  if (typeof input.command === 'string') return <pre className="cmd">{input.command}</pre>;
  if (typeof input.prompt === 'string') return <pre>{input.prompt}</pre>;
  if (Object.keys(input).length) return <pre>{JSON.stringify(input, null, 2)}</pre>;
  return null;
});
