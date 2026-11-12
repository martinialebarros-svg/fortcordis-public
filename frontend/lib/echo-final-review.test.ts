import { describe, expect, it } from "vitest";
import { buildEchoFinalReviewIssues, type EchoFinalReviewInput } from "./echo-final-review";

const base = (measurements: Record<string, string> = {}, overrides: Partial<EchoFinalReviewInput> = {}): EchoFinalReviewInput => ({
  measurements, species: "Canina", qualitative: {}, conclusion: "Conclusão registrada pelo examinador.", patientName: "QA SINTÉTICO",
  qualitativeApplied: true, images: [{ uploaded: true, included: true }], ...overrides,
});
const keys = (input: EchoFinalReviewInput) => buildEchoFinalReviewIssues(input).map((item) => item.key);

describe("conferência final compartilhada do ecocardiograma", () => {
  it("não declara normalidade, preenche valores nem exige intervalos inexistentes", () => {
    const input = base({ E_TRIV: "0.55", Diastolica_metodo: "outro", Diastolica_ondas: "separadas" });
    const original = structuredClone(input);
    expect(buildEchoFinalReviewIssues(input)).toEqual([]);
    expect(input).toEqual(original);
  });
  it("reúne identificação, conclusão, análise e imagens sem bloquear por um novo critério", () => {
    const issues = buildEchoFinalReviewIssues(base({}, { patientName: " ", conclusion: " ", qualitativeApplied: false, images: [] }));
    expect(issues.map((item) => item.key)).toEqual(["patient-name", "qualitative-not-applied", "conclusion", "images-empty"]);
    expect(issues.map((item) => item.target)).toEqual(["patient", "qualitative", "qualitative", "images"]);
    expect(issues.every((item) => item.kind === "attention")).toBe(true);
  });
  it("distingue imagens excluídas do PDF e arquivos ainda não enviados", () => {
    expect(keys(base({}, { images: [{ uploaded: true, included: false }] }))).toEqual(["images-empty"]);
    expect(keys(base({}, { images: [{ uploaded: false }, { uploaded: true }] }))).toEqual(["images-pending"]);
  });
  it("aponta a técnica VE somente quando coexistem M e 2D sem escolha válida", () => {
    const m = { DIVEd: "20", DIVEd_2D: "21", VE_vista_2D: "eixo_curto" };
    expect(keys(base(m))).toContain("lv-technique");
    expect(keys(base({ ...m, VE_tecnica_relatorio: "2d" }))).not.toContain("lv-technique");
    expect(keys(base({ DIVEd: "20" }))).not.toContain("lv-technique");
  });
  it("reaproveita a ambiguidade de unidades e as confirmações existentes", () => {
    const m = { DIVEd: "2.1", SIVd: "0.5", PLVEd: "0.5" };
    const issue = buildEchoFinalReviewIssues(base(m)).find((item) => item.key === "units");
    expect(issue?.message).toContain("DIVEd, SIVd, PLVEd");
    expect(keys(base({ ...m, unidade_confirmada_DIVEd: "cm", unidade_confirmada_SIVd: "cm", unidade_confirmada_PLVEd: "cm" }))).not.toContain("units");
  });
  it("não cobra aquisição de medidas ausentes nem aplica critérios caninos a gatos", () => {
    expect(keys(base())).toEqual([]);
    expect(keys(base({ TAPSE: "7", DIVEd_2D: "20" }, { species: "Cat" }))).not.toEqual(expect.arrayContaining(["tapse-method", "lv-2d-view"]));
    expect(keys(base({ TAPSE: "7", DIVEd_2D: "20" }))).toEqual(["tapse-method", "lv-2d-view"]);
  });
  it.each(["Canina", "Felina", "Gato", "Cat"])("reconfirma ondas após editar/reimportar para %s", (species) => {
    const input = base({ MV_E: "0.7", TDI_e: "0.1", Diastolica_ondas: "nao_confirmadas" }, { species });
    expect(keys(input)).toEqual(expect.arrayContaining(["flow-waves", "flow-method", "tissue-waves", "tissue-method"]));
  });
  it("trata fusão confirmada como informação, sem exigir protocolos para picos omitidos", () => {
    const issues = buildEchoFinalReviewIssues(base({ Onda_E: "0.7", Onda_A: "0.5", e_doppler: "0.1", a_doppler: "0.1",
      Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" }, { species: "Felina" }));
    expect(issues.map((item) => item.key)).toEqual(["flow-fusion", "tissue-fusion"]);
    expect(issues.every((item) => item.kind === "info")).toBe(true);
    expect(issues[0].message).toContain("omitidos");
  });
  it("preserva a aquisição independente de TRIV mesmo com E/A fundidas", () => {
    expect(keys(base({ TRIV: "85", Diastolica_ondas: "fundidas" }))).toEqual(["flow-fusion", "flow-method"]);
  });
  it("reúne as discrepâncias existentes entre conclusão e medidas", () => {
    const issues = buildEchoFinalReviewIssues(base({ AE_Ao: "1.5", AE_Ao_metodo: "outro" }, { conclusion: "AE/Ao 2,5." }));
    expect(issues.some((item) => item.key.startsWith("consistency-AE_Ao") && item.target === "qualitative")).toBe(true);
  });

});
