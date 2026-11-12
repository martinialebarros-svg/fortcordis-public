import type { FraseEcoEstruturadoTeste } from "@/lib/ecocardiograma-estruturado-teste";

export type GrauRapidoEco = "leve" | "moderado" | "importante";
export type FormatoConclusaoEco = "topicos" | "paragrafo";

export interface OpcaoGrauRapidoEco {
  grau: GrauRapidoEco;
  label: string;
  frase: FraseEcoEstruturadoTeste;
}

export interface AchadoParaConclusaoEco {
  aspecto: string;
  label: string;
  texto: string;
  frase?: FraseEcoEstruturadoTeste;
  origem?: "preset" | "alterado" | "manual" | "empty";
}

const GRAUS_RAPIDOS: Array<{
  grau: GrauRapidoEco;
  label: string;
  aliases: string[];
}> = [
  {
    grau: "leve",
    label: "Discreta",
    aliases: ["leve", "discreto", "discreta", "discretamente"],
  },
  {
    grau: "moderado",
    label: "Moderada",
    aliases: ["moderado", "moderada", "moderadamente"],
  },
  {
    grau: "importante",
    label: "Importante",
    aliases: ["grave", "importante", "acentuado", "acentuada", "acentuadamente"],
  },
];

const PALAVRAS_RUIDO_TITULO = new Set([
  "a",
  "ao",
  "aos",
  "as",
  "com",
  "da",
  "das",
  "de",
  "do",
  "dos",
  "e",
  "em",
  "o",
  "os",
  "por",
]);

const TAGS_RUIDO_CONTEXTO = new Set([
  "b1",
  "b2",
  "c",
  "d",
  "icc",
  "base",
  "cao",
  "gato",
  "conclusao",
  "normal",
]);

