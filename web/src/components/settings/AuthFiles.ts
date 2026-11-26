import { createContext, useContext } from 'react';

/** Which of your authentications' files are in place, each uploaded through the form. */
export interface AuthFiles {
  has: (name: string, field: string) => boolean;
  /** A file was uploaded, or deleted. */
  put: (name: string, field: string, exists: boolean) => void;
}

export const AuthFilesContext = createContext<AuthFiles | null>(null);

export function useAuthFiles(): AuthFiles {
  const files = useContext(AuthFilesContext);
  if (!files) throw new Error('not inside your authentications');
  return files;
}

/** A name a file can be kept under (auth.NAME). */
export const fileName = (name: string) => /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(name);
