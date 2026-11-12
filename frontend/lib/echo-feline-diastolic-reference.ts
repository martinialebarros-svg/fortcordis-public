import { isFelineEchoSpecies } from "./echo-species";

/** Descriptive feline cohorts, never individual reference intervals or grades. */
import type { EchoDiastolicReference } from "./echo-diastolic-reference-types";
export type FelineDiastolicReference = Omit<EchoDiastolicReference, "kind" | "min" | "max"> & {
  kind: "descriptive" | "uninterpretable" | "unconfirmed";
};

const ALIASES: Record<string, string> = {
  MV_E: "Onda_E", MV_A: "Onda_A", MV_E_A: "E_A", MV_DT: "TD", IVRT: "TRIV", MV_E_TRIV: "E_TRIV",
  TDI_e: "e_doppler", TDI_a: "a_doppler", EEp: "E_E_linha",
};
export const FELINE_DIASTOLIC_KEYS = [
  "Onda_E", "Onda_A", "E_A", "TD", "TRIV", "E_TRIV",
  "e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha",
] as const;

export function canonicalFelineDiastolicKey(key: string): string {
  return ALIASES[key] ?? key;
}

const DISATIAN = {
  source: "Disatian et al. (2008)", doi: "10.1111/j.1939-1676.2008.0066.x",
  bibliography: "Disatian et al. (2008). Association of Age and Heart Rate with Pulsed-Wave Doppler Measurements in Healthy, Nonsedated Cats. DOI: 10.1111/j.1939-1676.2008.0066.x.",
};
const SOARES = {
  source: "Soares et al. (2005)", doi: "10.1590/S0103-84782005000600020",
  bibliography: "Soares et al. (2005). Índices ecodopplercardiográficos de função diastólica de gatos saudáveis não sedados. DOI: 10.1590/S0103-84782005000600020.",
};
const WARD = {
  source: "Ward et al. (2012)", doi: "10.1177/1098612X12447729",
  bibliography: "Ward et al. (2012). Effects of sedation on echocardiographic variables of left atrial and left ventricular function in healthy cats. DOI: 10.1177/1098612X12447729.",
};
const KIATSILAPANAN = {
  source: "Kiatsilapanan & Surachetpong (2020)", doi: "10.1186/s12917-020-02557-3",
  bibliography: "Kiatsilapanan & Surachetpong (2020). Assessment of left atrial function in feline hypertrophic cardiomyopathy by using two-dimensional speckle tracking echocardiography. DOI: 10.1186/s12917-020-02557-3.",
};
const DESCRIPTIVE_NOTE = "Média ± DP da população estudada; não é intervalo individual de normalidade. Interprete com os demais achados.";

