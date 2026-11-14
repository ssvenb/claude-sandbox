// An edit as a diff: lines that left and lines that came, in order, with a little of what stayed
// around them. The comparing is jsdiff's.
import { structuredPatch } from 'diff';

export interface DiffRow {
  kind: 'same' | 'add' | 'del' | 'gap';
  text: string;
}

const CONTEXT = 2;
const KINDS: Record<string, DiffRow['kind']> = { '+': 'add', '-': 'del', ' ': 'same' };
const lines = (text: string): string[] => text.replace(/\n$/, '').split('\n');

export function diffRows(before: string, after: string): DiffRow[] {
  const a = lines(before), b = lines(after);
  // Too far apart to be worth comparing: all that left, then all that came.
  const patch = structuredPatch('', '', a.join('\n'), b.join('\n'), '', '', { context: CONTEXT, maxEditLength: 5000 });
  if (!patch) return [...a.map(text => ({ kind: 'del' as const, text })), ...b.map(text => ({ kind: 'add' as const, text }))];
  const rows: DiffRow[] = [];
  const gap = () => rows.push({ kind: 'gap', text: '  ⋯' });
  let reached = 1;  // the first old line not yet shown
  for (const hunk of patch.hunks) {
    const start = hunk.oldLines ? hunk.oldStart : hunk.oldStart + 1;
    if (start > reached) gap();
    for (const line of hunk.lines) {
      const kind = KINDS[line[0] ?? ''];
      if (kind) rows.push({ kind, text: line.slice(1) });  // not the "\ No newline at end of file" notes
    }
    reached = start + hunk.oldLines;
  }
  if (rows.length && reached <= a.length) gap();
  return rows;
}
