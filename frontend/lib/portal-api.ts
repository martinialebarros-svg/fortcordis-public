"use client";

import { getPortalAdminAuthHeaders } from "@/lib/portal-clinic-admin";
import { portalDateTimeMillis } from "@/lib/portal-datetime";
import { portalErrorMessageFromBody } from "@/lib/portal-errors";

export type PortalActorType = "tutor" | "clinica" | "parceiro";

export type PortalChallengeResponse = {
  accepted: boolean;
  challenge_id: string;
  message: string;
  expires_in_seconds: number;
  debug_code?: string | null;
};

export type PortalSessionResponse = {
  access_token: string;
  token_type: string;
  expires_at: string;
  actor_type: PortalActorType;
  actor_id: number;
  paciente_id?: number | null;
  clinica_id?: number | null;
  partner_id?: number | null;
  partner_nome?: string | null;
  partner_tipo?: PortalPartnerType | null;
  partner_tipo_label?: string | null;
  account_id?: number | null;
  auth_method?: string | null;
  trusted_session_expires_at?: string | null;
  scope: string[];
  message?: string | null;
};

export type PortalClinicAuthResponse = Partial<PortalSessionResponse> & {
  token_type?: string;
  scope?: string[];
  mfa_required?: boolean;
  challenge_id?: string | null;
  message?: string | null;
};

export type PortalPartnerAuthResponse = Partial<PortalSessionResponse> & {
  token_type?: string;
  scope?: string[];
  mfa_required?: boolean;
  challenge_id?: string | null;
  message?: string | null;
};

export type PortalClinicInviteStatusResponse = {
  status: "pending" | "used" | "expired" | "revoked";
  clinica_id: number;
  clinica_nome: string;
  unidade_nome: string;
  expires_at: string;
  can_activate: boolean;
  email_hint?: string | null;
};

export type PortalClinicActivationResponse = {
  activation_id: number;
  access_token?: string | null;
  token_type?: string;
  expires_at?: string | null;
  actor_type?: PortalActorType | null;
  actor_id?: number | null;
  clinica_id?: number | null;
  account_id?: number | null;
  auth_method?: string | null;
  trusted_session_expires_at?: string | null;
  scope?: string[];
  message: string;
};

export type PortalPartnerInviteStatusResponse = {
  status: "pending" | "used" | "expired" | "revoked";
  partner_id: number;
  partner_nome: string;
  partner_tipo: PortalPartnerType;
  partner_tipo_label: string;
  expires_at: string;
  can_activate: boolean;
  email_hint?: string | null;
};

export type PortalPartnerActivationResponse = {
  activation_id: number;
  access_token?: string | null;
  token_type?: string;
  expires_at?: string | null;
  actor_type?: PortalActorType | null;
  actor_id?: number | null;
  partner_id?: number | null;
  partner_nome?: string | null;
  partner_tipo?: PortalPartnerType | null;
  partner_tipo_label?: string | null;
  clinica_id?: number | null;
  account_id?: number | null;
  auth_method?: string | null;
  trusted_session_expires_at?: string | null;
  scope?: string[];
  message: string;
};

export type PortalSimpleAcceptedResponse = {
  accepted: boolean;
  message: string;
};

export type PortalAdminClinicInviteResponse = {
  invite_id?: number | null;
  status: string;
  expires_at?: string | null;
  activation_url: string;
  access_mode: "activation" | "login" | "temporary_password";
  delivery_channel: string;
  delivery_target_masked?: string | null;
  account_email_masked?: string | null;
  delivery_status: string;
  delivery_provider?: string | null;
  senha_temporaria?: string | null;
};

export type PortalAdminClinicInviteSnapshot = {
  id: number;
  status: string;
  delivery_channel: string;
  delivery_target_masked?: string | null;
  expires_at: string;
  created_at: string;
  delivered_at?: string | null;
  used_at?: string | null;
  revoked_at?: string | null;
};

export type PortalAdminClinicAccountSnapshot = {
  id: number;
  status: string;
  email_masked?: string | null;
  responsavel_nome: string;
  email_verified_at?: string | null;
  activated_at?: string | null;
  last_login_at?: string | null;
  force_mfa_on_next_login: boolean;
  revoked_at?: string | null;
};

