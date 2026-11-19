import { describe, expect, it } from "vitest";
import { buildEchoPreviousExamRows, isEchoPreviousExamResponse, type EchoExamSnapshot, type EchoPreviousExamResponse } from "./echo-previous-exam-comparison";

const snapshot = (id: number, date: string, medidas: Record<string, string>): EchoExamSnapshot =>
  ({ id, paciente_id: 7, status: "Finalizado", data_exame: date, medidas });
const m = { VE_tecnica_relatorio: "modo_m", DIVEd: "30", AE_Ao: "1.4", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" };
function response(): EchoPreviousExamResponse { return { estado: "disponivel", paciente_id: 7,
  atual: snapshot(20, "2026-10-27", m), anterior: snapshot(10, "2026-01-10", m), opcoes: [{ id: 10, data_exame: "2026-01-10" }] }; }

describe("comparação aritmética de exames registrados", () => {
  it("não produz linhas entre pacientes diferentes nem exames sem cronologia confirmada", () => {
    const c = snapshot(20, "2026-10-27", m), p = snapshot(10, "2026-01-10", m);
    for (const invalid of [{ ...p, paciente_id: 8 }, { ...p, id: 20 }, { ...p, data_exame: null }, { ...p, data_exame: c.data_exame }]) {
      expect(buildEchoPreviousExamRows(c, invalid)).toEqual([]);
    }
  });
  it("mostra apenas dimensões e AE/Ao e não modifica snapshots nem recalcula pelo peso atual", () => {
    const c = snapshot(20, "2026-10-27", { ...m, DIVEd: "32.5", AE_Ao: "1.3", FE_Teicholz: "80", DIVEd_normalizado: "1.8", Onda_E: "0.7" });
    const p = snapshot(10, "2026-01-10", m);
    const original = structuredClone([c, p]);
    expect(buildEchoPreviousExamRows(c, p)).toEqual([
      expect.objectContaining({ key: "DIVEd", current: "32,50 mm", previous: "30,00 mm", delta: "+2,50 mm", reason: "" }),
      expect.objectContaining({ key: "AE_Ao", delta: "-0,10", reason: "" }),
    ]);
    expect([c, p]).toEqual(original);
  });
  it("converte cm explícitos para comparar e mantém a origem visível", () => {
    const c = snapshot(20, "2026-10-27", { ...m, DIVEd: "3,2", unidade_confirmada_DIVEd: "cm" });
    const rows = buildEchoPreviousExamRows(c, snapshot(10, "2026-01-10", m));
    expect(rows[0]).toMatchObject({ current: "32,00 mm (3,2 cm de origem)", delta: "+2,00 mm" });
  });
  it("retém todo o contexto de 18 comprimentos para detectar unidade ambígua fora das linhas do VE", () => {
    const c = snapshot(20, "2026-10-27", { VE_tecnica_relatorio: "modo_m", DIVEd: "2", Aorta: "1", Atrio_esquerdo: "1.3" });
    const rows = buildEchoPreviousExamRows(c, snapshot(10, "2026-01-10", m));
    expect(rows[0]).toMatchObject({ current: "2 (unidade/valor a confirmar)", delta: "—", reason: "Unidade a confirmar" });
  });
  it.each(["", "cm.", "metros", "inferida"])("não transforma unidade explícita inválida %s em mm legado", (unit) => {
    const p = snapshot(10, "2026-01-10", { ...m, DIVEd: "3", unidade_confirmada_DIVEd: unit });
    expect(buildEchoPreviousExamRows(snapshot(20, "2026-10-27", m), p)[0]).toMatchObject({
      previous: "3 (unidade/valor a confirmar)", delta: "—", reason: "Unidade a confirmar",
    });
  });
  it.each(["", "2d"])("não compara o modo M quando a seleção anterior é %s", (technique) => {
    expect(buildEchoPreviousExamRows(snapshot(20, "2026-10-27", m), snapshot(10, "2026-01-10", { ...m, VE_tecnica_relatorio: technique }))[0])
      .toMatchObject({ previous: "30,00 mm", delta: "—", reason: "Técnica selecionada diferente ou não registrada" });
  });
  it.each(["eixo_curto", "eixo_longo"])("compara 2D na mesma vista %s", (view) => {
    const p = { DIVEd_2D: "33.53", VE_tecnica_relatorio: "2d", VE_vista_2D: view };
    const c = { ...p, DIVEd_2D: "34" };
    expect(buildEchoPreviousExamRows(snapshot(20, "2026-10-27", c), snapshot(10, "2026-01-10", p))[0].delta).toBe("+0,47 mm");
    for (const other of ["", "outra", view === "eixo_curto" ? "eixo_longo" : "eixo_curto"]) {
      expect(buildEchoPreviousExamRows(snapshot(20, "2026-10-27", c), snapshot(10, "2026-01-10", { ...p, VE_vista_2D: other }))[0].delta).toBe("—");
    }
  });
  it("mantém o valor visível e suprime diferenças com AE/Ao genérico vs sueco ou método não confirmado", () => {
    for (const method of ["", "outro", "2d_eixo_curto_diastole_inicial"]) {
      expect(buildEchoPreviousExamRows(snapshot(20, "2026-10-27", m), snapshot(10, "2026-01-10", { ...m, AE_Ao_metodo: method }))[1])
        .toMatchObject({ previous: "1.4", delta: "—", reason: "Método de AE/Ao diferente ou não confirmado" });
    }
  });
  it.each(["", "0", "-1", "NaN", "32 mm", "Infinity", "0x10", "0b10"])("não inventa diferença para valor inválido %s", (value) => {
    expect(buildEchoPreviousExamRows(snapshot(20, "2026-10-27", { ...m, DIVEd: value }), snapshot(10, "2026-01-10", m))[0].delta).toBe("—");
  });
});

describe("identidade e cronologia da resposta", () => {
  it("aceita o mesmo paciente e a seleção manual elegível, sem mutações", () => {
    const data = response(); const before = structuredClone(data);
    expect(isEchoPreviousExamResponse(data, 20, 7, null)).toBe(true);
    expect(isEchoPreviousExamResponse(data, 20, 7, 10)).toBe(true);
    expect(data).toEqual(before);
  });
  it("aceita exame concluído que passou ao estado Liberado no portal", () => {
    const published = response(); published.anterior!.status = "Liberado no portal";
    expect(isEchoPreviousExamResponse(published, 20, 7, null)).toBe(true);
    expect(isEchoPreviousExamResponse(published, 20, 7, 10)).toBe(true);
  });
  it("rejeita outro paciente em qualquer snapshot, ID obsoleto e seleção divergente", () => {
    for (const change of [
      (d: EchoPreviousExamResponse) => { d.paciente_id = 8; },
      (d: EchoPreviousExamResponse) => { d.atual.paciente_id = 8; },
      (d: EchoPreviousExamResponse) => { d.anterior!.paciente_id = 8; },
      (d: EchoPreviousExamResponse) => { d.atual.id = 21; },
      (d: EchoPreviousExamResponse) => { d.anterior!.status = "Rascunho"; },
      (d: EchoPreviousExamResponse) => { d.anterior!.data_exame = "2026-10-27"; },
      (d: EchoPreviousExamResponse) => { d.anterior!.data_exame = "2026-02-30"; },
      (d: EchoPreviousExamResponse) => { d.opcoes = []; },
      (d: EchoPreviousExamResponse) => { d.opcoes.push({ ...d.opcoes[0] }); },
      (d: EchoPreviousExamResponse) => { d.opcoes.push({ id: 9, data_exame: "2026-02-10" }); },
    ]) { const data = response(); change(data); expect(isEchoPreviousExamResponse(data, 20, 7, null)).toBe(false); }
    expect(isEchoPreviousExamResponse(response(), 20, 7, 11)).toBe(false);
    expect(isEchoPreviousExamResponse(null, 20, 7, null)).toBe(false);
  });
  it("exige escolha quando há dois laudos na data mais recente e aceita data atual ausente", () => {
    const data = response(); data.opcoes.push({ id: 11, data_exame: "2026-01-10" });
    expect(isEchoPreviousExamResponse(data, 20, 7, null)).toBe(false);
    expect(isEchoPreviousExamResponse(data, 20, 7, 10)).toBe(true);
    data.estado = "data_anterior_ambigua"; data.anterior = null;
    expect(isEchoPreviousExamResponse(data, 20, 7, null)).toBe(true);
    data.estado = "data_atual_ausente"; data.opcoes = []; data.atual.data_exame = null;
    expect(isEchoPreviousExamResponse(data, 20, 7, null)).toBe(true);
  });
});
