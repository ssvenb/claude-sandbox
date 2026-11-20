// The server's API, call by call.
import { api, post } from './client';
import type { Answers } from './events';
import type { AppState, AuthConfig, JsonObject, NewSession, Offer, Picture, ProjectConfig, Upload, ProjectInfo, Session } from './types';

const session = (id: string) => `/api/sessions/${id}`;
const project = (path: string) => 'project=' + encodeURIComponent(path);

export const getState = () => api<AppState>('/api/state');
export const getProject = (path: string) => api<ProjectInfo>('/api/project?' + project(path));

export const startSession = (what: NewSession) => post<Session>('/api/sessions', what);
export const stopSession = (id: string) => post(session(id) + '/stop');
export const getOffers = (id: string) => api<{ offers: Offer[] }>(session(id) + '/offers');
export const deleteSession = (id: string, tidy: string[]) => post<{ failed?: string[] }>(session(id) + '/delete', { tidy });

// A chat.
export const eventsUrl = (id: string) => session(id) + '/events';
export const sendPrompt = (id: string, text: string, images?: Picture[], files?: Upload[]) =>
  post(session(id) + '/prompt', { text, images, files });
export const sendAnswer = (id: string, ask: string, reply: { answers: Answers } | { cancel: true }) =>
  post(session(id) + '/answer', { id: ask, ...reply });
/** Stops the agent's turn: the conversation's, or with `side` that side chat's. */
export const interruptSession = (id: string, side?: string) => post(session(id) + '/interrupt', side ? { side } : undefined);
/** Asks in a side chat (a new one without `side`); answers with the chat's id. */
export const askSide = (id: string, side: string | null, text: string) =>
  post<{ id: string }>(session(id) + '/side', { text, ...(side && { id: side }) }).then(r => r.id);
export const closeSide = (id: string, side: string) => post(session(id) + '/side', { id: side, close: true });
export const chooseModel = (id: string, model: string) => post(session(id) + '/model', { id: model });
export const chooseEffort = (id: string, level: string) => post(session(id) + '/effort', { level });
export const stopTask = (id: string, task: string) => post(session(id) + '/task', { id: task });
/** What a plugin's command (web_command) says about the session's run: null where it has none. */
export const askPlugin = <T>(id: string, plugin: string, name: string) =>
  api<{ result: T | null }>(`${session(id)}/plugins/${plugin}/${name}`).then(r => r.result);

// A terminal: keystrokes go as they are, not as JSON.
export const streamUrl = (id: string) => session(id) + '/stream';
export const sendInput = (id: string, data: string) => fetch(session(id) + '/input', { method: 'POST', body: data });
export const resizeTerminal = (id: string, cols: number, rows: number) =>
  fetch(`${session(id)}/resize?cols=${cols}&rows=${rows}`, { method: 'POST' });

// A project's settings, its ~/.config/claude-sandbox/projects/<name>.json.
export const getConfig = (path: string) => api<ProjectConfig>('/api/config?' + project(path));
export const saveConfig = (path: string, config: JsonObject) => post<ProjectConfig>('/api/config', { project: path, config });

// The sandbox's own settings: your authentications (~/.config/claude-sandbox/auth.json), and the projects.
export const getAuth = () => api<AuthConfig>('/api/auth');
export const saveAuth = (config: JsonObject) => post<AuthConfig>('/api/auth', { config });
export const addProject = (name: string, repo: string) => post('/api/projects', { name, repo });
export const deleteProject = (name: string) => post('/api/projects/delete', { name });
