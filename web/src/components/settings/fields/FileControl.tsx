import { useRef, useState } from 'react';
import { message } from '../../../api/client';
import { putAuthFile } from '../../../api/sessions';
import { BusyButton } from '../../common/BusyButton';
import { fileName, filePath, useAuthFiles } from '../AuthFiles';
import type { ControlProps } from '../Control';

/** A file of an authentication: not a path to pick, its one place under the entry's name. Uploaded
 *  there at once (or put there by hand), it is the one the entry uses. */
export function FileControl({ spec, name, id, parent }: ControlProps) {
  const files = useAuthFiles();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  const entry = String(parent?.().name ?? '');
  const field = spec.key!;
  const named = fileName(entry);
  const here = named && files.has(entry, field);
  const put = async (file: File | null) => {
    setError('');
    try {
      const { exists } = await putAuthFile(entry, field, file);
      files.put(entry, field, exists);
    } catch (e) {
      setError(message(e));
    }
  };
  return (
    <div className="file" id={id}>
      {named ? <code className="mono" title={filePath(files.dir, entry, field)}>{filePath(files.dir, entry, field)}</code>
        : <span className="muted">{entry ? "A name of letters, digits, '_', '-' and '.' first" : 'Name the entry first'}</span>}
      <span className={'state ' + (here ? 'ok' : 'none')}>{here ? 'in place' : 'not there'}</span>
      <input ref={input} type="file" name={name} hidden aria-label={'Upload ' + (spec.label || field)}
        onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void put(f); }} />
      <button type="button" className="upload" disabled={!named} onClick={() => input.current?.click()}>{here ? 'Replace…' : 'Upload…'}</button>
      {here && <BusyButton className="remove" title="Delete the file" aria-label={'Delete ' + (spec.label || field)}
        onClick={() => confirm(`Delete ${filePath(files.dir, entry, field)}?`) && put(null)}>✕</BusyButton>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
