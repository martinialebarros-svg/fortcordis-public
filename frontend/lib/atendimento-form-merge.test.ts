import { describe, expect, it } from "vitest";
import type { AtendimentoForm, ExameSolicitacao } from "@/app/atendimento/page";
import {
  getExamStateKey,
  isClearedPersistedExamEligibleForRemoval,
  mergeAtendimentoFinalizado,
  mergeAutoSavedFormState,
  reconcileExamsDuringSave,
  restorePersistedAtendimentoDraft,
} from "./atendimento-form-merge";

const baseForm = (): AtendimentoForm => ({
  paciente_id: "1",
  especie: "Canina",
  clinica_id: "1",
  agendamento_id: "",
  data_atendimento: "2026-08-07T10:00",
  status: "Em atendimento",
  triagem: {
    peso: null,
    temperatura: null,
    frequencia_cardiaca: null,
    frequencia_respiratoria: null,
    pressao_arterial: "",
    saturacao_oxigenio: null,
    escore_condicion_corpo: null,
    mucosas: "",
    hidratacao: "",
    triagem_observacoes: "",
  },
  triagem_concluida: 0,
  consulta_concluida: 0,
  queixa_principal: "",
  anamnese: "",
  exame_fisico: "",
  dados_clinicos: "",
  diagnostico: {
    diagnostico_principal: "",
    diagnostico_secundario: "",
    diagnostico_diferencial: "",
    prognostico: "",
  },
  plano_terapeutico: "",
  retorno_recomendado: "",
  motivo_retorno: "",
  observacoes: "",
  exames: [],
  prescricao_alvo_id: null,
  prescricao_orientacoes: "",
  prescricao_retorno_dias: "",
  prescricao_itens: [],
  evolucoes: [],
  anexos: [],
  documentos: [],
});

const baseExam = (): ExameSolicitacao => ({
  catalogo_exame_id: null,
  painel_exame_id: null,
  tipo_exame: "Hemograma",
  prioridade: "Rotina",
  status: "Solicitado",
  observacoes: "",
});

describe("recuperacao do backup de atendimento concluido", () => {
  it("recupera o texto pendente sem reabrir nem trocar a data e o vinculo do encontro", () => {
    const persisted = { ...baseForm(), id: 63, status: "Concluido", agendamento_id: "1661", consulta_concluida: 1, triagem_concluida: 1 };
    const backup = { ...persisted, status: "Triagem", agendamento_id: "999", data_atendimento: "2026-10-10T10:00", consulta_concluida: 0, triagem_concluida: 0, anamnese: "Texto ainda nao sincronizado" };
    const restored = restorePersistedAtendimentoDraft(persisted, backup);
    expect(restored).toMatchObject({ status: "Concluido", agendamento_id: "1661", data_atendimento: persisted.data_atendimento, consulta_concluida: 1, triagem_concluida: 1, anamnese: backup.anamnese });
    expect(mergeAutoSavedFormState({ ...restored, status: "Triagem", anamnese: "Digitado durante o save" }, persisted)).toMatchObject({ status: "Concluido", anamnese: "Digitado durante o save" });
  });

  it("preserva correcao explicita de data, clinica e triagem durante o save do concluido", () => {
    const persisted = { ...baseForm(), id: 63, status: "Concluido", agendamento_id: "1661", consulta_concluida: 1 };
    const current = { ...persisted, data_atendimento: "2026-10-10T10:00", clinica_id: "2", triagem_concluida: 1 };
    expect(mergeAutoSavedFormState(current, persisted)).toEqual(current);
  });

  it("rejeita backup de outro paciente ou atendimento e preserva documentos do servidor", () => {
    const persisted = { ...baseForm(), id: 63 };
    expect(restorePersistedAtendimentoDraft(persisted, { id: 64, anamnese: "Outro encontro" })).toBe(persisted);
    expect(restorePersistedAtendimentoDraft(persisted, { paciente_id: "2", anamnese: "Outro paciente" })).toBe(persisted);
    const restored = restorePersistedAtendimentoDraft(persisted, { anamnese: "Recuperado", documentos: [{ id: 1 }] as never, evolucoes: [{ id: 2 }] as never, anexos: [{ id: 3 }] as never });
    expect(restored).toMatchObject({ anamnese: "Recuperado", documentos: [], evolucoes: [], anexos: [] });
  });

  it("mantem campos clinicos editados de um atendimento ainda em andamento", () => {
    const persisted = { ...baseForm(), id: 63 };
    expect(restorePersistedAtendimentoDraft(persisted, { status: "Em exame", anamnese: "Editado", data_atendimento: "2026-10-10T10:00" })).toMatchObject({ status: "Em exame", anamnese: "Editado", data_atendimento: "2026-10-10T10:00" });
  });
});

