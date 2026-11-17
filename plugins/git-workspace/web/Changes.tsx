import { Icon } from '@ui/components/common/Icon';

/** A file a session's checkout changed since it left its main branch: added, modified or deleted,
 *  and its lines added and removed (null for a binary file), as host/changes.py lists it. */
export interface ChangedFile {
  path: string;
  status: string;
  added: number | null;
  removed: number | null;
}

const STATUS: Record<string, string> = { A: 'Added', M: 'Modified', D: 'Deleted' };

/** A folder of the tree: its folders and files, and the lines changed in all of them. */
interface Folder {
  name: string;
  path: string;
  folders: Map<string, Folder>;
  files: ChangedFile[];
  added: number;
  removed: number;
}

const folder = (name: string, path: string): Folder => ({ name, path, folders: new Map(), files: [], added: 0, removed: 0 });

/** The files as a tree of their folders, each folder counting the lines of all below it. A folder
 *  that holds only one folder is shown together with it ("web/src"), as editors do. */
function tree(files: ChangedFile[]): Folder {
  const root = folder('', '');
  for (const f of files) {
    const count = (d: Folder) => {
      d.added += f.added ?? 0;
      d.removed += f.removed ?? 0;
    };
    const parts = f.path.split('/');
    let at = root;
    count(at);
    parts.slice(0, -1).forEach((part, k) => {
      if (!at.folders.has(part)) at.folders.set(part, folder(part, parts.slice(0, k + 1).join('/')));
      at = at.folders.get(part)!;
      count(at);
    });
    at.files.push(f);
  }
  const squash = (d: Folder): Folder => {
    for (const [k, sub] of d.folders) {
      let s = sub;
      while (s.folders.size === 1 && !s.files.length) {
        const only = [...s.folders.values()][0]!;
        s = { ...only, name: `${s.name}/${only.name}` };
      }
      d.folders.set(k, squash(s));
    }
    return d;
  };
  return squash(root);
}

/** Lines added and removed, each only when there are some. */
function Lines({ added, removed }: { added: number; removed: number }) {
  return <span className="n">{added > 0 && <ins>+{added}</ins>} {removed > 0 && <del>−{removed}</del>}</span>;
}

/** A folder's content: its folders first, each closed to begin with and opened with a click, then its files. */
function Items({ of }: { of: Folder }) {
  const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);
  return (
    <ul>
      {[...of.folders.values()].sort(byName).map(d => (
        <li key={d.path} className="folder">
          <details>
            <summary title={d.path}>
              <Icon name="down" />
              <span className="name">{d.name}</span>
              <Lines added={d.added} removed={d.removed} />
            </summary>
            <Items of={d} />
          </details>
        </li>
      ))}
      {of.files.map(f => (
        <li key={f.path} className="file" title={f.path}>
          <span className={'st ' + f.status} title={STATUS[f.status] ?? f.status}>{f.status}</span>
          <span className="name">{f.path.slice(f.path.lastIndexOf('/') + 1)}</span>
          {f.added === null ? <span className="n">binary</span> : <Lines added={f.added} removed={f.removed ?? 0} />}
        </li>
      ))}
    </ul>
  );
}

/** What the session's checkout changed, as a tree of folders: beside the chat on a desk, from the
 *  header's button (a popover) on a smaller screen. */
export function Changes({ files }: { files: ChangedFile[] }) {
  const root = tree(files);
  return (
    <aside id="changes" className="side" popover="auto" aria-label="Changed files">
      <div className="head">
        <b>Changed files</b>
        {files.length > 0 && <Lines added={root.added} removed={root.removed} />}
      </div>
      {files.length ? <div className="tree"><Items of={root} /></div> : <p className="none">No files changed yet.</p>}
    </aside>
  );
}