export type PortalAdminClinicSessionSnapshot = {
  id: number;
  account_id?: number | null;
  status: string;
  trusted_until: string;
  created_at: string;
  last_seen_at?: string | null;
  revoked_at?: string | null;
  device_label?: string | null;
};

export type PortalAdminClinicAccessSummaryResponse = {
  clinica_id: number;
  clinica_nome: string;
  invite?: PortalAdminClinicInviteSnapshot | null;
  account?: PortalAdminClinicAccountSnapshot | null;
  invites: PortalAdminClinicInviteSnapshot[];
  accounts: PortalAdminClinicAccountSnapshot[];
  active_session_count: number;
  active_sessions: PortalAdminClinicSessionSnapshot[];
};

export type PortalAdminClinicAccessOverviewMetrics = {
  total_clinicas: number;
  convites_pendentes: number;
  contas_ativas: number;
  clinicas_sem_convite: number;
  clinicas_precisam_email: number;
  sessoes_ativas: number;
  clinicas_com_downloads: number;
  downloads_total: number;
  downloads_ultimos_30_dias: number;
};

export type PortalAdminClinicAccessOverviewItem = {
  clinica_id: number;
  clinica_nome: string;
  cidade?: string | null;
  estado?: string | null;
  contato_email?: string | null;
  contato_whatsapp?: string | null;
  login_email?: string | null;
  invite?: PortalAdminClinicInviteSnapshot | null;
  invite_account_email_masked?: string | null;
  account?: PortalAdminClinicAccountSnapshot | null;
  active_session_count: number;
  active_accounts_count: number;
  status_key: string;
  status_label: string;
  needs_email_definition: boolean;
  download_count: number;
  last_download_at?: string | null;
  first_download_at?: string | null;
  last_access_at?: string | null;
  days_since_last_activity?: number | null;
  timeline: PortalAdminClinicTimelineEvent[];
};

export type PortalAdminClinicDownloadEvent = {
  audit_event_id: number;
  clinica_id: number;
  clinica_nome: string;
  account_email_masked?: string | null;
  exame_id?: number | null;
  paciente_nome?: string | null;
  tutor_nome?: string | null;
  tipo_exame?: string | null;
  anexo_nome?: string | null;
  downloaded_at: string;
  is_first_download: boolean;
};

export type PortalAdminClinicTimelineEvent = {
  event_id: string;
  event_type: string;
  title: string;
  description?: string | null;
  occurred_at: string;
  tone: "neutral" | "success" | "warning" | "danger";
};

export type PortalAdminClinicAccessOverviewResponse = {
  generated_at: string;
  metrics: PortalAdminClinicAccessOverviewMetrics;
  items: PortalAdminClinicAccessOverviewItem[];
  recent_downloads: PortalAdminClinicDownloadEvent[];
};

export type PortalPartnerType = "clinica" | "veterinario";

export type PortalPartnerClinicLink = {
  clinica_id: number;
  clinica_nome?: string | null;
  receber_todos_laudos: boolean;
};

