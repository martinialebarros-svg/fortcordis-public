import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Link from "next/link";
import api from "@/lib/axios";
import {
  FRONTEND_PERFORMANCE_TIMEOUT_MS,
  FRONTEND_ROUTE_READY_EVENT,
} from "@/lib/frontend-performance";
import FrontendPerformanceMonitor from "./FrontendPerformanceMonitor";

let pathname = "/dashboard";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

vi.mock("@/lib/axios", () => ({
  default: {
    post: vi.fn(),
  },
}));

const mockedPost = vi.mocked(api.post);

describe("FrontendPerformanceMonitor", () => {
  beforeEach(() => {
    pathname = "/dashboard";
    mockedPost.mockReset();
    mockedPost.mockResolvedValue({} as never);
    vi.spyOn(performance, "now").mockReturnValue(100);
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(performance.now());
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("envia a carga concluida depois do shell e do sinal da pagina", async () => {
    render(<FrontendPerformanceMonitor enabled />);
    act(() => {
      window.dispatchEvent(new CustomEvent(FRONTEND_ROUTE_READY_EVENT, {
        detail: { route: "/dashboard", outcome: "ready", readyAt: 450 },
      }));
    });

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith("/observability/frontend-performance", {
      route_group: "/dashboard",
      navigation_type: "initial",
      outcome: "ready",
      shell_ms: 100,
      content_ms: 450,
    });
  });

  it("marca timeout sem bloquear a pagina quando nao recebe prontidao", async () => {
    vi.useFakeTimers();
    render(<FrontendPerformanceMonitor enabled />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(FRONTEND_PERFORMANCE_TIMEOUT_MS);
    });

    expect(mockedPost).toHaveBeenCalledWith("/observability/frontend-performance", expect.objectContaining({
      route_group: "/dashboard",
      outcome: "timeout",
      content_ms: null,
    }));
  });

  it("marca a medicao anterior como cancelada quando outra rota assume", async () => {
    const view = render(<FrontendPerformanceMonitor enabled />);
    pathname = "/laudos";
    view.rerender(<FrontendPerformanceMonitor enabled />);

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith("/observability/frontend-performance", expect.objectContaining({
      route_group: "/dashboard",
      outcome: "cancelled",
      content_ms: null,
    }));
  });

  it("classifica como interna a primeira rota monitorada depois de uma pagina nao monitorada", async () => {
    pathname = "/agenda";
    const view = render(<FrontendPerformanceMonitor enabled />);

    pathname = "/dashboard";
    view.rerender(<FrontendPerformanceMonitor enabled />);
    act(() => {
      window.dispatchEvent(new CustomEvent(FRONTEND_ROUTE_READY_EVENT, {
        detail: { route: "/dashboard", outcome: "ready", readyAt: 450 },
      }));
    });

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost).toHaveBeenCalledWith("/observability/frontend-performance", expect.objectContaining({
      route_group: "/dashboard",
      navigation_type: "client",
    }));
  });

  it("registra timeout quando a navegacao interna nao chega a trocar de rota", async () => {
    vi.useFakeTimers();
    pathname = "/agenda";
    render(
      <>
        <FrontendPerformanceMonitor enabled />
        <Link href="/laudos" onClick={(event) => event.preventDefault()}>Abrir laudos</Link>
      </>,
    );

    fireEvent.click(screen.getByRole("link", { name: "Abrir laudos" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FRONTEND_PERFORMANCE_TIMEOUT_MS);
    });

    expect(mockedPost).toHaveBeenCalledTimes(1);
    expect(mockedPost).toHaveBeenCalledWith("/observability/frontend-performance", expect.objectContaining({
      route_group: "/laudos",
      navigation_type: "client",
      outcome: "timeout",
      content_ms: null,
    }));
  });
});
