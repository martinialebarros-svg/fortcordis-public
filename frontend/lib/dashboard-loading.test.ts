import { describe, expect, it, vi } from "vitest";
import { loadDashboardSection } from "./dashboard-loading";

describe("loadDashboardSection", () => {
  it("publica a secao que respondeu sem depender das outras leituras", async () => {
    const controller = new AbortController();
    const onSuccess = vi.fn();

    const result = await loadDashboardSection({
      section: "pacientes",
      request: Promise.resolve({ total: 1313 }),
      signal: controller.signal,
      onSuccess,
    });

    expect(result).toEqual({ section: "pacientes", status: "success" });
    expect(onSuccess).toHaveBeenCalledWith({ total: 1313 });
  });

  it("isola a falha da secao sem publicar um valor incompleto", async () => {
    const controller = new AbortController();
    const onSuccess = vi.fn();
    const error = new Error("timeout");

    const result = await loadDashboardSection({
      section: "clinicas",
      request: Promise.reject(error),
      signal: controller.signal,
      onSuccess,
    });

    expect(result).toEqual({ section: "clinicas", status: "failed", error });
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("descarta a resposta que chega depois de uma nova tentativa", async () => {
    const controller = new AbortController();
    const onSuccess = vi.fn();
    let resolveRequest: ((value: { total: number }) => void) | undefined;
    const request = new Promise<{ total: number }>((resolve) => {
      resolveRequest = resolve;
    });

    const pendingResult = loadDashboardSection({
      section: "servicos",
      request,
      signal: controller.signal,
      onSuccess,
    });
    controller.abort();
    resolveRequest?.({ total: 12 });

    await expect(pendingResult).resolves.toEqual({ section: "servicos", status: "cancelled" });
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