export type PortalPartnerProfile = {
  id: number;
  tipo: PortalPartnerType;
  tipo_label: string;
  clinica_id?: number | null;
  clinica_nome?: string | null;
  clinicas_vinculadas?: PortalPartnerClinicLink[];
  nome_exibicao: string;
  email_login?: string | null;
  telefone?: string | null;
  whatsapp?: string | null;
  cidade_base?: string | null;
  estado_base?: string | null;
  crmv?: string | null;
  cpf_documento?: string | null;
  area_atuacao?: string | null;
  observacoes?: string | null;
  ativo: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type PortalPartnerProfileListResponse = {
  total: number;
  items: PortalPartnerProfile[];
};

export type PortalPartnerClinicLinkPayload = {
  clinica_id: number;
  receber_todos_laudos?: boolean;
};

export type PortalPartnerProfileCreatePayload = {
  tipo: PortalPartnerType;
  clinica_id?: number;
  clinicas_vinculadas?: PortalPartnerClinicLinkPayload[];
  nome_exibicao?: string;
  email_login?: string;
  telefone?: string;
  whatsapp?: string;
  cidade_base?: string;
  estado_base?: string;
  crmv?: string;
  cpf_documento?: string;
  area_atuacao?: string;
  observacoes?: string;
  ativo?: boolean;
};

export type PortalPartnerProfileUpdatePayload = {
  clinicas_vinculadas?: PortalPartnerClinicLinkPayload[];
  nome_exibicao?: string;
  email_login?: string;
  telefone?: string;
  whatsapp?: string;
  cidade_base?: string;
  estado_base?: string;
  crmv?: string;
  cpf_documento?: string;
  area_atuacao?: string;
  observacoes?: string;
  ativo?: boolean;
};

export type PortalExamAttachment = {
  anexo_id: number;
  nome_original: string;
  mime_type: string;
  tamanho: number | null;
  download_available: boolean;
};

export type PortalExamItem = {
  id: number;
  paciente_id: number;
  paciente_nome?: string | null;
  tutor_nome?: string | null;
  especie?: string | null;
  atendimento_id: number | null;
  laudo_id: number | null;
  tipo_exame: string;
  categoria_exame: string | null;
  prioridade: string | null;
  status: string | null;
  data_exame: string | null;
  data_solicitacao: string | null;
  data_resultado: string | null;
  observacoes: string | null;
  anexos: PortalExamAttachment[];
};

export type PortalClinicOperationalSummary = {
  realizados_hoje: number;
  em_laudo: number;
  aguardando_liberacao: number;
  liberados_hoje: number;
  sla_horas: number;
};

export type PortalClinicOperationalItem = {
  item_id: string;
  origem: "laudo" | "exame";
  paciente_id: number | null;
  paciente_nome?: string | null;
  tutor_nome?: string | null;
  especie?: string | null;
  tipo_exame: string;
  status_key: string;
  status_label: string;
  data_realizacao?: string | null;
  data_liberacao?: string | null;
  previsao_liberacao?: string | null;
  observacoes?: string | null;
};

export type PortalExamListResponse = {
  total: number;
  clinica_id?: number | null;
  clinica_nome?: string | null;
  partner_id?: number | null;
  partner_nome?: string | null;
  partner_tipo?: PortalPartnerType | null;
  partner_tipo_label?: string | null;
  operational_summary?: PortalClinicOperationalSummary | null;
  operational_items?: PortalClinicOperationalItem[];
  operational_pending_items?: PortalClinicOperationalItem[];
  items: PortalExamItem[];
  must_change_password?: boolean | null;
};

export type PortalDownloadItem = {
  anexo_id: number;
  nome_original: string;
  mime_type: string;
  download_url: string;
  download_token: string;
  download_token_header: string;
  expires_at: string;
};

export type PortalDownloadUrlResponse = {
  exame_id: number;
  items: PortalDownloadItem[];
};

export type PortalExamLinkResponse = {
  clinica_nome: string;
  paciente_nome?: string | null;
  tipo_exame: string;
  data_exame?: string | null;
  arquivos: PortalDownloadItem[];
  dispositivo_confiavel_disponivel?: boolean;
};

const PORTAL_SESSION_STORAGE_KEY_PREFIX = "fortcordis_portal_session";

function getPortalSessionStorageKey(actorType: PortalActorType): string {
  return `${PORTAL_SESSION_STORAGE_KEY_PREFIX}:${actorType}`;
}

function getCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const encodedName = `${encodeURIComponent(name)}=`;
  const parts = document.cookie.split(";");
  for (const part of parts) {
    const trimmed = part.trim();
    if (trimmed.startsWith(encodedName)) {
      return decodeURIComponent(trimmed.slice(encodedName.length));
    }
  }
  return null;
}

/**
 * Erro de uma chamada ao portal que o servidor respondeu.
 *
 * Existe para distinguir "o servidor recusou" de "nao consegui falar com o
 * servidor". Sem isso, uma queda de rede era indistinguivel de um 401 e levava a
 * desconectar quem continuava autorizado.
 */
export class PortalRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "PortalRequestError";
    this.status = status;
  }
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    return portalErrorMessageFromBody(await response.text(), fallback);
  } catch {
    return fallback;
  }
}

async function portalFetchJson<T>(
  url: string,
  options: RequestInit = {},
  fallback = "Erro ao comunicar com o portal.",
): Promise<T> {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "GET").toUpperCase();
  if (!headers.has("Content-Type") && method !== "GET") {
    headers.set("Content-Type", "application/json");
  }

  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    const csrfToken = getCookie("fortcordis_csrf");
    if (csrfToken) {
      headers.set("x-csrf-token", csrfToken);
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: options.credentials || "same-origin",
  });

  if (!response.ok) {
    throw new PortalRequestError(response.status, await readErrorMessage(response, fallback));
  }

  return (await response.json()) as T;
}

