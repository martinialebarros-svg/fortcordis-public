"use client";

import { useState, useCallback, useEffect } from "react";
import api from "@/lib/axios";
import { getCanine2DReference } from "@/lib/echo-2d-reference";
import type { Echo2DView } from "@/lib/echo-2d-reference";
import { ComparacaoMedida, ReferenciaEco } from "../types/referencia-eco";
import { resolveEchoReferenceForMeasurements, selectEchoReferenceFromCatalog } from "@/lib/echo-reference-policy";
import { isCanineEchoSpecies, isFelineEchoSpecies, normalizeEchoSpecies } from "@/lib/echo-species";
import { canonicalEchoDiastolicKey, echoDiastolicReferences } from "@/lib/echo-diastolic-reference";
import { FELINE_DIASTOLIC_KEYS } from "@/lib/echo-feline-diastolic-reference";
import { lowWeightAgeContext, lowWeightEstimateText, makeLowWeightReference } from "@/lib/echo-low-weight-reference";

// Mapeamento de parâmetros das medidas para os campos da referência
// As chaves devem corresponder aos 'key' definidos na nova aba Medidas
// e aos nomes retornados pelo XML parser atualizado
const MAPEAMENTO_PARAMETROS: Record<string, { campo: string; nome: string; categoria: string }> = {
  // === VE - MODO M (DIÁSTOLE) ===
  DIVEd: { campo: "lvid_d", nome: "DIVEd (Diâmetro interno VE diástole)", categoria: "estrutural" },
  SIVd: { campo: "ivs_d", nome: "SIVd (Septo interventricular diástole)", categoria: "estrutural" },
  PLVEd: { campo: "lvpw_d", nome: "PLVEd (Parede livre VE diástole)", categoria: "estrutural" },
  
  // === VE - MODO M (SÍSTOLE) ===
  DIVES: { campo: "lvid_s", nome: "DIVÉs (Diâmetro interno VE sístole)", categoria: "estrutural" },
  SIVs: { campo: "ivs_s", nome: "SIVs (Septo interventricular sístole)", categoria: "estrutural" },
  PLVES: { campo: "lvpw_s", nome: "PLVÉs (Parede livre VE sístole)", categoria: "estrutural" },
  // O cadastro não identifica método 2D; manter a medida visível, sem aplicar limite de Modo M.
  DIVEd_2D: { campo: "", nome: "DIVEd 2D (Diâmetro interno VE diástole)", categoria: "estrutural" },
  DIVEd_normalizado_2D: { campo: "", nome: "DIVEd normalizado 2D (Visser)", categoria: "estrutural" },
  SIVd_2D: { campo: "", nome: "SIVd 2D (Septo interventricular diástole)", categoria: "estrutural" },
  PLVEd_2D: { campo: "", nome: "PLVEd 2D (Parede livre VE diástole)", categoria: "estrutural" },
  DIVES_2D: { campo: "", nome: "DIVEs 2D (Diâmetro interno VE sístole)", categoria: "estrutural" },
  SIVs_2D: { campo: "", nome: "SIVs 2D (Septo interventricular sístole)", categoria: "estrutural" },
  PLVES_2D: { campo: "", nome: "PLVEs 2D (Parede livre VE sístole)", categoria: "estrutural" },
  
  // === VOLUMES E FUNÇÃO ===
  VDF: { campo: "edv", nome: "VDF (Volume diastólico final)", categoria: "funcao" },
  VSF: { campo: "esv", nome: "VSF (Volume sistólico final)", categoria: "funcao" },
  FE_Teicholz: { campo: "", nome: "FE (Fração de ejeção - Teicholz)", categoria: "funcao" },
  DeltaD_FS: { campo: "fs", nome: "Delta D / %FS (Encurtamento)", categoria: "funcao" },
  VDF_2D: { campo: "", nome: "VDF 2D (Teichholz)", categoria: "funcao" },
  VSF_2D: { campo: "", nome: "VSF 2D (Teichholz)", categoria: "funcao" },
  FE_Teicholz_2D: { campo: "", nome: "FE 2D (Teichholz)", categoria: "funcao" },
  DeltaD_FS_2D: { campo: "", nome: "Delta D / %FS 2D (Encurtamento)", categoria: "funcao" },
  TAPSE: { campo: "tapse", nome: "TAPSE", categoria: "funcao" },
  MAPSE: { campo: "mapse", nome: "MAPSE", categoria: "funcao" },
  
  // === ÁTRIO ESQUERDO / AORTA ===
  Aorta: { campo: "ao", nome: "Aorta", categoria: "vasos" },
  Atrio_esquerdo: { campo: "la", nome: "Átrio Esquerdo", categoria: "vasos" },
  AE_Ao: { campo: "la_ao", nome: "AE/Ao", categoria: "vasos" },
  
  // === ARTÉRIA PULMONAR ===
  AP: { campo: "ap", nome: "AP (Artéria pulmonar)", categoria: "vasos" },
  AP_Ao: { campo: "ap_ao", nome: "AP/Ao", categoria: "vasos" },
  
  // === DIASTÓLICA ===
  Onda_E: { campo: "mv_e", nome: "Onda E", categoria: "doppler" },
  Onda_A: { campo: "mv_a", nome: "Onda A", categoria: "doppler" },
  E_A: { campo: "mv_ea", nome: "E/A", categoria: "doppler" },
  TD: { campo: "mv_dt", nome: "TD (Tempo desaceleração)", categoria: "doppler" },
  TRIV: { campo: "ivrt", nome: "TRIV", categoria: "doppler" },
  e_doppler: { campo: "tdi_e", nome: "e' (Doppler tecidual, m/s)", categoria: "doppler" },
  a_doppler: { campo: "tdi_a", nome: "a' (Doppler tecidual, m/s)", categoria: "doppler" },
  E_E_linha: { campo: "e_e_linha", nome: "E/E'", categoria: "doppler" },
  doppler_tecidual_relacao: { campo: "", nome: "e'/a'", categoria: "doppler" },
  E_TRIV: { campo: "", nome: "E/TRIV", categoria: "doppler" },
  
  // === DOPPLER - SAÍDAS ===
  Vmax_aorta: { campo: "vmax_ao", nome: "Vmax Aorta", categoria: "doppler" },
  Vmax_pulmonar: { campo: "vmax_pulm", nome: "Vmax Pulmonar", categoria: "doppler" },
  
  // === NOMES ANTIGOS (para compatibilidade com XMLs antigos e banco) ===
  LVIDd: { campo: "lvid_d", nome: "DIVEd (Diâmetro interno VE diástole)", categoria: "estrutural" },
  LVIDs: { campo: "lvid_s", nome: "DIVÉs (Diâmetro interno VE sístole)", categoria: "estrutural" },
  IVSd: { campo: "ivs_d", nome: "SIVd (Septo interventricular diástole)", categoria: "estrutural" },
  IVSs: { campo: "ivs_s", nome: "SIVs (Septo interventricular sístole)", categoria: "estrutural" },
  LVPWd: { campo: "lvpw_d", nome: "PLVEd (Parede livre VE diástole)", categoria: "estrutural" },
  LVPWs: { campo: "lvpw_s", nome: "PLVÉs (Parede livre VE sístole)", categoria: "estrutural" },
  FS: { campo: "", nome: "Delta D / %FS (método não identificado)", categoria: "funcao" },
  EF: { campo: "", nome: "FE (método não identificado)", categoria: "funcao" },
  EDV: { campo: "edv", nome: "VDF (Volume diastólico final)", categoria: "funcao" },
  ESV: { campo: "esv", nome: "VSF (Volume sistólico final)", categoria: "funcao" },
  SV: { campo: "sv", nome: "SV (Volume sistólico)", categoria: "funcao" },
  Ao: { campo: "ao", nome: "Aorta", categoria: "vasos" },
  LA: { campo: "la", nome: "Átrio Esquerdo", categoria: "vasos" },
  LA_Ao: { campo: "la_ao", nome: "AE/Ao", categoria: "vasos" },
  MV_E: { campo: "mv_e", nome: "Onda E", categoria: "doppler" },
  MV_A: { campo: "mv_a", nome: "Onda A", categoria: "doppler" },
  MV_E_A: { campo: "mv_ea", nome: "E/A", categoria: "doppler" },
  MV_DT: { campo: "mv_dt", nome: "TD (Tempo desaceleração)", categoria: "doppler" },
  IVRT: { campo: "ivrt", nome: "TRIV", categoria: "doppler" },
  Vmax_Ao: { campo: "vmax_ao", nome: "Vmax Aorta", categoria: "doppler" },
  Vmax_Pulm: { campo: "vmax_pulm", nome: "Vmax Pulmonar", categoria: "doppler" },
};

