import { createContext, useContext } from 'react';

/** Where your authentications' files are, and which are in place: each entry's at its one place,
 *  uploaded through the form or put there by hand. */
export interface AuthFiles {
  dir: string;
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

/** The place of the entry `name`'s file `field`: privateKeyFile is <dir>/<name>/privateKey. */
export const filePath = (dir: string, name: string, field: string) => `${dir}/${name}/${field.replace(/File$/, '')}`;
