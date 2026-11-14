// Talking to web/server.py: JSON in, JSON out, its `error` thrown.

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error);
  return body as T;
}

export const post = <T = unknown>(path: string, body?: unknown): Promise<T> =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

/** The message of whatever was thrown. */
export const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));