function removePortalSessionEverywhere(actorType: PortalActorType): void {
  if (typeof window === "undefined") {
    return;
  }
  const key = getPortalSessionStorageKey(actorType);
  window.sessionStorage.removeItem(key);
  window.localStorage.removeItem(key);
}

function shouldPersistPortalSession(session: PortalSessionResponse): boolean {
  if (session.actor_type !== "clinica" && session.actor_type !== "parceiro") {
    return false;
  }
  if (!session.trusted_session_expires_at) {
    return false;
  }
  return portalDateTimeMillis(session.trusted_session_expires_at) > Date.now();
}

export async function requestTutorPortalChallenge(payload: {
  tutor_id: number;
  paciente_id: number;
  canal: "email" | "whatsapp";
  contato: string;
}): Promise<PortalChallengeResponse> {
  return portalFetchJson<PortalChallengeResponse>("/api/v1/portal/tutores/sessao-link", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function requestClinicPortalChallenge(payload: {
  clinica_id: number;
  email: string;
  responsavel_nome: string;
}): Promise<PortalChallengeResponse> {
  return portalFetchJson<PortalChallengeResponse>("/api/v1/portal/clinicas/sessao-link", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function verifyPortalCode(payload: {
  challenge_id: string;
  codigo: string;
}): Promise<PortalSessionResponse> {
  return portalFetchJson<PortalSessionResponse>(
    "/api/v1/portal/auth/verificar-codigo",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel validar o codigo.",
  );
}

export async function getClinicInviteStatus(inviteToken: string): Promise<PortalClinicInviteStatusResponse> {
  return portalFetchJson<PortalClinicInviteStatusResponse>(
    `/api/v1/portal/clinicas/convites/${encodeURIComponent(inviteToken)}`,
    {},
    "Nao foi possivel consultar o convite da clinica.",
  );
}

export async function activateClinicInvite(payload: {
  invite_token: string;
  email?: string;
  responsavel_nome: string;
  password: string;
  password_confirmation: string;
}): Promise<PortalClinicActivationResponse> {
  return portalFetchJson<PortalClinicActivationResponse>(
    "/api/v1/portal/clinicas/ativacao",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel iniciar a ativacao da clinica.",
  );
}

export async function getPartnerInviteStatus(inviteToken: string): Promise<PortalPartnerInviteStatusResponse> {
  return portalFetchJson<PortalPartnerInviteStatusResponse>(
    `/api/v1/portal/parceiros/convites/${encodeURIComponent(inviteToken)}`,
    {},
    "Nao foi possivel consultar o convite do parceiro.",
  );
}

export async function activatePartnerInvite(payload: {
  invite_token: string;
  responsavel_nome: string;
  password: string;
  password_confirmation: string;
}): Promise<PortalPartnerActivationResponse> {
  return portalFetchJson<PortalPartnerActivationResponse>(
    "/api/v1/portal/parceiros/ativacao",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel iniciar a ativacao do parceiro.",
  );
}

export async function verifyClinicEmailCode(payload: {
  challenge_id: string;
  codigo: string;
}): Promise<PortalChallengeResponse> {
  return portalFetchJson<PortalChallengeResponse>(
    "/api/v1/portal/auth/email/verificar",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel validar o codigo do email.",
  );
}

export async function loginClinicPortal(payload: {
  email: string;
  password: string;
  remember_device_until_shift_end: boolean;
}): Promise<PortalClinicAuthResponse> {
  return portalFetchJson<PortalClinicAuthResponse>(
    "/api/v1/portal/auth/login",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel iniciar a sessao da clinica.",
  );
}

export async function verifyClinicPortalMfa(payload: {
  challenge_id: string;
  codigo: string;
  remember_device_until_shift_end: boolean;
}): Promise<PortalClinicAuthResponse> {
  return portalFetchJson<PortalClinicAuthResponse>(
    "/api/v1/portal/auth/mfa/verificar",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel confirmar o acesso da clinica.",
  );
}

export async function refreshClinicPortalSession(): Promise<PortalClinicAuthResponse> {
  return portalFetchJson<PortalClinicAuthResponse>(
    "/api/v1/portal/auth/refresh",
    {
      method: "POST",
      body: JSON.stringify({}),
    },
    "Nao foi possivel renovar a sessao da clinica.",
  );
}

export async function loginPartnerPortal(payload: {
  email: string;
  password: string;
  remember_device_until_shift_end: boolean;
}): Promise<PortalPartnerAuthResponse> {
  return portalFetchJson<PortalPartnerAuthResponse>(
    "/api/v1/portal/parceiros/auth/login",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel iniciar a sessao do parceiro.",
  );
}

export async function verifyPartnerPortalMfa(payload: {
  challenge_id: string;
  codigo: string;
  remember_device_until_shift_end: boolean;
}): Promise<PortalPartnerAuthResponse> {
  return portalFetchJson<PortalPartnerAuthResponse>(
    "/api/v1/portal/parceiros/auth/mfa/verificar",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel confirmar o acesso do parceiro.",
  );
}

export async function refreshPartnerPortalSession(): Promise<PortalPartnerAuthResponse> {
  return portalFetchJson<PortalPartnerAuthResponse>(
    "/api/v1/portal/parceiros/auth/refresh",
    {
      method: "POST",
      body: JSON.stringify({}),
    },
    "Nao foi possivel renovar a sessao do parceiro.",
  );
}

export async function logoutClinicPortal(token?: string | null): Promise<PortalSimpleAcceptedResponse> {
  return portalFetchJson<PortalSimpleAcceptedResponse>(
    "/api/v1/portal/auth/logout",
    {
      method: "POST",
      headers: token
        ? {
            Authorization: `Bearer ${token}`,
          }
        : undefined,
      body: JSON.stringify({}),
    },
    "Nao foi possivel encerrar a sessao da clinica.",
  );
}

export async function logoutPartnerPortal(token?: string | null): Promise<PortalSimpleAcceptedResponse> {
  return portalFetchJson<PortalSimpleAcceptedResponse>(
    "/api/v1/portal/parceiros/auth/logout",
    {
      method: "POST",
      headers: token
        ? {
            Authorization: `Bearer ${token}`,
          }
        : undefined,
      body: JSON.stringify({}),
    },
    "Nao foi possivel encerrar a sessao do parceiro.",
  );
}

export async function requestClinicPasswordReset(payload: {
  email: string;
}): Promise<PortalSimpleAcceptedResponse> {
  return portalFetchJson<PortalSimpleAcceptedResponse>(
    "/api/v1/portal/auth/esqueci-senha",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel processar a redefinicao de senha.",
  );
}

export async function resetClinicPassword(payload: {
  reset_token: string;
  password: string;
  password_confirmation: string;
}): Promise<PortalSimpleAcceptedResponse> {
  return portalFetchJson<PortalSimpleAcceptedResponse>(
    "/api/v1/portal/auth/redefinir-senha",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel redefinir a senha da clinica.",
  );
}

export async function changeClinicPortalPassword(
  payload: {
    senha_atual: string;
    nova_senha: string;
    nova_senha_confirmacao: string;
  },
  token: string,
): Promise<PortalSimpleAcceptedResponse> {
  return portalFetchJson<PortalSimpleAcceptedResponse>(
    "/api/v1/portal/auth/trocar-senha",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    },
    "Nao foi possivel trocar a senha da clinica.",
  );
}

export async function requestPartnerPasswordReset(payload: {
  email: string;
}): Promise<PortalSimpleAcceptedResponse> {
  return portalFetchJson<PortalSimpleAcceptedResponse>(
    "/api/v1/portal/parceiros/auth/esqueci-senha",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel processar a redefinicao de senha do parceiro.",
  );
}

export async function resetPartnerPassword(payload: {
  reset_token: string;
  password: string;
  password_confirmation: string;
}): Promise<PortalSimpleAcceptedResponse> {
  return portalFetchJson<PortalSimpleAcceptedResponse>(
    "/api/v1/portal/parceiros/auth/redefinir-senha",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel redefinir a senha do parceiro.",
  );
}

export async function createPortalPartnerInvite(
  partnerId: number,
  payload: {
    delivery_channel: "whatsapp";
    delivery_target: string;
    expires_in_hours: number;
    allow_manual_copy: boolean;
  },
): Promise<PortalAdminClinicInviteResponse> {
  return portalFetchJson<PortalAdminClinicInviteResponse>(
    `/api/v1/portal/parceiros/${partnerId}/convites`,
    {
      method: "POST",
      headers: getPortalAdminAuthHeaders(),
      body: JSON.stringify(payload),
    },
    "Nao foi possivel gerar o convite do parceiro.",
  );
}

export async function getPortalClinicAccessSummary(
  clinicaId: number,
): Promise<PortalAdminClinicAccessSummaryResponse> {
  return portalFetchJson<PortalAdminClinicAccessSummaryResponse>(
    `/api/v1/portal/admin/clinicas/${clinicaId}/acesso`,
    {},
    "Nao foi possivel carregar o resumo de acesso da clinica.",
  );
}

export async function createPortalClinicInvite(
  clinicaId: number,
  payload: {
    delivery_channel: "whatsapp";
    delivery_target: string;
    account_email?: string;
    expires_in_hours: number;
    allow_manual_copy: boolean;
  },
): Promise<PortalAdminClinicInviteResponse> {
  return portalFetchJson<PortalAdminClinicInviteResponse>(
    `/api/v1/portal/admin/clinicas/${clinicaId}/convites`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel gerar o convite da clinica.",
  );
}

export async function revokePortalClinicInvite(
  clinicaId: number,
  inviteId: number,
  reason: string,
): Promise<{ status: string; revoked_at: string }> {
  return portalFetchJson<{ status: string; revoked_at: string }>(
    `/api/v1/portal/admin/clinicas/${clinicaId}/convites/${inviteId}/revogar`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
    "Nao foi possivel revogar o convite da clinica.",
  );
}

export async function revokePortalClinicAccount(
  accountId: number,
  payload: { reason: string; revoke_sessions: boolean },
): Promise<{ status: string; revoked_at: string }> {
  return portalFetchJson<{ status: string; revoked_at: string }>(
    `/api/v1/portal/admin/clinica-accounts/${accountId}/revogar`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel revogar a conta da clinica.",
  );
}

export async function revokePortalClinicSessions(payload: {
  clinica_id: number;
  session_id?: number;
  reason: string;
}): Promise<{ revoked_count: number }> {
  return portalFetchJson<{ revoked_count: number }>(
    "/api/v1/portal/admin/clinica-sessions/revogar",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Nao foi possivel revogar as sessoes da clinica.",
  );
}

export async function listPortalPetExams(pacienteId: number, token: string): Promise<PortalExamListResponse> {
  return portalFetchJson<PortalExamListResponse>(
    `/api/v1/portal/pets/${pacienteId}/exames`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
    "Nao foi possivel carregar os exames.",
  );
}

export type PortalClinicExamFilters = {
  q?: string;
  pet?: string;
  tutor?: string;
  especie?: string;
  tipo_exame?: string;
  status_exame?: string;
  data_inicio?: string;
  data_fim?: string;
  sort_by?: "data" | "tipo_exame" | "especie" | "pet" | "tutor" | "status";
  sort_dir?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export async function listPortalClinicExams(
  filters: PortalClinicExamFilters,
  token: string,
): Promise<PortalExamListResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    params.set(key, String(value));
  });

  const query = params.toString();
  return portalFetchJson<PortalExamListResponse>(
    `/api/v1/portal/clinicas/exames${query ? `?${query}` : ""}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
    "Nao foi possivel carregar os exames da clinica.",
  );
}

export type PortalClinicaAgendamentoItem = {
  id: number;
  data: string | null;
  hora: string | null;
  inicio: string | null;
  fim: string | null;
  status: string;
  paciente_nome: string | null;
  tutor_nome: string | null;
  servico_nome: string | null;
  pode_cancelar: boolean;
};

export type PortalClinicaAgendamentoListResponse = {
  total: number;
  clinica_id: number;
  clinica_nome: string;
  items: PortalClinicaAgendamentoItem[];
};

export type PortalClinicaAgendamentoCancelResponse = {
  item: PortalClinicaAgendamentoItem;
  message: string;
};

export async function listPortalClinicAgendamentos(
  token: string,
): Promise<PortalClinicaAgendamentoListResponse> {
  return portalFetchJson<PortalClinicaAgendamentoListResponse>(
    "/api/v1/portal/clinicas/agendamentos",
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
    "Nao foi possivel carregar os agendamentos da clinica.",
  );
}

export async function cancelPortalClinicAgendamento(
  agendamentoId: number,
  token: string,
): Promise<PortalClinicaAgendamentoCancelResponse> {
  return portalFetchJson<PortalClinicaAgendamentoCancelResponse>(
    `/api/v1/portal/clinicas/agendamentos/${agendamentoId}/cancelar`,
    {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({}),
    },
    "Nao foi possivel cancelar o agendamento.",
  );
}

export type PortalClinicaOrdemServicoItem = {
  id: number;
  numero_os: string;
  status: string;
  valor: number;
  data_atendimento: string | null;
  paciente_nome: string | null;
  servico_nome: string | null;
};

export type PortalClinicaFinanceiroSummary = {
  total_pendente: number;
  total_pago: number;
  quantidade_pendente: number;
  quantidade_pago: number;
};

export type PortalClinicaFinanceiroResponse = {
  clinica_id: number;
  clinica_nome: string;
  summary: PortalClinicaFinanceiroSummary;
  pendentes: PortalClinicaOrdemServicoItem[];
  pagas: PortalClinicaOrdemServicoItem[];
};

export async function getPortalClinicFinanceiro(token: string): Promise<PortalClinicaFinanceiroResponse> {
  return portalFetchJson<PortalClinicaFinanceiroResponse>(
    "/api/v1/portal/clinicas/financeiro",
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
    "Nao foi possivel carregar o financeiro da clinica.",
  );
}

export async function downloadPortalClinicOSRecibo(
  ordemServicoId: number,
  token: string,
  filenameFallback = "recibo.pdf",
): Promise<void> {
  const response = await fetch(`/api/v1/portal/clinicas/ordens-servico/${ordemServicoId}/recibo`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Nao foi possivel baixar o recibo."));
  }

  const blob = await response.blob();
  const blobUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = filenameFallback;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(blobUrl);
}

export async function listPortalPartnerExams(
  filters: PortalClinicExamFilters,
  token: string,
): Promise<PortalExamListResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    params.set(key, String(value));
  });

  const query = params.toString();
  return portalFetchJson<PortalExamListResponse>(
    `/api/v1/portal/parceiros/exames${query ? `?${query}` : ""}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
    "Nao foi possivel carregar os exames do parceiro.",
  );
}

export async function listPortalAdminClinicMirrorExams(
  clinicaId: number,
  filters: PortalClinicExamFilters,
): Promise<PortalExamListResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    params.set(key, String(value));
  });

  const query = params.toString();
  return portalFetchJson<PortalExamListResponse>(
    `/api/v1/portal/admin/clinicas/${clinicaId}/espelho${query ? `?${query}` : ""}`,
    {
      headers: getPortalAdminAuthHeaders(),
    },
    "Nao foi possivel carregar a visao espelhada da clinica.",
  );
}

