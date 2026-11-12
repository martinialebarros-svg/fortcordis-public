export type StatusSinalVital = "baixo" | "alto";

interface FaixaReferencia {
  min: number;
  max: number;
}

type EspecieSuportada = "Canina" | "Felina";

const FAIXA_TEMPERATURA: Record<EspecieSuportada, FaixaReferencia> = {
  Canina: { min: 37.5, max: 39.2 },
  Felina: { min: 38.0, max: 39.2 },
};

const FAIXA_FREQUENCIA_CARDIACA: Record<EspecieSuportada, FaixaReferencia> = {
  Canina: { min: 60, max: 140 },
  Felina: { min: 140, max: 220 },
};

const FAIXA_FREQUENCIA_RESPIRATORIA: Record<EspecieSuportada, FaixaReferencia> = {
  Canina: { min: 10, max: 30 },
  Felina: { min: 20, max: 30 },
};

const FAIXA_SATURACAO_OXIGENIO: FaixaReferencia = { min: 95, max: 100 };

function normalizarEspecie(especie: string | null | undefined): EspecieSuportada | null {
  const valor = (especie || "").trim().toLowerCase();
  if (valor.startsWith("can")) return "Canina";
  if (valor.startsWith("fel")) return "Felina";
  return null;
}

function avaliarContraFaixa(valor: number, faixa: FaixaReferencia): StatusSinalVital | null {
  if (valor < faixa.min) return "baixo";
  if (valor > faixa.max) return "alto";
  return null;
}

// Faixas basicas de referencia (adulto, canino/felino) usadas so como sinal visual
// na triagem - nao substituem avaliacao clinica.
export function avaliarTemperatura(
  valor: number | null | undefined,
  especie: string | null | undefined
): StatusSinalVital | null {
  const especieNormalizada = normalizarEspecie(especie);
  if (valor == null || !especieNormalizada) return null;
  return avaliarContraFaixa(valor, FAIXA_TEMPERATURA[especieNormalizada]);
}

export function avaliarFrequenciaCardiaca(
  valor: number | null | undefined,
  especie: string | null | undefined
): StatusSinalVital | null {
  const especieNormalizada = normalizarEspecie(especie);
  if (valor == null || !especieNormalizada) return null;
  return avaliarContraFaixa(valor, FAIXA_FREQUENCIA_CARDIACA[especieNormalizada]);
}

export function avaliarFrequenciaRespiratoria(
  valor: number | null | undefined,
  especie: string | null | undefined
): StatusSinalVital | null {
  const especieNormalizada = normalizarEspecie(especie);
  if (valor == null || !especieNormalizada) return null;
  return avaliarContraFaixa(valor, FAIXA_FREQUENCIA_RESPIRATORIA[especieNormalizada]);
}

// SpO2 usa um unico limiar clinico, sem variacao por especie.
export function avaliarSaturacaoOxigenio(valor: number | null | undefined): StatusSinalVital | null {
  if (valor == null) return null;
  return avaliarContraFaixa(valor, FAIXA_SATURACAO_OXIGENIO);
}
