// What src/server/server.py says: its sessions, what a project's plugins describe, a project's settings.

export type SessionStatus = 'starting' | 'working' | 'idle' | 'question';
export type SessionKind = 'run' | 'resume';

/** A picture pasted into a message: its media type and its bytes in base64. Held in the tray, it may
 *  be any file attached by hand, then with its name: what is not a picture goes as a file. */
export interface Picture {
  type: string;
  data: string;
  name?: string;
}

/** A file attached to a message that is not a picture: saved in the sandbox for the agent to read. */
export interface Upload {
  name: string;
  data: string;
}

export type ItemStatus = 'ok' | 'fail' | 'pending' | 'done';

/** Something a plugin lists for a project or ties to a run: a pull request, an issue, a published port. */
export interface Item {
  url: string;
  title: string;
  ref?: string;
  /** The port a running session serves it on: a live server (dev-server's demo). */
  port?: number;
  /** It answers yet (the server asks it): a demo is published before its server listens. */
  up?: boolean;
  note?: string;
  status?: ItemStatus;
  status_text?: string;
  run_id?: string | null;
  section?: string;
  start?: { label: string; task: string };
}

export interface Session {
  id: string;
  project: string;
  kind: SessionKind;
  run_id: string | null;
  started: number;
  exit: number | null;
  ui?: 'chat' | 'terminal';
  status: SessionStatus | null;
  workspace?: string | null;
  /** Its project's enabled plugins. */
  plugins?: string[];
  items?: Item[];
  title?: string;
  activity?: string;
  said?: string;
  waiting?: number;
}

export interface AppState {
  projects: string[];
  projects_file?: string;
  sessions: Session[];
}

export interface ItemList {
  title: string;
  items: Item[];
}

/** What a project's plugins say about it (`run.sh --web`). */
export interface ProjectInfo {
  lists: ItemList[];
  notes: string[];
  agent?: string;
  run_items?: Item[];
  session_items?: Item[];
}

/** What deleting a session offers to tidy up with it, a yes/no each. */
export interface Offer {
  url: string;
  ask: string;
  ref?: string;
  title?: string;
}

export interface NewSession {
  project: string;
  kind: SessionKind;
  run_id?: string;
  task?: string;
  images?: Picture[];
}

// ---- settings -------------------------------------------------------------------------------

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export type SettingType = 'string' | 'path' | 'boolean' | 'enum' | 'integer' | 'text' | 'json' | 'list' | 'map' | 'object' | 'file';

/** One setting, as a manifest declares it: its type picks its control. */
export interface SettingSpec {
  type?: SettingType;
  key?: string;
  env?: string;
  label?: string;
  description?: string;
  default?: Json;
  placeholder?: string;
  required?: boolean;
  monospace?: boolean;
  pattern?: string;
  min?: number;
  max?: number;
  choices?: (string | number)[];
  items?: SettingSpec;
  fields?: SettingSpec[];
  title?: string;
  /** A list of objects shown in groups by this field's value, + Add and new entries on top. */
  groupBy?: string;
  when?: Record<string, Json[]>;
}

export interface SettingsPart {
  name: string;
  description?: string;
  settings: SettingSpec[];
}

export interface PluginManifest extends SettingsPart {
  defaultEnabled: boolean;
  requiredAgent?: string | null;
  requiredEnv?: string[];
}

/** What a file of an authentication is, told without a byte of it. */
export interface AuthFileInfo {
  /** "RSA private key", "OpenSSH private key", "3 hosts", "Not a PEM key"… */
  kind: string;
  size: number;
  /** When it was put there, in seconds. */
  modified: number;
}

/** Your authentications' file, and what each type of entry holds. */
export interface AuthConfig {
  file: string;
  exists: boolean;
  config: JsonObject;
  /** The files in place (each at its fixed place, never shown): entry name → field → what it is. */
  files: Record<string, Record<string, AuthFileInfo>>;
  types: Record<string, { required: string[]; optional: string[] }>;
}

export interface ProjectConfig {
  file: string;
  exists: boolean;
  config: JsonObject;
  kernel: { description?: string; settings: SettingSpec[] };
  agents: SettingsPart[];
  plugins: PluginManifest[];
}