const PAREDES_2D = new Set(["SIVd_2D", "SIVs_2D", "PLVEd_2D", "PLVES_2D"]);
const TEICHOLZ_2D = new Set(["VDF_2D", "VSF_2D", "FE_Teicholz_2D"]);
const DIASTOLIC_KEYS = new Set<string>(FELINE_DIASTOLIC_KEYS);

/** Shared publication evidence works without a weight catalog. Only a genuine
 * individual reference interval receives a numerical comparison status. */
export function compararMedidasDiastolicas(
  medidas: Record<string, string>, especie: string,
): Record<string, ComparacaoMedida> {
  // Explicit canonical entries also win when cleared or invalid; retain history.
  const values = { ...medidas };
  for (const [key, value] of Object.entries(medidas)) {
    const canonical = canonicalEchoDiastolicKey(key);
    if (!Object.hasOwn(values, canonical)) values[canonical] = value;
  }
  const references = echoDiastolicReferences(values, especie);
  const comparisons: Record<string, ComparacaoMedida> = {};
  for (const [key, reference] of Object.entries(references)) {
    const mapping = MAPEAMENTO_PARAMETROS[key];
    if (!mapping) continue;
    const value = values[key];
    const numeric = Number(String(value ?? "").replace(",", "."));
    let status: ComparacaoMedida["status"] = "nao_avaliado";
    let interpretation = reference.kind === "descriptive"
      ? "Dados descritivos; sem classificação automática" : reference.note;
    const interval = reference.kind === "reference_interval" && typeof reference.min === "number"
      && typeof reference.max === "number" && Number.isFinite(numeric);
    if (interval) {
      status = numeric < reference.min! ? "diminuido" : numeric > reference.max! ? "aumentado" : "normal";
      interpretation = status === "diminuido" ? "Abaixo do intervalo publicado"
        : status === "aumentado" ? "Acima do intervalo publicado" : "Dentro do intervalo publicado";
      interpretation += "; interpretar com os demais achados do exame";
    }
    comparisons[key] = {
      nome: mapping.nome, valor_medido: reference.kind === "uninterpretable" ? "Não mensurável" : value,
      referencia_min: interval ? reference.min! : null, referencia_max: interval ? reference.max! : null,
      referencia_texto: reference.text, referencia_tipo: reference.kind, estatistica: reference.statistic,
      fonte: reference.source, doi: reference.doi, nota_referencia: reference.note, status, interpretacao: interpretation, categoria: "doppler",
    };
  }
  return comparisons;
}

