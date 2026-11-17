import { useEffect, useRef } from 'react';
import { saveAuth, saveConfig } from '../../api/sessions';
import type { AuthConfig, ProjectConfig } from '../../api/types';
import { projectName } from '../../lib/session';
import { AuthCards } from './AuthCards';
import { SettingsCards } from './SettingsCards';
import { SettingsForm } from './SettingsForm';

/** The settings that are open, with what the server said about them: a project's, or the
 *  sandbox's own (your authentications, and the projects). */
export type OpenSettings = {
  /** Goes up with every opening: the form starts anew from the file. */
  opening: number;
} & ({ project: string; declared: ProjectConfig } | { auth: AuthConfig; projects: string[] });

interface Props {
  settings: OpenSettings | null;
  onClose: () => void;
  /** After a file was written: the project's, or (with none) your authentications. */
  onSaved: (project?: string) => void;
}

/** The page's dialog: open over it while settings are being edited. */
export function SettingsDialog({ settings, onClose, onSaved }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const opening = settings?.opening;
  useEffect(() => {
    const el = dialog.current!;
    if (opening === undefined) el.close();
    else if (!el.open) {
      el.showModal();
      el.querySelector<HTMLInputElement>('input[type=search]')?.focus();
    }
  }, [opening]);
  return (
    <dialog id="config" ref={dialog} onClose={onClose}>
      {settings && ('project' in settings ? (
        <SettingsForm key={settings.opening} title={projectName(settings.project) + ' settings'}
          file={settings.declared.file} exists={settings.declared.exists} config={settings.declared.config}
          save={c => saveConfig(settings.project, c)} cards={(draft, query) => <SettingsCards declared={settings.declared} draft={draft} query={query} />}
          onClose={onClose} onSaved={() => onSaved(settings.project)} />
      ) : (
        <SettingsForm key={settings.opening} title="Sandbox settings"
          file={settings.auth.file} exists={settings.auth.exists} config={settings.auth.config} save={saveAuth}
          cards={(draft, query) => <AuthCards auth={settings.auth} projects={settings.projects} draft={draft} query={query} onChanged={() => onSaved()} />}
          onClose={onClose} onSaved={() => onSaved()} />
      ))}
    </dialog>
  );
}