export async function createPortalExamDownloadUrls(
  exameId: number,
  token: string,
): Promise<PortalDownloadUrlResponse> {
  return portalFetchJson<PortalDownloadUrlResponse>(
    `/api/v1/portal/exames/${exameId}/download-url`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({}),
    },
    "Nao foi possivel preparar o download.",
  );
}

export async function createPortalAdminClinicExamDownloadUrls(
  clinicaId: number,
  exameId: number,
): Promise<PortalDownloadUrlResponse> {
  return portalFetchJson<PortalDownloadUrlResponse>(
    `/api/v1/portal/admin/clinicas/${clinicaId}/exames/${exameId}/download-url`,
    {
      method: "POST",
      headers: getPortalAdminAuthHeaders(),
      body: JSON.stringify({}),
    },
    "Nao foi possivel preparar o download na visao espelhada.",
  );
}

export type PortalDeviceTrustResponse = {
  access_token: string;
  token_type: string;
  expires_at: string;
  actor_type: "clinica";
  actor_id: number;
  clinica_id: number;
  clinica_nome: string;
  scope: string[];
  trusted_until: string;
  auth_method: string;
};

/** `clinic:read` separa o portal completo do modo laudos da recepcao. */
export const PORTAL_PERMISSION_CLINIC_READ = "clinic:read";

