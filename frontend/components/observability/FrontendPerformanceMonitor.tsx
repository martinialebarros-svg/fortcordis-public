"use client";

import { useCallback, useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import api from "@/lib/axios";
import {
  buildFrontendPerformancePayload,
  FRONTEND_PERFORMANCE_TIMEOUT_MS,
  FRONTEND_ROUTE_READY_EVENT,
  normalizeMonitoredFrontendRoute,
  type FrontendNavigationType,
  type FrontendPerformanceOutcome,
  type FrontendRouteReadyDetail,
  type MonitoredFrontendRoute,
} from "@/lib/frontend-performance";

interface ActiveMeasurement {
  route: MonitoredFrontendRoute;
  navigationType: FrontendNavigationType;
  startedAt: number;
  shellAt: number | null;
  readyAt: number | null;
  readyOutcome: FrontendRouteReadyDetail["outcome"] | null;
  timeoutId: number;
  sent: boolean;
}

interface PendingNavigation {
  route: MonitoredFrontendRoute;
  startedAt: number;
  timeoutId: number;
}

export default function FrontendPerformanceMonitor({ enabled }: { enabled: boolean }) {
  const pathname = usePathname();
  const activeRef = useRef<ActiveMeasurement | null>(null);
  const pendingNavigationRef = useRef<PendingNavigation | null>(null);
  const earlyReadyRef = useRef<FrontendRouteReadyDetail | null>(null);
  const firstMeasurementRef = useRef(true);

  const postMeasurement = useCallback((payload: ReturnType<typeof buildFrontendPerformancePayload>) => {
    void api.post("/observability/frontend-performance", payload).catch(() => {
      // Telemetria e best effort: falhas nunca interferem na navegacao medida.
    });
  }, []);

  const sendMeasurement = useCallback((measurement: ActiveMeasurement, outcome: FrontendPerformanceOutcome) => {
    if (measurement.sent || measurement.shellAt == null) return;
    measurement.sent = true;
    window.clearTimeout(measurement.timeoutId);
    const payload = buildFrontendPerformancePayload({
      route: measurement.route,
      navigationType: measurement.navigationType,
      outcome,
      startedAt: measurement.startedAt,
      shellAt: measurement.shellAt,
      contentAt: outcome === "timeout" || outcome === "cancelled" ? null : measurement.readyAt,
    });
    postMeasurement(payload);
  }, [postMeasurement]);

  const finishIfReady = useCallback((measurement: ActiveMeasurement) => {
    if (measurement.shellAt == null || measurement.readyAt == null || !measurement.readyOutcome) return;
    sendMeasurement(measurement, measurement.readyOutcome);
  }, [sendMeasurement]);

  useEffect(() => {
    if (!enabled) return;

    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(target instanceof HTMLAnchorElement) || target.target === "_blank" || target.hasAttribute("download")) return;
      const url = new URL(target.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      const route = normalizeMonitoredFrontendRoute(url.pathname);
      if (!route || url.pathname === window.location.pathname) return;
      const previousPending = pendingNavigationRef.current;
      if (previousPending) window.clearTimeout(previousPending.timeoutId);
      const pending: PendingNavigation = {
        route,
        startedAt: performance.now(),
        timeoutId: 0,
      };
      pending.timeoutId = window.setTimeout(() => {
        if (pendingNavigationRef.current !== pending) return;
        pendingNavigationRef.current = null;
        const timedOutAt = performance.now();
        postMeasurement(buildFrontendPerformancePayload({
          route: pending.route,
          navigationType: "client",
          outcome: "timeout",
          startedAt: pending.startedAt,
          shellAt: timedOutAt,
          contentAt: null,
        }));
      }, FRONTEND_PERFORMANCE_TIMEOUT_MS);
      pendingNavigationRef.current = pending;
    };

    const onReady = (event: Event) => {
      const detail = (event as CustomEvent<FrontendRouteReadyDetail>).detail;
      if (!detail?.route) return;
      const measurement = activeRef.current;
      if (!measurement || measurement.route !== detail.route) {
        earlyReadyRef.current = detail;
        return;
      }
      measurement.readyAt = detail.readyAt;
      measurement.readyOutcome = detail.outcome;
      finishIfReady(measurement);
    };

    document.addEventListener("click", onClick, true);
    window.addEventListener(FRONTEND_ROUTE_READY_EVENT, onReady);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener(FRONTEND_ROUTE_READY_EVENT, onReady);
    };
  }, [enabled, finishIfReady, postMeasurement]);

  useEffect(() => {
    if (!enabled) return;
    const route = normalizeMonitoredFrontendRoute(pathname);
    const previous = activeRef.current;
    if (previous && !previous.sent && previous.route !== route) {
      if (previous.shellAt == null) previous.shellAt = performance.now();
      sendMeasurement(previous, "cancelled");
    }
    activeRef.current = null;
    const pending = pendingNavigationRef.current;
    if (pending) window.clearTimeout(pending.timeoutId);
    pendingNavigationRef.current = null;
    const isInitial = firstMeasurementRef.current && Boolean(route);
    firstMeasurementRef.current = false;
    if (!route) return;

    const measurement: ActiveMeasurement = {
      route,
      navigationType: isInitial ? "initial" : "client",
      startedAt: isInitial
        ? 0
        : pending?.route === route
          ? pending.startedAt
          : performance.now(),
      shellAt: null,
      readyAt: null,
      readyOutcome: null,
      timeoutId: 0,
      sent: false,
    };
    const earlyReady = earlyReadyRef.current;
    if (earlyReady?.route === route && earlyReady.readyAt >= measurement.startedAt) {
      measurement.readyAt = earlyReady.readyAt;
      measurement.readyOutcome = earlyReady.outcome;
      earlyReadyRef.current = null;
    }

    measurement.timeoutId = window.setTimeout(() => {
      if (activeRef.current === measurement && !measurement.sent) {
        if (measurement.shellAt == null) measurement.shellAt = performance.now();
        sendMeasurement(measurement, "timeout");
      }
    }, FRONTEND_PERFORMANCE_TIMEOUT_MS);
    activeRef.current = measurement;

    let secondFrame = 0;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        measurement.shellAt = performance.now();
        finishIfReady(measurement);
      });
    });

    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame) window.cancelAnimationFrame(secondFrame);
    };
  }, [enabled, finishIfReady, pathname, sendMeasurement]);

  useEffect(() => () => {
    const measurement = activeRef.current;
    if (measurement && !measurement.sent) {
      window.clearTimeout(measurement.timeoutId);
    }
    const pending = pendingNavigationRef.current;
    if (pending) window.clearTimeout(pending.timeoutId);
  }, []);

  return null;
}