describe("mergeAutoSavedFormState (finalizarAtendimento)", () => {
  it("preserva edicao de campo de texto feita durante o round-trip do POST /finalizar", () => {
    const current = { ...baseForm(), queixa_principal: "Vomito e apatia ha 2 dias - editado durante o finalizar" };
    const persisted = { ...baseForm(), queixa_principal: "Vomito e apatia ha 2 dias" };

    const merged = mergeAutoSavedFormState(current, persisted);

    expect(merged.queixa_principal).toBe("Vomito e apatia ha 2 dias - editado durante o finalizar");
  });

  it("adota o id retornado pelo servidor quando o form local ainda nao tem id", () => {
    const current = { ...baseForm(), id: undefined };
    const persisted = { ...baseForm(), id: 42 };

    const merged = mergeAutoSavedFormState(current, persisted);

    expect(merged.id).toBe(42);
  });

  it("mescla exame existente por id preservando edicao local de resultado", () => {
    const exameBase = { ...baseExam(), id: 7 };
    const current = { ...baseForm(), exames: [{ ...exameBase, resultado: "Editado apos o save, antes do finalizar responder" }] };
    const persisted = { ...baseForm(), exames: [{ ...exameBase, resultado: "" }] };

    const merged = mergeAutoSavedFormState(current, persisted);

    expect(merged.exames).toHaveLength(1);
    expect(merged.exames[0].resultado).toBe("Editado apos o save, antes do finalizar responder");
  });

  it("mantem exame sem correspondencia no persisted (adicionado apos o snapshot enviado)", () => {
    const current = { ...baseForm(), exames: [{ ...baseExam(), tipo_exame: "Exame novo, ainda nao salvo" }] };
    const persisted = { ...baseForm(), exames: [] };

    const merged = mergeAutoSavedFormState(current, persisted);

    expect(merged.exames).toHaveLength(1);
    expect(merged.exames[0].tipo_exame).toBe("Exame novo, ainda nao salvo");
  });

  it("marca para exclusao o exame removido enquanto seu primeiro save ainda estava em voo", () => {
    const exameEnviado = {
      ...baseExam(),
      catalogo_exame_id: 174,
      tipo_exame: "Ultrassom abdominal",
      _localId: "ultrassom-em-voo",
    };
    const examePersistido = { ...exameEnviado, id: 88 };

    const reconciliados = reconcileExamsDuringSave(
      [
        {
          ...baseExam(),
          tipo_exame: "",
          _localId: "campo-vazio",
        },
      ],
      [exameEnviado],
      [examePersistido],
      new Set()
    );

    expect(reconciliados).toContainEqual(expect.objectContaining({ id: 88, _destroy: true }));

    const merged = mergeAutoSavedFormState(
      { ...baseForm(), exames: reconciliados },
      { ...baseForm(), exames: [examePersistido] }
    );
    expect(merged.exames).toContainEqual(expect.objectContaining({ id: 88, _destroy: true }));
  });

  it("remove do estado a exclusao que o servidor ja confirmou", () => {
    const exame = { ...baseExam(), id: 88, _destroy: true };

    expect(reconcileExamsDuringSave([exame], [exame], [], new Set([88]))).toEqual([]);
  });

  it("remove do estado o card manual esvaziado cuja exclusao derivada foi confirmada", () => {
    const exame = { ...baseExam(), id: 88, tipo_exame: "" };

    expect(reconcileExamsDuringSave([exame], [exame], [], new Set([88]))).toEqual([]);
  });

  it("preserva como nova solicitacao o texto retomado enquanto a exclusao estava em voo", () => {
    const sentExam = { ...baseExam(), id: 88, tipo_exame: "" };
    const currentExam = {
      ...sentExam,
      tipo_exame: "Relacao proteina/ creatinina urinaria",
      data_solicitacao: "2026-08-26T14:13:00",
    };

    expect(
      reconcileExamsDuringSave([currentExam], [sentExam], [], new Set([88]))
    ).toEqual([
      expect.objectContaining({
        id: undefined,
        _destroy: false,
        tipo_exame: "Relacao proteina/ creatinina urinaria",
        data_solicitacao: "",
      }),
    ]);
  });

  it("associa o id criado ao mesmo campo que continuou sendo editado durante o autosave", () => {
    const sentExam = {
      ...baseExam(),
      tipo_exame: "Rela",
      _localId: "relacao-urinaria",
    };
    const currentExam = {
      ...sentExam,
      tipo_exame: "Relacao proteina/ creatinina urinaria",
    };
    const persistedExam = { ...sentExam, id: 88 };

    const reconciled = reconcileExamsDuringSave(
      [currentExam],
      [sentExam],
      [persistedExam],
      new Set()
    );
    const merged = mergeAutoSavedFormState(
      { ...baseForm(), exames: reconciled },
      { ...baseForm(), exames: [persistedExam] }
    );

    expect(merged.exames).toHaveLength(1);
    expect(merged.exames[0]).toEqual(
      expect.objectContaining({
        id: 88,
        _localId: "relacao-urinaria",
        tipo_exame: "Relacao proteina/ creatinina urinaria",
      })
    );
  });

  it("marca para exclusao o texto apagado enquanto o primeiro autosave estava em voo", () => {
    const sentExam = {
      ...baseExam(),
      tipo_exame: "Rela",
      _localId: "relacao-apagada",
    };
    const persistedExam = { ...sentExam, id: 89 };

    expect(
      reconcileExamsDuringSave(
        [{ ...sentExam, tipo_exame: "" }],
        [sentExam],
        [persistedExam],
        new Set()
      )
    ).toContainEqual(
      expect.objectContaining({ id: 89, _localId: "relacao-apagada", _destroy: true })
    );
  });

  it("nao confunde uma repeticao manual valida com o registro criado pelo autosave", () => {
    const existingExam = { ...baseExam(), id: 70, _localId: "hemograma-existente" };
    const sentNewExam = { ...baseExam(), _localId: "hemograma-novo" };

    const reconciled = reconcileExamsDuringSave(
      [existingExam, sentNewExam],
      [existingExam, sentNewExam],
      [existingExam, { ...sentNewExam, id: 71 }],
      new Set()
    );

    expect(reconciled.map((item) => item.id)).toEqual([70, 71]);
  });

  it("mantem a chave visual enquanto o id do banco e incorporado", () => {
    const before = { ...baseExam(), _localId: "campo-estavel" };
    const after = { ...before, id: 88 };

    expect(getExamStateKey(before)).toBe("campo-estavel");
    expect(getExamStateKey(after)).toBe("campo-estavel");
  });

  it("permite remover ao limpar apenas uma solicitacao manual sem conteudo clinico", () => {
    expect(
      isClearedPersistedExamEligibleForRemoval({ ...baseExam(), id: 88, tipo_exame: "" })
    ).toBe(true);
    expect(
      isClearedPersistedExamEligibleForRemoval({
        ...baseExam(),
        id: 88,
        tipo_exame: "",
        resultado: "Resultado preservado",
      })
    ).toBe(false);
    expect(
      isClearedPersistedExamEligibleForRemoval({
        ...baseExam(),
        id: 88,
        tipo_exame: "",
        catalogo_exame_id: 12,
      })
    ).toBe(false);
  });
});

