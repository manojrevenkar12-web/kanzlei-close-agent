import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../../shared/api/client";
import type { DemoUser, User } from "../../shared/api/types";
import { session } from "../../shared/lib/session";

/** "demo": pick a person; "sso": the load balancer has signed the person in with the group's identity
 * provider and the API reads that; "none": this installation has no sign-in configured. */
export function useSignInMode() {
  return useQuery({
    queryKey: ["sign-in"],
    queryFn: () => api.get<{ mode: "demo" | "sso" | "none" }>("/api/sign-in"),
    staleTime: Infinity,
  });
}

export function useDemoUsers(enabled: boolean) {
  return useQuery({
    queryKey: ["demo-users"],
    queryFn: () => api.get<DemoUser[]>("/api/demo-users"),
    enabled,
  });
}

export function useSignIn() {
  return useMutation({
    mutationFn: async (login: string | null) => {
      const { token } = await api.post<{ token: string }>("/api/session", login ? { login } : {});
      session.set({
        token,
        user: { login: login ?? "", name: login ?? "", role: "buchhaltung", firm: null, can_sign_off: false },
      });
      const user = await api.get<User>("/api/me");
      session.set({ token, user });
      return user;
    },
  });
}
