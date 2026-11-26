import { useRef, useState, type DragEvent } from 'react';
import { message } from '../../../api/client';
import { putAuthFile } from '../../../api/sessions';
import type { AuthFileInfo } from '../../../api/types';
import { BusyButton } from '../../common/BusyButton';
import { Icon } from '../../common/Icon';
import { fileName, useAuthFiles } from '../AuthFiles';
import type { ControlProps } from '../Control';

/** What a field's file is called in a sentence, and what it may be. */
const WHAT: Record<string, { noun: string; hint: string; icon: 'key' | 'hosts' }> = {
  privateKeyFile: { noun: 'the private key', hint: 'PEM or OpenSSH key · up to 1 MiB', icon: 'key' },
  credentialFile: { noun: 'the credentials JSON', hint: 'Google credentials JSON · up to 1 MiB', icon: 'key' },
  knownHostsFile: { noun: 'a known_hosts file', hint: 'One host per line · up to 1 MiB', icon: 'hosts' },
};

const size = (n: number) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KiB`);

const when = (seconds: number) => {
  const d = new Date(seconds * 1000), now = new Date();
  if (d.toDateString() === now.toDateString())
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', ...(d.getFullYear() !== now.getFullYear() && { year: 'numeric' }) });
};

/** A file of an authentication: no path to pick or to see, and no text drawn. With none there, a
 *  place to drop one or tap to browse; with one there, a key with a tick (what it is on hover), to
 *  replace or delete.
 *  Uploaded at once, it is the one the entry uses. */
export function FileControl({ spec, name, id, parent }: ControlProps) {
  const files = useAuthFiles();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [fresh, setFresh] = useState(false);
  const entry = String(parent?.().name ?? '');
  const field = spec.key!;
  const label = spec.label || field;
  const what = WHAT[field] ?? { noun: 'the file', hint: 'Up to 1 MiB', icon: 'key' as const };
  const named = fileName(entry);
  const info: AuthFileInfo | null = named ? files.get(entry, field) : null;
  // No text is drawn: what it is, or what it takes, is told on hover and to a screen reader.
  const described = !info ? "" : `${info.kind} · ${size(info.size)} · uploaded ${when(info.modified)}`;
  const hint = !named ? (entry ? "Give the entry a name of letters, digits, '_', '-' and '.' first" : 'Name the entry first')
    : `Upload ${what.noun} (${what.hint}): drop it here or browse`;

  const put = async (file: File | null) => {
    setError('');
    setBusy(!!file);
    try {
      const { file: got } = await putAuthFile(entry, field, file);
      files.put(entry, field, got);
      setFresh(!!got);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  const browse = () => input.current?.click();
  const drop = {
    onDragOver: (e: DragEvent) => {
      if (!named || busy || !e.dataTransfer.types.includes('Files')) return;
      e.preventDefault();
      setOver(true);
    },
    onDragLeave: (e: DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
    },
    onDrop: (e: DragEvent) => {
      setOver(false);
      const f = e.dataTransfer.files[0];
      if (!named || busy || !f) return;
      e.preventDefault();
      void put(f);
    },
  };

  return (
    <div className="file" id={id}>
      <input ref={input} type="file" name={name} hidden aria-label={'Upload ' + label}
        onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void put(f); }} />
      {info ? (
        <div className={'filecard' + (over ? ' over' : '') + (busy ? ' loading' : '') + (fresh ? ' fresh' : '')} {...drop}
          onAnimationEnd={() => setFresh(false)}>
          <span className="tile" role="img" aria-label={described}
            title={described}>
            <Icon name={what.icon} />
            <span className="tick"><Icon name="check" /></span>
          </span>
          <span className="acts">
            <button type="button" className="replace icon" disabled={busy} onClick={browse}
              title={'Replace ' + label} aria-label={'Replace ' + label}>
              <Icon name="upload" />
            </button>
            <BusyButton className="remove icon" title={'Delete ' + label} aria-label={'Delete ' + label}
              onClick={() => confirm(`Delete the ${label} of ${entry}?`) && put(null)}>
              <Icon name="trash" />
            </BusyButton>
          </span>
        </div>
      ) : (
        <button type="button" className={'dropzone' + (over ? ' over' : '') + (busy ? ' loading' : '')} disabled={!named || busy}
          onClick={browse} {...drop} title={hint} aria-label={hint}>
          <span className="tile"><Icon name="upload" /></span>
        </button>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
