export type EscolhaTutor = "principal" | "secundario";
export type ValorTutor = string | number | boolean | null | Record<string, string | number | null>;
export interface PreviaMesclagem {
  principal: Record<string, ValorTutor> & { id: number };
  secundario: Record<string, ValorTutor> & { id: number };
  campos: string[];
  conflitos: string[];
  bloqueios: string[];
  avisos: string[];
  token_previa: string;
  vinculos: Record<string, { principal: number; secundario: number }>;
  pets: { id: number; nome: string; tutor_id: number }[];
}

export interface PreviaReversaoMesclagem {
  principal_id: number;
  secundario_id: number;
  bloqueios: string[];
  avisos: string[];
  vinculos: Record<string, number>;
  token_previa: string;
}

function serializarIntencao(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(serializarIntencao).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => `${JSON.stringify(key)}:${serializarIntencao(item)}`).join(",")}}`;
  return JSON.stringify(value) ?? "null";
}

// Guardamos só a assinatura e a chave, nunca os dados pessoais do formulário.
export async function chaveOperacaoTutor(escopo: string, payload: unknown): Promise<string> {
  const texto = serializarIntencao(payload);
  const bytes = new TextEncoder().encode(texto);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const assinatura = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  const storageKey = `fortcordis:tutor-operacao:${escopo}`;
  const atual = operacoesTutor.get(storageKey);
  if (atual?.assinatura === assinatura) return atual.chave;
  try {
    const persistida = JSON.parse(sessionStorage.getItem(storageKey) || "null") as { assinatura?: string; chave?: string } | null;
    if (persistida?.assinatura === assinatura && typeof persistida.chave === "string") {
      operacoesTutor.set(storageKey, { assinatura, chave: persistida.chave });
      return persistida.chave;
    }
  } catch { /* Armazenamento indisponível: a chave em memória mantém a repetição segura. */ }
  const operacao = { assinatura, chave: crypto.randomUUID() };
  operacoesTutor.set(storageKey, operacao);
  try { sessionStorage.setItem(storageKey, JSON.stringify(operacao)); } catch { /* Memória acima é o fallback. */ }
  return operacao.chave;
}

const operacoesTutor = new Map<string, { assinatura: string; chave: string }>();

export function concluirOperacaoTutor(escopo: string): void {
  const storageKey = `fortcordis:tutor-operacao:${escopo}`;
  operacoesTutor.delete(storageKey);
  try { sessionStorage.removeItem(storageKey); } catch { /* Não impede a conclusão já conhecida. */ }
}

export const nomesCamposTutor: Record<string, string> = {
  nome: "Nome", telefone: "Telefone", whatsapp: "WhatsApp", email: "E-mail", cpf: "CPF",
  identificacao_pendente: "Identificação pendente", origem_cadastro: "Origem do cadastro",
  identificacao_observacoes: "Observações da identificação", endereco: "Endereço completo e localização",
};
export const nomesVinculosTutor: Record<string, string> = {
  pacientes: "Animais", agendamentos: "Agendamentos", atendimentos_clinicos: "Atendimentos",
  creditos_financeiros: "Movimentos de crédito",
  tutores_contatos: "Contatos adicionais", tutores_origens: "Clínicas e origens",
};

export function valorTutorPreenchido(value: ValorTutor): boolean {
  if (value !== null && typeof value === "object") return Object.values(value).some((v) => v !== null && v !== "");
  return value !== null && value !== "";
}

export function resultadoCampoTutor(previa: PreviaMesclagem, escolhas: Record<string, EscolhaTutor>, campo: string): ValorTutor {
  const escolha = escolhas[campo];
  if (escolha) return previa[escolha][campo];
  const value = previa.principal[campo];
  return valorTutorPreenchido(value) ? value : previa.secundario[campo];
}

export function formatarValorTutor(value: ValorTutor): string {
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (value !== null && typeof value === "object") return Object.entries(value)
    .filter(([, v]) => v !== null && v !== "").map(([k, v]) => `${k}: ${v}`).join(" · ") || "Não informado";
  return String(value ?? "").trim() || "Não informado";
}

export function erroTutor(error: unknown): string {
  const e = error as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "mensagem" in detail) return String(detail.mensagem);
  return "Não foi possível concluir a operação. Confira os dados e tente novamente.";
}
