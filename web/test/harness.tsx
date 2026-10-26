/** Renders the real app routes against a stubbed API, and records what the app sent. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MotionConfig } from "framer-motion";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "../src/app/App";
import type { User } from "../src/shared/api/types";
import { session } from "../src/shared/lib/session";

export type Reply = unknown | Response | ((body: unknown, url: string) => unknown | Response);
export type Routes = Record<string, Reply>;
export interface Call {
  method: string;
  path: string;
  body: unknown;
}

export const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

/** Routes are keyed "GET /api/x?y=1"; the first exact match wins, then a match without the query. */
export function stubApi(routes: Routes): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      let body: unknown = undefined;
      if (typeof init?.body === "string") body = JSON.parse(init.body);
      else if (init?.body instanceof FormData) body = Object.fromEntries(init.body.entries());
      calls.push({ method, path: input, body });
      const key = `${method} ${input}`;
      const reply = key in routes ? routes[key] : routes[`${method} ${input.split("?")[0]}`];
      if (reply === undefined) return json({ detail: `no stub for ${key}` }, 404);
      const value =
        typeof reply === "function" ? (reply as (b: unknown, u: string) => unknown)(body, input) : reply;
      return value instanceof Response ? value : json(value);
    }),
  );
  return calls;
}

export function signIn(user: User, token = "test-token") {
  session.set({ token, user });
}

export function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  return render(
    <QueryClientProvider client={qc}>
      <MotionConfig reducedMotion="always">
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </MotionConfig>
    </QueryClientProvider>,
  );
}

/** A deep copy so a test can change a fixture without touching the others. */
export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
