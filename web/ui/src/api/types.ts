// What web/server.py says: its sessions, what a project's plugins describe, a project's settings.

export type SessionStatus = 'starting' | 'working' | 'idle' | 'question';
export type SessionKind = 'run' | 'resume' | 'shell';

/** A picture pasted into a message: its media type and its bytes in base64. */
export interface Picture {
  type: string;
  data: string;
}

export type ItemStatus = 'ok' | 'fail' | 'pending' | 'done';

/** Something a plugin lists for a project or ties to a run: a pull request, an issue, a published port. */
export interface Item {
  url: string;
  title: string;
  ref?: string;
  note?: string;
  branch?: string;
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

export type SettingType = 'string' | 'path' | 'boolean' | 'enum' | 'integer' | 'text' | 'json' | 'list' | 'map' | 'object';

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
  secret?: boolean;
  monospace?: boolean;
  pattern?: string;
  min?: number;
  max?: number;
  choices?: (string | number)[];
  items?: SettingSpec;
  fields?: SettingSpec[];
  title?: string;
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

export interface ProjectConfig {
  file: string;
  exists: boolean;
  config: JsonObject;
  kernel: { description?: string; settings: SettingSpec[] };
  agents: SettingsPart[];
  plugins: PluginManifest[];
}
