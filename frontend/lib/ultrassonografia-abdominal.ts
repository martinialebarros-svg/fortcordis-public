export type SexoPaciente = "Macho" | "Femea";

export interface OrgaoUltrassomAbdominal {
  key: string;
  label: string;
  sexo?: SexoPaciente;
}

export interface FraseUltrassomAbdominal {
  id: number;
  orgao: string;
  sexo: string;
  titulo: string;
  texto: string;
  ativo?: number;
}

export const ORGAOS_ULTRASSOM_ABDOMINAL: OrgaoUltrassomAbdominal[] = [
  { key: "figado", label: "Figado" },
  { key: "vesicula_biliar", label: "Vesicula biliar" },
  { key: "estomago", label: "Estomago" },
  { key: "alcas_intestinais", label: "Alcas intestinais" },
  { key: "duodeno", label: "Duodeno" },
  { key: "colon", label: "Colon" },
  { key: "juncao_ileo_ceco_colica", label: "Juncao ileo-ceco-colica" },
  { key: "baco", label: "Baco" },
  { key: "rins", label: "Rins" },
  { key: "bexiga", label: "Bexiga" },
  { key: "pancreas", label: "Pancreas" },
  { key: "adrenais", label: "Adrenais" },
  { key: "prostata", label: "Prostata", sexo: "Macho" },
  { key: "testiculos", label: "Testiculos", sexo: "Macho" },
  { key: "utero", label: "Utero", sexo: "Femea" },
  { key: "ovarios", label: "Ovarios", sexo: "Femea" },
];

export const ORGAO_OBSERVACOES_GERAIS = "observacoes_gerais";

export function normalizarSexoPaciente(sexo?: string | null): SexoPaciente {
  const valor = (sexo || "").trim().toLowerCase();
  return valor.startsWith("f") ? "Femea" : "Macho";
}

export function getOrgaosVisiveis(sexo?: string | null): OrgaoUltrassomAbdominal[] {
  const sexoNormalizado = normalizarSexoPaciente(sexo);
  return ORGAOS_ULTRASSOM_ABDOMINAL.filter((orgao) => !orgao.sexo || orgao.sexo === sexoNormalizado);
}

export function fraseCompativelComSexo(fraseSexo?: string | null, sexoPaciente?: string | null): boolean {
  const sexoFrase = (fraseSexo || "Todos").trim().toLowerCase();
  if (!sexoFrase || sexoFrase === "todos") {
    return true;
  }

  return sexoFrase.startsWith(normalizarSexoPaciente(sexoPaciente).toLowerCase().charAt(0));
}

export function getLabelFrase(frase: Pick<FraseUltrassomAbdominal, "titulo" | "texto">): string {
  const titulo = (frase.titulo || "").trim();
  if (titulo) {
    return titulo;
  }

  const texto = (frase.texto || "").trim();
  if (texto.length <= 72) {
    return texto;
  }

  return `${texto.slice(0, 69)}...`;
}
