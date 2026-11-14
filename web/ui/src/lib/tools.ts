// A tool call, in a few words: what it is called and what it was about.
import type { PlanItem, ToolInput } from '../api/events';

const VERBS: Record<string, string> = {
  bash: 'Run', shell: 'Run', powershell: 'Run', read: 'Read', view: 'Read', edit: 'Edit', multiedit: 'Edit', str_replace: 'Edit',
  str_replace_editor: 'Edit', write: 'Write', create: 'Write', grep: 'Search', glob: 'Find files', ls: 'List', webfetch: 'Fetch',
  web_fetch: 'Fetch', fetch: 'Fetch', websearch: 'Search the web', web_search: 'Search the web', task: 'Subagent', agent: 'Subagent',
  todowrite: 'Plan', update_todo: 'Plan', skill: 'Skill', askuserquestion: 'Ask', ask_user: 'Ask', exitplanmode: 'Propose plan',
  notebookedit: 'Edit notebook', toolsearch: 'Find tools', report_intent: 'Intent',
};

export function verb(tool: { name?: string; title?: string }): string {
  if (tool.title) return tool.title;
  const mcp = /^mcp__(.+?)__(.+)$/.exec(tool.name ?? '');
  if (mcp) return `${mcp[1]}: ${mcp[2]!.replaceAll('_', ' ')}`;
  return VERBS[String(tool.name).toLowerCase()] ?? String(tool.name);
}

const TELLING = ['command', 'file_path', 'notebook_path', 'pattern', 'query', 'url', 'path', 'skill', 'description', 'intent', 'prompt'];
const firstLine = (text: string): string => text.trim().split('\n')[0] ?? '';

/** What a call was about: the most telling of what went in, on one line. */
export function what(input: ToolInput | undefined): string {
  if (!input || typeof input !== 'object') return '';
  for (const key of TELLING) {
    const value = input[key];
    if (typeof value === 'string' && value.trim()) return firstLine(value) + (key === 'pattern' && input.path ? `  in ${String(input.path)}` : '');
  }
  const first = Object.values(input).find((v): v is string => typeof v === 'string' && !!v.trim());
  return first ? firstLine(first) : '';
}

interface Todo {
  content?: string;
  title?: string;
  status?: string;
}
const TODO_STATUS: Record<string, PlanItem['status']> = { in_progress: 'active', completed: 'done', done: 'done' };

/** A todo tool's input, as the steps of a plan. */
export const todoItems = (input: ToolInput): PlanItem[] =>
  ((input.todos as Todo[] | undefined) ?? []).map(t => ({ text: t.content || t.title || '', status: TODO_STATUS[t.status ?? ''] ?? 'pending' }));
