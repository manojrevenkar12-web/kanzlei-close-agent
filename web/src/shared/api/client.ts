import { session } from "../lib/session";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function authHeaders(): Record<string, string> {
  const s = session.get();
  return s ? { Authorization: `Bearer ${s.token}` } : {};
}

async function send(method: string, path: string, body?: BodyInit, json = true): Promise<Response> {
  const headers: Record<string, string> = authHeaders();
  if (json && body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body });
  } catch {
    throw new ApiError(0, "Der Server ist nicht erreichbar. Bitte prüfen Sie die Verbindung.");
  }
  if (res.status === 401 && session.get()) session.clear();
  if (!res.ok) {
    let message = `Anfrage fehlgeschlagen (${res.status})`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* no JSON body */
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body === undefined ? undefined : JSON.stringify(body));
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  upload: async <T>(path: string, form: FormData): Promise<T> => {
    const res = await send("POST", path, form, false);
    return (await res.json()) as T;
  },
  /** Downloads a file the API produces (DATEV export) under the person's rights. */
  download: async (path: string, fallbackName: string): Promise<void> => {
    const res = await send("GET", path);
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") ?? "";
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  },
};
