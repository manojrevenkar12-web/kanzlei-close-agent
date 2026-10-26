import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "framer-motion";
import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { ApiError } from "../shared/api/client";
import { useSession } from "../shared/lib/session";
import { SkeletonRows } from "../shared/ui";
import { Layout } from "./Layout";

const LoginPage = lazy(() => import("../features/auth/LoginPage"));
const BoardPage = lazy(() => import("../features/board/BoardPage"));
const ClientPage = lazy(() => import("../features/client/ClientPage"));
const RolloutPage = lazy(() => import("../features/group/RolloutPage"));
const QualityPage = lazy(() => import("../features/quality/QualityPage"));
const PortalPage = lazy(() => import("../features/portal/PortalPage"));

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

function RequireSession({ children }: { children: ReactNode }) {
  const s = useSession();
  const loc = useLocation();
  if (!s) return <Navigate to="/anmelden" replace state={{ from: loc.pathname + loc.search }} />;
  return <>{children}</>;
}

function Home() {
  const s = useSession();
  return <Navigate to={s?.user.role === "gruppe" ? "/gruppe" : "/abschluss"} replace />;
}

export function AppRoutes() {
  return (
    <Suspense fallback={<SkeletonRows label="Seite wird geladen" />}>
      <Routes>
        <Route path="/anmelden" element={<LoginPage />} />
        <Route path="/portal/:token" element={<PortalPage />} />
        <Route
          element={
            <RequireSession>
              <Layout />
            </RequireSession>
          }
        >
          <Route path="/" element={<Home />} />
          <Route path="/abschluss" element={<BoardPage />} />
          <Route path="/mandanten/:clientId/:period" element={<ClientPage />} />
          <Route path="/mandanten/:clientId/:period/:tab" element={<ClientPage />} />
          <Route path="/gruppe" element={<RolloutPage />} />
          <Route path="/qualitaet" element={<QualityPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export function App() {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <MotionConfig reducedMotion="user">
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </MotionConfig>
    </QueryClientProvider>
  );
}
