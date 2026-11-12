import { describe, expect, it } from "vitest";

import {
  buildAtendimentoDocumentRevision,
  buildAtendimentoWhatsAppUrl,
  formatAtendimentoWhatsAppPhone,
  normalizeAtendimentoWhatsAppPhone,
} from "./atendimento-whatsapp";

describe("telefone WhatsApp do atendimento", () => {
  it.each(["(85) 99999-1234", "+55 (85) 99999-1234", "5585999991234", "0055 85 99999 1234"])("normaliza %s", (value) => {
    expect(normalizeAtendimentoWhatsAppPhone(value)).toBe("5585999991234");
  });

  it("aceita número fixo com DDD e número do DDD 55 sem confundir país", () => {
    expect(normalizeAtendimentoWhatsAppPhone("85 3333-1234")).toBe("558533331234");
    expect(normalizeAtendimentoWhatsAppPhone("55 99999-1234")).toBe("5555999991234");
  });

  it.each(["", "999991234", "00 99999-1234", "+1 415 555 1234", "+55 99999-1234", "++55 85 99999-1234", "85+99999-1234", "85 19999-1234", "85 99999-1234 ramal 2", "javascript:5585999991234"])("rejeita número ambíguo ou inválido %s", (value) => {
    expect(normalizeAtendimentoWhatsAppPhone(value)).toBeNull();
    expect(buildAtendimentoWhatsAppUrl(value)).toBeNull();
  });

  it("formata o número efetivamente usado no link", () => {
    expect(formatAtendimentoWhatsAppPhone("5585999991234")).toBe("+55 (85) 99999-1234");
    expect(formatAtendimentoWhatsAppPhone("558533331234")).toBe("+55 (85) 3333-1234");
  });

  it("gera mensagem neutra sem receber dados clínicos ou URLs protegidas", () => {
    const url = new URL(buildAtendimentoWhatsAppUrl("85 99999-1234")!);
    expect(url.origin).toBe("https://wa.me");
    expect(url.pathname).toBe("/5585999991234");
    expect([...url.searchParams.keys()]).toEqual(["text"]);
    expect(url.searchParams.get("text")).toBe("Olá! Aqui é da Fort Cordis. Posso compartilhar os documentos do atendimento por aqui?");
  });
});

describe("revisão do conteúdo de PDF", () => {
  const form = {
    paciente_id: "42", clinica_id: "7", data_atendimento: "2026-10-26T09:00:00",
    queixa_principal: "Reavaliação", triagem: { peso: "4.5" },
    prescricao_alvo_id: null, prescricao_orientacoes: "Orientação de teste", prescricao_retorno_dias: "7",
    prescricao_itens: [{ medicamento_id: 2, medicamento_nome: "Medicamento de teste", dose: "Dose revisada", frequencia: "Frequência revisada", duracao: "Duração revisada", via: "Via revisada", instrucoes: "Instrução revisada", apresentacao_selecionada: "Apresentação de teste" }],
    exames: [{ tipo_exame: "Hemograma", _localId: "local-1" }],
  };
  const cadastro = {
    paciente: { id: 42, nome: "Paciente", especie: "Canina", raca: "SRD", sexo: "Macho", idade: "8 anos", data_nascimento: "2018-10-26", peso_kg: 4.5, observacoes: "" },
    tutor: { id: 11, nome: "Tutor", whatsapp: "85999991234", email: "teste@example.com" },
  };

  it("não invalida PDF quando o próprio save adiciona IDs, datas e histórico", () => {
    const saved = {
      ...form, id: 99, updated_at: "2026-10-26T09:01:00",
      prescricao_itens: form.prescricao_itens.map((item) => ({ ...item, id: 321, historico_ajustes: [{ id: 1, campo: "dose" }] })),
      exames: form.exames.map((item) => ({ ...item, id: 123, data_solicitacao: "2026-10-26T09:01:00", anexos_resultado: [], laudo_id: null })),
    };
    expect(buildAtendimentoDocumentRevision(saved, cadastro)).toBe(buildAtendimentoDocumentRevision(form, cadastro));
  });

  it.each([
    { queixa_principal: "Queixa corrigida" },
    { triagem: { peso: "5" } },
    { clinica_id: "8" },
    { paciente_id: "43" },
    { data_atendimento: "2026-10-27T09:00:00" },
    { prescricao_alvo_id: 100 },
    { prescricao_orientacoes: "Nova orientação" },
    { prescricao_retorno_dias: "14" },
    { prescricao_itens: [{ ...form.prescricao_itens[0], dose: "Dose corrigida" }] },
    { prescricao_itens: [{ ...form.prescricao_itens[0], instrucoes: "Instrução corrigida" }] },
    { exames: [{ tipo_exame: "Bioquímica" }] },
    { exames: [{ ...form.exames[0], _destroy: true }] },
  ])("invalida PDF por alteração de conteúdo %#", (change) => {
    expect(buildAtendimentoDocumentRevision({ ...form, ...change }, cadastro)).not.toBe(buildAtendimentoDocumentRevision(form, cadastro));
  });

  it("considera correções de dados demográficos impressos", () => {
    const corrected = { ...cadastro, paciente: { ...cadastro.paciente, nome: "Nome corrigido", peso_kg: 5 } };
    expect(buildAtendimentoDocumentRevision(form, corrected)).not.toBe(buildAtendimentoDocumentRevision(form, cadastro));
  });

  it("não cancela preparação por uma linha vazia ou metadados não impressos", () => {
    const withEmptyRow = { ...form, exames: [...form.exames, { tipo_exame: "", _localId: "novo" }], prescricao_itens: [...form.prescricao_itens, { medicamento_nome: "" }] };
    const refreshed = { ...cadastro, tutor: { ...cadastro.tutor, email: "corrigido@example.com", updated_at: "agora" } };
    expect(buildAtendimentoDocumentRevision(withEmptyRow, refreshed)).toBe(buildAtendimentoDocumentRevision(form, cadastro));
  });
});