function normalizar(valor: unknown): string {
  return String(valor || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function identificarGrau(frase: FraseEcoEstruturadoTeste): GrauRapidoEco | null {
  const tags = new Set((frase.tags || []).map(normalizar));
  const titulo = normalizar(frase.titulo);
  for (const item of GRAUS_RAPIDOS) {
    if (
      item.aliases.some(
        (alias) => tags.has(normalizar(alias)) || titulo.split(" ").includes(normalizar(alias)),
      )
    ) {
      return item.grau;
    }
  }
  return null;
}

function tokensTituloClinico(frase: FraseEcoEstruturadoTeste): Set<string> {
  const aliasesGrau = new Set(GRAUS_RAPIDOS.flatMap((item) => item.aliases.map(normalizar)));
  return new Set(
    normalizar(frase.titulo)
      .split(" ")
      .filter(
        (token) =>
          token.length > 1 &&
          !PALAVRAS_RUIDO_TITULO.has(token) &&
          !aliasesGrau.has(token),
      ),
  );
}

function tagsContexto(frase: FraseEcoEstruturadoTeste): Set<string> {
  const aliasesGrau = new Set(GRAUS_RAPIDOS.flatMap((item) => item.aliases.map(normalizar)));
  return new Set(
    (frase.tags || [])
      .map(normalizar)
      .filter((tag) => tag && !aliasesGrau.has(tag) && !TAGS_RUIDO_CONTEXTO.has(tag)),
  );
}

function intersecao<T>(a: Set<T>, b: Set<T>): number {
  return [...a].filter((item) => b.has(item)).length;
}

function pontuarRelacao(
  referencia: FraseEcoEstruturadoTeste,
  candidata: FraseEcoEstruturadoTeste,
): number {
  const tokensComuns = intersecao(tokensTituloClinico(referencia), tokensTituloClinico(candidata));
  const tagsComuns = intersecao(tagsContexto(referencia), tagsContexto(candidata));
  return tokensComuns * 2 + tagsComuns * 3;
}

export function obterOpcoesDeGrauRelacionadas(
  frases: FraseEcoEstruturadoTeste[],
  fraseSelecionadaId: string,
): OpcaoGrauRapidoEco[] {
  const ativas = frases.filter(
    (frase) => Number(frase.ativo ?? 1) === 1 && frase.id !== undefined,
  );
  const referencia = ativas.find((frase) => String(frase.id) === fraseSelecionadaId);
  if (!referencia || !identificarGrau(referencia)) {
    return [];
  }

  const selecionadas = GRAUS_RAPIDOS.map((config) => {
    const candidatas = ativas
      .filter((frase) => identificarGrau(frase) === config.grau)
      .map((frase) => ({ frase, score: pontuarRelacao(referencia, frase) }))
      .filter(({ frase, score }) => frase.id === referencia.id || score >= 4)
      .sort((a, b) => {
        if (a.frase.id === referencia.id) return -1;
        if (b.frase.id === referencia.id) return 1;
        if (a.score !== b.score) return b.score - a.score;
        return (a.frase.ordem || 999) - (b.frase.ordem || 999);
      });
    const escolhida = candidatas[0]?.frase;
    return escolhida
      ? {
          grau: config.grau,
          label: config.label,
          frase: escolhida,
        }
      : null;
  }).filter(Boolean) as OpcaoGrauRapidoEco[];

  return selecionadas.length >= 2 ? selecionadas : [];
}

function separarItensClinicos(texto: string): string[] {
  const valor = String(texto || "").trim();
  if (!valor) {
    return [];
  }

  return valor
    .split(/(?:^|[\r\n]+|\s+)(?:[-*•]+)\s+/g)
    .map((item) => item.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function pontuarFraseClinica(texto: string): string {
  const valor = String(texto || "").replace(/\s+/g, " ").trim();
  if (!valor) {
    return "";
  }
  return /[.!?]$/.test(valor) ? valor : `${valor}.`;
}

function fraseRepresentaNormalidade(frase?: FraseEcoEstruturadoTeste): boolean {
  if (!frase) {
    return false;
  }
  const tags = new Set((frase.tags || []).map(normalizar));
  return tags.has("normal") || tags.has("fisiologico");
}

export function comporRascunhoConclusaoDosAchados(
  achados: AchadoParaConclusaoEco[],
  formato: FormatoConclusaoEco,
  conclusaoBase = "",
): string {
  const base = String(conclusaoBase || "").trim();
  const itens = achados
    .filter(
      (achado) =>
        achado.aspecto !== "conclusao" &&
        String(achado.texto || "").trim() &&
        (base
          ? achado.origem === "alterado" || achado.origem === "manual"
          : !fraseRepresentaNormalidade(achado.frase)),
    )
    .map((achado) => {
      const resumo = String(achado.frase?.titulo || achado.texto || "").trim();
      return pontuarFraseClinica(`${achado.label}: ${resumo}`);
    })
    .filter(Boolean);

  if (formato === "paragrafo") {
    return [base, itens.join(" ")].filter(Boolean).join(" ");
  }
  const complementos = itens.map((item) => `* ${item}`).join("\n");
  return [base, complementos].filter(Boolean).join("\n");
}

export function comporConclusaoDeFrases(
  frases: FraseEcoEstruturadoTeste[],
  idsSelecionados: string[],
  formato: FormatoConclusaoEco,
): string {
  const idsUnicos = Array.from(new Set(idsSelecionados.map(String).filter(Boolean)));
  const porId = new Map(
    frases
      .filter((frase) => Number(frase.ativo ?? 1) === 1 && frase.id !== undefined)
      .map((frase) => [String(frase.id), frase]),
  );
  const itens = idsUnicos
    .map((id) => porId.get(id))
    .filter(Boolean)
    .flatMap((frase) => separarItensClinicos(String(frase?.texto || "")));

  if (formato === "paragrafo") {
    return itens.join(" ");
  }
  return itens.map((item) => `* ${item}`).join("\n");
}
