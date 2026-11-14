import { useEffect, useRef } from 'react';
import type { ProjectConfig } from '../../api/types';
import { SettingsForm } from './SettingsForm';

/** A project whose settings are open, with what the server said about them. */
export interface OpenSettings {
  project: string;
  declared: ProjectConfig;
  /** Goes up with every opening: the form starts anew from the file. */
  opening: number;
}

interface Props {
  settings: OpenSettings | null;
  onClose: () => void;
  onSaved: (project: string) => void;
}

/** The page's dialog: open over it while a project's settings are being edited. */
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
      {settings && (
        <SettingsForm key={settings.opening} project={settings.project} declared={settings.declared}
          onClose={onClose} onSaved={() => onSaved(settings.project)} />
      )}
    </dialog>
  );
}
