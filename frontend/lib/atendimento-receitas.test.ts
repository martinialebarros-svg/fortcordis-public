import { describe, expect, it } from "vitest";

import {
  montarSnapshotDoAtendimento,
  prescricaoEntraNoPayloadDoAtendimento,
  resolverPrescricaoDoForm,
} from "./atendimento-receitas";

const receitaDoDia = { id: 10, sequencia: 1, orientacoes_gerais: "Repouso", itens: [{ id: 1 }] };
const complementar = { id: 11, sequencia: 2, orientacoes_gerais: "Ajuste", itens: [{ id: 2 }] };
const detalhe = { prescricao: receitaDoDia, prescricoes: [receitaDoDia, complementar] };

describe("prescricaoEntraNoPayloadDoAtendimento", () => {
  it("deixa a receita do dia viajar no payload do atendimento", () => {
    expect(prescricaoEntraNoPayloadDoAtendimento({ prescricao_alvo_id: null })).toBe(true);
    expect(prescricaoEntraNoPayloadDoAtendimento({})).toBe(true);
    expect(prescricaoEntraNoPayloadDoAtendimento(null)).toBe(true);
  });

  it("tira a prescricao do payload enquanto uma complementar esta aberta", () => {
    // Invariante central: sem isso, o autosave do prontuario gravaria o
    // conteudo da complementar por cima da receita ja entregue ao tutor.
    expect(prescricaoEntraNoPayloadDoAtendimento({ prescricao_alvo_id: 11 })).toBe(false);
  });
});

describe("resolverPrescricaoDoForm", () => {
  it("usa a receita do dia quando nao ha alvo", () => {
    const resultado = resolverPrescricaoDoForm(detalhe, null);
    expect(resultado.prescricao.id).toBe(10);
    expect(resultado.alvoId).toBeNull();
  });

  it("usa a complementar quando ela e o alvo", () => {
    const resultado = resolverPrescricaoDoForm(detalhe, 11);
    expect(resultado.prescricao.id).toBe(11);
    expect(resultado.alvoId).toBe(11);
  });

  it("volta para a receita do dia quando o alvo sumiu do servidor", () => {
    const resultado = resolverPrescricaoDoForm({ prescricao: receitaDoDia, prescricoes: [receitaDoDia] }, 11);
    expect(resultado.prescricao.id).toBe(10);
    expect(resultado.alvoId).toBeNull();
  });

  it("nao trata a receita do dia como alvo complementar", () => {
    const resultado = resolverPrescricaoDoForm(detalhe, 10);
    expect(resultado.prescricao.id).toBe(10);
    expect(resultado.alvoId).toBeNull();
  });

  it("aguenta detalhe sem lista de receitas", () => {
    const resultado = resolverPrescricaoDoForm({ prescricao: receitaDoDia }, 11);
    expect(resultado.prescricao.id).toBe(10);
    expect(resultado.alvoId).toBeNull();
  });
});

describe("montarSnapshotDoAtendimento", () => {
  // Defeito encontrado em stage: com a complementar aberta, `prescricao` sai
  // do payload do atendimento; se o snapshot fosse so o payload, editar a
  // complementar nao mudaria nada comparavel e o autosave nunca dispararia -
  // o texto so era gravado com "Salvar atendimento".
  const payloadSemPrescricao = { paciente_id: 1, status: "Concluido" };
  const form = { prescricao_alvo_id: 12 };

  it("muda quando a receita complementar muda, mesmo com o payload igual", () => {
    const antes = montarSnapshotDoAtendimento(payloadSemPrescricao, form, {
      itens: [{ id: 9, dose: "1/2 comprimido" }],
    });
    const depois = montarSnapshotDoAtendimento(payloadSemPrescricao, form, {
      itens: [{ id: 9, dose: "1 comprimido" }],
    });
    expect(antes).not.toBe(depois);
  });

  it("nao muda quando nada mudou", () => {
    const receita = { itens: [{ id: 9, dose: "1/2 comprimido" }] };
    expect(montarSnapshotDoAtendimento(payloadSemPrescricao, form, receita)).toBe(
      montarSnapshotDoAtendimento(payloadSemPrescricao, form, receita)
    );
  });

  it("distingue trocar de receita alvo", () => {
    const receita = { itens: [{ id: 9, dose: "1/2 comprimido" }] };
    expect(montarSnapshotDoAtendimento(payloadSemPrescricao, { prescricao_alvo_id: null }, receita)).not.toBe(
      montarSnapshotDoAtendimento(payloadSemPrescricao, form, receita)
    );
  });
});