/** Existing callers keep the feline-only contract. */
export function compararMedidasDiastolicasFelinas(medidas: Record<string, string>, especie: string) {
  return isFelineEchoSpecies(especie) ? compararMedidasDiastolicas(medidas, especie) : {};
}

function motivoSemFaixa2D(
  key: string,
  especie: string,
  pesoPacienteKg: number | undefined,
  plano2D: Echo2DView | "",
  fsCompativelComPar: boolean,
  age?: unknown,
): string {
  if (PAREDES_2D.has(key)) return "Sem intervalo 2D por peso para esta espessura nas fontes adotadas";
  if (TEICHOLZ_2D.has(key)) return "Teichholz: intervalos 2D de Simpson não são aplicáveis";
  if (!isCanineEchoSpecies(especie)) return "Sem faixa 2D desta população nas fontes adotadas";
  if (lowWeightAgeContext(age) === "juvenile") return "Faixa 2D de cães adultos não aplicável à idade em crescimento";
  if (!plano2D) return "Confirme cão adulto e vista 2D para comparar";
  if (!Number.isFinite(pesoPacienteKg) || pesoPacienteKg === undefined || pesoPacienteKg < 2.6 || pesoPacienteKg > 67.8) {
    return "Peso fora da população estudada (2,6 a 67,8 kg)";
  }
  if (key === "DeltaD_FS_2D" && !fsCompativelComPar) {
    return "Encurtamento exige DIVEd e DIVEs 2D compatíveis";
  }
  return "Sem faixa 2D aplicável nas fontes adotadas";
}