export function portalSessionHasClinicRead(session: PortalSessionResponse | null): boolean {
  return Boolean(session?.scope?.includes(PORTAL_PERMISSION_CLINIC_READ));
}

/** Metodo de autenticacao da sessao nascida do link do laudo. */
export const PORTAL_AUTH_METHOD_DEVICE_TRUST = "device_trust";

export function portalSessionIsDeviceTrust(session: PortalSessionResponse | null): boolean {
  return session?.auth_method === PORTAL_AUTH_METHOD_DEVICE_TRUST;
}

function deviceTrustToSession(payload: PortalDeviceTrustResponse): PortalSessionResponse {
  return {
    access_token: payload.access_token,
    token_type: payload.token_type || "bearer",
    expires_at: payload.expires_at,
    actor_type: "clinica",
    actor_id: payload.actor_id,
    clinica_id: payload.clinica_id,
    paciente_id: null,
    account_id: null,
    auth_method: payload.auth_method || "device_trust",
    trusted_session_expires_at: payload.trusted_until,
    scope: payload.scope || [],
    message: null,
  };
}

/** Conecta este computador ao portal em modo laudos, a partir do link do laudo. */
export async function trustPortalDevice(
  linkToken: string,
  deviceLabel?: string,
): Promise<PortalSessionResponse> {
  const payload = await portalFetchJson<PortalDeviceTrustResponse>(
    `/api/v1/portal/laudo-link/${encodeURIComponent(linkToken)}/confiar-dispositivo`,
    {
      method: "POST",
      body: JSON.stringify({ device_label: deviceLabel ?? null }),
    },
    "Nao foi possivel conectar este computador.",
  );
  return deviceTrustToSession(payload);
}

