import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../shared/api/client";
import type { Family, ItemDetailResponse, ItemsResponse, QueryBundle, Ustva } from "../../shared/api/types";

export const keys = {
  items: (c: string, p: string) => ["items", c, p] as const,
  item: (id: number) => ["item", id] as const,
  queries: (c: string, p: string) => ["queries", c, p] as const,
  ustva: (c: string, p: string) => ["ustva", c, p] as const,
};

export function useItems(clientId: string, period: string) {
  return useQuery({ queryKey: keys.items(clientId, period), queryFn: () => api.get<ItemsResponse>(`/api/clients/${clientId}/periods/${period}/items`) });
}

export function useItem(id: number | null) {
  return useQuery({ queryKey: keys.item(id ?? 0), queryFn: () => api.get<ItemDetailResponse>(`/api/items/${id}`), enabled: id !== null });
}

export function useFamilies() {
  return useQuery({ queryKey: ["families"], queryFn: () => api.get<Family[]>("/api/families"), staleTime: Infinity });
}

export function useQueries(clientId: string, period: string) {
  return useQuery({ queryKey: keys.queries(clientId, period), queryFn: () => api.get<QueryBundle[]>(`/api/clients/${clientId}/periods/${period}/queries`) });
}

export function useUstva(clientId: string, period: string) {
  return useQuery({ queryKey: keys.ustva(clientId, period), queryFn: () => api.get<Ustva>(`/api/clients/${clientId}/periods/${period}/ustva`) });
}

function useRefresh(clientId: string, period: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: keys.items(clientId, period) });
    void qc.invalidateQueries({ queryKey: keys.queries(clientId, period) });
    void qc.invalidateQueries({ queryKey: keys.ustva(clientId, period) });
    void qc.invalidateQueries({ queryKey: ["board"] });
  };
}

export type Decision = { kind: "accept" } | { kind: "correct"; family: string; tax: string | null; reason: string } | { kind: "park"; note: string } | { kind: "dismiss"; note: string };

export function useDecide(clientId: string, period: string) {
  const refresh = useRefresh(clientId, period);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, d }: { id: number; d: Decision }) => {
      const path = `/api/items/${id}/${d.kind}`;
      if (d.kind === "accept") return api.post<ItemDetailResponse>(path);
      if (d.kind === "correct") return api.post<ItemDetailResponse>(path, { family: d.family, tax: d.tax, reason: d.reason });
      return api.post<ItemDetailResponse>(path, { note: d.note });
    },
    onSuccess: (data) => {
      qc.setQueryData(keys.item(data.id), data);
      refresh();
    },
  });
}

export function useRun(clientId: string, period: string) {
  const refresh = useRefresh(clientId, period);
  return useMutation({
    mutationFn: () => api.post<{ items: number; created: { payment: number; invoice: number }; query?: { portal_link: string; items: number } }>(`/api/clients/${clientId}/periods/${period}/run`),
    onSuccess: refresh,
  });
}

export function useApplyAnswers(clientId: string, period: string) {
  const refresh = useRefresh(clientId, period);
  return useMutation({ mutationFn: () => api.post<{ applied: number }>(`/api/clients/${clientId}/periods/${period}/apply-answers`), onSuccess: refresh });
}

export function useUpload(clientId: string, period: string) {
  const refresh = useRefresh(clientId, period);
  return useMutation({
    mutationFn: async ({ file, kind }: { file: File; kind: "statement" | "document" }) => {
      const form = new FormData();
      form.append("file", file);
      if (kind === "document") form.append("direction", "in");
      return api.upload<Record<string, unknown>>(`/api/clients/${clientId}/${kind === "statement" ? "statements" : "documents"}`, form);
    },
    onSuccess: refresh,
  });
}

export function useSignOff(clientId: string, period: string) {
  const refresh = useRefresh(clientId, period);
  return useMutation({
    mutationFn: (acknowledge: boolean) => api.post<{ sha256: string; export: string }>(`/api/clients/${clientId}/periods/${period}/sign-off`, { acknowledge_flags: acknowledge }),
    onSuccess: refresh,
  });
}
