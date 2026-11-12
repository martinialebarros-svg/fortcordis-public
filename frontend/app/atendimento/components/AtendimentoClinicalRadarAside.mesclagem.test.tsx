import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import AtendimentoClinicalRadarAside from "./AtendimentoClinicalRadarAside";

it("oferece revisão em outra aba sem iniciar trabalho nem exigir alteração da consulta", () => {
  const herdarAtendimentoAnterior = vi.fn();
  render(<AtendimentoClinicalRadarAside
    form={{
      paciente_id: "31", queixa_principal: "", anamnese: "", plano_terapeutico: "",
      retorno_recomendado: "", exames: [], prescricao_itens: [], diagnostico: {}, status: "Triagem",
    }}
    alertasAtivos={[]}
    autosaveLabel="Salvo"
    autosaveState="idle"
    clinicalSummary={{ completeness: 42, pending: [] }}
    historicoPaciente={{ atendimentos: [] }}
    herdarAtendimentoAnterior={herdarAtendimentoAnterior}
    selecionado={91}
  />);
  const link = screen.getByRole("link", { name: /Revisar duplicidade do paciente/ });
  expect(link).toHaveAttribute("href", "/pacientes/mesclagens?paciente=31");
  expect(link).toHaveAttribute("target", "_blank");
  expect(herdarAtendimentoAnterior).not.toHaveBeenCalled();
});