export function compararMedidasComReferencia(
  medidas: Record<string, string>,
  referencia: ReferenciaEco,
  plano2D: Echo2DView | "" = "",
  pesoPacienteKg?: number,
): Record<string, ComparacaoMedida> {
  const comparacoes: Record<string, ComparacaoMedida> = {};
  const referenciaSegura = resolveEchoReferenceForMeasurements(referencia, medidas, pesoPacienteKg)!;
  const diastolicComparisons = compararMedidasDiastolicas(medidas, referencia.especie);

  Object.entries(medidas).forEach(([key, valor]) => {
    const canonical = canonicalEchoDiastolicKey(key);
    if (DIASTOLIC_KEYS.has(canonical)) {
      // Never resurrect a cleared alias through generic catalogue comparison.
      if (diastolicComparisons[canonical]) comparacoes[canonical] = diastolicComparisons[canonical];
      return;
    }
    if (!valor || valor.trim() === "") return;
    const mapeamento = MAPEAMENTO_PARAMETROS[key];
    if (!mapeamento) return;

    const valorNumerico = parseFloat(valor.replace(",", "."));
    if (isNaN(valorNumerico)) return;

    const minKey = `${mapeamento.campo}_min` as keyof ReferenciaEco;
    const maxKey = `${mapeamento.campo}_max` as keyof ReferenciaEco;

    const lvidD2D = Number.parseFloat(String(medidas.DIVEd_2D ?? "").replace(",", "."));
    const lvidS2D = Number.parseFloat(String(medidas.DIVES_2D ?? "").replace(",", "."));
    const fsDoPar = lvidD2D > 0 && lvidS2D > 0 && lvidS2D <= lvidD2D
      ? ((lvidD2D - lvidS2D) / lvidD2D) * 100
      : null;
    const fsCompativelComPar = key !== "DeltaD_FS_2D" ||
      (fsDoPar !== null && Math.abs(valorNumerico - fsDoPar) <= 1);
    const faixa2D = isCanineEchoSpecies(referencia.especie) && fsCompativelComPar
      ? getCanine2DReference(key, pesoPacienteKg, plano2D, referenciaSegura.patient_age)
      : null;
    const metadados = referenciaSegura.range_metadata?.[mapeamento.campo];
    const podeComparar = mapeamento.campo !== "fs" || Boolean(referenciaSegura.fs_source);
    const refMinRaw = faixa2D?.min ?? (mapeamento.campo && podeComparar ? referenciaSegura[minKey] as number | null | undefined : null);
    const refMaxRaw = faixa2D?.max ?? (mapeamento.campo && podeComparar ? referenciaSegura[maxKey] as number | null | undefined : null);
    let refMin = typeof refMinRaw === "number" ? refMinRaw : null;
    let refMax = typeof refMaxRaw === "number" ? refMaxRaw : null;
    if (key === "e_doppler" || key === "a_doppler") {
      refMin = refMin === null ? null : refMin / 100;
      refMax = refMax === null ? null : refMax / 100;
    }
    const estimate = lowWeightEstimateText(metadados);
    if (estimate) {
      comparacoes[key] = { nome: mapeamento.nome, valor_medido: valor,
        referencia_min: null, referencia_max: null, referencia_texto: estimate,
        status: "nao_avaliado", interpretacao: metadados?.reason || "Estimativa; sem comparação automática",
        categoria: mapeamento.categoria, fonte: metadados?.source, doi: metadados?.doi, metadados };
      return;
    }

    if (
      refMin === null ||
      refMax === null ||
      (refMin === 0 && refMax === 0)
    ) {
      comparacoes[key] = {
        nome: mapeamento.nome,
        valor_medido: valor,
        referencia_min: refMin,
        referencia_max: refMax,
        status: "nao_avaliado",
        interpretacao: key.endsWith("_2D")
          ? motivoSemFaixa2D(key, referencia.especie, pesoPacienteKg, plano2D, fsCompativelComPar, referenciaSegura.patient_age)
          : metadados?.reason || "Faixa não cadastrada",
        categoria: mapeamento.categoria,
        fonte: metadados?.source,
        doi: metadados?.doi,
        metadados,
      };
      return;
    }

    let status: ComparacaoMedida["status"];
    let interpretacao: string;

    const calculated = !faixa2D && metadados?.model_weight_kg != null
      && ["allometric", "interpolated"].includes(metadados.calculation || "");
    const tipoFaixa = faixa2D ? "2D publicada" : metadados?.status === "published" ? "publicada" : "cadastrada";
    if (valorNumerico < refMin) {
      status = "diminuido";
      interpretacao = calculated ? `Abaixo dos limites calculados (< ${refMin})` : `Abaixo da faixa ${tipoFaixa} (< ${refMin})`;
    } else if (valorNumerico > refMax) {
      status = "aumentado";
      interpretacao = calculated ? `Acima dos limites calculados (> ${refMax})` : `Acima da faixa ${tipoFaixa} (> ${refMax})`;
    } else {
      status = "normal";
      interpretacao = calculated ? "Dentro dos limites calculados" : `Dentro da faixa ${tipoFaixa}`;
    }

    comparacoes[key] = {
      nome: mapeamento.nome,
      valor_medido: valor,
      referencia_min: refMin,
      referencia_max: refMax,
      status,
      interpretacao,
      categoria: mapeamento.categoria,
      fonte: faixa2D?.source ?? metadados?.source,
      doi: metadados?.doi,
      metadados,
    };
  });

  return { ...comparacoes, ...diastolicComparisons };
}

