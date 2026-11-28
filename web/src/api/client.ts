// Talking to src/server/server.py: JSON in, JSON out, its `error` thrown.

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error);
  return body as T;
}

const send = (method: string) => <T = unknown>(path: string, body?: unknown): Promise<T> =>
  api<T>(path, body === undefined ? { method } : { method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });

export const post = send('POST');
export const put = send('PUT');
export const del = send('DELETE');

/** The message of whatever was thrown. */
export const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));
