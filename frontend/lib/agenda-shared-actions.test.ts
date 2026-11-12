import { describe, expect, it } from "vitest";
import { obterAcoesStatusPorFluxo, obterProximosStatus } from "./agenda-shared-actions";

describe("obterProximosStatus", () => {
  it("lista Agendado antes de Confirmado para uma reserva, priorizando a etapa intermediaria", () => {
    expect(obterProximosStatus("Reservado")).toEqual(["Agendado", "Confirmado", "Cancelado"]);
  });
});

describe("obterAcoesStatusPorFluxo", () => {
  it("renderiza o botao Agendar antes do botao Confirmar para uma reserva", () => {
    const acoes = obterAcoesStatusPorFluxo("Reservado").map((acao) => acao.status);
    expect(acoes.indexOf("Agendado")).toBeLessThan(acoes.indexOf("Confirmado"));
  });
});
