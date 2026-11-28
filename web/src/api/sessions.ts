// The server's API, call by call: its resources, as src/server/server.py's routes name them.
import { api, del, post, put } from './client';
import type { Answers } from './events';
import type { AppState, AuthConfig, AuthFileInfo, JsonObject, NewSession, Offer, Picture, ProjectConfig, Upload, ProjectInfo, Session } from './types';

const session = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;
const project = (name: string) => `/api/projects/${encodeURIComponent(name)}`;
const part = encodeURIComponent;

export const getState = () => api<AppState>('/api/state');
export const getProject = (name: string) => api<ProjectInfo>(project(name));

export const startSession = (what: NewSession) => post<Session>('/api/sessions', what);
export const stopSession = (id: string) => post(session(id) + '/stop');
export const getOffers = (id: string) => api<{ offers: Offer[] }>(session(id) + '/cleanup-offers');
export const deleteSession = (id: string, tidy: string[]) => del<{ failed?: string[] }>(session(id), { tidy });

// A chat.
export const eventsUrl = (id: string) => session(id) + '/events';
/** `nonce` names the message: the server's event for it carries it, and it is taken once however often it is sent. */
export const sendPrompt = (id: string, text: string, images?: Picture[], files?: Upload[], nonce?: string) =>
  post(session(id) + '/messages', { text, images, files, nonce });
export const sendAnswer = (id: string, ask: string, reply: { answers: Answers } | { cancel: true }) =>
  post(`${session(id)}/questions/${part(ask)}/answer`, reply);
/** Stops the agent's turn: the conversation's, or with `side` that side chat's. */
export const interruptSession = (id: string, side?: string) =>
  post(side ? `${session(id)}/sides/${part(side)}/interrupt` : session(id) + '/interrupt');
/** Asks in a side chat (a new one without `side`); answers with the chat's id. */
export const askSide = (id: string, side: string | null, text: string) =>
  post<{ id: string }>(side ? `${session(id)}/sides/${part(side)}/messages` : session(id) + '/sides', { text }).then(r => r.id);
export const closeSide = (id: string, side: string) => del(`${session(id)}/sides/${part(side)}`);
export const chooseModel = (id: string, model: string) => put(session(id) + '/model', { id: model });
export const chooseEffort = (id: string, level: string) => put(session(id) + '/effort', { level });
export const stopTask = (id: string, task: string) => del(`${session(id)}/tasks/${part(task)}`);
/** Sends the task a tool call waits on to the background: the call returns, the task runs on. */
export const backgroundTask = (id: string, call: string) => post(`${session(id)}/calls/${part(call)}/background`);
/** What a plugin's command (web_command) says about the session's run: null where it has none. */
export const askPlugin = <T>(id: string, plugin: string, name: string) =>
  api<{ result: T | null }>(`${session(id)}/plugins/${part(plugin)}/commands/${part(name)}`).then(r => r.result);

// A project's settings, its ~/.config/claude-sandbox/projects/<name>.json.
export const getConfig = (name: string) => api<ProjectConfig>(project(name) + '/config');
export const saveConfig = (name: string, config: JsonObject) => put<ProjectConfig>(project(name) + '/config', config);

// The sandbox's own settings: your authentications (~/.config/claude-sandbox/auth.json), and the projects.
export const getAuth = () => api<AuthConfig>('/api/auth');
export const saveAuth = (config: JsonObject) => put<AuthConfig>('/api/auth', config);
/** Stores a file of an authentication at its place (`file` null: deletes it). */
export const putAuthFile = (name: string, field: string, file: Blob | null) =>
  api<{ exists: boolean; file: AuthFileInfo | null }>(
    `/api/auth/${part(name)}/files/${part(field)}`, { method: file ? 'PUT' : 'DELETE', body: file ?? undefined });
export const addProject = (name: string, repo: string) => post('/api/projects', { name, repo });
export const deleteProject = (name: string) => del(project(name));

// The server itself, and the agents' sign-ins on it.
/** Pulls main, runs install.sh and, under systemd, restarts the server. */
export const syncServer = () => post<{ restarting: boolean }>('/api/server/sync');
/** A link to follow, not to fetch: it starts the agent's sign-in and goes on to its page. */
export const signInUrl = (agent: string) => `/api/agents/${part(agent)}/sign-in`;
export const sendSignInCode = (agent: string, code: string) => post(signInUrl(agent), { code });
export const getSignInStatus = (agent: string) => api<{ signedIn: boolean }>(`/api/agents/${part(agent)}/sign-in-status`);
