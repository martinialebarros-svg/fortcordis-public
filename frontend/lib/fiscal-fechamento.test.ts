import { describe, expect, it } from "vitest";
import { assinaturaSelecao, competenciaValida, formatarCompetencia, lerErroFiscal, servicoSelecionavel, type FiscalServico } from "./fiscal-fechamento";

describe("contrato do fechamento fiscal", () => {
  it("valida o mês sem aceitar períodos soltos", () => {
    expect(competenciaValida("2026-08")).toBe(true);
    for (const value of ["", "2026-00", "2026-13", "08/2026", "2026-08-31"]) expect(competenciaValida(value)).toBe(false);
    expect(formatarCompetencia("2026-08")).toBe("08/2026");
  });
  it("não seleciona serviço de outra competência, cancelado ou vinculado a pacote", () => {
    const item = { elegivel: true, competencia: "2026-08", fechamento_id: null, status_os: "Pendente" } as FiscalServico;
    expect(servicoSelecionavel(item, "2026-08")).toBe(true);
    expect(servicoSelecionavel(item, "2026-09")).toBe(false);
    expect(servicoSelecionavel({ ...item, status_os: "Cancelado" }, "2026-08")).toBe(false);
    expect(servicoSelecionavel({ ...item, fechamento_id: 4 }, "2026-08")).toBe(false);
  });
  it("uma seleção tem a mesma assinatura independentemente da ordem", () => {
    expect(assinaturaSelecao("2026-08", [8, 1, 8])).toBe(assinaturaSelecao("2026-08", [1, 8]));
    expect(assinaturaSelecao("2026-08", [1])).not.toBe(assinaturaSelecao("2026-09", [1]));
  });
  it("recupera conflitos de resposta binária e os pacotes anteriores", async () => {
    const binaryError = new Blob([JSON.stringify({ detail: { message: "Conflito de seleção", fechamento_id: 8, fechamentos_ids: [8, 9] } })]);
    const result = await lerErroFiscal({ response: { data: binaryError } }, "Erro");
    expect(result).toEqual({ mensagem: "Conflito de seleção", fechamentoIds: [8, 9] });
  });
});
