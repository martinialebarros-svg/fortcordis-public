export type ClinicalFieldKey =
  | "queixa_principal"
  | "anamnese"
  | "exame_fisico"
  | "dados_clinicos"
  | "diagnostico_principal"
  | "diagnostico_secundario"
  | "diagnostico_diferencial"
  | "plano_terapeutico"
  | "retorno_recomendado"
  | "motivo_retorno"
  | "observacoes";

export interface ClinicalQuickPhrase {
  label: string;
  text: string;
}

export interface ClinicalPhraseRecord {
  id: number;
  secao: ClinicalFieldKey;
  titulo: string;
  texto: string;
  ordem: number;
  ativo: number;
  parametrizacao_origem: string;
}

export interface ClinicalFieldConfig {
  key: ClinicalFieldKey;
  title: string;
  subtitle: string;
  placeholder: string;
  rows: number;
  tone: "teal" | "sky" | "rose" | "violet" | "amber" | "slate";
  scaffold?: {
    label: string;
    text: string;
  };
  quickPhrases: ClinicalQuickPhrase[];
}

export interface ClinicalFieldValues {
  queixa_principal: string;
  anamnese: string;
  exame_fisico: string;
  dados_clinicos: string;
  diagnostico_principal: string;
  diagnostico_secundario: string;
  diagnostico_diferencial: string;
  plano_terapeutico: string;
  retorno_recomendado: string;
  motivo_retorno: string;
  observacoes: string;
}

export interface ClinicalCoberturaMinima {
  percentual: number;
  completos: number;
  total: number;
  pendencias: string[];
}

export interface ClinicalQuickSummary {
  headline: string;
  highlights: Array<{ label: string; text: string }>;
  pending: string[];
  completeness: number;
  coberturaMinima: ClinicalCoberturaMinima;
}

// Mesmos 3 grupos (logica OR) exigidos por `_calcular_pendencias_documentacao`
// no backend para permitir a primeira conclusao do atendimento - mantidos em
// sincronia manual com `backend/app/api/v1/endpoints/atendimento.py`.
const GRUPOS_COBERTURA_MINIMA: Array<{ label: string; keys: ClinicalFieldKey[] }> = [
  { label: "Queixa principal", keys: ["queixa_principal"] },
  { label: "Anamnese, exame fisico ou dados clinicos", keys: ["anamnese", "exame_fisico", "dados_clinicos"] },
  {
    label: "Diagnostico ou plano terapeutico",
    keys: ["diagnostico_principal", "diagnostico_secundario", "diagnostico_diferencial", "plano_terapeutico"],
  },
];

const CLINICAL_FIELD_ORDER: ClinicalFieldKey[] = [
  "queixa_principal",
  "anamnese",
  "exame_fisico",
  "dados_clinicos",
  "diagnostico_principal",
  "diagnostico_secundario",
  "diagnostico_diferencial",
  "plano_terapeutico",
  "retorno_recomendado",
  "motivo_retorno",
  "observacoes",
];

