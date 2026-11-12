import { FELINE_DIASTOLIC_KEYS } from "./echo-feline-diastolic-reference";

const DIASTOLIC_KEYS = new Set<string>(FELINE_DIASTOLIC_KEYS);

export interface QualitativaEcoLegada {
  valvas: string;
  camaras: string;
  funcao: string;
  pericardio: string;
  vasos: string;
  ad_vd: string;
}

export interface EcocardiogramaEstruturadoPersistido {
  versao: number;
  modo: string;
  usar_no_laudo: boolean;
  preset_id: number | null;
  preset_label: string;
  preset_textos: Record<string, string>;
  updated_at: string;
  textos: Record<string, string>;
}

interface AspectoEcoMeta {
  key: string;
  label: string;
  legacyField: keyof QualitativaEcoLegada | "conclusao";
}

const ASPECTOS_ECO_META: AspectoEcoMeta[] = [
  { key: "valva_mitral", label: "Valva mitral", legacyField: "valvas" },
  { key: "valva_aortica", label: "Valva aortica", legacyField: "valvas" },
  { key: "valva_tricuspide", label: "Valva tricuspide", legacyField: "valvas" },
  { key: "valva_pulmonar", label: "Valva pulmonar", legacyField: "valvas" },
  { key: "atrio_esquerdo", label: "Atrio esquerdo", legacyField: "camaras" },
  { key: "ventriculo_esquerdo", label: "Ventriculo esquerdo", legacyField: "camaras" },
  { key: "funcao_sistolica_ve", label: "Funcao sistolica do VE", legacyField: "funcao" },
  { key: "funcao_diastolica", label: "Funcao diastolica", legacyField: "funcao" },
  { key: "atrio_direito", label: "Atrio direito", legacyField: "ad_vd" },
  { key: "ventriculo_direito", label: "Ventriculo direito", legacyField: "ad_vd" },
  { key: "septos", label: "Septos", legacyField: "camaras" },
  { key: "aorta", label: "Aorta", legacyField: "vasos" },
  { key: "arteria_pulmonar", label: "Arteria pulmonar", legacyField: "vasos" },
  { key: "pericardio", label: "Pericardio", legacyField: "pericardio" },
  { key: "conclusao", label: "Conclusao", legacyField: "conclusao" },
];

export function criarQualitativaEcoLegadaVazia(): QualitativaEcoLegada {
  return {
    valvas: "",
    camaras: "",
    funcao: "",
    pericardio: "",
    vasos: "",
    ad_vd: "",
  };
}

export function extrairQualitativaEcoDaDescricao(descricao: string): QualitativaEcoLegada {
  const resultado = criarQualitativaEcoLegadaVazia();
  const linhas = String(descricao || "").split(/\r?\n/);
  let dentroDaSecao = false;
  let campoAtual: keyof QualitativaEcoLegada | null = null;
  let conteudo: string[] = [];

  const guardar = () => {
    if (campoAtual) resultado[campoAtual] = conteudo.join("\n").trim();
  };

  for (const linha of linhas) {
    if (/^\s*##/.test(linha)) {
      if (dentroDaSecao) break;
      const normalizada = linha.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
      dentroDaSecao = normalizada.includes("qualitativa") && normalizada.includes("avalia");
      continue;
    }
    if (!dentroDaSecao) continue;
    const marcador = linha.match(/^\s*-\s*(valvas|camaras|funcao|pericardio|vasos|ad_vd)\s*:\s*(.*)$/i);
    if (marcador) {
      guardar();
      campoAtual = marcador[1].toLowerCase() as keyof QualitativaEcoLegada;
      conteudo = marcador[2] ? [marcador[2]] : [];
    } else if (campoAtual) {
      conteudo.push(linha);
    }
  }
  guardar();
  return resultado;
}

export function criarEcocardiogramaEstruturadoInicial(): EcocardiogramaEstruturadoPersistido {
  return {
    versao: 1,
    modo: "teste",
    usar_no_laudo: false,
    preset_id: null,
    preset_label: "",
    preset_textos: {},
    updated_at: "",
    textos: {},
  };
}

export function temPresetDiastolicoFelinoAplicado(
  estado: EcocardiogramaEstruturadoPersistido
): boolean {
  return estado.preset_label.startsWith("Função diastólica felina:") &&
    Boolean(estado.textos.funcao_diastolica?.trim());
}

