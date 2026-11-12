import { describe, expect, it } from "vitest";
import { MAX_HISTORICO_SIMULACAO, parseHistorico } from "./whatsapp-bot-historico";

describe("parseHistorico", () => {
  it("reconhece os dois prefixos", () => {
    expect(parseHistorico("cliente: quanto custa o eco?\nnos: R$ 180,00.")).toEqual([
      { de: "cliente", texto: "quanto custa o eco?" },
      { de: "nos", texto: "R$ 180,00." },
    ]);
  });

  it("linha sem prefixo conta como cliente", () => {
    expect(parseHistorico("quanto custa o eco?")).toEqual([
      { de: "cliente", texto: "quanto custa o eco?" },
    ]);
  });

  it("nao quebra mensagem que tem dois-pontos no meio", () => {
    // "funciona das 8:00 as 14:00" nao pode virar prefixo "funciona das 8".
    expect(parseHistorico("nos: funciona das 8:00 as 14:00")).toEqual([
      { de: "nos", texto: "funciona das 8:00 as 14:00" },
    ]);
    expect(parseHistorico("abre 8:00?")).toEqual([{ de: "cliente", texto: "abre 8:00?" }]);
  });

  it("ignora linhas vazias e prefixo sem texto", () => {
    expect(parseHistorico("\n  \ncliente:   \nok\n")).toEqual([
      { de: "cliente", texto: "ok" },
    ]);
  });

  it("aceita 'nós' com acento", () => {
    expect(parseHistorico("nós: pronto")).toEqual([{ de: "nos", texto: "pronto" }]);
  });

  it("mantem as mais recentes ao passar do teto", () => {
    const bruto = Array.from({ length: MAX_HISTORICO_SIMULACAO + 5 }, (_, i) => `m${i}`).join("\n");
    const saida = parseHistorico(bruto);
    expect(saida).toHaveLength(MAX_HISTORICO_SIMULACAO);
    expect(saida[saida.length - 1].texto).toBe(`m${MAX_HISTORICO_SIMULACAO + 4}`);
  });

  it("vazio devolve lista vazia", () => {
    expect(parseHistorico("")).toEqual([]);
    expect(parseHistorico("   \n  ")).toEqual([]);
  });
});
