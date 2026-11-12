import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chaveOperacaoTutor, concluirOperacaoTutor } from "./tutor-mesclagem";

describe("Chave da intenção de cadastro de tutor", () => {
  beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); concluirOperacaoTutor("teste"); });
  afterEach(() => vi.unstubAllGlobals());

  it("reaproveita a intenção enquanto a resposta é desconhecida, independentemente da ordem dos campos", async () => {
    const a = await chaveOperacaoTutor("teste", { nome: "Cristiane", telefone: "85999991111" });
    const b = await chaveOperacaoTutor("teste", { telefone: "85999991111", nome: "Cristiane" });
    expect(a).toBe(b);
    const persistido = sessionStorage.getItem("fortcordis:tutor-operacao:teste");
    expect(persistido).not.toContain("Cristiane"); expect(persistido).not.toContain("85999991111");
  });

  it("gera outra chave quando o conteúdo muda ou quando começa uma nova intenção após o sucesso", async () => {
    const a = await chaveOperacaoTutor("teste", { nome: "Cristiane" });
    const b = await chaveOperacaoTutor("teste", { nome: "Cristiane Silva" });
    expect(a).not.toBe(b);
    concluirOperacaoTutor("teste");
    const c = await chaveOperacaoTutor("teste", { nome: "Cristiane Silva" });
    expect(b).not.toBe(c);
  });
});
