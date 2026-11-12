export const FRONTEND_ROUTE_READY_EVENT = "fortcordis:frontend-route-ready";
export const FRONTEND_PERFORMANCE_TIMEOUT_MS = 30_000;

export const MONITORED_FRONTEND_ROUTES = [
  "/dashboard",
  "/atendimento",
  "/laudos",
  "/configuracoes",
] as const;

export type MonitoredFrontendRoute = (typeof MONITORED_FRONTEND_ROUTES)[number];
export type FrontendNavigationType = "initial" | "client";
export type FrontendPerformanceOutcome = "ready" | "partial" | "error" | "timeout" | "cancelled";

export interface FrontendPerformancePayload {
  route_group: MonitoredFrontendRoute;
  navigation_type: FrontendNavigationType;
  outcome: FrontendPerformanceOutcome;
  shell_ms: number;
  content_ms: number | null;
}
export interface FrontendRouteReadyDetail {
  route: MonitoredFrontendRoute;
  outcome: Extract<FrontendPerformanceOutcome, "ready" | "partial" | "error">;
  readyAt: number;
}

export function normalizeMonitoredFrontendRoute(pathname: string): MonitoredFrontendRoute | null {
  const cleanPath = String(pathname || "").split(/[?#]/, 1)[0].replace(/\/+$/, "") || "/";
  return MONITORED_FRONTEND_ROUTES.find((route) => route === cleanPath) || null;
}

export function roundFrontendDuration(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.round(Math.min(120_000, Math.max(0, value)) * 1000) / 1000;
}

export function buildFrontendPerformancePayload(input: {
  route: MonitoredFrontendRoute;
  navigationType: FrontendNavigationType;
  outcome: FrontendPerformanceOutcome;
  startedAt: number;
  shellAt: number;
  contentAt?: number | null;
}): FrontendPerformancePayload {
  const shellMs = roundFrontendDuration(input.shellAt - input.startedAt);
  const rawContentMs = input.contentAt == null ? null : roundFrontendDuration(input.contentAt - input.startedAt);
  return {
    route_group: input.route,
    navigation_type: input.navigationType,
    outcome: input.outcome,
    shell_ms: shellMs,
    content_ms: rawContentMs == null ? null : Math.max(shellMs, rawContentMs),
  };
}

export function signalFrontendRouteReady(
  pathname: string,
  outcome: FrontendRouteReadyDetail["outcome"] = "ready",
): void {
  if (typeof window === "undefined") return;
  const route = normalizeMonitoredFrontendRoute(pathname);
  if (!route) return;
  const detail: FrontendRouteReadyDetail = {
    route,
    outcome,
    readyAt: performance.now(),
  };
  window.dispatchEvent(new CustomEvent<FrontendRouteReadyDetail>(FRONTEND_ROUTE_READY_EVENT, { detail }));
}