export function removerPresetDiastolicoFelino(
  estado: EcocardiogramaEstruturadoPersistido
): EcocardiogramaEstruturadoPersistido {
  if (!temPresetDiastolicoFelinoAplicado(estado)) return estado;
  const textos = { ...estado.textos };
  const preset_textos = { ...estado.preset_textos };
  delete textos.funcao_diastolica;
  delete preset_textos.funcao_diastolica;
  return {
    ...estado,
    preset_id: null,
    preset_label: "",
    preset_textos,
    textos,
    updated_at: new Date().toISOString(),
  };
}

function normalizarQuebrasDeLinha(texto: string): string {
  return String(texto || "").replace(/\r\n/g, "\n");
}

function normalizarTextoEstruturado(texto: string): string {
  return String(texto || "")
    .replace(/\r\n/g, "\n")
    .replace(/\n\s{4}/g, "\n")
    .trim();
}

function escaparRegex(valor: string): string {
  return valor.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extrairTextoAspectoDoBloco(bloco: string, label: string): string {
  const textoNormalizado = normalizarTextoEstruturado(bloco);
  if (!textoNormalizado) {
    return "";
  }

  const regex = new RegExp(
    `(?:^|\\n)\\s*-\\s*${escaparRegex(label)}:\\s*([\\s\\S]*?)(?=\\n\\s*-\\s*[^\\n:]+:\\s*|$)`,
    "i"
  );
  const match = regex.exec(textoNormalizado);
  return match ? normalizarTextoEstruturado(match[1]) : "";
}

export function normalizarEcocardiogramaEstruturado(
  raw: unknown
): EcocardiogramaEstruturadoPersistido {
  const inicial = criarEcocardiogramaEstruturadoInicial();
  if (!raw || typeof raw !== "object") {
    return inicial;
  }

  const source = raw as Record<string, unknown>;
  const textosRaw =
    source.textos && typeof source.textos === "object"
      ? (source.textos as Record<string, unknown>)
      : {};
  const presetTextosRaw =
    source.preset_textos && typeof source.preset_textos === "object"
      ? (source.preset_textos as Record<string, unknown>)
      : {};

  const textos = ASPECTOS_ECO_META.reduce<Record<string, string>>((acc, aspecto) => {
    const texto = normalizarQuebrasDeLinha(String(textosRaw[aspecto.key] || ""));
    if (texto.trim()) {
      acc[aspecto.key] = texto;
    }
    return acc;
  }, {});
  const preset_textos = ASPECTOS_ECO_META.reduce<Record<string, string>>((acc, aspecto) => {
    const texto = normalizarQuebrasDeLinha(String(presetTextosRaw[aspecto.key] || ""));
    if (texto.trim()) {
      acc[aspecto.key] = texto;
    }
    return acc;
  }, {});

  return {
    versao: Number(source.versao || 1) || 1,
    modo: String(source.modo || "teste").trim() || "teste",
    usar_no_laudo: Boolean(source.usar_no_laudo),
    preset_id:
      source.preset_id === null || source.preset_id === undefined || source.preset_id === ""
        ? null
        : Number(source.preset_id),
    preset_label: String(source.preset_label || "").trim(),
    preset_textos,
    updated_at: String(source.updated_at || "").trim(),
    textos,
  };
}

export function hidratarEcocardiogramaEstruturadoDeLegado(
  raw: unknown,
  qualitativa: Partial<QualitativaEcoLegada> | null | undefined,
  conclusao: string | null | undefined
): EcocardiogramaEstruturadoPersistido {
  const base = normalizarEcocardiogramaEstruturado(raw);
  const textos = { ...base.textos };

  ASPECTOS_ECO_META.forEach((aspecto) => {
    if (textos[aspecto.key]) {
      return;
    }

    if (aspecto.legacyField === "conclusao") {
      const textoConclusao = normalizarTextoEstruturado(String(conclusao || ""));
      if (textoConclusao) {
        textos[aspecto.key] = textoConclusao;
      }
      return;
    }

    const bloco = normalizarTextoEstruturado(String(qualitativa?.[aspecto.legacyField] || ""));
    if (!bloco) {
      return;
    }

    const outrosAspectosDoMesmoGrupo = ASPECTOS_ECO_META.filter(
      (item) => item.legacyField === aspecto.legacyField
    );

    if (outrosAspectosDoMesmoGrupo.length === 1) {
      textos[aspecto.key] = bloco;
      return;
    }

    const textoAspecto = extrairTextoAspectoDoBloco(bloco, aspecto.label);
    if (textoAspecto) {
      textos[aspecto.key] = textoAspecto;
    }
  });

  return {
    ...base,
    textos,
  };
}

export function serializarEcocardiogramaEstruturado(
  raw: EcocardiogramaEstruturadoPersistido
): EcocardiogramaEstruturadoPersistido | null {
  const normalizado = normalizarEcocardiogramaEstruturado(raw);
  const temTextos = Object.values(normalizado.textos).some((texto) => texto.trim());
  if (!temTextos && !normalizado.preset_label && normalizado.preset_id == null) {
    return null;
  }

  return {
    ...normalizado,
    updated_at: new Date().toISOString(),
  };
}

function montarBlocoLegado(
  itens: Array<{ label: string; texto: string }>
): string {
  if (!itens.length) {
    return "";
  }
  if (itens.length === 1) {
    return itens[0].texto;
  }
  return itens
    .map((item) => `  - ${item.label}: ${item.texto.replace(/\n/g, "\n    ")}`)
    .join("\n");
}

export function derivarLegadoDeEcocardiogramaEstruturado(
  raw: EcocardiogramaEstruturadoPersistido | null | undefined
): { qualitativa: QualitativaEcoLegada; conclusao: string } {
  const normalizado = normalizarEcocardiogramaEstruturado(raw);
  const qualitativa = criarQualitativaEcoLegadaVazia();
  const grupos: Partial<Record<keyof QualitativaEcoLegada, Array<{ label: string; texto: string }>>> = {};
  let conclusao = "";

  ASPECTOS_ECO_META.forEach((aspecto) => {
    const texto = String(normalizado.textos[aspecto.key] || "").trim();
    if (!texto) {
      return;
    }
    if (aspecto.legacyField === "conclusao") {
      conclusao = texto;
      return;
    }
    const grupo = grupos[aspecto.legacyField] || [];
    grupo.push({ label: aspecto.label, texto });
    grupos[aspecto.legacyField] = grupo;
  });

  (Object.keys(qualitativa) as Array<keyof QualitativaEcoLegada>).forEach((campo) => {
    qualitativa[campo] = montarBlocoLegado(grupos[campo] || []);
  });

  return { qualitativa, conclusao };
}

export function resolverTextoClinicoNaEdicao(
  estruturado: EcocardiogramaEstruturadoPersistido | null,
  qualitativaSalva: QualitativaEcoLegada,
  conclusaoSalva: string,
  aplicar: { qualitativa: boolean; conclusao: boolean }
): { qualitativa: QualitativaEcoLegada; conclusao: string } {
  if (!estruturado?.usar_no_laudo || (!aplicar.qualitativa && !aplicar.conclusao)) {
    return { qualitativa: qualitativaSalva, conclusao: conclusaoSalva };
  }
  const derivado = derivarLegadoDeEcocardiogramaEstruturado(estruturado);
  return {
    qualitativa: aplicar.qualitativa ? derivado.qualitativa : qualitativaSalva,
    conclusao: aplicar.conclusao ? derivado.conclusao : conclusaoSalva,
  };
}

export function montarDescricaoEcocardiograma(
  medidas: Record<string, string>,
  qualitativa: QualitativaEcoLegada
): string {
  let descricao = "## Medidas Ecocardiograficas\n";
  Object.entries(medidas).forEach(([key, value]) => {
    if (value || DIASTOLIC_KEYS.has(key)) {
      // An explicit clearing must survive beside an unchanged historical alias.
      descricao += `- ${key}: ${value ?? ""}\n`;
    }
  });

  descricao += "\n## Avaliacao Qualitativa\n";
  Object.entries(qualitativa).forEach(([key, value]) => {
    if (value) {
      if (value.includes("\n")) {
        descricao += `- ${key}:\n${value}\n`;
      } else {
        descricao += `- ${key}: ${value}\n`;
      }
    }
  });
  return descricao;
}

export function qualitativaEcoLegadaIgual(
  a: QualitativaEcoLegada,
  b: QualitativaEcoLegada
): boolean {
  return (
    a.valvas === b.valvas &&
    a.camaras === b.camaras &&
    a.funcao === b.funcao &&
    a.pericardio === b.pericardio &&
    a.vasos === b.vasos &&
    a.ad_vd === b.ad_vd
  );
}
