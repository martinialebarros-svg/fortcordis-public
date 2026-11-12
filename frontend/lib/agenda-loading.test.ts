import { describe, expect, it, vi } from "vitest";
import {
  agruparIdsAgendamentosVisiveis,
  createAgendaCatalogLoader,
  executarCargasAuxiliaresAgenda,
  extrairIdsAgendamentosVisiveis,
  normalizarOpcoesFiltroAgenda,
} from "./agenda-loading";

describe("executarCargasAuxiliaresAgenda", () => {
  it("inicia as leituras independentes em paralelo", async () => {
    let concluirRelacionados: (() => void) | undefined;
    let concluirResumo: (() => void) | undefined;
    const relacionados = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          concluirRelacionados = resolve;
        })
    );
    const resumo = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          concluirResumo = resolve;
        })
    );

    const resultado = executarCargasAuxiliaresAgenda([relacionados, resumo]);

    expect(relacionados).toHaveBeenCalledTimes(1);
    expect(resumo).toHaveBeenCalledTimes(1);
    concluirRelacionados?.();
    concluirResumo?.();
    await expect(resultado).resolves.toEqual([
      { status: "fulfilled", value: undefined },
      { status: "fulfilled", value: undefined },
    ]);
  });

  it("isola a falha de uma leitura auxiliar", async () => {
    const resultado = await executarCargasAuxiliaresAgenda([
      async () => {
        throw new Error("falha nos relacionados");
      },
      async () => "resumo disponivel",
    ]);

    expect(resultado[0].status).toBe("rejected");
    expect(resultado[1]).toEqual({ status: "fulfilled", value: "resumo disponivel" });
  });
});

describe("extrairIdsAgendamentosVisiveis", () => {
  it("mantem apenas IDs positivos, inteiros e unicos", () => {
    expect(
      extrairIdsAgendamentosVisiveis([
        { id: 7 },
        { id: "8" },
        { id: 7 },
        { id: 0 },
        { id: "invalido" },
      ])
    ).toEqual([7, 8]);
  });

  it("limita o lote antes de chamar o contrato de relacionados", () => {
    const items = Array.from({ length: 120 }, (_, index) => ({ id: index + 1 }));
    expect(extrairIdsAgendamentosVisiveis(items)).toHaveLength(100);
  });
});

describe("agruparIdsAgendamentosVisiveis", () => {
  it("divide periodos amplos em lotes compativeis com a API", () => {
    const items = Array.from({ length: 205 }, (_, index) => ({ id: index + 1 }));
    expect(agruparIdsAgendamentosVisiveis(items).map((lote) => lote.length)).toEqual([100, 100, 5]);
  });
});

describe("normalizarOpcoesFiltroAgenda", () => {
  it("descarta opcoes invalidas e ordena em portugues", () => {
    expect(
      normalizarOpcoesFiltroAgenda({
        items: [
          { id: 2, nome: " Zebra " },
          { id: 1, nome: "Ágata" },
          { id: 0, nome: "Invalida" },
          { id: 3, nome: "" },
        ],
      })
    ).toEqual([
      { id: 1, nome: "Ágata" },
      { id: 2, nome: "Zebra" },
    ]);
  });
});

describe("createAgendaCatalogLoader", () => {
  it("compartilha a requisicao em voo e nao repete depois do sucesso", async () => {
    let resolver: ((value: string[]) => void) | undefined;
    const request = vi.fn(
      () =>
        new Promise<string[]>((resolve) => {
          resolver = resolve;
        })
    );
    const onSuccess = vi.fn();
    const loader = createAgendaCatalogLoader({ request, onSuccess });

    const primeira = loader.load();
    const segunda = loader.load();
    expect(request).toHaveBeenCalledTimes(1);

    resolver?.(["Clinica A"]);
    await expect(Promise.all([primeira, segunda])).resolves.toEqual([true, true]);
    await expect(loader.load()).resolves.toBe(true);
    expect(request).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledWith(["Clinica A"]);
  });

  it("libera nova tentativa depois de uma falha", async () => {
    const request = vi
      .fn<() => Promise<string[]>>()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce(["Servico A"]);
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const loader = createAgendaCatalogLoader({ request, onSuccess, onError });

    await expect(loader.load()).resolves.toBe(false);
    await expect(loader.load()).resolves.toBe(true);
    expect(request).toHaveBeenCalledTimes(2);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledWith(["Servico A"]);
  });
});
