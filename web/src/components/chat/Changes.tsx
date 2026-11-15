import type { ChangedFile } from '../../api/types';

const STATUS: Record<string, string> = { A: 'Added', M: 'Modified', D: 'Deleted' };

/** Lines added and removed, each only when there are some. */
function Lines({ added, removed }: { added: number; removed: number }) {
  return <span className="n">{added > 0 && <ins>+{added}</ins>} {removed > 0 && <del>−{removed}</del>}</span>;
}

/** What the session's checkout changed, a file a line: beside the chat on a desk, from the
 *  header's button (a popover) on a smaller screen. */
export function Changes({ files }: { files: ChangedFile[] }) {
  const sum = (k: 'added' | 'removed') => files.reduce((n, f) => n + (f[k] ?? 0), 0);
  return (
    <aside id="changes" popover="auto" aria-label="Changed files">
      <div className="head">
        <b>Changed files</b>
        {files.length > 0 && <Lines added={sum('added')} removed={sum('removed')} />}
      </div>
      {files.length ? (
        <ul>
          {files.map(f => {
            const cut = f.path.lastIndexOf('/') + 1;
            return (
              <li key={f.path}>
                <span className={'st ' + f.status} title={STATUS[f.status] ?? f.status}>{f.status}</span>
                <span className="path" title={f.path}>
                  <b>{f.path.slice(cut)}</b>
                  {cut > 0 && <span className="dir"><bdi>{f.path.slice(0, cut - 1)}</bdi></span>}
                </span>
                {f.added === null ? <span className="n">binary</span> : <Lines added={f.added} removed={f.removed ?? 0} />}
              </li>
            );
          })}
        </ul>
      ) : <p className="none">No files changed yet.</p>}
    </aside>
  );
}
