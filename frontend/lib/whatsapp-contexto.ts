export interface WhatsAppContextCandidate {
  id: number;
  nome: string;
}

export interface WhatsAppContextSelection {
  match_type: "clinica" | "tutor" | null;
  cadastro_id: number | null;
  versao: number;
  valida: boolean;
  atualizado_por_id?: number | null;
  updated_at?: string | null;
}

export interface WhatsAppContextSelectionPayload {
  match_type: "clinica" | "tutor" | null;
  cadastro_id: number | null;
  versao_esperada: number;
}

export interface WhatsAppSelectableContext {
  candidatos?: { clinicas: WhatsAppContextCandidate[]; tutores: WhatsAppContextCandidate[] };
  selecao?: WhatsAppContextSelection | null;
  contexto_chave?: string;
}