export const CLINICAL_FIELD_CONFIGS: ClinicalFieldConfig[] = [
  {
    key: "queixa_principal",
    title: "Queixa principal",
    subtitle: "Motivo da consulta e foco imediato.",
    placeholder: "Descreva a queixa principal em uma ou duas linhas.",
    rows: 3,
    tone: "rose",
    scaffold: {
      label: "Roteiro de entrada",
      text: "Queixa principal:\n- Inicio dos sinais:\n- Evolucao recente:\n- Impacto funcional:",
    },
    quickPhrases: [
      {
        label: "Tosse e cansaco",
        text: "Tutor refere tosse cronica associada a cansaco aos esforcos, em investigacao cardiologica.",
      },
      {
        label: "Sopro em revisao",
        text: "Paciente encaminhado para revisao cardiologica apos identificacao de sopro em avaliacao de rotina.",
      },
      {
        label: "Sincope",
        text: "Historico recente de episodios de sincope, com recuperacao espontanea e sem trauma associado.",
      },
    ],
  },
  {
    key: "anamnese",
    title: "Anamnese dirigida",
    subtitle: "Historico, medicacoes em uso e resposta clinica.",
    placeholder: "Organize a historia do tutor, tratamentos anteriores e eventos relevantes.",
    rows: 8,
    tone: "teal",
    scaffold: {
      label: "Roteiro cardiologico",
      text:
        "Historico relatado pelo tutor:\n- Inicio dos sinais:\n- Progressao / periodicidade:\n- Medicacoes em uso:\n- Resposta ao tratamento:\n- Eventos recentes (sincope, dispneia, tosse):\n- Apetite / hidratacao / eliminacoes:",
    },
    quickPhrases: [
      {
        label: "Progressao lenta",
        text: "Tutor refere progressao lenta dos sinais clinicos, com piora discreta no periodo noturno e aos esforcos.",
      },
      {
        label: "Em tratamento",
        text: "Paciente ja faz uso domiciliar de medicacao cardiologica, sem eventos adversos importantes relatados.",
      },
      {
        label: "Sem sinais congestivos",
        text: "No domicilio, tutor nao observa dispneia em repouso, ascite ou intolerancia alimentar significativa.",
      },
    ],
  },
  {
    key: "exame_fisico",
    title: "Exame fisico",
    subtitle: "Achados de ausculta, perfusao e estabilidade.",
    placeholder: "Registre os achados relevantes do exame fisico.",
    rows: 7,
    tone: "sky",
    scaffold: {
      label: "Checklist do exame",
      text:
        "Estado geral:\nMucosas / hidratacao:\nAusculta cardiaca:\nAusculta pulmonar:\nPerfusao / pulsos:\nAbdome / edema / outros:",
    },
    quickPhrases: [
      {
        label: "Estavel",
        text: "Paciente alerta, responsivo, normohidratado, com mucosas rosadas e perfusao periferica adequada.",
      },
      {
        label: "Sopro apical",
        text: "Ausculta cardiaca com sopro em foco mitral, ritmo regular no momento da avaliacao.",
      },
      {
        label: "Pulmao limpo",
        text: "Ausculta pulmonar sem crepitacoes, sem aumento do esforco respiratorio em repouso.",
      },
    ],
  },
  {
    key: "dados_clinicos",
    title: "Dados clinicos",
    subtitle: "Contexto interpretativo e correlacao com exames.",
    placeholder: "Resuma a leitura clinica do caso e os pontos de vigilancia.",
    rows: 5,
    tone: "violet",
    scaffold: {
      label: "Pontos de correlacao",
      text: "Leitura clinica atual:\n- Hipoteses principais:\n- Correlacao com exames:\n- Riscos imediatos:\n- Ponto de acompanhamento:",
    },
    quickPhrases: [
      {
        label: "PA controlada",
        text: "Pressao arterial sem desvios marcantes na avaliacao atual, com seguimento ambulatorial recomendado.",
      },
      {
        label: "Sem congestao",
        text: "Nao ha sinais clinicos de congestao no exame de hoje, apesar do historico cardiologico em acompanhamento.",
      },
      {
        label: "Correlacionar ECO",
        text: "Achados devem ser correlacionados ao ecocardiograma e a monitorizacao seriada conforme evolucao clinica.",
      },
    ],
  },
  {
    key: "diagnostico_principal",
    title: "Diagnostico principal",
    subtitle: "Definicao central do caso.",
    placeholder: "Diagnostico principal ou sindrome clinica dominante.",
    rows: 4,
    tone: "amber",
    quickPhrases: [
      {
        label: "Endocardiose mitral",
        text: "Doenca valvar degenerativa mitral em acompanhamento cardiologico.",
      },
      {
        label: "ICC compensada",
        text: "Insuficiencia cardiaca congestiva previamente tratada, no momento clinicamente compensada.",
      },
      {
        label: "Hipertensao suspeita",
        text: "Suspeita de hipertensao arterial sistemica, demandando afericao seriada e correlacao com lesoes alvo.",
      },
    ],
  },
  {
    key: "diagnostico_secundario",
    title: "Diagnostico secundario",
    subtitle: "Comorbidades e achados associados.",
    placeholder: "Comorbidades ou diagnosticos secundarios relevantes.",
    rows: 4,
    tone: "slate",
    quickPhrases: [
      {
        label: "Sem comorbidades",
        text: "Sem comorbidades adicionais relevantes registradas nesta consulta.",
      },
      {
        label: "Degeneracao valvar",
        text: "Degeneracao mixomatosa valvar associada a remodelamento discreto.",
      },
      {
        label: "Arritmia em investigacao",
        text: "Arritmia intermitente em investigacao complementar.",
      },
    ],
  },
  {
    key: "diagnostico_diferencial",
    title: "Diagnostico diferencial",
    subtitle: "Hipoteses ainda em aberto.",
    placeholder: "Liste os principais diferenciais para o quadro.",
    rows: 4,
    tone: "slate",
    quickPhrases: [
      {
        label: "Cardiaco x respiratorio",
        text: "Necessario diferenciar componente cardiaco de causa respiratoria primaria.",
      },
      {
        label: "Sincope vagal",
        text: "Considerar evento vasovagal ou arritmico conforme recorrencia e contexto clinico.",
      },
      {
        label: "Doenca sistemica",
        text: "Nao afastar contribuicao de doenca sistemica ou endocrina sobre o quadro cardiovascular.",
      },
    ],
  },
  {
    key: "plano_terapeutico",
    title: "Plano terapeutico",
    subtitle: "Conduta, exames e orientacoes ao tutor.",
    placeholder: "Descreva a conduta proposta e os proximos passos.",
    rows: 7,
    tone: "teal",
    scaffold: {
      label: "Plano em blocos",
      text:
        "Conduta imediata:\nExames complementares:\nAjustes terapeuticos:\nOrientacoes ao tutor:\nCriticos para retorno antecipado:",
    },
    quickPhrases: [
      {
        label: "Solicitar ECO + ECG",
        text: "Solicitar ecocardiograma e eletrocardiograma para complementar o estadiamento cardiologico.",
      },
      {
        label: "Monitorar FRR",
        text: "Orientado tutor a monitorar frequencia respiratoria em repouso e registrar intercorrencias.",
      },
      {
        label: "Ajuste por peso",
        text: "Ajustes de medicacao devem respeitar o peso clinico aferido nesta consulta e a resposta clinica subsequente.",
      },
    ],
  },
  {
    key: "retorno_recomendado",
    title: "Retorno recomendado",
    subtitle: "Prazo e objetivo da reavaliacao.",
    placeholder: "Defina quando e por que o paciente deve retornar.",
    rows: 4,
    tone: "sky",
    scaffold: {
      label: "Plano de retorno",
      text: "Prazo sugerido:\nObjetivo da reavaliacao:\nExames para retorno:",
    },
    quickPhrases: [
      {
        label: "Retorno em 7 dias",
        text: "Reavaliacao em 7 dias para revisao clinica, resposta terapeutica e checagem de exames.",
      },
      {
        label: "Retorno se piora",
        text: "Antecipar retorno em caso de dispneia, sincope, piora da tosse ou reducao importante de apetite.",
      },
      {
        label: "Retorno programado",
        text: "Retorno programado apos liberacao dos exames complementares para definicao de conduta.",
      },
    ],
  },
  {
    key: "motivo_retorno",
    title: "Motivo do retorno",
    subtitle: "O que precisa ser reavaliado na proxima visita.",
    placeholder: "Descreva o foco da proxima consulta.",
    rows: 4,
    tone: "amber",
    quickPhrases: [
      {
        label: "Reavaliar congestao",
        text: "Reavaliar sinais de congestao, tolerancia ao protocolo e estabilidade hemodinamica.",
      },
      {
        label: "Checar pressao",
        text: "Repetir afericao pressorica e correlacionar com achados de orgao alvo.",
      },
      {
        label: "Rever dose",
        text: "Rever doses e resposta clinica domiciliar apos ajustes terapeuticos.",
      },
    ],
  },
  {
    key: "observacoes",
    title: "Observacoes gerais",
    subtitle: "Orientacoes adicionais e contexto administrativo.",
    placeholder: "Anote recados relevantes para equipe e tutor.",
    rows: 4,
    tone: "slate",
    quickPhrases: [
      {
        label: "Tutor orientado",
        text: "Tutor orientado quanto a sinais de alerta, horarios de medicacao e necessidade de retorno programado.",
      },
      {
        label: "Sem intercorrencias",
        text: "Consulta transcorrida sem intercorrencias imediatas durante o atendimento.",
      },
      {
        label: "Contato aberto",
        text: "Liberado canal de contato para intercorrencias clinicas ate a proxima reavaliacao.",
      },
    ],
  },
];

