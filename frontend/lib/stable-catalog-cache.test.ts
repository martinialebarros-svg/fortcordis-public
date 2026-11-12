import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  invalidateStableCatalog,
  invalidateStableCatalogForMutation,
  loadStableCatalog,
  resetStableCatalogCacheForTests,
  STABLE_CATALOG_CACHE_TTL_MS,
} from "./stable-catalog-cache";

describe("cache de catalogos estaveis", () => {
  beforeEach(() => {
    resetStableCatalogCacheForTests();
    window.localStorage.setItem("token", "sessao-a");
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-31T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
    resetStableCatalogCacheForTests();
  });

  it("reutiliza uma lista enquanto a entrada estiver valida", async () => {
    const load = vi.fn().mockResolvedValue([{ id: 1, nome: "Clinica A" }]);

    await expect(loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load })).resolves.toEqual([
      { id: 1, nome: "Clinica A" },
    ]);
    await loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load });

    expect(load).toHaveBeenCalledTimes(1);
  });

  it("compartilha uma requisicao pendente para o mesmo catalogo", async () => {
    let resolveLoad: ((value: string[]) => void) | undefined;
    const load = vi.fn(
      () =>
        new Promise<string[]>((resolve) => {
          resolveLoad = resolve;
        })
    );

    const first = loadStableCatalog({ catalog: "servicos", variant: "limit=1000", load });
    const second = loadStableCatalog({ catalog: "servicos", variant: "limit=1000", load });
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    resolveLoad?.(["Ecocardiograma"]);

    await expect(Promise.all([first, second])).resolves.toEqual([
      ["Ecocardiograma"],
      ["Ecocardiograma"],
    ]);
  });

  it("busca novamente quando o TTL expira", async () => {
    const load = vi.fn().mockResolvedValue(["Clinica A"]);

    await loadStableCatalog({ catalog: "clinicas", variant: "limit=500", load });
    vi.advanceTimersByTime(STABLE_CATALOG_CACHE_TTL_MS + 1);
    await loadStableCatalog({ catalog: "clinicas", variant: "limit=500", load });

    expect(load).toHaveBeenCalledTimes(2);
  });

  it("nao reaproveita uma falha e permite nova tentativa", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("timeout")).mockResolvedValueOnce(["Clinica A"]);

    await expect(loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load })).rejects.toThrow("timeout");
    await expect(loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load })).resolves.toEqual([
      "Clinica A",
    ]);

    expect(load).toHaveBeenCalledTimes(2);
  });

  it("invalida todas as variantes do catalogo apos uma mutacao", async () => {
    const load = vi.fn().mockResolvedValue(["Clinica A"]);

    await loadStableCatalog({ catalog: "clinicas", variant: "limit=500", load });
    await loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load });
    invalidateStableCatalog("clinicas");
    await loadStableCatalog({ catalog: "clinicas", variant: "limit=500", load });

    expect(load).toHaveBeenCalledTimes(3);
  });

  it("invalida somente os recursos afetados por mutacoes de catalogo", async () => {
    const clinicas = vi.fn().mockResolvedValue(["Clinica A"]);
    const servicos = vi.fn().mockResolvedValue(["Ecocardiograma"]);

    await loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load: clinicas });
    await loadStableCatalog({ catalog: "servicos", variant: "limit=1000", load: servicos });
    invalidateStableCatalogForMutation("put", "/clinicas/12");
    await loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load: clinicas });
    await loadStableCatalog({ catalog: "servicos", variant: "limit=1000", load: servicos });

    expect(clinicas).toHaveBeenCalledTimes(2);
    expect(servicos).toHaveBeenCalledTimes(1);
  });

  it("descarta o cache quando a sessao muda", async () => {
    const load = vi.fn().mockResolvedValue(["Clinica A"]);

    await loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load });
    window.localStorage.setItem("token", "sessao-b");
    await loadStableCatalog({ catalog: "clinicas", variant: "limit=1000", load });

    expect(load).toHaveBeenCalledTimes(2);
  });
});
