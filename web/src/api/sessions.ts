// The server's API, call by call.
import { api, post } from './client';
import type { Answers } from './events';
import type { AppState, JsonObject, NewSession, Offer, Picture, ProjectConfig, Upload, ProjectInfo, Session } from './types';

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
export const interruptSession = (id: string) => post(session(id) + '/interrupt');
export const chooseModel = (id: string, model: string) => post(session(id) + '/model', { id: model });
export const chooseEffort = (id: string, level: string) => post(session(id) + '/effort', { level });
export const stopTask = (id: string, task: string) => post(session(id) + '/task', { id: task });
export const openVscode = (id: string) => post<{ folder: string }>('/api/vscode', { session: id });

// A terminal: keystrokes go as they are, not as JSON.
export const streamUrl = (id: string) => session(id) + '/stream';
export const sendInput = (id: string, data: string) => fetch(session(id) + '/input', { method: 'POST', body: data });
export const resizeTerminal = (id: string, cols: number, rows: number) =>
  fetch(`${session(id)}/resize?cols=${cols}&rows=${rows}`, { method: 'POST' });

// A project's settings, its .claude-sandbox.json.
export const getConfig = (path: string) => api<ProjectConfig>('/api/config?' + project(path));
export const saveConfig = (path: string, config: JsonObject) => post<ProjectConfig>('/api/config', { project: path, config });