export const CLINICAL_SECTION_OPTIONS = CLINICAL_FIELD_CONFIGS.map((config) => ({
  key: config.key,
  label: config.title,
}));

function normalizeMultiline(value: string): string {
  return String(value || "").replace(/\r\n/g, "\n");
}

function cleanWhitespace(value: string): string {
  return normalizeMultiline(value).replace(/[ \t]+\n/g, "\n").trim();
}

export function buildClinicalFieldValues(
  input: Partial<ClinicalFieldValues> | null | undefined
): ClinicalFieldValues {
  const source = input || {};
  return CLINICAL_FIELD_ORDER.reduce((acc, key) => {
    acc[key] = normalizeMultiline(String(source[key] || ""));
    return acc;
  }, {} as ClinicalFieldValues);
}

export function buildClinicalQuickSummary(
  input: Partial<ClinicalFieldValues> | null | undefined,
  prognostico: string
): ClinicalQuickSummary {
  const values = buildClinicalFieldValues(input);
  const rawHighlights: Array<{ label: string; text: string }> = [
    { label: "Queixa", text: values.queixa_principal },
    { label: "Exame", text: values.exame_fisico },
    { label: "Diagnostico", text: values.diagnostico_principal },
    { label: "Plano", text: values.plano_terapeutico },
    { label: "Retorno", text: values.retorno_recomendado },
  ];

  const highlights = rawHighlights
    .map((item) => ({ label: item.label, text: summarizeClinicalText(item.text, 170) }))
    .filter((item) => item.text);

  const headline =
    summarizeClinicalText(values.diagnostico_principal, 180) ||
    summarizeClinicalText(values.queixa_principal, 180) ||
    summarizeClinicalText(values.anamnese, 180) ||
    "Resumo automatico sera montado conforme o atendimento for preenchido.";

  const pending: string[] = [];
  if (!cleanWhitespace(values.queixa_principal)) pending.push("Registrar a queixa principal.");
  if (!cleanWhitespace(values.anamnese)) pending.push("Completar a anamnese dirigida.");
  if (!cleanWhitespace(values.exame_fisico)) pending.push("Descrever o exame fisico.");
  if (!cleanWhitespace(values.diagnostico_principal)) pending.push("Definir o diagnostico principal.");
  if (!cleanWhitespace(values.plano_terapeutico)) pending.push("Fechar o plano terapeutico.");
  if (!cleanWhitespace(values.retorno_recomendado)) pending.push("Orientar o retorno.");
  if (!String(prognostico || "").trim()) pending.push("Selecionar o prognostico.");

  const preenchidos = CLINICAL_FIELD_ORDER.filter((key) => cleanWhitespace(values[key])).length;
  const completeness = Math.round((preenchidos / CLINICAL_FIELD_ORDER.length) * 100);
  const coberturaMinima = buildCoberturaMinima(values);

  return {
    headline,
    highlights,
    pending: pending.slice(0, 4),
    completeness,
    coberturaMinima,
  };
}

