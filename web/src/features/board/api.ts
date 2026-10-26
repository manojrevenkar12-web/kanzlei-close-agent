import { useQuery } from "@tanstack/react-query";

import { api } from "../../shared/api/client";
import type { BoardRow } from "../../shared/api/types";

export function usePeriods() {
  return useQuery({ queryKey: ["periods"], queryFn: () => api.get<string[]>("/api/periods") });
}

export function useBoard(period: string | undefined) {
  return useQuery({
    queryKey: ["board", period],
    queryFn: () => api.get<BoardRow[]>(`/api/closes?period=${period}`),
    enabled: !!period,
  });
}
