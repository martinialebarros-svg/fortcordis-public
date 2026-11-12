import { describe, expect, it } from "vitest";

import {
  deveResetarAssistentePorTrocaDeData,
  excecaoManualEstaLiberada,
  type EstadoExcecaoManual,
} from "./agenda-assistente-excecao";

const base: EstadoExcecaoManual = {
  isEditando: false,
  isAdmin: true,
  decisaoAssistente: "sem_opcao",
  excecaoConcedida: true,
};

describe("excecaoManualEstaLiberada", () => {
  it("libera quando admin recusou todas as ofertas e concedeu excecao", () => {
    expect(excecaoManualEstaLiberada(base)).toBe(true);
  });

  it("nao libera enquanto a excecao nao foi concedida", () => {
    expect(excecaoManualEstaLiberada({ ...base, excecaoConcedida: false })).toBe(false);
  });

  it("nao libera para perfil sem permissao de admin", () => {
    expect(excecaoManualEstaLiberada({ ...base, isAdmin: false })).toBe(false);
  });

  it("nao libera antes do desfecho de recusa", () => {
    expect(excecaoManualEstaLiberada({ ...base, decisaoAssistente: "pendente" })).toBe(false);
    expect(excecaoManualEstaLiberada({ ...base, decisaoAssistente: "aceito" })).toBe(false);
  });

  it("nao se aplica ao modo de edicao", () => {
    expect(excecaoManualEstaLiberada({ ...base, isEditando: true })).toBe(false);
  });
});

describe("deveResetarAssistentePorTrocaDeData", () => {
  it("preserva motivo e excecao quando a excecao manual esta ativa", () => {
    expect(deveResetarAssistentePorTrocaDeData(base)).toBe(false);
  });

  it("reseta o fluxo guiado enquanto nao ha excecao concedida", () => {
    expect(deveResetarAssistentePorTrocaDeData({ ...base, excecaoConcedida: false })).toBe(true);
    expect(deveResetarAssistentePorTrocaDeData({ ...base, decisaoAssistente: "pendente" })).toBe(true);
    expect(deveResetarAssistentePorTrocaDeData({ ...base, isAdmin: false })).toBe(true);
  });

  it("nao reseta nada no modo de edicao", () => {
    expect(deveResetarAssistentePorTrocaDeData({ ...base, isEditando: true })).toBe(false);
    expect(
      deveResetarAssistentePorTrocaDeData({ ...base, isEditando: true, decisaoAssistente: "pendente" })
    ).toBe(false);
  });
});
