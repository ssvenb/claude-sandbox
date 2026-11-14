import { useMemo } from 'react';
import { diffRows } from '../../lib/diff';

/** An edit: the lines that left and the lines that came. */
export function Diff({ before, after }: { before: string; after: string }) {
  const rows = useMemo(() => diffRows(before, after), [before, after]);
  return (
    <pre className="diff">
      {rows.map((row, k) => (
        <span key={k} className={row.kind}>{row.text || ' '}</span>
      ))}
    </pre>
  );
}