/** Retoma a sessao do computador confiavel pelo cookie, sem pedir senha. */
export async function resumePortalDeviceSession(): Promise<PortalSessionResponse> {
  const payload = await portalFetchJson<PortalDeviceTrustResponse>(
    "/api/v1/portal/clinicas/dispositivo/sessao",
    { method: "POST" },
    "Dispositivo nao esta mais conectado.",
  );
  return deviceTrustToSession(payload);
}

export async function endPortalDeviceTrust(): Promise<void> {
  await portalFetchJson<{ encerrado: boolean }>(
    "/api/v1/portal/clinicas/dispositivo/encerrar",
    { method: "POST" },
    "Nao foi possivel encerrar o acesso deste computador.",
  );
}

/** Abre UM laudo pelo link recebido no WhatsApp da clinica - sem sessao, sem senha. */
export async function resolvePortalExamLink(token: string): Promise<PortalExamLinkResponse> {
  return portalFetchJson<PortalExamLinkResponse>(
    `/api/v1/portal/laudo-link/${encodeURIComponent(token)}`,
    { method: "POST" },
    "Este link nao esta mais disponivel.",
  );
}

export async function downloadPortalAttachment(item: PortalDownloadItem): Promise<void> {
  const response = await fetch(item.download_url, {
    headers: {
      [item.download_token_header]: item.download_token,
    },
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Nao foi possivel baixar o anexo."));
  }

  const blob = await response.blob();
  const blobUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = item.nome_original || "anexo";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(blobUrl);
}

export function savePortalSession(session: PortalSessionResponse): void {
  if (typeof window === "undefined") {
    return;
  }
  const key = getPortalSessionStorageKey(session.actor_type);
  const serialized = JSON.stringify(session);
  if (shouldPersistPortalSession(session)) {
    window.localStorage.setItem(key, serialized);
    window.sessionStorage.removeItem(key);
    return;
  }
  window.sessionStorage.setItem(key, serialized);
  window.localStorage.removeItem(key);
}

export function loadPortalSession(expectedActorType?: PortalActorType): PortalSessionResponse | null {
  if (typeof window === "undefined" || !expectedActorType) {
    return null;
  }

  const key = getPortalSessionStorageKey(expectedActorType);
  const candidates = [
    { storage: window.sessionStorage, raw: window.sessionStorage.getItem(key) },
    { storage: window.localStorage, raw: window.localStorage.getItem(key) },
  ];

  for (const candidate of candidates) {
    const raw = candidate.raw;
    if (!raw) {
      continue;
    }
    try {
      const parsed = JSON.parse(raw) as PortalSessionResponse;
      if (!parsed?.access_token || !parsed?.expires_at || parsed.actor_type !== expectedActorType) {
        candidate.storage.removeItem(key);
        continue;
      }
      if (portalDateTimeMillis(parsed.expires_at) <= Date.now()) {
        candidate.storage.removeItem(key);
        continue;
      }
      return parsed;
    } catch {
      candidate.storage.removeItem(key);
    }
  }

  return null;
}

export function clearPortalSession(actorType: PortalActorType): void {
  removePortalSessionEverywhere(actorType);
}
