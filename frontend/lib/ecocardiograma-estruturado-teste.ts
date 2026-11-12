import { normalizeEchoSpecies } from "./echo-species";

export interface FraseEcoEstruturadoTeste {
  id?: number;
  titulo: string;
  texto: string;
  tags?: string[];
  patologias?: string[];
  ordem?: number;
  ativo?: number;
}

export interface AspectoEcoEstruturadoTeste {
  key: string;
  label: string;
  categoria: string;
  descricao: string;
  placeholder: string;
  legacy_field: string;
  ordem: number;
  frases: FraseEcoEstruturadoTeste[];
}

export interface PresetSelecaoEcoEstruturadoTeste {
  aspecto: string;
  frase_id?: number | string | null;
  frase_titulo?: string;
}

export interface PresetSelecaoResolvidaEcoEstruturadoTeste
  extends PresetSelecaoEcoEstruturadoTeste {
  texto?: string;
}

export interface PresetEcoEstruturadoTeste {
  id?: number;
  key: string;
  label: string;
  patologia?: string;
  grau?: string;
  descricao?: string;
  tags?: string[];
  ordem?: number;
  ativo?: number;
  selecoes: PresetSelecaoEcoEstruturadoTeste[];
  selecoes_resolvidas?: PresetSelecaoResolvidaEcoEstruturadoTeste[];
}

export interface PayloadEcoEstruturadoTeste {
  version: string;
  mode: string;
  last_updated: string;
  aspectos: AspectoEcoEstruturadoTeste[];
  presets: PresetEcoEstruturadoTeste[];
}

export function presetCompativelComEspecie(
  preset: PresetEcoEstruturadoTeste,
  especie?: string,
): boolean {
  const especieNormalizada = normalizeEchoSpecies(especie);
  const tags = (preset.tags || []).map((tag) => tag.toLocaleLowerCase("pt-BR"));
  if (especieNormalizada === "Felina") return !tags.includes("cao") || tags.includes("gato");
  if (especieNormalizada === "Canina") return !tags.includes("gato") || tags.includes("cao");
  return true;
}

export function ordenarAspectos(aspectos: AspectoEcoEstruturadoTeste[]): AspectoEcoEstruturadoTeste[] {
  return [...aspectos].sort((a, b) => {
    if ((a.ordem || 999) !== (b.ordem || 999)) {
      return (a.ordem || 999) - (b.ordem || 999);
    }
    return (a.label || "").localeCompare(b.label || "");
  });
}
