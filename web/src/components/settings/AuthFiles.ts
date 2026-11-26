import { createContext, useContext } from 'react';
import type { AuthFileInfo } from '../../api/types';

/** Which of your authentications' files are in place, each uploaded through the form. */
export interface AuthFiles {
  /** What the entry's file is, or null when there is none. */
  get: (name: string, field: string) => AuthFileInfo | null;
  /** A file was uploaded (what it is), or deleted (null). */
  put: (name: string, field: string, info: AuthFileInfo | null) => void;
}

export const AuthFilesContext = createContext<AuthFiles | null>(null);

export function useAuthFiles(): AuthFiles {
  const files = useContext(AuthFilesContext);
  if (!files) throw new Error('not inside your authentications');
  return files;
}

/** A name a file can be kept under (auth.NAME). */
export const fileName = (name: string) => /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(name);