export function useReferenciaEco() {
  const [loading, setLoading] = useState(false);

  const buscarReferencia = useCallback(async (especie: string, peso: number, idade?: string | null): Promise<ReferenciaEco | null> => {
    const especieNormalizada = normalizeEchoSpecies(especie);
    const pesoNormalizado = Number(peso);
    if (!especieNormalizada || !Number.isFinite(pesoNormalizado) || pesoNormalizado <= 0) {
      return null;
    }

    try {
      setLoading(true);
      const url = `/referencias-eco/buscar/${encodeURIComponent(especieNormalizada)}/${pesoNormalizado}`;
      const response = idade === undefined ? await api.get(url) : await api.get(url, { params: { idade } });
      const reference = response.data || makeLowWeightReference(especieNormalizada, pesoNormalizado, 0, {}, idade);
      return resolveEchoReferenceForMeasurements(reference, {}, pesoNormalizado, idade);
    } catch (error) {
      console.warn("Falha na busca direta de referencia; tentando fallback por listagem.", error);
      try {
        const response = await api.get(
          `/referencias-eco?especie=${encodeURIComponent(especieNormalizada)}`
        );
        const items = Array.isArray(response.data?.items) ? (response.data.items as ReferenciaEco[]) : [];
        return selectEchoReferenceFromCatalog(items, pesoNormalizado, especieNormalizada, idade);
      } catch (fallbackError) {
        console.error("Erro ao buscar referencia:", fallbackError);
        return resolveEchoReferenceForMeasurements(makeLowWeightReference(especieNormalizada, pesoNormalizado, 0, {}, idade), {}, pesoNormalizado, idade);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const compararMedidas = useCallback(compararMedidasComReferencia, []);

  return {
    buscarReferencia,
    compararMedidas,
    loading,
  };
}

// Hook legado para compatibilidade
export function useReferenciaEcoLegacy(especie: string, pesoKg?: number) {
  const [referencia, setReferencia] = useState<ReferenciaEco | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { buscarReferencia } = useReferenciaEco();

  useEffect(() => {
    let ativo = true;
    if (!pesoKg || !especie) {
      setReferencia(null);
      return;
    }
    const carregar = async () => {
      setLoading(true);
      const ref = await buscarReferencia(especie, pesoKg);
      if (!ativo) return;
      setReferencia(resolveEchoReferenceForMeasurements(ref, {}, pesoKg));
      setError(ref ? null : "Referência não encontrada");
      setLoading(false);
    };
    void carregar();
    return () => { ativo = false; };
  }, [especie, pesoKg, buscarReferencia]);

  const interpretarMedida = (
    valor: number | undefined,
    parametro: string
  ): { status: "normal" | "alterado" | "nao_avaliado"; mensagem: string } => {
    if (!referencia || valor === undefined || valor === null) {
      return { status: "nao_avaliado", mensagem: "Sem referência" };
    }

    const minKey = `${parametro}_min` as keyof ReferenciaEco;
    const maxKey = `${parametro}_max` as keyof ReferenciaEco;
    
    const min = referencia[minKey] as number | undefined;
    const max = referencia[maxKey] as number | undefined;

    if (typeof min !== "number" || typeof max !== "number" || !Number.isFinite(min) || !Number.isFinite(max)
        || (parametro === "fs" && !referencia.fs_source)) {
      return { status: "nao_avaliado", mensagem: "Sem referência" };
    }

    if (valor < min) {
      return { status: "alterado", mensagem: `Abaixo da faixa (< ${min})` };
    } else if (valor > max) {
      return { status: "alterado", mensagem: `Acima da faixa (> ${max})` };
    } else {
      return { status: "normal", mensagem: "Dentro da faixa" };
    }
  };

  const getFaixaReferencia = (parametro: string): string => {
    if (!referencia) return "-";
    
    const minKey = `${parametro}_min` as keyof ReferenciaEco;
    const maxKey = `${parametro}_max` as keyof ReferenciaEco;
    
    const min = referencia[minKey] as number | undefined;
    const max = referencia[maxKey] as number | undefined;

    if (typeof min !== "number" || typeof max !== "number" || !Number.isFinite(min) || !Number.isFinite(max)
        || (parametro === "fs" && !referencia.fs_source)) return "-";
    return `${min} - ${max}`;
  };

  return {
    referencia,
    loading,
    error,
    interpretarMedida,
    getFaixaReferencia,
  };
}

// Mapeamento de parâmetros do XML para os campos da referência (compatibilidade)
// Inclui novos nomes e nomes antigos para retrocompatibilidade
export const mapeamentoParametros: Record<string, string> = {
  // Novos nomes
  "DIVEd": "lvid_d",
  "DIVES": "lvid_s",
  "SIVd": "ivs_d",
  "SIVs": "ivs_s",
  "PLVEd": "lvpw_d",
  "PLVES": "lvpw_s",
  "VDF": "edv",
  "VSF": "esv",
  // FE Teichholz e medidas 2D não têm intervalo validado no cadastro.
  "DeltaD_FS": "fs",
  "Aorta": "ao",
  "Atrio_esquerdo": "la",
  "AE_Ao": "la_ao",
  "Onda_E": "mv_e",
  "Onda_A": "mv_a",
  "E_A": "mv_ea",
  "TD": "mv_dt",
  "TRIV": "ivrt",
  "Vmax_aorta": "vmax_ao",
  "Vmax_pulmonar": "vmax_pulm",
  // Nomes antigos (retrocompatibilidade)
  "LVIDd": "lvid_d",
  "LVIDs": "lvid_s",
  "IVSd": "ivs_d",
  "IVSs": "ivs_s",
  "LVPWd": "lvpw_d",
  "LVPWs": "lvpw_s",
  "Ao": "ao",
  "LA": "la",
  "LA_Ao": "la_ao",
  "Vmax_Ao": "vmax_ao",
  "Vmax_Pulm": "vmax_pulm",
  "MV_E": "mv_e",
  "MV_A": "mv_a",
  "MV_E_A": "mv_ea",
  "EDV": "edv",
  "ESV": "esv",
  "SV": "sv",
};
