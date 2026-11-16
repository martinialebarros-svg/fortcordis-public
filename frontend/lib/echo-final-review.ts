import { hasAnyMeasurement, LV_2D_KEYS, LV_M_MODE_KEYS } from "./echo-derived-measurements";
import { canonicalEchoDiastolicKey } from "./echo-diastolic-reference";
import { findEchoNarrativeDiscrepancies } from "./echo-narrative-consistency";
import { evaluatePulmonaryProbability } from "./echo-pulmonary-probability";
import { isCanineEchoSpecies, normalizeEchoSpecies } from "./echo-species";
import { ambiguousEchoLengthKeys } from "./echo-unit-provenance";

export type EchoReviewTarget = "patient" | "technique" | "units" | "references" | "diastolic" | "pulmonary" | "qualitative" | "images";
export type EchoFinalReviewIssue = {
  key: string;
  title: string;
  message: string;
  kind: "attention" | "info";
  target: EchoReviewTarget;
};
export type EchoFinalReviewInput = {
  measurements: Record<string, string>;
  species: string;
  qualitative: object;
  conclusion: string;
  patientName: string;
  qualitativeApplied: boolean;
  images: ReadonlyArray<{ uploaded: boolean; included?: boolean }>;
};

/** Reuse existing acquisition and consistency policies. These are review cues,
 * never a diagnosis, a completeness certificate or a new emission gate. */
export function buildEchoFinalReviewIssues(input: EchoFinalReviewInput): EchoFinalReviewIssue[] {
  const { measurements: m, species, qualitative, conclusion, images } = input;
  const items: EchoFinalReviewIssue[] = [];
  const add = (key: string, title: string, message: string, target: EchoReviewTarget, kind: "attention" | "info" = "attention") =>
    items.push({ key, title, message, target, kind });
  const has = (...keys: string[]) => keys.some((key) => String(m[key] ?? "").trim() !== "");
  if (!input.patientName.trim()) add("patient-name", "Identificação do paciente", "Preencha o nome do paciente antes de emitir.", "patient");
  if (hasAnyMeasurement(m, LV_M_MODE_KEYS) && hasAnyMeasurement(m, LV_2D_KEYS)
      && !["modo_m", "2d"].includes(m.VE_tecnica_relatorio)) {
    add("lv-technique", "Técnica do ventrículo esquerdo", "Há medidas em Modo M e 2D. Escolha qual bloco será apresentado no PDF.", "technique");
  }
  const units = [...ambiguousEchoLengthKeys(m)];
  if (units.length) add("units", "Unidades a confirmar", `Confira cm ou mm nas medidas legadas: ${units.join(", ")}.`, "units");
  if (has("AE_Ao", "LA_Ao", "Aorta", "Atrio_esquerdo") && !m.AE_Ao_metodo) {
    add("la-ao-method", "Método de AE/Ao", "Confirme a vista e a fase de aquisição para consultar a referência correspondente.", "references");
  }
  if (isCanineEchoSpecies(species) && has("TAPSE") && !m.TAPSE_metodo) {
    add("tapse-method", "Método de TAPSE", "Confirme a técnica de obtenção para consultar a faixa aplicável.", "references");
  }
  if (isCanineEchoSpecies(species) && hasAnyMeasurement(m, LV_2D_KEYS) && !m.VE_vista_2D) {
    add("lv-2d-view", "Vista do VE em 2D", "Confirme a vista de obtenção para consultar a faixa 2D aplicável.", "references");
  }
  const knownSpecies = ["Canina", "Felina"].includes(normalizeEchoSpecies(species));
  const present = new Set(Object.entries(m).filter(([, value]) => {
    const number = Number(String(value).replace(",", "."));
    return Number.isFinite(number) && number > 0;
  }).map(([key]) => canonicalEchoDiastolicKey(key)));
  const flow = ["Onda_E", "Onda_A", "E_A", "TD", "TRIV", "E_TRIV", "E_E_linha"].some((key) => present.has(key));
  const tissue = ["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"].some((key) => present.has(key));
  if (knownSpecies && (flow || m.Diastolica_ondas)) {
    if (m.Diastolica_ondas === "fundidas") {
      add("flow-fusion", "Ondas E/A fundidas", "Picos individuais e relações dependentes serão omitidos como valores mensuráveis. Confira a descrição da limitação no PDF.", "diastolic", "info");
    } else if (flow && m.Diastolica_ondas !== "separadas") {
      add("flow-waves", "Ondas transmitrais E/A", "Confirme se as ondas estão separadas e mensuráveis ou fundidas; edição e reimportação podem exigir reconfirmação.", "diastolic");
    }
    if (flow && (m.Diastolica_ondas !== "fundidas" || present.has("TRIV")) && !m.Diastolica_metodo) add("flow-method", "Protocolo transmitral e TRIV", "Confirme a técnica de obtenção. Ausência de faixa compatível não indica anormalidade.", "references");
  }
  if (knownSpecies && (tissue || m.TDI_ondas)) {
    if (m.TDI_ondas === "fundidas") {
      add("tissue-fusion", "Ondas e′/a′ fundidas", "Picos teciduais e relações dependentes serão omitidos como valores mensuráveis. O fluxo transmitral é avaliado independentemente.", "diastolic", "info");
    } else if (tissue && m.TDI_ondas !== "separadas") {
      add("tissue-waves", "Ondas teciduais e′/a′", "Confirme se os picos teciduais estão separados e mensuráveis ou fundidos.", "diastolic");
    }
    if (tissue && m.TDI_ondas !== "fundidas" && !m.TDI_metodo) add("tissue-method", "Técnica e sítio do Doppler tecidual", "Confirme a técnica e o local de obtenção para consultar os valores publicados.", "references");
  }
  const pulmonary = evaluatePulmonaryProbability(m, species);
  if (pulmonary.active && pulmonary.status === "pending") {
    add("pulmonary-pending", "Avaliação de HP pendente", pulmonary.missing.join(" "), "pulmonary");
  } else if (pulmonary.active && pulmonary.status === "unsupported") {
    add("pulmonary-descriptive", "HP: registro descritivo", "A classificação canina não é aplicada a esta espécie. Confira os achados descritivos no PDF.", "pulmonary", "info");
  }
  if (!input.qualitativeApplied) add("qualitative-not-applied", "Análise estruturada não aplicada", "Confira o texto qualitativo que será apresentado antes da emissão.", "qualitative");
  if (!conclusion.trim()) add("conclusion", "Conclusão vazia", "Confira e preencha a conclusão do exame.", "qualitative");
  for (const [index, discrepancy] of findEchoNarrativeDiscrepancies(m, qualitative, conclusion, species).entries()) {
    add(`consistency-${discrepancy.key}-${index}`, "Coerência entre texto e medidas", discrepancy.message, "qualitative");
  }
  const pending = images.filter((image) => !image.uploaded).length;
  if (pending) add("images-pending", "Envio de imagens pendente", `${pending} imagem(ns) precisam ser reenviadas ou removidas antes de emitir.`, "images");
  if (!images.some((image) => image.uploaded && image.included !== false)) {
    add("images-empty", "PDF sem imagens selecionadas", "Nenhuma imagem enviada está selecionada para inclusão no PDF.", "images");
  }
  return items;
}
