import { describe, expect, it } from "vitest";
import type { AtendimentoForm } from "@/app/atendimento/page";
import { assessAtendimentoBackup, atendimentoBackupDifferences, writePendingAtendimentoBackup } from "./atendimento-draft-recovery";

const base = () => ({
  id: 63, paciente_id: "1", clinica_id: "1", agendamento_id: "1661", data_atendimento: "2026-09-11T13:00",
  status: "Concluido", triagem_concluida: 1, consulta_concluida: 1,
  anamnese: "Texto inicial", prescricao_alvo_id: null, prescricao_orientacoes: "Orientacao inicial",
  prescricao_itens: [{ id: 1, medicamento_nome: "Medicamento de teste", dose: "Dose original" }],
  especie: "Canina", documentos: [], evolucoes: [], anexos: [],
} as unknown as AtendimentoForm);
const snapshot = (form: AtendimentoForm) => JSON.stringify({
  paciente_id: form.paciente_id, clinica_id: form.clinica_id, agendamento_id: form.agendamento_id,
  data_atendimento: form.data_atendimento, status: form.status,
  consulta_concluida: form.consulta_concluida, triagem_concluida: form.triagem_concluida,
  anamnese: form.anamnese, _receita_alvo: form.prescricao_alvo_id,
  _receita: { orientacoes_gerais: form.prescricao_orientacoes, itens: form.prescricao_itens },
});

describe("recuperacao sem sobrescrever outra sessao", () => {
  it("dirty, undo e reload nao ressuscitam texto abandonado antes do autosave", () => {
    const saved = base();
    const pending = { ...saved, anamnese: "Texto desfeito pelo usuario" };
    const key = "backup-undo";
    const raw = writePendingAtendimentoBackup(localStorage, key, pending, snapshot(saved), snapshot, null, "sessao-A");
    expect(localStorage.getItem(key)).toBe(raw);
    writePendingAtendimentoBackup(localStorage, key, saved, snapshot(saved), snapshot, raw, "sessao-A");
    expect(localStorage.getItem(key)).toBeNull();
  });

  it("undo na sessao A nao apaga texto pendente escrito pela sessao B", () => {
    const saved = base();
    const key = "backup-outra-aba";
    const rawA = writePendingAtendimentoBackup(localStorage, key, { ...saved, anamnese: "Texto da A" }, snapshot(saved), snapshot, null, "sessao-A");
    const rawB = writePendingAtendimentoBackup(localStorage, key, { ...saved, anamnese: "Texto da B" }, snapshot(saved), snapshot, null, "sessao-B");
    writePendingAtendimentoBackup(localStorage, key, saved, snapshot(saved), snapshot, rawA, "sessao-A");
    expect(localStorage.getItem(key)).toBe(rawB);
  });

  it("copia limpa da sessao A jamais desfaz receita corrigida na sessao B", () => {
    const savedA = base();
    const backupA = { form: savedA, base_snapshot: snapshot(savedA) };
    const savedB = { ...savedA, prescricao_orientacoes: "Correcao salva pela sessao B" };
    const result = assessAtendimentoBackup(savedB, backupA, snapshot);
    expect(result.mode).toBe("clean");
    expect(result.candidate).toBe(savedB);
    expect(result.candidate.prescricao_orientacoes).toBe("Correcao salva pela sessao B");
  });

  it("recupera edicao nao salva somente quando servidor ainda corresponde a sua base", () => {
    const saved = base();
    const pending = { ...saved, anamnese: "Texto digitado sem rede" };
    const result = assessAtendimentoBackup(saved, { form: pending, base_snapshot: snapshot(saved) }, snapshot);
    expect(result.mode).toBe("automatic");
    expect(result.candidate.anamnese).toBe(pending.anamnese);
  });

  it("preserva texto local divergente para comparacao sem aplica-lo automaticamente", () => {
    const initial = base();
    const local = { ...initial, prescricao_orientacoes: "Texto nao salvo da A" };
    const backup = { form: local, base_snapshot: snapshot(initial), updated_at: "2099-01-01T00:00:00" };
    const serializedBefore = JSON.stringify(backup);
    const savedB = { ...initial, prescricao_orientacoes: "Texto corrigido pela B" };
    const result = assessAtendimentoBackup(savedB, backup, snapshot);
    expect(result.mode).toBe("review");
    expect(JSON.stringify(backup)).toBe(serializedBefore);
    expect(result.candidate.prescricao_orientacoes).toBe(local.prescricao_orientacoes);
    const diff = atendimentoBackupDifferences(savedB, result.candidate, snapshot);
    expect(diff).toEqual([expect.objectContaining({ campo: "prescricao", salvo: expect.objectContaining({ orientacoes_gerais: "Texto corrigido pela B" }), local: expect.objectContaining({ orientacoes_gerais: "Texto nao salvo da A" }) })]);
    expect(savedB.prescricao_orientacoes).toBe("Texto corrigido pela B");
  });

  it("backup legado sem baseline exige revisao mesmo que seu relogio pareca novo", () => {
    const saved = base();
    const result = assessAtendimentoBackup(saved, { form: { ...saved, anamnese: "Texto legado", status: "Triagem" }, updated_at: "2099-12-31T23:59:59" }, snapshot);
    expect(result.mode).toBe("review");
    expect(result.candidate).toMatchObject({ status: "Concluido", anamnese: "Texto legado", data_atendimento: saved.data_atendimento });
  });

  it("conclusao do encontro nao bloqueia texto local baseado no mesmo conteudo clinico", () => {
    const beforeClosing = { ...base(), status: "Triagem", consulta_concluida: 0 };
    const saved = base();
    const pending = { ...beforeClosing, anamnese: "Texto nao sincronizado", data_atendimento: "2026-10-10T10:00" };
    const result = assessAtendimentoBackup(saved, { form: pending, base_snapshot: snapshot(beforeClosing) }, snapshot);
    expect(result.mode).toBe("automatic");
    expect(result.candidate).toMatchObject({ status: "Concluido", consulta_concluida: 1, data_atendimento: saved.data_atendimento, anamnese: pending.anamnese });
  });

  it("nunca autoaplica copia de outro paciente ou receita", () => {
    const saved = base();
    const wrongPatient = { ...saved, paciente_id: "2", anamnese: "Outro paciente" };
    expect(assessAtendimentoBackup(saved, { form: wrongPatient, base_snapshot: snapshot(saved) }, snapshot)).toEqual({ mode: "review", candidate: saved });
    const otherRecipe = { ...saved, prescricao_alvo_id: 9 };
    expect(assessAtendimentoBackup(saved, { form: { ...otherRecipe, prescricao_orientacoes: "Outra receita" }, base_snapshot: snapshot(otherRecipe) }, snapshot).mode).toBe("review");
  });

  it("copia que ja foi sincronizada nao precisa novo autosave", () => {
    const previous = base();
    const saved = { ...previous, anamnese: "Texto ja salvo" };
    expect(assessAtendimentoBackup(saved, { form: saved, base_snapshot: snapshot(previous) }, snapshot)).toEqual({ mode: "clean", candidate: saved });
  });
});
