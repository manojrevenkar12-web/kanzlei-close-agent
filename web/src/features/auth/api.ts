import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../../shared/api/client";
import type { DemoUser, User } from "../../shared/api/types";
import { session } from "../../shared/lib/session";

export function useDemoUsers() {
  return useQuery({ queryKey: ["demo-users"], queryFn: () => api.get<DemoUser[]>("/api/demo-users") });
}

export function useSignIn() {
  return useMutation({
    mutationFn: async (login: string) => {
      const { token } = await api.post<{ token: string }>("/api/session", { login });
      session.set({
        token,
        user: { login, name: login, role: "buchhaltung", firm: null, can_sign_off: false },
      });
      const user = await api.get<User>("/api/me");
      session.set({ token, user });
      return user;
    },
  });
}
