import { normalizeEchoSpecies } from "./echo-species";
import { canonicalFelineDiastolicKey, FELINE_DIASTOLIC_KEYS } from "./echo-feline-diastolic-reference";
import type { EchoDiastolicReference } from "./echo-diastolic-reference-types";

const CHOMPOOSAN = {
  source: "Chompoosan et al. (2022)", doi: "10.1111/jsap.13472",
  bibliography: "Chompoosan et al. (2022). Epidemiology of heart disease in English Bull Terriers and echocardiographic characteristics of mitral valve abnormalities. Tabela 3: controles saudáveis de múltiplas raças. DOI: 10.1111/jsap.13472.",
};
const PEREIRA = {
  source: "Pereira et al. (2009)", doi: "10.1590/S0100-736X2009000400003",
  bibliography: "Pereira et al. (2009). Doppler transmitral e TRIV em cães saudáveis. DOI: 10.1590/S0100-736X2009000400003.",
};
const CHOI = {
  source: "Choi et al. (2013)", doi: "10.4142/jvs.2013.14.1.85",
  bibliography: "Choi et al. (2013). Doppler tecidual pulsado do anel mitral septal em cães saudáveis. DOI: 10.4142/jvs.2013.14.1.85.",
};
const WESS = {
  source: "Wess et al. (2010)", doi: "10.1111/j.1939-1676.2009.0460.x",
  bibliography: "Wess et al. (2010). Doppler tecidual pulsado e colorido em cães saudáveis. DOI: 10.1111/j.1939-1676.2009.0460.x.",
};
export const CANINE_FLOW_METHODS = ["canino_nao_sedado_pw_apical", "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo"] as const;
export const CANINE_TDI_METHODS = ["canino_pw_anel_septal_choi", "canino_pw_basal_septal_wess", "canino_pw_basal_lateral_wess"] as const;

/** Never infer a protocol from the patient's measured value or a weight catalog.
 * The operator confirms the study population and acquisition for this exam. */
export function canineDiastolicReferences(
  measurements: Record<string, string>, species: string,
): Record<string, EchoDiastolicReference> {
  if (normalizeEchoSpecies(species) !== "Canina") return {};
  const values: Record<string, string> = {};
  for (const [key, value] of Object.entries(measurements)) {
    const canonical = canonicalFelineDiastolicKey(key);
    if (key === canonical || !Object.hasOwn(values, canonical)) values[canonical] = value;
  }
  const result: Record<string, EchoDiastolicReference> = {};
  for (const key of FELINE_DIASTOLIC_KEYS) {
    const value = Number(String(values[key] ?? "").replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) continue;
    result[key] = { text: "—", source: "", doi: "", statistic: "", bibliography: "", kind: "unconfirmed",
      note: "Confirme técnica, população estudada e separação das ondas para consultar os valores publicados. A interpretação diastólica exige os demais achados do exame." };
  }
  const flowConfirmed = CANINE_FLOW_METHODS.some((method) => measurements.Diastolica_metodo === method);
  const flowSeparate = measurements.Diastolica_ondas === "separadas";
  const tissueSeparate = measurements.TDI_ondas === "separadas";
  const descriptive = (key: string, text: string, study: typeof PEREIRA, population: string) => {
    if (!result[key]) return;
    result[key] = { ...study, text, statistic: "mean_sd", kind: "descriptive",
      note: `${population}. Média ± DP da população estudada; não é intervalo individual de normalidade. Interprete com os demais achados.` };
  };
  if (flowConfirmed && flowSeparate && result.Onda_E) {
    result.Onda_E = { ...CHOMPOOSAN, text: "IR95%: 0,51-1,10 m/s", statistic: "reference_interval_95", kind: "reference_interval", min: 0.51, max: 1.10,
      note: "Intervalo de referência de 95% (percentis 2,5–97,5): 120 cães saudáveis de 19 raças, não sedados e sem fármacos cardioativos; Doppler pulsado apical de 4 câmaras, amostra nas pontas dos folhetos mitrais, ondas separadas. FC observada no PW: 55–171 bpm; não é um intervalo clínico de FC. Posição numérica não determina diagnóstico." };
  }
  if (measurements.Diastolica_metodo === "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo") {
    const population = "40 cães saudáveis, não sedados, 2–6 anos, 4,2–37,4 kg; Doppler pulsado apical nas pontas dos folhetos mitrais; idade e frequência cardíaca influenciam parte dos parâmetros";
    if (flowSeparate) {
      descriptive("Onda_A", "0,487 ± 0,062 m/s", PEREIRA, population);
      descriptive("E_A", "1,533 ± 0,198", PEREIRA, population);
      descriptive("TD", "88,7 ± 9,2 ms", PEREIRA, population);
    }
    descriptive("TRIV", "80 ± 9 ms", PEREIRA, `${population}; TRIV na vista apical de 5 câmaras, do fim do fluxo aórtico ao início do fluxo mitral`);
  }
  const site = measurements.TDI_metodo;
  if (tissueSeparate && site === "canino_pw_anel_septal_choi") {
    const population = "45 cães saudáveis, não sedados, 1–9,6 anos, 1,3–14 kg; Doppler tecidual pulsado no anel mitral septal";
    descriptive("e_doppler", "0,0658 ± 0,0181 m/s", CHOI, population);
    descriptive("a_doppler", "0,0510 ± 0,0200 m/s", CHOI, population);
    descriptive("doppler_tecidual_relacao", "1,40 ± 0,40", CHOI, population);
    if (flowConfirmed && flowSeparate) descriptive("E_E_linha", "10,94 ± 3,27", CHOI, population);
  } else if (tissueSeparate && (site === "canino_pw_basal_septal_wess" || site === "canino_pw_basal_lateral_wess")) {
    const lateral = site === "canino_pw_basal_lateral_wess";
    const population = `71 cães saudáveis, não sedados, 1–14 anos, 3–55 kg; Doppler tecidual pulsado, amostra de 5 mm no segmento basal ${lateral ? "lateral" : "septal"} do VE, vista apical de 4 câmaras; não intercambiar com anel mitral ou Doppler colorido`;
    descriptive("e_doppler", lateral ? "0,1041 ± 0,0294 m/s" : "0,0741 ± 0,0146 m/s", WESS, population);
    descriptive("a_doppler", lateral ? "0,0906 ± 0,0247 m/s" : "0,0716 ± 0,0208 m/s", WESS, population);
  }
  if (result.E_TRIV) result.E_TRIV.note = "Sem intervalo individual genérico adotado. Os limiares publicados para E[cm/s]/TRIV[ms] dependem da cardiopatia e do desfecho estudado; não usar como faixa de normalidade nem diagnóstico isolado.";
  const fusion = (keys: string[], text: string, note: string) => {
    for (const key of keys) result[key] = { text, note, source: "", doi: "", statistic: "", bibliography: "", kind: "uninterpretable" };
  };
  if (measurements.Diastolica_ondas === "fundidas") fusion(
    ["Onda_E", "Onda_A", "E_A", "TD", "E_E_linha", "E_TRIV"], "Ondas E/A fundidas",
    "Ondas E e A não são separadamente mensuráveis; estes valores e relações não permitem comparação diastólica independente. Valores registrados preservados.");
  if (measurements.TDI_ondas === "fundidas") fusion(
    ["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"], "Ondas e'/a' fundidas",
    "Ondas e' e a' não são separadamente mensuráveis; não interpretar suas velocidades ou relações isoladamente. Valores registrados preservados.");
  return result;
}