export function felineDiastolicReferences(
  measurements: Record<string, string>, species: string,
): Record<string, FelineDiastolicReference> {
  if (!isFelineEchoSpecies(species)) return {};
  const values: Record<string, string> = {};
  for (const [key, value] of Object.entries(measurements)) {
    const canonical = canonicalFelineDiastolicKey(key);
    if (key === canonical || !Object.hasOwn(values, canonical)) values[canonical] = value;
  }
  const result: Record<string, FelineDiastolicReference> = {};
  for (const key of FELINE_DIASTOLIC_KEYS) {
    const number = Number(String(values[key] ?? "").replace(",", "."));
    if (!Number.isFinite(number) || number <= 0) continue;
    result[key] = {
      text: "—", source: "", doi: "", statistic: "",
      note: "Confirme a técnica e se as ondas são separadamente mensuráveis. A classificação diastólica exige interpretação integrada.",
      bibliography: "", kind: "unconfirmed",
    };
  }
  function descriptive(key: string, text: string, study: typeof DISATIAN, population: string) {
    if (!result[key]) return;
    result[key] = { ...study, text, statistic: "mean_sd", kind: "descriptive",
      note: `${population}. ${DESCRIPTIVE_NOTE}` };
  }
  const method = measurements.Diastolica_metodo;
  const confirmed = method === "felino_adulto_nao_sedado_pw_apical_clique_aortico"
    || method === "felino_adulto_nao_sedado_pw_apical_fim_fluxo";
  const trivClick = method === "felino_adulto_nao_sedado_pw_apical_clique_aortico"
    || method === "felino_adulto_nao_sedado_pw_clique_aortico";
  const trivEnd = method === "felino_adulto_nao_sedado_pw_apical_fim_fluxo"
    || method === "felino_adulto_nao_sedado_pw_fim_fluxo";
  if (!confirmed) {
    for (const key of ["Onda_E", "Onda_A", "E_A", "TD", "E_E_linha"]) {
      if (result[key]) result[key].note = "Confirme Doppler pulsado transmitral na vista apical esquerda de 4 câmaras, amostra nas pontas dos folhetos mitrais, paciente adulto não sedado e ondas separadas. A classificação diastólica exige interpretação integrada.";
    }
  }
  if (confirmed && measurements.Diastolica_ondas === "separadas") {
    descriptive("Onda_E", "0,70 ± 0,14 m/s", DISATIAN, "66 gatos saudáveis, não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras, nas pontas dos folhetos mitrais");
    descriptive("Onda_A", "0,65 ± 0,14 m/s", DISATIAN, "66 gatos saudáveis, não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras, nas pontas dos folhetos mitrais");
    descriptive("E_A", "1,12 ± 0,22", DISATIAN, "66 gatos saudáveis, não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras; ondas E e A separadas");
    descriptive("TD", "72,29 ± 9,56 ms", SOARES, "24 gatos adultos saudáveis, não sedados; Doppler pulsado transmitral na vista apical esquerda de 4 câmaras; desaceleração da onda E");
  }
  if (trivClick) {
    descriptive("TRIV", "46,2 ± 7,6 ms", DISATIAN, "87 gatos saudáveis, não sedados; TRIV em apical esquerdo de 5 câmaras, do início do clique de fechamento aórtico ao início do fluxo mitral");
  } else if (trivEnd) {
    descriptive("TRIV", "68,75 ± 19,14 ms", SOARES, "40 gatos adultos saudáveis, não sedados; TRIV em apical esquerdo de 5 câmaras, do fim do fluxo aórtico ao início do fluxo mitral");
  }
  const site = measurements.TDI_metodo;
  if (measurements.TDI_ondas === "separadas"
      && (site === "felino_pw_anel_lateral" || site === "felino_pw_anel_septal")) {
    const lateral = site === "felino_pw_anel_lateral";
    const study = lateral ? KIATSILAPANAN : WARD;
    const population = lateral
      ? "20 gatos saudáveis, não sedados; ondas fundidas excluídas; Doppler tecidual pulsado no anel lateral"
      : "7 gatos jovens (1–3 anos), saudáveis, antes da sedação; Doppler tecidual pulsado no anel septal";
    descriptive("e_doppler", lateral ? "0,11 ± 0,03 m/s" : "0,075 ± 0,026 m/s", study, population);
    descriptive("a_doppler", lateral ? "0,08 ± 0,03 m/s" : "0,061 ± 0,017 m/s", study, population);
    if (lateral) {
      descriptive("doppler_tecidual_relacao", "1,33 ± 0,31", study, population);
    } else if (result.doppler_tecidual_relacao) {
      result.doppler_tecidual_relacao.note = "Sem comparador septal reconciliado para e'/a' na fonte de Ward et al. (2012). O valor registrado é preservado; não derivar intervalo nem substituir pelo quociente das médias publicadas.";
    }
    if (confirmed && measurements.Diastolica_ondas === "separadas") {
      descriptive("E_E_linha", lateral ? "7,8 ± 2,92" : "8,7 ± 1,7", study, population);
    }
  }
  if (result.E_TRIV) result.E_TRIV.note = "Sem intervalo individual validado na população não sedada adotada. O índice depende da técnica e das condições de carga; não diagnostica insuficiência cardíaca isoladamente.";
  function fusion(keys: string[], text: string, note: string) {
    for (const key of keys) {
      result[key] = { text, note, source: "", doi: "", statistic: "", bibliography: "", kind: "uninterpretable" };
    }
  }
  if (measurements.Diastolica_ondas === "fundidas") {
    fusion(["Onda_E", "Onda_A", "E_A", "TD", "E_E_linha", "E_TRIV"],
      "Ondas E/A fundidas",
      "Ondas E e A não são separadamente mensuráveis; estes valores e relações não permitem comparação diastólica independente. Valores registrados preservados.");
  }
  if (measurements.TDI_ondas === "fundidas") {
    fusion(["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"],
      "Ondas e'/a' fundidas",
      "Ondas e' e a' não são separadamente mensuráveis; não interpretar suas velocidades ou relações isoladamente. Valores registrados preservados.");
  }
  return result;
}