describe("mergeAtendimentoFinalizado", () => {
  // Defeito visto em producao em 2026-09-11, no atendimento #62: depois de
  // finalizar, todo autosave voltava 409 "nao pode ser reaberto isoladamente"
  // e o botao de emitir receita morria em silencio, porque ele salva antes de
  // gerar o PDF. A causa era o status antigo sobrevivendo no formulario.
  it("adota o status Concluido devolvido pelo finalizar", () => {
    const current = { ...baseForm(), status: "Em atendimento" };
    const persisted = { ...baseForm(), status: "Concluido" };

    const merged = mergeAtendimentoFinalizado(current, persisted);

    expect(merged.status).toBe("Concluido");
  });

  it("continua preservando a edicao de texto feita durante o round-trip", () => {
    const current = {
      ...baseForm(),
      status: "Em atendimento",
      queixa_principal: "digitado enquanto o finalizar respondia",
    };
    const persisted = { ...baseForm(), status: "Concluido", queixa_principal: "" };

    const merged = mergeAtendimentoFinalizado(current, persisted);

    expect(merged.queixa_principal).toBe("digitado enquanto o finalizar respondia");
    expect(merged.status).toBe("Concluido");
  });

  it("mantem o status local quando o servidor nao devolve um", () => {
    const current = { ...baseForm(), status: "Em atendimento" };
    const persisted = { ...baseForm(), status: "" };

    const merged = mergeAtendimentoFinalizado(current, persisted);

    expect(merged.status).toBe("Em atendimento");
  });
});
