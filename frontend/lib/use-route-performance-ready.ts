"use client";

import { useEffect, useRef } from "react";
import {
  normalizeMonitoredFrontendRoute,
  signalFrontendRouteReady,
  type FrontendRouteReadyDetail,
} from "@/lib/frontend-performance";

export function useRoutePerformanceReady(
  pending: boolean,
  outcome: FrontendRouteReadyDetail["outcome"] = "ready",
): void {
  const signaledRouteRef = useRef<string | null>(null);

  useEffect(() => {
    const pathname = window.location.pathname;
    const route = normalizeMonitoredFrontendRoute(pathname);
    if (!route || pending || signaledRouteRef.current === route) return;

    const frame = window.requestAnimationFrame(() => {
      signalFrontendRouteReady(pathname, outcome);
      signaledRouteRef.current = route;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [outcome, pending]);
}