// Mesmo criterio de "pronto para concluir" usado por
// `_validar_primeira_conclusao_atendimento` no backend - ao contrario de
// `completeness` (media dos 11 campos), aqui cada grupo em
// `GRUPOS_COBERTURA_MINIMA` conta como satisfeito se AO MENOS UM dos seus
// campos estiver preenchido, exatamente como a barreira real de conclusao.
function buildCoberturaMinima(values: ClinicalFieldValues): ClinicalCoberturaMinima {
  const pendencias = GRUPOS_COBERTURA_MINIMA.filter(
    (grupo) => !grupo.keys.some((key) => cleanWhitespace(values[key]))
  ).map((grupo) => grupo.label);
  const total = GRUPOS_COBERTURA_MINIMA.length;
  const completos = total - pendencias.length;
  return {
    percentual: Math.round((completos / total) * 100),
    completos,
    total,
    pendencias,
  };
}

export function summarizeClinicalText(value: string, maxLength = 140): string {
  const normalized = cleanWhitespace(value);
  if (!normalized) return "";
  const firstLine = normalized
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstLine) return "";
  if (firstLine.length <= maxLength) return firstLine;
  return `${firstLine.slice(0, Math.max(0, maxLength - 1)).trimEnd()}...`;
}

export function hasMeaningfulDraft(input: Partial<ClinicalFieldValues> | null | undefined): boolean {
  const values = buildClinicalFieldValues(input);
  return CLINICAL_FIELD_ORDER.some((key) => cleanWhitespace(values[key]));
}

export function buildClinicalFieldConfigsWithPhraseBank(
  phrases: ClinicalPhraseRecord[]
): ClinicalFieldConfig[] {
  const grouped = phrases.reduce<Record<string, ClinicalQuickPhrase[]>>((acc, item) => {
    if (Number(item.ativo ?? 1) !== 1) return acc;
    const key = String(item.secao || "").trim();
    if (!key) return acc;
    const bucket = acc[key] || [];
    bucket.push({
      label: String(item.titulo || "").trim(),
      text: String(item.texto || "").trim(),
    });
    acc[key] = bucket;
    return acc;
  }, {});

  return CLINICAL_FIELD_CONFIGS.map((config) => ({
    ...config,
    quickPhrases: grouped[config.key]?.length ? grouped[config.key] : config.quickPhrases,
  }));
}

export function insertSnippetIntoText(
  currentValue: string,
  snippet: string,
  selectionStart?: number | null,
  selectionEnd?: number | null
): { value: string; cursor: number } {
  const current = normalizeMultiline(currentValue);
  const cleanSnippet = cleanWhitespace(snippet);
  if (!cleanSnippet) {
    const cursor = typeof selectionEnd === "number" ? selectionEnd : current.length;
    return { value: current, cursor };
  }

  const start = typeof selectionStart === "number" ? selectionStart : current.length;
  const end = typeof selectionEnd === "number" ? selectionEnd : start;

  const before = current.slice(0, start);
  const after = current.slice(end);
  const leadingBreak = before && !before.endsWith("\n") ? "\n" : "";
  const trailingBreak = after && !after.startsWith("\n") ? "\n" : "";
  const value = `${before}${leadingBreak}${cleanSnippet}${trailingBreak}${after}`.replace(/\n{3,}/g, "\n\n");
  const cursor = (before + leadingBreak + cleanSnippet).length;
  return { value, cursor };
}
