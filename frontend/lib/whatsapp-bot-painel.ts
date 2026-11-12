/**
 * Formatação e normalização do painel do bot de atendimento (Fase 6).
 *
 * Por que isso vive em `lib` e não na página: `app/configuracoes/page.tsx`
 * tem mais de 3400 linhas e nenhum teste de componente. Criar o primeiro
 * só para cobrir um card novo seria desproporcional; extrair a lógica e
 * testá-la aqui cobre o que de fato pode errar.
 *
 * A regra mais importante deste arquivo: o backend usa `null` para "sem
 * amostra" em toda taxa, e para "tarifa não configurada" em custo. Renderizar
 * `null` como `0%` transformaria "não medido" em "medido e ruim" — que é
 * exatamente a leitura errada para quem vai decidir se liga o modo `auto`.
 */

export const SEM_DADO = "—";

export function formatarTaxa(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return SEM_DADO;
  return `${Math.round(valor * 1000) / 10}%`;
}

export function formatarInteiro(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return SEM_DADO;
  return String(valor);
}

export function formatarLatencia(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return SEM_DADO;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatarCusto(
  valor: number | null | undefined,
  configurado: boolean | undefined,
): string {
  if (!configurado) return "não configurado";
  if (valor === null || valor === undefined || Number.isNaN(valor)) return SEM_DADO;
  return valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export type ItemProntidao = {
  intent: string;
  rotulo: string;
  pronto: boolean;
  diagnostico: string | null;
  auto_elegivel: boolean;
  depende_da_conversa?: boolean;
  pergunta_exemplo?: string | null;
  tool?: string | null;
};

export type PersonaProntidao = {
  itens: ItemProntidao[];
  total: number;
  prontos: number;
  pendentes: number;
};

/** Ordena para o trabalho aparecer primeiro: pendente antes de pronto. */
export function ordenarPorPendencia(itens: ItemProntidao[]): ItemProntidao[] {
  return [...itens].sort((a, b) => {
    if (a.pronto !== b.pronto) return a.pronto ? 1 : -1;
    // "depende da conversa" não é trabalho de configuração; vai para o fim.
    const aDep = a.depende_da_conversa ? 1 : 0;
    const bDep = b.depende_da_conversa ? 1 : 0;
    if (aDep !== bDep) return aDep - bDep;
    return a.rotulo.localeCompare(b.rotulo, "pt-BR");
  });
}

export type ResumoProntidao = {
  total: number;
  prontos: number;
  pendentes: number;
  acionaveis: number;
};

/**
 * `acionaveis` separa o que o admin pode resolver cadastrando/configurando
 * do que só se resolve numa conversa real (status de laudo). Sem essa
 * distinção o painel mostraria uma pendência permanente e treinaria o
 * usuário a ignorar o vermelho.
 */
export function resumirProntidao(
  personas: Record<string, PersonaProntidao> | undefined,
): ResumoProntidao {
  const vazio = { total: 0, prontos: 0, pendentes: 0, acionaveis: 0 };
  if (!personas) return vazio;
  return Object.values(personas).reduce((acc, persona) => {
    const itens = persona?.itens ?? [];
    const prontos = itens.filter((i) => i.pronto).length;
    const acionaveis = itens.filter((i) => !i.pronto && !i.depende_da_conversa).length;
    return {
      total: acc.total + itens.length,
      prontos: acc.prontos + prontos,
      pendentes: acc.pendentes + (itens.length - prontos),
      acionaveis: acc.acionaveis + acionaveis,
    };
  }, vazio);
}

export const PUBLICOS_CONHECIMENTO = [
  { valor: "ambos", rotulo: "Tutor e clínica" },
  { valor: "tutor", rotulo: "Somente tutor" },
  { valor: "clinica", rotulo: "Somente clínica parceira" },
] as const;

export type PublicoConhecimento = (typeof PUBLICOS_CONHECIMENTO)[number]["valor"];

export type ValidacaoConteudo = { valido: boolean; erros: string[] };

/**
 * Espelha as regras do backend antes de gastar requisição. As duas primeiras
 * existem porque eram exatamente os jeitos silenciosos de criar um documento
 * invisível para o bot: categoria errada e fonte vazia.
 */
export function validarConteudoBot(entrada: {
  titulo: string;
  conteudo: string;
  fonte: string;
  publico: string;
}): ValidacaoConteudo {
  const erros: string[] = [];
  if (entrada.titulo.trim().length < 3) erros.push("Informe um título com ao menos 3 caracteres.");
  if (entrada.conteudo.trim().length < 20) erros.push("O conteúdo precisa de ao menos 20 caracteres.");
  if (entrada.fonte.trim().length < 2) {
    erros.push("Informe a fonte: o bot só afirma o que tem fonte para citar.");
  }
  if (!PUBLICOS_CONHECIMENTO.some((p) => p.valor === entrada.publico)) {
    erros.push("Escolha para quem esse conteúdo vale.");
  }
  return { valido: erros.length === 0, erros };
}

export type ChecklistAuto = {
  tem_uma_semana_de_dados?: boolean;
  tem_rascunho_decidido?: boolean;
  amostra_suficiente_nas_duas_personas?: boolean;
  decididos_por_persona?: Record<string, number>;
  min_decididos_por_persona?: number;
  personas_com_amostra_suficiente?: string[];
  observacao?: string;
};

export type LinhaChecklist = { rotulo: string; atendido: boolean; detalhe?: string };

/**
 * Renderiza o checklist como itens, nunca como um selo de "liberado".
 * O backend é explícito: nenhum campo desse payload autoriza ligar `auto`.
 */
export function linhasDoChecklist(checklist: ChecklistAuto | undefined): LinhaChecklist[] {
  if (!checklist) return [];
  const minimo = checklist.min_decididos_por_persona ?? 20;
  const decididos = checklist.decididos_por_persona ?? {};
  const detalhePersonas = ["tutor", "clinica"]
    .map((p) => `${p}: ${decididos[p] ?? 0}/${minimo}`)
    .join(" · ");
  return [
    { rotulo: "Pelo menos uma semana de dados", atendido: !!checklist.tem_uma_semana_de_dados },
    { rotulo: "Há rascunho já decidido", atendido: !!checklist.tem_rascunho_decidido },
    {
      rotulo: "Amostra suficiente nas duas personas",
      atendido: !!checklist.amostra_suficiente_nas_duas_personas,
      detalhe: detalhePersonas,
    },
  ];
}
