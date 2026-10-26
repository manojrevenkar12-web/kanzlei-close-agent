/** The signed-in user, kept in localStorage (wrapped: storage can throw in private windows). */
import { useSyncExternalStore } from "react";

import type { User } from "../api/types";

export interface StoredSession {
  token: string;
  user: User;
}

const KEY = "kanzlei.session";
const listeners = new Set<() => void>();
let cached: StoredSession | null | undefined;

function read(): StoredSession | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return null;
  }
}

export const session = {
  get(): StoredSession | null {
    if (cached === undefined) cached = read();
    return cached;
  },
  set(s: StoredSession): void {
    cached = s;
    try {
      window.localStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      /* in memory only */
    }
    listeners.forEach((l) => l());
  },
  clear(): void {
    cached = null;
    try {
      window.localStorage.removeItem(KEY);
    } catch {
      /* nothing stored */
    }
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

export function useSession(): StoredSession | null {
  return useSyncExternalStore(session.subscribe, session.get, () => null);
}
