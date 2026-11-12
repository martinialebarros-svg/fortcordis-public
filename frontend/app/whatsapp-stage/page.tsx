"use client";

import { ChangeEvent, FormEvent, Fragment, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle, Building2, CalendarDays, Check, CheckCheck, ChevronRight,
  CircleDot, ClipboardList, Clock3, FileText, Filter, Inbox, Info, Link2,
  MessageSquare, MessagesSquare, Paperclip, PawPrint, Pencil, RefreshCw, Search, Send, Settings,
  ShieldAlert, Sparkles, UserCheck, UserRound, Users, X,
} from "lucide-react";
import DashboardLayout from "../layout-dashboard";
import AppointmentQueue from "./AppointmentQueue";
import WaitingForTeamNotice from "./WaitingForTeamNotice";
import ConversationContextSelector from "./ConversationContextSelector";
import type { WhatsAppContextSelectionPayload, WhatsAppSelectableContext } from "@/lib/whatsapp-contexto";
import {
  CustomerServiceWindow,
  evaluateCustomerServiceWindow,
} from "@/lib/whatsapp-customer-service-window";
import {
  buildMessageResendRequest,
  shouldOfferMessageResend,
} from "@/lib/whatsapp-message-retry";
import { useWhatsAppDrafts } from "@/lib/use-whatsapp-drafts";
import { agendaReceiptLabel } from "@/lib/whatsapp-agenda-receipt";
import { useCurrentUser } from "@/lib/useCurrentUser";
import QuickReplyLibrary from "@/components/whatsapp/QuickReplyLibrary";

import FollowUpPanel, { FollowUp, followUpLabel } from "@/components/whatsapp/FollowUpPanel";

type FollowUpFilter = "" | "all" | "due" | "today" | "upcoming" | "responded" | "ready";
type AssignedFilter = "all" | "assigned" | "unassigned" | "mine";
type ConversationStatus = "open" | "pending" | "closed";
type ComposerMode = "message" | "template";

interface Conversation {
  id: string;
  wa_phone_number: string;
  wa_psid: string | null;
  status: string;
  subject: string | null;
  last_agent_id: string | null;
  assigned_agent_name?: string | null;
  assigned_agent_email?: string | null;
  last_activity_at: string;
  last_inbound_at?: string | null;
  last_seen_at?: string | null;
  unread?: boolean;
  follow_up?: FollowUp | null;
  needs_reply?: boolean;
  waiting_since?: string | null;
  last_message_id?: string | null;
  created_at: string;
  updated_at: string;
  last_message_body?: string | null;
  last_message_at?: string | null;
  last_message_from_me?: boolean | null;
  last_message_type?: string | null;
  customer_service_window?: CustomerServiceWindow;
}

interface Message {
  id: string;
  conversation_id: string;
  wa_message_id: string | null;
  from_me: boolean;
  body: string | null;
  type: string;
  status: string;
  created_at: string;
  metadata?: unknown;
}

interface Agent {
  id: string;
  name: string | null;
  email: string | null;
  role: string;
  active: boolean;
  created_at: string;
}

interface TemplateCatalogItem {
  key: string;
  name: string;
  meta_id: string;
  language: string;
  body: string;
  body_parameter_count: number;
  variable_labels: string[];
  quick_replies: readonly string[];
  category: "agenda" | "laudos" | "financeiro";
  workflow_label: string;
  requires_document: boolean;
  can_copy_as_free_text: boolean;
  meta_approval_live: null;
}

interface Pagination { page: number; limit: number; total: number }
interface ApiResult<T> { ok: boolean; status: number; data: T | null; errorText?: string }
interface QueueSummary { total: number; unread: number; unassigned: number; open: number; pending: number; closed: number; needs_reply?: number; follow_up_due?: number; follow_up_ready?: number; my_follow_up_ready?: number }
interface ConversationsResponse { data: Conversation[]; pagination: Pagination; summary?: QueueSummary }
interface AgentsResponse { data: Agent[] }
interface MessagesResponse {
  data: Message[];
  last_message_id?: string | null;
  pagination: Pagination;
  last_inbound_at?: string | null;
  customer_service_window: CustomerServiceWindow;
}
interface TemplateCatalogResponse {
  data: TemplateCatalogItem[];
  source: "configured_catalog";
  meta_approval_live: null;
}
interface DomainClinic { id: number; nome: string; cidade: string | null; estado: string | null }
interface DomainTutor { id: number; nome: string }
interface DomainPet {
  id: number; tutor_id: number | null; nome: string; especie: string | null; raca: string | null;
}
interface DomainAppointment {
  id: number; inicio: string | null; fim: string | null; status: string;
  clinica_id: number | null; clinica_nome: string; tutor_id: number | null; tutor_nome: string;
  pet_id: number | null; pet_nome: string; servico_id: number | null; servico_nome: string;
}
interface DomainServiceOrder {
  id: number; numero_os: string; agendamento_id: number; data_atendimento: string | null;
  status: string; valor_final: number; clinica_id: number | null; clinica_nome: string;
  tutor_id: number | null; tutor_nome: string; pet_id: number | null; pet_nome: string;
  servico_id: number | null; servico_nome: string;
}
interface ConversationDomainContext extends WhatsAppSelectableContext {
  normalized_phone: string;
  resolution: "matched" | "ambiguous" | "not_found" | "selection_invalid";
  match_type: "clinica" | "tutor" | null;
  clinicas: DomainClinic[];
  tutores: DomainTutor[];
  pets: DomainPet[];
  agendamentos: DomainAppointment[];
  ordens_servico: DomainServiceOrder[];
}
interface LoadMessagesOptions { isCurrent?: () => boolean; silent?: boolean }
type WhatsAppBotMode = "off" | "suggest" | "auto";
interface WhatsAppBotDraft {
  resposta_id: number;
  texto_gerado: string;
  criado_em: string | null;
}
/** Sem `texto_gerado` de proposito: em `blocked` o texto e o que o guardrail
 *  recusou, e o backend nao o devolve. Aqui so o motivo e acionavel. */
interface WhatsAppBotRecusa {
  resposta_id: number;
  decisao: "blocked" | "handoff";
  motivo: string | null;
  criado_em: string | null;
  aviso_enviado?: boolean;
}
interface WhatsAppBotSilencio {
  resposta_id: number;
  motivo: string | null;
  criado_em: string | null;
}
interface WhatsAppBotConversationState {
  wa_identity: string;
  modo: WhatsAppBotMode;
  modo_origem: "conversa" | "institucional";
  pausado_ate: string | null;
  pausado: boolean;
  envio_automatico_liberado?: boolean;
  solicitacao_agendamento?: { status: string; status_equipe?: string; resumo: string; preferencia_recebida_em?: string | null } | null;
  handoff_motivo: string | null;
  rascunho_pendente: WhatsAppBotDraft | null;
  ultima_recusa: WhatsAppBotRecusa | null;
  ultimo_silencio: WhatsAppBotSilencio | null;
}

/** Motivos que o guardrail grava, em portugues de atendente. Chave
 *  desconhecida cai no proprio motivo bruto, que e melhor que sumir. */
const BOT_RECUSA_MOTIVOS: Record<string, string> = {
  envio_auto_incerto: "a entrega automática não foi confirmada; confira a conversa antes de responder novamente",
  auto_interrompido: "a automação foi interrompida por uma alteração nos controles da conversa",
  diagnostico: "a resposta continha diagnóstico",
  dose_medicacao: "a resposta continha medicação ou dose",
  prognostico: "a resposta continha prognóstico",
  avaliacao_sintoma: "a resposta avaliava um sintoma",
  vazamento_conteudo_laudo: "a resposta trazia conteúdo de laudo",
  sem_fonte: "não havia fonte para o que seria afirmado",
  valor_fora_tabela: "havia valor fora da tabela de preços",
  prazo_nao_confirmado: "havia prazo ou horário sem confirmação",
  contato_fora_da_fonte: "havia telefone ou CEP fora do cadastro",
  endereco_sem_fonte: "havia endereço sem cadastro que o sustente",
  teto_caracteres: "a resposta passou do limite de tamanho",
  emergencia: "possível emergência: contato telefônico imediato",
  pedido_humano: "o cliente pediu para falar com uma pessoa",
  identidade_nao_resolvida: "não foi possível determinar qual cadastro usar nesta conversa",
  identidade_ambigua: "há mais de um cadastro vinculado a este número; escolha o cadastro em Vínculos do cadastro",
  identidade_selecao_invalida: "o cadastro escolhido não está mais disponível para este número; revise a escolha em Vínculos do cadastro",
  identidade_indisponivel: "a consulta aos cadastros está temporariamente indisponível",
  tipo_nao_suportado: "a mensagem não é de texto",
  escopo_incoerente: "o escopo da conversa está inconsistente",
  conversa_divergente: "o serviço devolveu outra conversa para este número",
  modelo_pediu_humano: "o próprio bot pediu ajuda humana",
};

/** Motivos de SILENCIO: o bot viu a mensagem e nao respondeu, sem que isso
 *  seja recusa do guardrail. Só entram aqui os acionaveis - o backend ja
 *  filtra o ruido (`bot_desabilitado`, `modo_off`, cortesia). */
const BOT_SILENCIO_MOTIVOS: Record<string, string> = {
  pausado: "o atendimento automático desta conversa está pausado",
  contexto_alterado: "o cadastro usado pelo bot mudou; aguardando uma nova mensagem do cliente",
  janela_fechada: "a janela de 24 horas do WhatsApp está fechada",
  teto_diario: "o limite diário de respostas desta conversa foi atingido",
  conversa_divergente: "a mensagem não confere com a conversa registrada",
};

const MESSAGE_STATUS_REFRESH_INTERVAL_MS = 5_000;
const QUEUE_REFRESH_INTERVAL_MS = 15_000;
const CUSTOMER_SERVICE_WINDOW_CLOCK_INTERVAL_MS = 30_000;
const CONVERSATION_STATUS_OPTIONS: Array<{ value: "" | ConversationStatus; label: string }> = [
  { value: "", label: "Todas" },
  { value: "open", label: "Em atendimento" },
  { value: "pending", label: "Aguardando" },
  { value: "closed", label: "Resolvidas" },
];

function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<ApiResult<T>> {
  const controller = (!init?.method || init.method === "GET") && !init?.signal ? new AbortController() : null;
  const timeout = controller ? window.setTimeout(() => controller.abort(), 15_000) : null;
  try {
    const response = await fetch(url, {
      cache: "no-store", ...init,
      signal: init?.signal ?? controller?.signal,
      headers: { "Content-Type": "application/json", ...getAuthHeaders(), ...(init?.headers || {}) },
    });
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const parsed = (await response.json()) as T;
      return { ok: response.ok, status: response.status, data: parsed,
        errorText: response.ok ? undefined : JSON.stringify(parsed) };
    }
    const text = await response.text();
    const normalizedText = /<!doctype html/i.test(text)
      ? "Backend WhatsApp não configurado neste ambiente." : text.trim().slice(0, 500);
    return { ok: response.ok, status: response.status, data: null,
      errorText: normalizedText || `HTTP ${response.status}` };
  } finally { if (timeout !== null) window.clearTimeout(timeout); }
}

const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const ATTACHMENT_ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt";
const ATTACHMENT_CAPTION_MAX_LENGTH = 1024;
const ATTACHMENT_EXTENSION_MIME_TYPES: Record<string, string> = {
  ".pdf": "application/pdf",
  ".doc": "application/msword",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xls": "application/vnd.ms-excel",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".ppt": "application/vnd.ms-powerpoint",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".csv": "text/csv",
  ".txt": "text/plain",
};
const GENERIC_ATTACHMENT_MIME_TYPES = new Set(["", "application/octet-stream", "application/binary"]);

function isAllowedAttachment(file: File): boolean {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  const expectedMimeType = ATTACHMENT_EXTENSION_MIME_TYPES[extension];
  if (!expectedMimeType) return false;
  return file.type === expectedMimeType || GENERIC_ATTACHMENT_MIME_TYPES.has(file.type);
}

async function requestWithAttachment<T>(url: string, file: File, body: string): Promise<ApiResult<T>> {
  const formData = new FormData();
  formData.append("attachment", file);
  if (body.trim()) formData.append("body", body.trim());
  const response = await fetch(url, { method: "POST", body: formData, headers: getAuthHeaders() });
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const parsed = (await response.json()) as T;
    return { ok: response.ok, status: response.status, data: parsed,
      errorText: response.ok ? undefined : JSON.stringify(parsed) };
  }
  const text = await response.text();
  return { ok: response.ok, status: response.status, data: null,
    errorText: text.trim().slice(0, 500) || `HTTP ${response.status}` };
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function formatMessageTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" }).format(date);
}

function formatMessageDay(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "Hoje";
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Ontem";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "long" }).format(date);
}

function formatPhone(value: string): string {
  const digits = value.replace(/\D/g, "");
  const brazilian = digits.startsWith("55") ? digits.slice(2) : digits;
  if (brazilian.length === 11) return `+55 (${brazilian.slice(0, 2)}) ${brazilian.slice(2, 7)}-${brazilian.slice(7)}`;
  if (brazilian.length === 10) return `+55 (${brazilian.slice(0, 2)}) ${brazilian.slice(2, 6)}-${brazilian.slice(6)}`;
  return value.startsWith("+") ? value : `+${value}`;
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value || 0);
}

function formatWaitingTime(since: string | null | undefined, now: number): string {
  if (!since || !Number.isFinite(Date.parse(since))) return "Precisa de resposta";
  const minutes = Math.max(0, Math.floor((now - Date.parse(since)) / 60_000));
  if (minutes < 1) return "Aguardando há menos de 1 min";
  if (minutes < 60) return `Aguardando há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Aguardando há ${hours} h ${minutes % 60} min`;
  return `Aguardando há ${Math.floor(hours / 24)} d ${hours % 24} h`;
}

function conversationStatusLabel(status: string): string {
  return status === "open" ? "Em atendimento" : status === "pending" ? "Aguardando" :
    status === "closed" ? "Resolvida" : status || "Sem status";
}
function conversationStatusClass(status: string): string {
  return status === "open" ? "fc-wa-status-open" : status === "pending" ? "fc-wa-status-pending" :
    status === "closed" ? "fc-wa-status-closed" : "fc-wa-status-neutral";
}
function messageStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    read: "Lida", delivered: "Entregue", sent: "Enviada", failed: "Falhou",
    pending: "Enviando", received: "Recebida",
  };
  return labels[status] || status || "Registrada";
}
function messageStatusIcon(status: string) {
  if (status === "read" || status === "delivered") return <CheckCheck className="h-3.5 w-3.5" />;
  if (status === "sent" || status === "received") return <Check className="h-3.5 w-3.5" />;
  if (status === "failed") return <AlertCircle className="h-3.5 w-3.5" />;
  return <Clock3 className="h-3.5 w-3.5" />;
}
function isBotAssistedMessage(message: Message): boolean {
  if (!message.metadata || typeof message.metadata !== "object" || Array.isArray(message.metadata)) return false;
  const metadata = message.metadata as Record<string, unknown>;
  return metadata.origem === "bot" || metadata.source === "bot_suggest_reviewed";
}
function templateCategoryLabel(category: TemplateCatalogItem["category"]): string {
  return category === "agenda" ? "Agenda" : category === "laudos" ? "Laudos" : "Financeiro";
}
function renderTemplateBody(template: TemplateCatalogItem, parameters: string[]): string {
  return template.body.replace(/\{\{(\d+)\}\}/g, (_placeholder, rawIndex: string) =>
    parameters[Number(rawIndex) - 1]?.trim() || `{{${rawIndex}}}`);
}
function getInitials(value: string): string {
  return value.trim().split(/\s+/).filter(Boolean).slice(0, 2)
    .map((word) => word[0]?.toUpperCase()).join("") || "WA";
}

function DomainContextPanel({
  context,
  loading,
  error,
  onSaveSelection,
  onReload,
}: {
  context: ConversationDomainContext | null;
  loading: boolean;
  error: string | null;
  onSaveSelection: (payload: WhatsAppContextSelectionPayload) => Promise<void>;
  onReload: () => void;
}) {
  return <section className="fc-wa-domain-context" aria-live="polite">
    <div className="fc-wa-context-section-title"><Link2 className="h-4 w-4" /><h3>Vínculos do cadastro</h3></div>
    {!loading && !error && context ? <ConversationContextSelector context={context} onSave={onSaveSelection} onReload={onReload} /> : null}
    {loading ? <div className="fc-wa-domain-state"><RefreshCw className="h-4 w-4 animate-spin" /><span>Localizando cadastros pelo telefone...</span></div> :
      error ? <div className="fc-wa-domain-state fc-wa-domain-state-error" role="alert"><AlertCircle className="h-4 w-4" /><span>Não foi possível consultar os vínculos agora.</span><button type="button" className="fc-wa-secondary" onClick={onReload}>Atualizar vínculos</button></div> :
      context?.resolution === "selection_invalid" ? <div className="fc-wa-domain-state fc-wa-domain-state-error" role="alert"><AlertCircle className="h-4 w-4" /><div><strong>Escolha de cadastro inválida</strong><span>O cadastro escolhido não está mais disponível para este número. Escolha outro vínculo ou remova a escolha para voltar à verificação pelo telefone.</span></div></div> :
      context?.resolution === "not_found" ? <div className="fc-wa-domain-state"><Info className="h-4 w-4" /><div><strong>Nenhum cadastro encontrado</strong><span>Confira se este número está salvo na clínica ou no tutor.</span></div></div> :
      context?.resolution === "ambiguous" ? <div className="fc-wa-domain-ambiguous"><AlertCircle className="h-4 w-4" /><div><strong>Número presente em mais de um cadastro</strong>
        <span>Revise os candidatos antes de usar dados de agenda ou financeiro.</span>
        <ul>{context.clinicas.map((clinic) => <li key={`clinic-${clinic.id}`}><Building2 className="h-3.5 w-3.5" /> Clínica: {clinic.nome}</li>)}
          {context.tutores.map((tutor) => <li key={`tutor-${tutor.id}`}><UserRound className="h-3.5 w-3.5" /> Tutor: {tutor.nome}</li>)}</ul>
      </div></div> : context?.resolution === "matched" ? <div className="fc-wa-domain-groups">
        <div className="fc-wa-domain-match"><Check className="h-4 w-4" /><span>{context.selecao?.valida && context.selecao.match_type ? "Cadastro escolhido pela equipe" : "Vínculo automático por telefone"}</span><strong>{context.match_type === "clinica" ? "Clínica" : "Tutor"}</strong></div>

        <div className="fc-wa-domain-group"><div><Building2 className="h-4 w-4" /><h4>Clínicas</h4><span>{context.clinicas.length}</span></div>
          {context.clinicas.length ? <ul>{context.clinicas.map((clinic) => <li key={clinic.id}><span><strong>{clinic.nome}</strong><small>{[clinic.cidade, clinic.estado].filter(Boolean).join(" · ") || "Local não informado"}</small></span>
            <Link href={`/clinicas/${clinic.id}`}>Abrir</Link></li>)}</ul> : <p>Nenhuma clínica relacionada.</p>}</div>

        <div className="fc-wa-domain-group"><div><UserRound className="h-4 w-4" /><h4>Tutores</h4><span>{context.tutores.length}</span></div>
          {context.tutores.length ? <ul>{context.tutores.map((tutor) => <li key={tutor.id}><span><strong>{tutor.nome}</strong><small>Tutor vinculado</small></span></li>)}</ul> : <p>Nenhum tutor relacionado.</p>}</div>

        <div className="fc-wa-domain-group"><div><PawPrint className="h-4 w-4" /><h4>Pets</h4><span>{context.pets.length}</span></div>
          {context.pets.length ? <ul>{context.pets.map((pet) => <li key={pet.id}><span><strong>{pet.nome}</strong><small>{[pet.especie, pet.raca].filter(Boolean).join(" · ") || "Dados não informados"}</small></span>
            <Link href={`/pacientes/${pet.id}`}>Abrir</Link></li>)}</ul> : <p>Nenhum pet relacionado.</p>}</div>

        <div className="fc-wa-domain-group"><div><CalendarDays className="h-4 w-4" /><h4>Agendamentos</h4><span>{context.agendamentos.length}</span></div>
          {context.agendamentos.length ? <ul>{context.agendamentos.map((appointment) => <li key={appointment.id}><span><strong>{appointment.pet_nome || "Pet não informado"} · {appointment.servico_nome || "Serviço"}</strong>
            <small>{formatDateTime(appointment.inicio)} · {appointment.status}</small></span><Link href={`/agenda?agendamento_id=${appointment.id}`}>Agenda</Link></li>)}</ul> : <p>Nenhum agendamento recente ou futuro.</p>}</div>

        <div className="fc-wa-domain-group"><div><ClipboardList className="h-4 w-4" /><h4>Ordens de serviço</h4><span>{context.ordens_servico.length}</span></div>
          {context.ordens_servico.length ? <ul>{context.ordens_servico.map((serviceOrder) => <li key={serviceOrder.id}><span><strong>{serviceOrder.numero_os} · {serviceOrder.pet_nome || "Pet não informado"}</strong>
            <small>{serviceOrder.servico_nome || "Serviço"} · {serviceOrder.status} · {formatCurrency(serviceOrder.valor_final)}</small></span><Link href={`/financeiro?os_id=${serviceOrder.id}`}>Financeiro</Link></li>)}</ul> : <p>Nenhuma OS relacionada.</p>}</div>
      </div> : null}
  </section>;
}

const DOWNLOADABLE_MEDIA_TYPES = new Set(["image", "audio", "video", "document", "sticker"]);
const MEDIA_ACTION_LABEL: Record<string, string> = {
  image: "Ver imagem", audio: "Ouvir áudio", video: "Ver vídeo",
  document: "Baixar documento", sticker: "Ver sticker",
};

function WhatsAppMediaViewer({ conversationId, message }: { conversationId: string; message: Message }) {
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [audioPlaybackError, setAudioPlaybackError] = useState(false);

  useEffect(() => () => { if (blobUrl) URL.revokeObjectURL(blobUrl); }, [blobUrl]);

  if (!DOWNLOADABLE_MEDIA_TYPES.has(message.type)) return null;
  if (message.status === "failed") return null;

  const carregarMidia = async () => {
    setState("loading");
    try {
      const response = await fetch(
        `/whatsapp/conversations/${conversationId}/messages/${message.id}/media`,
        { headers: getAuthHeaders() },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      if (message.type === "audio") {
        console.debug("[WhatsAppMediaViewer] audio fetch", {
          responseContentType: response.headers?.get("content-type") ?? null,
          blobType: blob.type,
          blobSize: blob.size,
        });
      }
      setBlobUrl(URL.createObjectURL(blob));
      setState("idle");
    } catch {
      setState("error");
    }
  };

  if (blobUrl) {
    if (message.type === "image" || message.type === "sticker") {
      return <img src={blobUrl} alt={message.body || "Imagem recebida"} className="fc-wa-media-preview" />;
    }
    if (message.type === "audio") {
      if (audioPlaybackError) {
        return <a href={blobUrl} download="audio.mp3" className="fc-wa-media-download-link">
          <FileText className="h-4 w-4" /> Este navegador não toca este áudio — baixar para ouvir em outro app
        </a>;
      }
      return <audio
        controls
        src={blobUrl}
        className="fc-wa-media-preview"
        onError={(event) => {
          console.error("[WhatsAppMediaViewer] audio playback error", {
            mediaErrorCode: event.currentTarget.error?.code ?? null,
            currentSrc: event.currentTarget.currentSrc,
          });
          setAudioPlaybackError(true);
        }}
      />;
    }
    if (message.type === "video") {
      return <video controls src={blobUrl} className="fc-wa-media-preview" />;
    }
    return <a href={blobUrl} download={message.body || "documento"} className="fc-wa-media-download-link">
      <FileText className="h-4 w-4" /> Salvar {message.body || "documento"}
    </a>;
  }

  return <button type="button" className="fc-wa-media-button" onClick={() => void carregarMidia()} disabled={state === "loading"}>
    {state === "loading" ? "Carregando..." : state === "error" ? "Falha ao carregar. Tentar de novo" : MEDIA_ACTION_LABEL[message.type]}
  </button>;
}

export default function WhatsAppStagePage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsPagination, setConversationsPagination] = useState<Pagination>({ page: 1, limit: 20, total: 0 });
  const [queueSummary, setQueueSummary] = useState<QueueSummary | null>(null);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [queueUpdatedAt, setQueueUpdatedAt] = useState<string | null>(null);
  const queueRequestRef = useRef(0);
  const queueAbortRef = useRef<AbortController | null>(null);
  const queueBusyRef = useRef(false);
  const appliedSearchRef = useRef("");
  const [unreadFilter, setUnreadFilter] = useState(false);
  const [followUpFilter, setFollowUpFilter] = useState<FollowUpFilter>("");
  const [myFollowUps, setMyFollowUps] = useState(false);
  const [needsReplyFilter, setNeedsReplyFilter] = useState(false);
  const selectionVersionRef = useRef(0);
  const viewedMessageIdRef = useRef<Record<string, string | null>>({});
  const statusActionRef = useRef(false);
  const assignmentActionRef = useRef(false);
  const [selectedConversationSnapshot, setSelectedConversationSnapshot] = useState<Conversation | null>(null);
  const messageRequestRef = useRef(0);
  const messageReadsRef = useRef(0);
  const historyPageRef = useRef(1);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const messageStreamRef = useRef<HTMLDivElement>(null);
  const followMessagesRef = useRef(true);
  const prependScrollRef = useRef<{ height: number; top: number } | null>(null);
  const [showLatestButton, setShowLatestButton] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const [messagesPagination, setMessagesPagination] = useState<Pagination>({ page: 1, limit: 50, total: 0 });
  const [agents, setAgents] = useState<Agent[]>([]);
  const [templates, setTemplates] = useState<TemplateCatalogItem[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const selectedConversationIdRef = useRef<string | null>(null);
  useEffect(() => { selectedConversationIdRef.current = selectedConversationId; }, [selectedConversationId]);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const lastSeenInboundRef = useRef<Record<string, string | null>>({});
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [loadingDomainContext, setLoadingDomainContext] = useState(false);
  const [domainContext, setDomainContext] = useState<ConversationDomainContext | null>(null);
  const [domainContextError, setDomainContextError] = useState<string | null>(null);
  const domainRequestRef = useRef(0);
  const [botConversationState, setBotConversationState] = useState<WhatsAppBotConversationState | null>(null);
  const [loadingBotState, setLoadingBotState] = useState(false);
  const [savingBotAction, setSavingBotAction] = useState(false);
  const [editingBotDraft, setEditingBotDraft] = useState(false);
  const [editedBotDraft, setEditedBotDraft] = useState("");
  const editingBotDraftRef = useRef(false);
  editingBotDraftRef.current = editingBotDraft;
  const botDraftIdRef = useRef<number | null>(null);
  botDraftIdRef.current = botConversationState?.rascunho_pendente?.resposta_id ?? null;
  const botRequestRef = useRef(0);
  const botActionRef = useRef(false);
  const [savingStatus, setSavingStatus] = useState(false);
  const [integrationState, setIntegrationState] = useState<"checking" | "available" | "unavailable">("checking");
  const [statusFilter, setStatusFilter] = useState<"" | ConversationStatus>("");
  const [assignedFilter, setAssignedFilter] = useState<AssignedFilter>("all");
  const [searchFilter, setSearchFilter] = useState("");
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentEmail, setNewAgentEmail] = useState("");
  const [newAgentRole, setNewAgentRole] = useState("agent");
  const [agentActionId, setAgentActionId] = useState("");
  const [editingAgentId, setEditingAgentId] = useState<string | null>(null);
  const [editAgentName, setEditAgentName] = useState("");
  const [editAgentEmail, setEditAgentEmail] = useState("");
  const [editAgentRole, setEditAgentRole] = useState("agent");
  const [savingAgentId, setSavingAgentId] = useState<string | null>(null);
  const {
    body: sendMessageBody, file: attachmentFile, setBody: setSendMessageBody, setFile: setAttachmentFile,
    draftSnapshot, clearDraftIfUnchanged, hasDraft,
  } = useWhatsAppDrafts(selectedConversationId);
  const sendingRef = useRef(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [savingAssignment, setSavingAssignment] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [resendingMessageId, setResendingMessageId] = useState<string | null>(null);
  const resendingRef = useRef(false);
  const [composerMode, setComposerMode] = useState<ComposerMode>("message");
  const [selectedTemplateKey, setSelectedTemplateKey] = useState("");
  const [templateParameters, setTemplateParameters] = useState<string[]>([]);
  const [templateCatalogError, setTemplateCatalogError] = useState<string | null>(null);
  const [customerServiceWindows, setCustomerServiceWindows] = useState<Record<string, CustomerServiceWindow>>({});
  const [customerServiceWindowClock, setCustomerServiceWindowClock] = useState(() => Date.now());
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const selectedConversation = useMemo(() =>
    conversations.find((item) => item.id === selectedConversationId) ||
      (selectedConversationSnapshot?.id === selectedConversationId ? selectedConversationSnapshot : null),
  [conversations, selectedConversationId, selectedConversationSnapshot]);
  const selectedTemplate = useMemo(() => templates.find((item) => item.key === selectedTemplateKey) || null,
    [selectedTemplateKey, templates]);
  const selectedCustomerServiceWindow = selectedConversationId
    ? customerServiceWindows[selectedConversationId] || selectedConversation?.customer_service_window || null : null;
  const windowState = evaluateCustomerServiceWindow(selectedCustomerServiceWindow, customerServiceWindowClock);
  const conversationDisplayName = selectedConversation?.subject?.trim() || "Contato do WhatsApp";
  const selectedAgent = agents.find((agent) => agent.id === selectedConversation?.last_agent_id) || null;
  const currentUser = useCurrentUser();
  const myAgentId = useMemo(() => {
    const myEmail = currentUser?.email?.trim().toLowerCase();
    if (!myEmail) return null;
    return agents.find((agent) => agent.active && agent.email?.trim().toLowerCase() === myEmail)?.id || null;
  }, [agents, currentUser]);
  const queueViewKey = JSON.stringify([statusFilter, assignedFilter, searchFilter, unreadFilter, needsReplyFilter, followUpFilter, myFollowUps, conversationsPagination.page]);
  const queueViewKeyRef = useRef(queueViewKey);
  const queueViewVersionRef = useRef(0);
  if (queueViewKeyRef.current !== queueViewKey) {
    queueViewKeyRef.current = queueViewKey;
    queueViewVersionRef.current += 1;
  }
  const shortcutMatch = sendMessageBody.match(/(?:^|\s)\/([a-zA-Z0-9_-]*)$/);
  const insertQuickReply = (body: string): void => {
    if (!selectedConversationId || !windowState.isOpen) return;
    setSendMessageBody(shortcutMatch
      ? sendMessageBody.slice(0, sendMessageBody.length - shortcutMatch[1].length - 1) + body
      : sendMessageBody.trim() ? `${sendMessageBody}\n\n${body}` : body);
    composerRef.current?.focus();
  };
  const templatePreview = selectedTemplate ? renderTemplateBody(selectedTemplate, templateParameters) : "";
  const templateComplete = Boolean(selectedTemplate &&
    templateParameters.length === selectedTemplate.body_parameter_count &&
    templateParameters.every((parameter) => parameter.trim()));

  const selectConversation = (conversation: Conversation): void => {
    if (selectedConversationIdRef.current !== conversation.id) {
      selectionVersionRef.current += 1;
      domainRequestRef.current += 1;
      setDomainContext(null); setDomainContextError(null); setLoadingDomainContext(true);
      setBotConversationState(null); setLoadingBotState(false); setEditingBotDraft(false); setEditedBotDraft("");
      setInfoMessage(null); setErrorMessage(null);
    }
    selectedConversationIdRef.current = conversation.id;
    setSelectedConversationSnapshot(conversation);
    setSelectedConversationId(conversation.id);
  };

  const loadConversations = async (
    page = 1,
    overrides: { status?: "" | ConversationStatus; assigned?: AssignedFilter; search?: string; unread?: boolean; needsReply?: boolean; followUp?: FollowUpFilter; myFollowUps?: boolean; silent?: boolean } = {},
  ): Promise<void> => {
    const requestId = ++queueRequestRef.current;
    queueAbortRef.current?.abort();
    const controller = new AbortController();
    queueAbortRef.current = controller;
    queueBusyRef.current = true;
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    if (!overrides.silent) setLoadingConversations(true);
    try {
      const params = new URLSearchParams({ page: String(page), limit: String(conversationsPagination.limit) });
      const effectiveAssigned = overrides.assigned ?? assignedFilter;
      const effectiveStatus = overrides.status ?? statusFilter;
      const effectiveSearch = (overrides.search ?? searchFilter).trim();
      appliedSearchRef.current = effectiveSearch;
      if (effectiveStatus) params.set("status", effectiveStatus);
      if (effectiveAssigned === "mine") {
        if (!myAgentId) return;
        params.set("agent_id", myAgentId);
      } else if (effectiveAssigned !== "all") params.set("assigned", effectiveAssigned);
      if (overrides.unread ?? unreadFilter) params.set("unread", "true");
      if (overrides.needsReply ?? needsReplyFilter) params.set("needs_reply", "true");
      const effectiveFollowUp = overrides.followUp ?? followUpFilter;
      if (effectiveFollowUp) params.set("follow_up", effectiveFollowUp);
      if ((overrides.myFollowUps ?? myFollowUps) && myAgentId) params.set("follow_up_agent_id", myAgentId);
      if (myAgentId) params.set("summary_agent_id", myAgentId);
      if (effectiveSearch) params.set("search", effectiveSearch);
      const result = await requestJson<ConversationsResponse>(`/whatsapp/conversations?${params}`, { signal: controller.signal });
      if (requestId !== queueRequestRef.current) return;
      if (!result.ok || !result.data) throw new Error("Não foi possível atualizar a fila. Tente novamente.");
      const lastPage = Math.max(1, Math.ceil(result.data.pagination.total / result.data.pagination.limit));
      if (page > lastPage) { await loadConversations(lastPage, overrides); return; }
      // A fila pode mudar enquanto a equipe escreve; a conversa aberta continua acessível.
      const selected = result.data.data.find((item) => item.id === selectedConversationIdRef.current);
      if (selected) setSelectedConversationSnapshot(selected);
      setConversations(result.data.data); setConversationsPagination(result.data.pagination);
      setQueueSummary(result.data.summary ?? null); setQueueError(null);
      setQueueUpdatedAt(new Date().toISOString()); setIntegrationState("available");
      if (!selectedConversationIdRef.current && result.data.data.length) selectConversation(result.data.data[0]);
    } catch {
      if (requestId === queueRequestRef.current) {
        setIntegrationState("unavailable");
        setQueueError("Não foi possível atualizar a fila. As conversas já carregadas foram mantidas.");
      }
    } finally {
      window.clearTimeout(timeout);
      if (requestId === queueRequestRef.current) { queueBusyRef.current = false; setLoadingConversations(false); }
    }
  };

  const loadMessages = async (conversationId: string, page = 1, options: LoadMessagesOptions = {}): Promise<void> => {
    const { isCurrent, silent = false } = options;
    if (selectedConversationIdRef.current !== conversationId) return;
    if (silent && messageReadsRef.current > 0) return;
    const requestId = ++messageRequestRef.current;
    messageReadsRef.current += 1;
    const current = () => selectedConversationIdRef.current === conversationId &&
      requestId === messageRequestRef.current && (!isCurrent || isCurrent());
    if (!silent) { if (page > 1) setLoadingHistory(true); else setLoadingMessages(true); }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
      const params = new URLSearchParams({ page: String(page), limit: "50", order: "latest" });
      const result = await requestJson<MessagesResponse>(`/whatsapp/conversations/${conversationId}/messages?${params}`, { signal: controller.signal });
      if (!current()) return;
      if (!result.ok || !result.data) throw new Error("Não foi possível carregar as mensagens. Atualize a conversa para tentar novamente.");
      if (page === 1) {
        viewedMessageIdRef.current[conversationId] = result.data.last_message_id ??
          result.data.data.reduce<string | null>((max, item) => max === null || item.id.localeCompare(max, undefined, { numeric: true }) > 0 ? item.id : max, null);
      }
      if (page > 1 && messageStreamRef.current) prependScrollRef.current = {
        height: messageStreamRef.current.scrollHeight, top: messageStreamRef.current.scrollTop,
      };
      if (page === 1 && messagesRef.current.length && result.data.data.length &&
          !result.data.data.some((incoming) => messagesRef.current.some((existing) => existing.id === incoming.id))) {
        // Muitos recebimentos entre polls deslocam o histórico; revisite a segunda página para preencher a lacuna.
        historyPageRef.current = 1;
      }
      // Atualiza a página recente sem apagar o histórico que já foi aberto.
      setMessages((existing) => {
        const merged = new Map(existing.map((message) => [message.id, message]));
        for (const message of result.data!.data) merged.set(message.id, message);
        return [...merged.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) ||
          a.id.localeCompare(b.id, undefined, { numeric: true }));
      });
      if (page > 1) historyPageRef.current = page;
      setMessagesPagination(result.data.pagination);
      setCustomerServiceWindows((windows) => ({ ...windows, [conversationId]: result.data!.customer_service_window }));
      const latestInbound = result.data.last_inbound_at ?? result.data.customer_service_window?.last_inbound_at ?? null;
      const hasNewInbound = latestInbound !== (lastSeenInboundRef.current[conversationId] ?? null);
      if (page === 1 && (!silent || hasNewInbound) && document.visibilityState !== "hidden") {
        void requestJson(`/whatsapp/conversations/${conversationId}/seen`, { method: "PATCH" }).then((seen) => {
          if (!seen.ok || selectedConversationIdRef.current !== conversationId) return;
          lastSeenInboundRef.current[conversationId] = latestInbound;
          setConversations((items) => items.map((item) => item.id === conversationId ? { ...item, unread: false } : item));
        }).catch(() => { /* A próxima atualização tenta marcar novamente. */ });
      }
    } catch (error) {
      if (current() && !silent) setErrorMessage(error instanceof Error ? error.message : "Não foi possível carregar as mensagens. Tente novamente.");
    } finally {
      window.clearTimeout(timeout);
      messageReadsRef.current -= 1;
      if (current() && !silent) { setLoadingMessages(false); setLoadingHistory(false); }
    }
  };

  const loadAgents = async (): Promise<void> => {
    setLoadingAgents(true);
    try {
      const result = await requestJson<AgentsResponse>("/whatsapp/agents");
      if (!result.ok || !result.data) throw new Error(result.errorText || `Falha ao carregar atendentes (HTTP ${result.status})`);
      setAgents(result.data.data);
    } catch (error) { setErrorMessage(error instanceof Error ? error.message : "Erro ao carregar atendentes"); }
    finally { setLoadingAgents(false); }
  };

  const loadTemplates = async (): Promise<void> => {
    setLoadingTemplates(true); setTemplateCatalogError(null);
    try {
      const result = await requestJson<TemplateCatalogResponse>("/whatsapp/automation/templates");
      if (!result.ok || !result.data) throw new Error(result.errorText || `Falha ao carregar modelos (HTTP ${result.status})`);
      setTemplates(result.data.data);
      if (!selectedTemplateKey && result.data.data[0]) setSelectedTemplateKey(result.data.data[0].key);
    } catch (error) { setTemplateCatalogError(error instanceof Error ? error.message : "Catálogo indisponível"); }
    finally { setLoadingTemplates(false); }
  };

  const loadDomainContext = async (
    phone: string,
    isCurrent: () => boolean,
  ): Promise<void> => {
    const requestId = ++domainRequestRef.current;
    const current = () => isCurrent() && requestId === domainRequestRef.current;
    setLoadingDomainContext(true); setDomainContext(null); setDomainContextError(null);
    try {
      const params = new URLSearchParams({ telefone: phone });
      const result = await requestJson<ConversationDomainContext>(`/api/v1/whatsapp-contexto?${params}`);
      if (!result.ok || !result.data) {
        throw new Error(result.errorText || `Falha ao carregar o vínculo cadastral (HTTP ${result.status})`);
      }
      if (current()) setDomainContext(result.data);
    } catch (error) {
      if (current()) setDomainContextError(error instanceof Error ? error.message : "Vínculo cadastral indisponível");
    } finally {
      if (current()) setLoadingDomainContext(false);
    }
  };

  const reloadDomainContext = (): void => {
    if (!selectedConversation) return;
    const version = selectionVersionRef.current;
    const id = selectedConversation.id;
    void loadDomainContext(selectedConversation.wa_phone_number,
      () => selectedConversationIdRef.current === id && selectionVersionRef.current === version);
  };

  const saveDomainSelection = async (payload: WhatsAppContextSelectionPayload): Promise<void> => {
    if (!selectedConversation || !domainContext) throw new Error("Atualize os vínculos antes de escolher o cadastro.");
    const id = selectedConversation.id;
    const phone = selectedConversation.wa_phone_number;
    const version = selectionVersionRef.current;
    const current = () => selectedConversationIdRef.current === id && selectionVersionRef.current === version;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
      const result = await requestJson<ConversationDomainContext>(
        `/api/v1/whatsapp-contexto/${encodeURIComponent(phone)}/selecao`,
        { method: "PATCH", body: JSON.stringify(payload), signal: controller.signal },
      );
      if (!current()) return;
      if (result.status === 409) throw new Error("Os vínculos ou a escolha mudaram. Atualize os vínculos e confira o cadastro antes de salvar novamente.");
      if (!result.ok || !result.data) throw new Error("Não foi possível salvar a escolha. Atualize os vínculos e tente novamente.");
      domainRequestRef.current += 1;
      setDomainContext(result.data); setDomainContextError(null);
      await loadBotConversationState(phone, current, true);
    } catch (cause) {
      if (!current()) return;
      if (cause instanceof Error && cause.name !== "AbortError" && !(cause instanceof TypeError)) throw cause;
      throw new Error("Não foi possível confirmar a escolha. Atualize os vínculos para conferir o resultado antes de tentar novamente.");
    } finally { window.clearTimeout(timeout); }
  };

  const loadBotConversationState = async (
    waIdentity: string,
    isCurrent: () => boolean,
    silent = false,
  ): Promise<void> => {
    const requestId = ++botRequestRef.current;
    if (!silent) setLoadingBotState(true);
    const current = () => isCurrent() && requestId === botRequestRef.current;
    try {
      const result = await requestJson<WhatsAppBotConversationState>(
        `/api/v1/whatsapp/bot/conversas/${encodeURIComponent(waIdentity)}/estado`,
      );
      if (!result.ok || !result.data) {
        throw new Error(result.errorText || `Falha ao carregar o estado do bot (HTTP ${result.status})`);
      }
      if (current()) {
        setBotConversationState(result.data);
        const nextDraft = result.data.rascunho_pendente;
        const keepEditing = editingBotDraftRef.current && nextDraft?.resposta_id === botDraftIdRef.current;
        if (!keepEditing) { setEditedBotDraft(nextDraft?.texto_gerado || ""); setEditingBotDraft(false); }
      }
    } catch (error) {
      if (current() && !silent) {
        setBotConversationState(null);
        setErrorMessage(error instanceof Error ? error.message : "Estado do bot indisponível");
      }
    } finally {
      if (current() && !silent) setLoadingBotState(false);
    }
  };

  const refreshSelectedBotState = async (): Promise<void> => {
    const selected = selectedConversation;
    if (!selected) return;
    const selectedId = selected.id;
    await loadBotConversationState(
      selected.wa_phone_number,
      () => selectedConversationIdRef.current === selectedId,
    );
  };

  const updateBotState = async (body: { modo: WhatsAppBotMode } | { pausar: boolean }): Promise<void> => {
    if (!selectedConversation || botActionRef.current) return;
    const requestConversationId = selectedConversation.id;
    botActionRef.current = true; botRequestRef.current += 1;
    setSavingBotAction(true); setErrorMessage(null);
    try {
      const result = await requestJson<WhatsAppBotConversationState>(
        `/api/v1/whatsapp/bot/conversas/${encodeURIComponent(selectedConversation.wa_phone_number)}/estado`,
        { method: "PATCH", body: JSON.stringify(body) },
      );
      if (!result.ok || !result.data) throw new Error("Não foi possível atualizar o copiloto. Tente novamente.");
      if (selectedConversationIdRef.current !== requestConversationId) return;
      botRequestRef.current += 1;
      setBotConversationState(result.data);
      setInfoMessage("modo" in body ? `Modo do bot alterado para ${body.modo === "suggest" ? "copiloto" : "desligado"}.` :
        body.pausar ? "Bot pausado nesta conversa." : "Pausa do bot removida.");
    } catch (error) {
      if (selectedConversationIdRef.current === requestConversationId) setErrorMessage(error instanceof Error ? error.message : "Não foi possível atualizar o copiloto.");
    } finally { botActionRef.current = false; setSavingBotAction(false); }
  };
  const handleBotModeChange = (modo: WhatsAppBotMode) => updateBotState({ modo });
  const handleBotPause = (pausar: boolean) => updateBotState({ pausar });

  const performBotDraftAction = async (
    draft: WhatsAppBotDraft, action: "enviar" | "descartar", body: { texto?: string } = {},
  ): Promise<void> => {
    if (!selectedConversationId || botActionRef.current) return;
    const requestConversationId = selectedConversationId;
    botActionRef.current = true; botRequestRef.current += 1;
    setSavingBotAction(true); setErrorMessage(null);
    try {
      const result = await requestJson<{ status: string; idempotent?: boolean }>(
        `/api/v1/whatsapp/bot/respostas/${draft.resposta_id}/${action}`,
        { method: "POST", body: JSON.stringify(body) },
      );
      if (!result.ok) throw new Error(result.errorText || "Não foi possível concluir a ação do copiloto.");
      if (selectedConversationIdRef.current === requestConversationId) {
        setInfoMessage(action === "descartar" ? "Rascunho descartado sem envio." :
          result.data?.idempotent ? "Rascunho já havia sido enviado." : "Rascunho revisado e enviado.");
        if (botDraftIdRef.current === draft.resposta_id) { setEditingBotDraft(false); setEditedBotDraft(""); }
        await refreshSelectedBotState();
      }
      if (action === "enviar") {
        void loadMessages(requestConversationId, 1, { silent: true });
        latestQueueRefreshRef.current();
      }
    } catch (error) {
      if (selectedConversationIdRef.current === requestConversationId) setErrorMessage(error instanceof Error ? error.message :
        "Não foi possível confirmar a ação do copiloto. Atualize a conversa antes de tentar novamente.");
    } finally { botActionRef.current = false; setSavingBotAction(false); }
  };

  const handleDiscardBotDraft = async (): Promise<void> => {
    const draft = botConversationState?.rascunho_pendente;
    if (!draft || botActionRef.current || !window.confirm("Descartar este rascunho sem enviar mensagem ao contato?")) return;
    await performBotDraftAction(draft, "descartar");
  };

  const handleSendBotDraft = async (edited: boolean): Promise<void> => {
    const draft = botConversationState?.rascunho_pendente;
    if (!draft || botActionRef.current) return;
    if (!windowState.isOpen) { setErrorMessage("A janela de 24 horas está fechada; o rascunho não pode ser enviado como texto livre."); return; }
    const texto = edited ? editedBotDraft.trim() : draft.texto_gerado.trim();
    if (!texto) { setErrorMessage("O rascunho não pode ficar vazio."); return; }
    await performBotDraftAction(draft, "enviar", edited ? { texto } : {});
  };

  const handleFilterSubmit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); await loadConversations(1); };
  const handleCreateAgent = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault(); setErrorMessage(null);
    if (!newAgentEmail.trim()) { setErrorMessage("Email do atendente é obrigatório."); return; }
    const result = await requestJson<Agent>("/whatsapp/agents", { method: "POST", body: JSON.stringify({
      name: newAgentName.trim() || null, email: newAgentEmail.trim(), role: newAgentRole.trim() || "agent",
    }) });
    if (!result.ok) { setErrorMessage(result.errorText || `Falha ao criar atendente (HTTP ${result.status})`); return; }
    setInfoMessage("Atendente criado com sucesso."); setNewAgentName(""); setNewAgentEmail(""); setNewAgentRole("agent");
    await loadAgents();
  };

  const startEditAgent = (agent: Agent): void => {
    setEditingAgentId(agent.id); setEditAgentName(agent.name || ""); setEditAgentEmail(agent.email || ""); setEditAgentRole(agent.role);
  };
  const cancelEditAgent = (): void => setEditingAgentId(null);
  const handleUpdateAgent = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (!editingAgentId) return;
    if (!editAgentEmail.trim()) { setErrorMessage("Email do atendente é obrigatório."); return; }
    setSavingAgentId(editingAgentId); setErrorMessage(null);
    const result = await requestJson<Agent>(`/whatsapp/agents/${editingAgentId}`, { method: "PATCH", body: JSON.stringify({
      name: editAgentName.trim() || null, email: editAgentEmail.trim(), role: editAgentRole.trim() || "agent",
    }) });
    setSavingAgentId(null);
    if (!result.ok) { setErrorMessage(result.errorText || `Falha ao salvar atendente (HTTP ${result.status})`); return; }
    setInfoMessage("Atendente atualizado com sucesso."); setEditingAgentId(null);
    await loadAgents();
  };
  const handleToggleAgentActive = async (agent: Agent): Promise<void> => {
    setSavingAgentId(agent.id); setErrorMessage(null);
    const result = await requestJson<Agent>(`/whatsapp/agents/${agent.id}`, { method: "PATCH", body: JSON.stringify({ active: !agent.active }) });
    setSavingAgentId(null);
    if (!result.ok) { setErrorMessage(result.errorText || `Falha ao ${agent.active ? "desativar" : "reativar"} atendente (HTTP ${result.status})`); return; }
    setInfoMessage(agent.active ? "Atendente desativado." : "Atendente reativado.");
    await loadAgents();
  };

  const handleClaimToggle = async (mode: "claim" | "unclaim", requestedAgentId?: string, onlyIfUnassigned = false): Promise<void> => {
    if (!selectedConversationId || assignmentActionRef.current) return;
    const requestConversationId = selectedConversationId;
    const targetAgentId = requestedAgentId || agentActionId;
    if (!targetAgentId) { setErrorMessage("Selecione um atendente."); return; }
    assignmentActionRef.current = true; setSavingAssignment(true); setErrorMessage(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
      const integrado = mode === "claim" && targetAgentId === myAgentId;
      const result = await requestJson<{ message: string; code?: string }>(integrado ? "/api/v1/whatsapp/bot/atendimentos/assumir" : `/whatsapp/conversations/${requestConversationId}/${mode}`, {
        method: "POST", signal: controller.signal, body: JSON.stringify(integrado ? {conversation_id: requestConversationId, telefone: selectedConversation?.wa_phone_number} : { agent_id: Number(targetAgentId), ...(onlyIfUnassigned ? { only_if_unassigned: true } : {}) }),
      });
      if (result.status === 409 && result.data?.code === "CONVERSATION_ALREADY_ASSIGNED") {
        latestQueueRefreshRef.current();
        throw new Error("Esta conversa já foi assumida por outra pessoa. O responsável foi mantido.");
      }
      if (!result.ok) throw new Error(result.errorText || "Não foi possível atualizar o responsável.");
      const agent = mode === "claim" ? agents.find((item) => item.id === targetAgentId) : null;
      const update = (conversation: Conversation) => conversation.id === requestConversationId ? { ...conversation,
        last_agent_id: mode === "claim" ? targetAgentId : null,
        assigned_agent_name: agent?.name ?? null, assigned_agent_email: agent?.email ?? null,
      } : conversation;
      setConversations((items) => items.map(update));
      setSelectedConversationSnapshot((item) => item ? update(item) : null);
      if (selectedConversationIdRef.current === requestConversationId) setInfoMessage(integrado ? "Conversa e pedidos assumidos. O bot aguarda a equipe." : mode === "claim" ? "Responsável atualizado." : "Conversa liberada para a equipe.");
      window.dispatchEvent(new Event("whatsapp-pedidos-atualizados"));
      latestQueueRefreshRef.current();
    } catch (error) {
      latestQueueRefreshRef.current();
      if (selectedConversationIdRef.current === requestConversationId) setErrorMessage(error instanceof Error ? error.message : "Não foi possível atualizar o responsável. Tente novamente.");
    } finally { window.clearTimeout(timeout); assignmentActionRef.current = false; setSavingAssignment(false); }
  };

  const handleStatusChange = async (status: ConversationStatus, openNext = false): Promise<void> => {
    if (!selectedConversationId || status === selectedConversation?.status || statusActionRef.current) return;
    const requestConversationId = selectedConversationId;
    const selectionVersion = selectionVersionRef.current;
    const viewVersion = queueViewVersionRef.current;
    const isSameSelection = () => selectedConversationIdRef.current === requestConversationId && selectionVersionRef.current === selectionVersion;
    if (status === "closed" && !(requestConversationId in viewedMessageIdRef.current)) {
      setErrorMessage("Aguarde o histórico carregar antes de resolver a conversa."); return;
    }
    statusActionRef.current = true; setSavingStatus(true); setErrorMessage(null);
    let resolved = false;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
      const result = await requestJson<{ data: Conversation; changed: boolean; code?: string }>(
        `/whatsapp/conversations/${requestConversationId}/status`, {
          method: "PATCH", signal: controller.signal, body: JSON.stringify({ status, ...(status === "closed"
            ? { expected_last_message_id: viewedMessageIdRef.current[requestConversationId] } : {}) }),
        });
      if (result.status === 409 && result.data?.code === "CONVERSATION_CHANGED") {
        if (isSameSelection()) {
          setErrorMessage("Chegou uma nova mensagem. Revise o histórico antes de resolver a conversa.");
          void loadMessages(requestConversationId, 1);
        }
        latestQueueRefreshRef.current(); return;
      }
      if (!result.ok) throw new Error("Não foi possível atualizar o status. Tente novamente.");
      resolved = status === "closed";
      const update = (item: Conversation): Conversation => item.id === requestConversationId
        ? { ...item, status, ...(resolved ? { needs_reply: false, waiting_since: null } : {}) } : item;
      setConversations((items) => items.map(update));
      setSelectedConversationSnapshot((item) => item ? update(item) : null);
      if (isSameSelection()) setInfoMessage(`Conversa marcada como ${conversationStatusLabel(status).toLowerCase()}.`);
      if (!openNext || !isSameSelection() || queueViewVersionRef.current !== viewVersion) {
        latestQueueRefreshRef.current(); return;
      }
      // Consulta nova: a próxima pendência pode estar fora da página já carregada.
      const params = new URLSearchParams({ page: "1", limit: "2", needs_reply: "true" });
      if (statusFilter) params.set("status", statusFilter);
      if (searchFilter.trim()) params.set("search", searchFilter.trim());
      if (unreadFilter) params.set("unread", "true");
      if (assignedFilter === "mine") {
        if (!myAgentId) return;
        params.set("agent_id", myAgentId);
      } else if (assignedFilter !== "all") params.set("assigned", assignedFilter);
      if (followUpFilter) params.set("follow_up", followUpFilter);
      if (myFollowUps && myAgentId) params.set("follow_up_agent_id", myAgentId);
      const nextResult = await requestJson<ConversationsResponse>(`/whatsapp/conversations?${params}`);
      if (!isSameSelection() || queueViewVersionRef.current !== viewVersion) return;
      if (!nextResult.ok || !nextResult.data) throw new Error("Conversa resolvida. Não foi possível carregar a próxima pendência; atualize a fila.");
      const next = nextResult.data.data.find((item) => item.id !== requestConversationId);
      if (next) { selectConversation(next); setInfoMessage("Conversa resolvida. Próxima pendência aberta."); }
      else setInfoMessage("Conversa resolvida. Não há outra pendência nos filtros atuais.");
    } catch (error) {
      if (isSameSelection()) setErrorMessage(error instanceof Error ? error.message :
        resolved ? "Conversa resolvida. Atualize a fila para continuar." : "Erro ao atualizar o status.");
    } finally {
      window.clearTimeout(timeout);
      if (openNext && resolved) latestQueueRefreshRef.current();
      statusActionRef.current = false; setSavingStatus(false);
    }
  };

  const clearAttachment = (): void => {
    setAttachmentFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };
  const handleAttachmentButtonClick = (): void => fileInputRef.current?.click();
  const handleAttachmentChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0] || null;
    if (!file) return;
    if (!isAllowedAttachment(file)) {
      setErrorMessage("Tipo de arquivo não suportado. Envie PDF, Word, Excel, PowerPoint, CSV ou texto.");
      clearAttachment();
      return;
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
      setErrorMessage("Arquivo excede o limite de 8 MB.");
      clearAttachment();
      return;
    }
    setAttachmentFile(file);
  };

  const handleSendMessage = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (sendingRef.current) return;
    if (!selectedConversationId) { setErrorMessage("Selecione uma conversa para enviar mensagem."); return; }
    if (!windowState.isOpen) {
      setErrorMessage(windowState.hasInboundMessage ? "A janela de 24 horas foi encerrada. Use o fluxo de modelo aprovado correspondente."
        : "Aguarde uma mensagem da clínica antes de responder com texto livre."); return;
    }
    if (!sendMessageBody.trim() && !attachmentFile) { setErrorMessage("Digite uma mensagem ou anexe um arquivo antes de enviar."); return; }
    if (attachmentFile && sendMessageBody.length > ATTACHMENT_CAPTION_MAX_LENGTH) {
      setErrorMessage(`A legenda do anexo excede ${ATTACHMENT_CAPTION_MAX_LENGTH} caracteres.`); return;
    }
    const requestConversationId = selectedConversationId;
    const sentDraft = draftSnapshot;
    sendingRef.current = true; setSendingMessage(true); setErrorMessage(null);
    try {
      const result = attachmentFile
        ? await requestWithAttachment<{ status?: string; code?: string; customer_service_window?: CustomerServiceWindow }>(
            `/whatsapp/conversations/${requestConversationId}/messages`, attachmentFile, sendMessageBody)
        : await requestJson<{ status?: string; code?: string; customer_service_window?: CustomerServiceWindow }>(
            `/whatsapp/conversations/${requestConversationId}/messages`, {
              method: "POST", body: JSON.stringify({ body: sendMessageBody.trim(), type: "text" }),
            });
      if (!result.ok) {
        if (result.status === 409 && result.data?.code === "CUSTOMER_SERVICE_WINDOW_CLOSED") {
          if (result.data.customer_service_window) setCustomerServiceWindows((current) => ({
            ...current, [requestConversationId]: result.data!.customer_service_window!,
          }));
          if (selectedConversationIdRef.current === requestConversationId) setErrorMessage("A janela de 24 horas foi encerrada. Use um modelo aprovado.");
        } else if (selectedConversationIdRef.current === requestConversationId) {
          setErrorMessage(result.errorText || `Falha ao enviar mensagem (HTTP ${result.status}). O rascunho foi mantido.`);
        }
      } else {
        clearDraftIfUnchanged(requestConversationId, sentDraft);
        if (selectedConversationIdRef.current === requestConversationId) {
          setInfoMessage(attachmentFile ? "Anexo enviado." : "Mensagem enviada.");
          if (fileInputRef.current) fileInputRef.current.value = "";
          followMessagesRef.current = true;
          composerRef.current?.focus();
        }
      }
      void loadMessages(requestConversationId, 1, { silent: true });
      latestQueueRefreshRef.current();
    } catch {
      if (selectedConversationIdRef.current === requestConversationId) {
        setErrorMessage("Não foi possível confirmar o envio. Seu rascunho foi mantido; confira o histórico antes de tentar novamente.");
      }
    } finally { sendingRef.current = false; setSendingMessage(false); }
  };

  const handleResendMessage = async (message: Message): Promise<void> => {
    if (!selectedConversationId || !shouldOfferMessageResend(message) || resendingRef.current) return;
    const requestConversationId = selectedConversationId;
    const retryRequest = buildMessageResendRequest(message, requestConversationId);
    resendingRef.current = true; setResendingMessageId(message.id); setErrorMessage(null);
    try {
      const result = await requestJson<{ code?: string; customer_service_window?: CustomerServiceWindow }>(
        retryRequest.url, { method: "POST", body: JSON.stringify(retryRequest.body) });
      if (!result.ok) {
        if (result.status === 409 && result.data?.code === "CUSTOMER_SERVICE_WINDOW_CLOSED") {
          if (result.data.customer_service_window) setCustomerServiceWindows((current) => ({
            ...current, [requestConversationId]: result.data!.customer_service_window!,
          }));
          throw new Error("A janela de 24 horas foi encerrada. Use um modelo aprovado.");
        }
        throw new Error(result.errorText || "Não foi possível reenviar a mensagem.");
      }
      if (selectedConversationIdRef.current === requestConversationId) {
        setInfoMessage(retryRequest.botReviewed ? "Rascunho revisado e reenviado." : "Mensagem reenviada.");
        if (retryRequest.botReviewed) await refreshSelectedBotState();
      }
      void loadMessages(requestConversationId, 1, { silent: true });
      latestQueueRefreshRef.current();
    } catch (error) {
      if (selectedConversationIdRef.current === requestConversationId) setErrorMessage(error instanceof Error ? error.message : "Não foi possível confirmar o reenvio. Confira o histórico antes de tentar novamente.");
    } finally { resendingRef.current = false; setResendingMessageId(null); }
  };

  const handleTemplateSelection = (templateKey: string): void => {
    setSelectedTemplateKey(templateKey);
    const template = templates.find((item) => item.key === templateKey);
    const parameters = Array.from({ length: template?.body_parameter_count || 0 }, () => "");
    if (template && parameters.length && selectedConversation?.subject) parameters[0] = selectedConversation.subject;
    setTemplateParameters(parameters);
  };
  const handleCopyTemplateToComposer = (): void => {
    if (!selectedTemplate || !templateComplete) { setErrorMessage("Preencha todas as variáveis do modelo antes de copiar o texto."); return; }
    if (!windowState.isOpen || !selectedTemplate.can_copy_as_free_text) return;
    setSendMessageBody(sendMessageBody.trim() ? `${sendMessageBody}\n\n${templatePreview}` : templatePreview); setComposerMode("message");
    setInfoMessage("Texto copiado para o rascunho. Revise antes de enviar como resposta livre.");
  };

  useEffect(() => { void Promise.all([loadConversations(1), loadAgents(), loadTemplates()]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const intervalId = window.setInterval(() => setCustomerServiceWindowClock(Date.now()), CUSTOMER_SERVICE_WINDOW_CLOCK_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, []);
  useEffect(() => {
    setMessages([]); setMessagesPagination({ page: 1, limit: 50, total: 0 });
    historyPageRef.current = 1; followMessagesRef.current = true;
    prependScrollRef.current = null; setShowLatestButton(false); setLoadingHistory(false);
    if (!selectedConversationId) return;
    let active = true; let refreshInProgress = false;
    const refreshMessages = async (silent: boolean) => {
      if (refreshInProgress || (silent && document.visibilityState === "hidden")) return; refreshInProgress = true;
      try { await loadMessages(selectedConversationId, 1, { isCurrent: () => active, silent }); }
      finally { refreshInProgress = false; }
    };
    void refreshMessages(false);
    const intervalId = window.setInterval(() => void refreshMessages(true), MESSAGE_STATUS_REFRESH_INTERVAL_MS);
    return () => { active = false; window.clearInterval(intervalId); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedConversationId]);
  useEffect(() => {
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [selectedConversationId]);
  useEffect(() => {
    if (!selectedConversation) {
      setDomainContext(null); setDomainContextError(null); setLoadingDomainContext(false);
      setBotConversationState(null); setLoadingBotState(false); setEditingBotDraft(false); setEditedBotDraft("");
      return;
    }
    let active = true;
    void loadDomainContext(selectedConversation.wa_phone_number, () => active);
    let refreshInProgress = false;
    const refreshBot = async (silent = false) => {
      if (refreshInProgress || botActionRef.current || (silent && document.visibilityState === "hidden")) return;
      refreshInProgress = true;
      try { await loadBotConversationState(selectedConversation.wa_phone_number, () => active, silent); }
      finally { refreshInProgress = false; }
    };
    void refreshBot();
    const intervalId = window.setInterval(
      () => void refreshBot(true),
      MESSAGE_STATUS_REFRESH_INTERVAL_MS,
    );
    return () => { active = false; window.clearInterval(intervalId); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedConversation?.id, selectedConversation?.wa_phone_number]);
  const firstActiveAgentId = agents.find((agent) => agent.active)?.id || "";
  useEffect(() => {
    setAgentActionId(selectedConversation?.last_agent_id || myAgentId || firstActiveAgentId);
  }, [selectedConversation?.id, selectedConversation?.last_agent_id, myAgentId, firstActiveAgentId]);

  const latestQueueRefreshRef = useRef(() => {});
  latestQueueRefreshRef.current = () => {
    if (!queueBusyRef.current && appliedSearchRef.current === searchFilter.trim()) {
      void loadConversations(conversationsPagination.page, { silent: true });
    }
  };
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") latestQueueRefreshRef.current();
    }, QUEUE_REFRESH_INTERVAL_MS);
    const onVisible = () => { if (document.visibilityState !== "hidden") latestQueueRefreshRef.current(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("whatsapp-pedidos-atualizados", onVisible);
    return () => {
      window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("whatsapp-pedidos-atualizados", onVisible);
      queueRequestRef.current += 1; queueAbortRef.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (searchFilter.trim() === appliedSearchRef.current) return;
    const timer = window.setTimeout(() => {
      if (searchFilter.trim() !== appliedSearchRef.current) void loadConversations(1, { search: searchFilter });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchFilter]);
  useEffect(() => {
    const stream = messageStreamRef.current;
    if (!stream || loadingMessages) return;
    if (prependScrollRef.current) {
      stream.scrollTop = prependScrollRef.current.top + stream.scrollHeight - prependScrollRef.current.height;
      prependScrollRef.current = null;
    } else if (followMessagesRef.current) {
      stream.scrollTop = stream.scrollHeight;
      setShowLatestButton(false);
    }
  }, [messages, loadingMessages]);

  useEffect(() => {
    if (!selectedTemplate) return;
    const parameters = Array.from({ length: selectedTemplate.body_parameter_count }, () => "");
    if (parameters.length && selectedConversation?.subject) parameters[0] = selectedConversation.subject;
    setTemplateParameters(parameters);
  }, [selectedConversation?.id, selectedTemplate]);

  return (
    <DashboardLayout>
      <main className="fc-wa-page">
        <header className="fc-wa-header">
          <div><span className="fc-wa-kicker"><MessageSquare className="h-4 w-4" /> Central de atendimento</span>
            <h1>WhatsApp Fort Cordis</h1><p>Atenda clínicas parceiras, organize a fila e acompanhe cada conversa em um só lugar.</p></div>
          <div className="fc-wa-header-actions"><span className={`fc-wa-live-dot fc-wa-live-dot-${integrationState}`}><span />
            {integrationState === "available" ? "Integração disponível" : integrationState === "unavailable" ? "Integração indisponível" : "Verificando integração"}
          </span></div>
        </header>

        <AppointmentQueue onOpen={async (id, identity) => {
          const conversation = conversations.find(c => c.id === id);
          if (conversation) selectConversation(conversation);
          else {
            try {
              const result = await requestJson<{ data: Conversation[] }>(`/whatsapp/conversations?search=${encodeURIComponent(identity)}&limit=100`);
              const found = result.data?.data.find(c => c.id === id);
              if (found) selectConversation(found);
              else setErrorMessage("Conversa não encontrada. Atualize a central.");
            } catch { setErrorMessage("Não foi possível abrir a conversa. Tente novamente."); }
          }
        }} />
        <section className="fc-wa-metrics" aria-label="Resumo do atendimento WhatsApp">
          <button type="button" className="fc-wa-metric fc-wa-metric-amber fc-wa-metric-action" aria-label="Ver conversas que precisam de resposta" onClick={() => {
            setFollowUpFilter(""); setMyFollowUps(false); setNeedsReplyFilter(true); setUnreadFilter(false); setStatusFilter(""); setSearchFilter(""); setAssignedFilter("all");
            void loadConversations(1, { needsReply: true, unread: false, status: "", search: "", assigned: "all", followUp: "", myFollowUps: false });
          }}><Clock3 className="h-5 w-5" /><strong>{queueSummary?.needs_reply ?? "—"}</strong><span>Precisam de resposta · total</span></button>
          <div className="fc-wa-metric fc-wa-metric-cordis"><MessagesSquare className="h-5 w-5" /><strong>{queueSummary?.total ?? "—"}</strong><span>Conversas cadastradas</span></div>
          <div className="fc-wa-metric fc-wa-metric-vital"><MessageSquare className="h-5 w-5" /><strong>{queueSummary?.unread ?? "—"}</strong><span>Conversas não lidas</span></div>
          <div className="fc-wa-metric fc-wa-metric-amber"><UserCheck className="h-5 w-5" /><strong>{queueSummary?.unassigned ?? "—"}</strong><span>Sem responsável · total</span></div>
          <div className="fc-wa-metric fc-wa-metric-ink"><Users className="h-5 w-5" /><strong>{agents.filter((agent) => agent.active).length}</strong><span>Atendentes ativos</span></div>
        </section>
        <div className="fc-wa-follow-up-summary" role="status">
          <span><strong>{queueSummary?.follow_up_due ?? "—"}</strong> retornos atrasados na equipe</span>
          <button type="button" onClick={() => {
            setFollowUpFilter("ready"); setMyFollowUps(false); setNeedsReplyFilter(false); setUnreadFilter(false); setStatusFilter(""); setAssignedFilter("all"); setSearchFilter("");
            void loadConversations(1, { followUp: "ready", myFollowUps: false, needsReply: false, unread: false, status: "", assigned: "all", search: "" });
          }}>Ver retornos que precisam de atenção ({queueSummary?.follow_up_ready ?? "—"})</button>
          {myAgentId ? <button type="button" onClick={() => {
            setFollowUpFilter("ready"); setMyFollowUps(true); setNeedsReplyFilter(false); setUnreadFilter(false); setStatusFilter(""); setAssignedFilter("all"); setSearchFilter("");
            void loadConversations(1, { followUp: "ready", myFollowUps: true, needsReply: false, unread: false, status: "", assigned: "all", search: "" });
          }}>Meus retornos para revisar ({queueSummary?.my_follow_up_ready ?? "—"})</button> : null}
          <small>Lembretes atualizados enquanto este módulo estiver aberto.</small>
        </div>
        {infoMessage ? <div className="fc-wa-message fc-wa-message-info">{infoMessage}</div> : null}
        {errorMessage ? <div className="fc-wa-message fc-wa-message-error">{errorMessage}</div> : null}

        <section className="fc-wa-workspace">
          <aside className="fc-wa-inbox" aria-label="Caixa de entrada">
            <div className="fc-wa-panel-heading"><div className="fc-wa-heading-icon"><Inbox className="h-5 w-5" /></div>
              <div><span>Caixa de entrada</span><h2>Conversas</h2></div>
              <button type="button" className="fc-wa-icon-button ml-auto" onClick={() => void loadConversations(conversationsPagination.page)} aria-label="Atualizar conversas" disabled={loadingConversations}>
                <RefreshCw className={`h-4 w-4 ${loadingConversations ? "animate-spin" : ""}`} /></button></div>
            <form className="fc-wa-search" onSubmit={handleFilterSubmit}><Search className="h-4 w-4" />
              <input value={searchFilter} onChange={(event) => {
                queueRequestRef.current += 1; queueAbortRef.current?.abort(); queueBusyRef.current = false; setLoadingConversations(false);
                setSearchFilter(event.target.value);
              }} placeholder="Nome, telefone ou última mensagem" aria-label="Buscar conversas" />
              <button type="submit" aria-label="Aplicar busca"><ChevronRight className="h-4 w-4" /></button></form>
            <div className="fc-wa-queue-tabs" aria-label="Filtrar por status">
              {CONVERSATION_STATUS_OPTIONS.map((option) => <button key={option.value || "all"} type="button"
                aria-pressed={statusFilter === option.value} className={statusFilter === option.value ? "active" : ""} onClick={() => { setStatusFilter(option.value); void loadConversations(1, { status: option.value }); }}>{option.label}</button>)}
            </div>
            <div className="fc-wa-follow-up-filter"><label>Retornos<select aria-label="Filtrar retornos" value={followUpFilter} onChange={(event) => {
              const value = event.target.value as FollowUpFilter; setFollowUpFilter(value);
              void loadConversations(1, { followUp: value });
            }}><option value="">Todas as conversas</option><option value="all">Todos os retornos pendentes</option>
              <option value="ready">Precisam de atenção</option><option value="due">Atrasados</option><option value="today">Hoje, a vencer</option>
              <option value="upcoming">A partir de amanhã</option><option value="responded">Cliente respondeu</option></select></label>
              <label><input type="checkbox" checked={myFollowUps} disabled={!myAgentId} onChange={(event) => {
                setMyFollowUps(event.target.checked); void loadConversations(1, { myFollowUps: event.target.checked });
              }} /> Meus retornos</label></div>
            <div className="fc-wa-assignment-filter"><Filter className="h-3.5 w-3.5" /><select value={assignedFilter}
              onChange={(event) => { const value = event.target.value as AssignedFilter; setAssignedFilter(value); void loadConversations(1, { assigned: value }); }} aria-label="Filtrar por responsável">
              <option value="all">Todos os responsáveis</option><option value="mine" disabled={!myAgentId}>Minhas conversas</option><option value="assigned">Com responsável</option><option value="unassigned">Sem responsável</option></select></div>
            <div className="fc-wa-queue-tools">
              <label><input type="checkbox" checked={needsReplyFilter} onChange={(event) => {
                setNeedsReplyFilter(event.target.checked); void loadConversations(1, { needsReply: event.target.checked });
              }} /> Precisa de resposta</label>
              <label><input type="checkbox" checked={unreadFilter} onChange={(event) => {
                setUnreadFilter(event.target.checked); void loadConversations(1, { unread: event.target.checked });
              }} /> Somente não lidas</label>
              {searchFilter || statusFilter || assignedFilter !== "all" || unreadFilter || needsReplyFilter || followUpFilter || myFollowUps ? <button type="button" onClick={() => {
                setSearchFilter(""); setStatusFilter(""); setAssignedFilter("all"); setUnreadFilter(false); setNeedsReplyFilter(false); setFollowUpFilter(""); setMyFollowUps(false);
                void loadConversations(1, { search: "", status: "", assigned: "all", unread: false, needsReply: false, followUp: "", myFollowUps: false });
              }}>Limpar filtros</button> : null}
              {needsReplyFilter ? <small>Mais antigas primeiro. Ler a mensagem não encerra a pendência.</small> : null}
              <small>{loadingConversations ? "Atualizando fila..." : queueUpdatedAt ? `Atualizada às ${formatMessageTime(queueUpdatedAt)} · a cada 15 s` : "Aguardando atualização"}</small>
            </div>
            {queueError ? <div className="fc-wa-queue-error" role="status"><span>{queueError}</span><button type="button" onClick={() => void loadConversations(conversationsPagination.page)}>Tentar novamente</button></div> : null}
            <div className="fc-wa-conversation-list" aria-busy={loadingConversations}>
              {loadingConversations && conversations.length === 0 ? <div className="fc-wa-empty">Carregando conversas...</div> : conversations.length === 0 ?
                <div className="fc-wa-empty"><Inbox className="h-8 w-8" /><strong>Nenhuma conversa encontrada</strong><span>Tente alterar os filtros ou a busca.</span></div> :
                conversations.map((conversation) => {
                  const label = conversation.subject?.trim() || formatPhone(conversation.wa_phone_number);
                  return <button key={conversation.id} type="button" onClick={() => selectConversation(conversation)} aria-pressed={conversation.id === selectedConversationId}
                    className={`fc-wa-conversation ${conversation.id === selectedConversationId ? "fc-wa-conversation-active" : ""} ${conversation.unread ? "fc-wa-conversation-unread" : ""}`}>
                    <span className="fc-wa-avatar">{getInitials(label)}</span><span className="fc-wa-conversation-content">
                      <span className="fc-wa-conversation-line">{conversation.unread ? <span className="fc-wa-unread-dot" aria-label="Não lida" /> : null}<strong>{label}</strong><time>{formatMessageTime(conversation.last_message_at || conversation.last_activity_at)}</time></span>
                      {conversation.subject ? <small>{formatPhone(conversation.wa_phone_number)}</small> : null}
                      <span className="fc-wa-conversation-preview">{conversation.last_message_from_me ? "Você: " : ""}{conversation.last_message_body || "Conversa iniciada"}</span>
                      {conversation.follow_up?.status === "pending" ? <span className="fc-wa-waiting">{followUpLabel(conversation.follow_up, customerServiceWindowClock)} · {conversation.follow_up.agent_name || "Responsável cadastrado"}</span> : null}
                      {conversation.needs_reply ? <span className="fc-wa-waiting" title={`Precisa de resposta desde ${formatDateTime(conversation.waiting_since)}`}><Clock3 className="h-3 w-3" />{formatWaitingTime(conversation.waiting_since, customerServiceWindowClock)}</span> : null}
                      <span className="fc-wa-conversation-meta"><span className={`fc-wa-status ${conversationStatusClass(conversation.status)}`}>{conversationStatusLabel(conversation.status)}</span>
                        <span>{conversation.assigned_agent_name || "Sem responsável"}</span>{hasDraft(conversation.id) ? <span className="fc-wa-draft-label">Rascunho</span> : null}</span></span></button>;
                })}
            </div>
            <div className="fc-wa-pagination"><span>{conversationsPagination.total === 0 ? "0 conversas" :
              `${(conversationsPagination.page - 1) * conversationsPagination.limit + 1}-${Math.min(conversationsPagination.page * conversationsPagination.limit, conversationsPagination.total)} de ${conversationsPagination.total}`}</span>
              <div><button type="button" onClick={() => void loadConversations(Math.max(1, conversationsPagination.page - 1))} disabled={conversationsPagination.page <= 1 || loadingConversations} aria-label="Página anterior">‹</button>
                <button type="button" onClick={() => { const totalPages = Math.max(1, Math.ceil(conversationsPagination.total / conversationsPagination.limit)); void loadConversations(Math.min(totalPages, conversationsPagination.page + 1)); }}
                  disabled={loadingConversations || conversationsPagination.page >= Math.max(1, Math.ceil(conversationsPagination.total / conversationsPagination.limit))} aria-label="Próxima página">›</button></div></div>
          </aside>

          <section className="fc-wa-chat" aria-label="Conversa selecionada">
            <div className="fc-wa-chat-heading">{selectedConversation ? <>
              <span className="fc-wa-avatar fc-wa-avatar-large">{getInitials(conversationDisplayName)}</span><div><h2>{conversationDisplayName}</h2><p>{formatPhone(selectedConversation.wa_phone_number)}</p></div>
              <span className={`fc-wa-status ${conversationStatusClass(selectedConversation.status)} ml-auto`}>{conversationStatusLabel(selectedConversation.status)}</span>
              <button type="button" className="fc-wa-icon-button" onClick={() => selectedConversationId && void loadMessages(selectedConversationId, 1)} disabled={loadingMessages} aria-label="Atualizar mensagens">
                <RefreshCw className={`h-4 w-4 ${loadingMessages ? "animate-spin" : ""}`} /></button></> :
              <div><h2>Nenhuma conversa selecionada</h2><p>Escolha um contato na caixa de entrada.</p></div>}</div>
            {selectedConversation ? <div className="fc-wa-work-actions" aria-label="Ações do atendimento">
              {selectedConversation.needs_reply ? <span className="fc-wa-waiting">{formatWaitingTime(selectedConversation.waiting_since, customerServiceWindowClock)}</span> : <span />}
              {(!selectedConversation.last_agent_id || selectedConversation.last_agent_id === myAgentId) ? <button type="button" className="fc-wa-secondary" onClick={() => myAgentId && void handleClaimToggle("claim", myAgentId, true)} disabled={savingAssignment || !myAgentId}
                title={!myAgentId ? "Seu usuário precisa estar vinculado a um atendente ativo pelo email." : undefined}><UserCheck className="h-4 w-4" />{selectedConversation.last_agent_id === myAgentId ? "Sincronizar pedidos" : "Assumir atendimento"}</button> : null}
              <button type="button" className="fc-wa-secondary" onClick={() => void handleStatusChange("closed", true)}
                disabled={savingStatus || loadingMessages || sendingMessage || selectedConversation.status === "closed"} title="Resolve esta conversa e abre a pendência mais antiga nos filtros atuais. O rascunho será preservado.">
                <Check className="h-4 w-4" />{savingStatus ? "Atualizando..." : "Resolver e abrir próxima"}</button>
            </div> : null}
            {selectedConversationId && <AppointmentQueue key={selectedConversationId} conversationId={selectedConversationId} onOpen={() => {}} />}
            {selectedConversation ? <div className={`fc-wa-window ${windowState.isOpen ? "fc-wa-window-open" : "fc-wa-window-closed"}`} role="status" aria-live="polite">
              <Clock3 className="h-4 w-4" /><span>{windowState.isOpen ? `Resposta livre disponível até ${formatDateTime(windowState.expiresAt)}` : windowState.hasInboundMessage ?
                `Janela encerrada em ${formatDateTime(windowState.expiresAt)}. Use o fluxo de modelo correspondente.` : "Aguardando uma mensagem da clínica para liberar respostas em texto livre."}</span></div> : null}
            {selectedConversation && !conversations.some((item) => item.id === selectedConversation.id) ? <p className="fc-wa-selection-note">Esta conversa continua aberta fora dos filtros ou da página atual.</p> : null}
            {selectedConversationId && messages.length < messagesPagination.total ? <div className="fc-wa-history-actions"><button type="button" className="fc-wa-secondary" disabled={loadingMessages || loadingHistory}
              onClick={() => void loadMessages(selectedConversationId, historyPageRef.current + 1)}>{loadingHistory ? "Carregando histórico..." : "Carregar mensagens anteriores"}</button><small>{messages.length} de {messagesPagination.total} mensagens</small></div> : null}
            <div ref={messageStreamRef} className="fc-wa-message-stream" onScroll={(event) => {
              const stream = event.currentTarget;
              followMessagesRef.current = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 80;
              setShowLatestButton(!followMessagesRef.current);
            }}>{!selectedConversationId ? <div className="fc-wa-empty"><MessageSquare className="h-8 w-8" /><strong>Selecione uma conversa</strong></div> : loadingMessages ?
              <div className="fc-wa-empty">Carregando mensagens...</div> : messages.length === 0 ? <div className="fc-wa-empty"><MessageSquare className="h-8 w-8" /><strong>A conversa ainda não tem mensagens</strong></div> :
              <div className="space-y-3">{messages.map((message, index) => {
                const previous = messages[index - 1]; const showDay = !previous || new Date(previous.created_at).toDateString() !== new Date(message.created_at).toDateString();
                const receiptLabel = agendaReceiptLabel(message);
                return <Fragment key={message.id}>{showDay ? <div className="fc-wa-day-separator"><span>{formatMessageDay(message.created_at)}</span></div> : null}
                  <article className={`fc-wa-bubble ${message.from_me ? "fc-wa-bubble-agent" : "fc-wa-bubble-client"}`}>
                    {isBotAssistedMessage(message) ? <span className="fc-wa-bot-badge"><Sparkles className="h-3 w-3" /> Rascunho do bot aprovado</span> : null}
                    <p>{message.body || `[${message.type}]`}</p>
                    {receiptLabel ? <span className="fc-wa-bot-badge mt-1.5"><Check className="h-3 w-3" /> {receiptLabel}</span> : null}
                    {selectedConversationId ? <WhatsAppMediaViewer conversationId={selectedConversationId} message={message} /> : null}
                    <footer><time>{formatMessageTime(message.created_at)}</time><span className={`fc-wa-delivery fc-wa-delivery-${message.status}`}>{messageStatusIcon(message.status)} {messageStatusLabel(message.status)}</span>
                      {shouldOfferMessageResend(message) ? <button type="button" className="fc-wa-resend-button"
                        onClick={() => void handleResendMessage(message)} disabled={resendingMessageId !== null || !windowState.isOpen}>
                        <RefreshCw className={`h-3.5 w-3.5 ${resendingMessageId === message.id ? "animate-spin" : ""}`} /> Reenviar
                      </button> : null}</footer>
                    <details><summary>Detalhes técnicos</summary><span>Tipo: {message.type}</span>{message.wa_message_id ? <span>ID Meta: {message.wa_message_id}</span> : null}</details></article></Fragment>;
              })}</div>}</div>

            {showLatestButton ? <div className="fc-wa-history-actions"><button type="button" className="fc-wa-secondary" onClick={() => {
              if (messageStreamRef.current) messageStreamRef.current.scrollTop = messageStreamRef.current.scrollHeight;
              followMessagesRef.current = true; setShowLatestButton(false);
            }}>Ir para última mensagem</button></div> : null}
            {botConversationState?.rascunho_pendente ? <section className="fc-wa-bot-draft" aria-label="Rascunho sugerido pelo bot">
              <div className="fc-wa-bot-draft-heading"><span><Sparkles className="h-4 w-4" /> Sugestão do bot</span>
                <small>{formatDateTime(botConversationState.rascunho_pendente.criado_em)}</small></div>
              {editingBotDraft ? <textarea value={editedBotDraft} onChange={(event) => setEditedBotDraft(event.target.value)} rows={4}
                aria-label="Editar rascunho do bot" disabled={savingBotAction} /> :
                <p>{botConversationState.rascunho_pendente.texto_gerado}</p>}
              <div className="fc-wa-bot-draft-actions">
                {editingBotDraft ? <>
                  <button type="button" className="fc-wa-secondary" onClick={() => { setEditingBotDraft(false); setEditedBotDraft(botConversationState.rascunho_pendente?.texto_gerado || ""); }} disabled={savingBotAction}>Cancelar edição</button>
                  <button type="button" className="fc-wa-send" onClick={() => void handleSendBotDraft(true)} disabled={savingBotAction || !editedBotDraft.trim() || !windowState.isOpen}><Send className="h-4 w-4" /> Enviar edição</button>
                </> : <>
                  <button type="button" className="fc-wa-send" onClick={() => void handleSendBotDraft(false)} disabled={savingBotAction || !windowState.isOpen}><Send className="h-4 w-4" /> Enviar</button>
                  <button type="button" className="fc-wa-secondary" onClick={() => { setEditedBotDraft(botConversationState.rascunho_pendente?.texto_gerado || ""); setEditingBotDraft(true); }} disabled={savingBotAction}><Pencil className="h-4 w-4" /> Editar e enviar</button>
                </>}
                <button type="button" className="fc-wa-ghost-danger" onClick={() => void handleDiscardBotDraft()} disabled={savingBotAction}>Descartar</button>
              </div>
              {!windowState.isOpen ? <small className="fc-wa-bot-draft-warning">Janela de 24 horas fechada: revise o rascunho, mas use um modelo aprovado para responder.</small> : null}
            </section> : loadingBotState && selectedConversationId ? <div className="fc-wa-bot-draft-loading">Verificando sugestão do bot...</div> : null}

            {/* RF-022: bloqueio nunca vira silencio. Sem esta secao o bot
                recusava responder e ninguem na central ficava sabendo.
                Deliberadamente sem Enviar/Editar: o texto recusado nem chega
                do backend, justamente para nao ficar a um clique do cliente. */}
            {botConversationState?.ultima_recusa ? <section className="fc-wa-bot-recusa" aria-label={botConversationState.ultima_recusa.aviso_enviado ? "Encaminhamento para a equipe" : "O bot não respondeu"}>
              <div className="fc-wa-bot-recusa-heading">
                <span><ShieldAlert className="h-4 w-4" /> {botConversationState.ultima_recusa.decisao === "handoff" ? "O bot passou para a equipe" : "O bot não respondeu"}</span>
                <small>{formatDateTime(botConversationState.ultima_recusa.criado_em)}</small>
              </div>
              <p>{BOT_RECUSA_MOTIVOS[botConversationState.ultima_recusa.motivo || ""] || botConversationState.ultima_recusa.motivo || "motivo não registrado"}.</p>
              {botConversationState.ultima_recusa.aviso_enviado ? <small>Um aviso de encaminhamento para a equipe foi enviado ao cliente. Confira os vínculos e continue o atendimento.</small> :
                <small>Responda você mesmo pelo campo abaixo. O texto que o bot chegou a montar não é exibido nem enviável.</small>}
            </section> : null}

            {/* Silencio: o bot viu e nao respondeu por operacao normal. Medido
                em producao em 2026-08-25 - um envio assistido pausou a conversa
                e as mensagens seguintes sumiram sem deixar rastro na tela, o
                que pareceu bot quebrado. Tier mais fraco que a recusa e sem
                nenhum botao: e informacao, nao tarefa. */}
            {botConversationState?.ultimo_silencio ? <div className="fc-wa-bot-silencio" role="status" aria-live="polite">
              <Info className="h-3.5 w-3.5" />
              <span>O bot viu esta mensagem e não respondeu: {BOT_SILENCIO_MOTIVOS[botConversationState.ultimo_silencio.motivo || ""] || botConversationState.ultimo_silencio.motivo || "motivo não registrado"}{botConversationState.ultimo_silencio.motivo === "pausado" && botConversationState.pausado_ate ? `, até ${formatDateTime(botConversationState.pausado_ate)}` : ""}.</span>
            </div> : null}

            {selectedConversation ? <WaitingForTeamNotice
              needsReply={selectedConversation.needs_reply}
              ownerId={selectedConversation.last_agent_id}
              ownerName={selectedConversation.assigned_agent_name || selectedAgent?.name}
              waitingLabel={formatWaitingTime(selectedConversation.waiting_since, customerServiceWindowClock)}
              paused={botConversationState?.pausado}
              pausedUntil={botConversationState?.pausado_ate}
              handoffReason={botConversationState?.handoff_motivo}
              windowOpen={windowState.isOpen}
            /> : null}

            <div className="fc-wa-composer"><div className="fc-wa-composer-tabs" role="tablist" aria-label="Modo de resposta">
              <button type="button" role="tab" aria-selected={composerMode === "message"} className={composerMode === "message" ? "active" : ""} onClick={() => setComposerMode("message")}><MessageSquare className="h-4 w-4" /> Mensagem</button>
              <button type="button" role="tab" aria-selected={composerMode === "template"} className={composerMode === "template" ? "active" : ""} onClick={() => setComposerMode("template")}><Sparkles className="h-4 w-4" /> Modelos configurados</button></div>
              {composerMode === "message" ? <><QuickReplyLibrary onInsert={insertQuickReply}
                disabled={!selectedConversationId || !windowState.isOpen} shortcutQuery={shortcutMatch?.[1]} userId={currentUser?.id ? String(currentUser.id) : undefined} />
                <form onSubmit={handleSendMessage}>
                <input ref={fileInputRef} type="file" className="sr-only" accept={ATTACHMENT_ACCEPT} aria-label="Selecionar arquivo para anexar" onChange={handleAttachmentChange} />
                {attachmentFile ? <div className="fc-wa-attachment-chip"><FileText className="h-3.5 w-3.5" /><span>{attachmentFile.name}</span>
                  <button type="button" onClick={clearAttachment} aria-label="Remover anexo"><X className="h-3.5 w-3.5" /></button></div> : null}
                <div className="fc-wa-compose-row">
                  <button type="button" className="fc-wa-icon-button" onClick={handleAttachmentButtonClick} disabled={!selectedConversationId || !windowState.isOpen}
                    aria-label="Anexar arquivo" title="Anexar PDF, Word, Excel, PowerPoint, CSV ou texto (até 8 MB)"><Paperclip className="h-4 w-4" /></button>
                  <textarea ref={composerRef} placeholder="Digite sua resposta" aria-label="Digite sua resposta" value={sendMessageBody} onChange={(event) => setSendMessageBody(event.target.value)}
                  onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }}
                  disabled={!selectedConversationId || !windowState.isOpen} rows={3} />
                  <button type="submit" className="fc-wa-send" disabled={sendingMessage || !selectedConversationId || !windowState.isOpen || (!sendMessageBody.trim() && !attachmentFile)}><Send className="h-4 w-4" /> {sendingMessage ? "Enviando…" : "Enviar"}</button></div>
                <p className="fc-wa-composer-hint">{windowState.isOpen ? "Ctrl/Cmd + Enter para enviar · Rascunhos mantidos ao trocar conversa, até sair desta página" : "Texto livre indisponível. Consulte os modelos e use o fluxo correspondente."}</p></form></> :
                <div className="fc-wa-template-composer"><div className="fc-wa-template-notice"><Info className="h-4 w-4" /><span>Catálogo configurado no Fort Cordis. A aprovação atual na Meta não é consultada nesta tela.</span></div>
                  {loadingTemplates ? <div className="fc-wa-empty">Carregando modelos...</div> : templateCatalogError ? <div className="fc-wa-template-error">{templateCatalogError}</div> : templates.length === 0 ? <div className="fc-wa-empty">Nenhum modelo configurado.</div> : <>
                    <label className="fc-wa-field"><span>Modelo</span><select value={selectedTemplateKey} onChange={(event) => handleTemplateSelection(event.target.value)}>
                      {(["agenda", "laudos", "financeiro"] as const).map((category) => <optgroup key={category} label={templateCategoryLabel(category)}>
                        {templates.filter((template) => template.category === category).map((template) => <option key={template.key} value={template.key}>{template.workflow_label}</option>)}</optgroup>)}</select></label>
                    {selectedTemplate ? <div className="fc-wa-template-grid"><div className="fc-wa-template-fields">{selectedTemplate.variable_labels.map((label, index) =>
                      <label className="fc-wa-field" key={`${selectedTemplate.key}-${label}-${index}`}><span>{label}</span><input value={templateParameters[index] || ""}
                        onChange={(event) => { const next = [...templateParameters]; next[index] = event.target.value; setTemplateParameters(next); }} placeholder={`Valor de {{${index + 1}}}`} /></label>)}</div>
                      <div className="fc-wa-template-preview"><span>Prévia da mensagem</span>{selectedTemplate.requires_document ? <em><FileText className="h-4 w-4" /> Inclui documento PDF</em> : null}<p>{templatePreview}</p>
                        {selectedTemplate.quick_replies.length ? <div>{selectedTemplate.quick_replies.map((reply) => <span key={reply}>{reply}</span>)}</div> : null}</div></div> : null}
                    <div className="fc-wa-template-actions"><p>{selectedTemplate?.requires_document ? "Este modelo deve ser enviado pelo fluxo Financeiro, junto com o PDF correto." : windowState.isOpen ?
                      "Você pode copiar apenas o texto para revisar e enviar como resposta livre. Os botões do modelo não serão incluídos." : "Fora da janela de 24 horas, envie pelo fluxo de Agenda, Laudos ou Financeiro para preservar vínculos e botões."}</p>
                      <button type="button" className="fc-wa-secondary" onClick={handleCopyTemplateToComposer} disabled={!templateComplete || !windowState.isOpen || !selectedTemplate?.can_copy_as_free_text}>Copiar texto para resposta</button></div></>}
                </div>}
            </div>
          </section>

          <aside className="fc-wa-context" aria-label="Contexto da conversa"><div className="fc-wa-context-heading"><UserRound className="h-5 w-5" /><div><span>Contexto</span><h2>Atendimento</h2></div></div>
            {selectedConversation ? <div className="fc-wa-context-body"><section className="fc-wa-contact-card"><span className="fc-wa-avatar fc-wa-avatar-xl">{getInitials(conversationDisplayName)}</span><h3>{conversationDisplayName}</h3>
              <p>{formatPhone(selectedConversation.wa_phone_number)}</p><span className={`fc-wa-status ${conversationStatusClass(selectedConversation.status)}`}>{conversationStatusLabel(selectedConversation.status)}</span></section>
              <FollowUpPanel key={currentUser?.id ?? "anonymous"} conversationId={selectedConversation.id} agents={agents} defaultAgentId={myAgentId || selectedConversation.last_agent_id}
                onChanged={() => void loadConversations(conversationsPagination.page, { silent: true })} />
              <section className="fc-wa-context-section"><div className="fc-wa-context-section-title"><CircleDot className="h-4 w-4" /><h3>Classificação</h3></div>
                <label className="fc-wa-field"><span>Status da conversa</span><select value={selectedConversation.status} onChange={(event) => void handleStatusChange(event.target.value as ConversationStatus)} disabled={savingStatus}>
                  <option value="open">Em atendimento</option><option value="pending">Aguardando cliente</option><option value="closed">Resolvida</option></select></label></section>
              <section className="fc-wa-context-section"><div className="fc-wa-context-section-title"><Sparkles className="h-4 w-4" /><h3>Copiloto do WhatsApp</h3></div>
                {loadingBotState ? <p className="fc-wa-bot-state-note">Carregando estado...</p> : botConversationState ? <>
                  <label className="fc-wa-field"><span>Modo nesta conversa</span><select value={botConversationState.modo}
                    onChange={(event) => void handleBotModeChange(event.target.value as WhatsAppBotMode)} disabled={savingBotAction}>
                    <option value="off">Desligado</option><option value="suggest">Copiloto (sugerir)</option><option value="auto" disabled={!botConversationState.envio_automatico_liberado}>Automático{botConversationState.envio_automatico_liberado ? "" : " (aguarda ativação)"}</option>
                  </select></label>
                  <p className="fc-wa-bot-state-note">Origem: {botConversationState.modo_origem === "institucional" ? "padrão institucional" : "definido nesta conversa"}.</p>
                  <button type="button" className={botConversationState.pausado ? "fc-wa-secondary" : "fc-wa-ghost-danger"}
                    onClick={() => void handleBotPause(!botConversationState.pausado)} disabled={savingBotAction}>
                    {botConversationState.pausado ? "Retomar bot" : "Pausar bot"}
                  </button>
                  {botConversationState.pausado_ate ? <p className="fc-wa-bot-state-note">Pausado até {formatDateTime(botConversationState.pausado_ate)}.</p> : null}
                </> : <p className="fc-wa-bot-state-note">Estado do bot indisponível.</p>}
              </section>
              <section className="fc-wa-context-section"><div className="fc-wa-context-section-title"><UserCheck className="h-4 w-4" /><h3>Responsável</h3></div>
                <p className="fc-wa-current-agent">{selectedAgent?.name || selectedConversation.assigned_agent_name || "Nenhum atendente atribuído"}
                  {(selectedAgent?.email || selectedConversation.assigned_agent_email) ? <small>{selectedAgent?.email || selectedConversation.assigned_agent_email}</small> : null}</p>
                <label className="fc-wa-field"><span>{selectedConversation.last_agent_id ? "Transferir para" : "Atribuir para"}</span><select value={agentActionId} onChange={(event) => setAgentActionId(event.target.value)}>
                  <option value="">Selecione um atendente</option>{agents.filter((agent) => agent.active).map((agent) => <option key={agent.id} value={agent.id}>{agent.name || agent.email || `Atendente ${agent.id}`}</option>)}</select></label>
                <div className="fc-wa-owner-actions"><button type="button" className="fc-wa-secondary" onClick={() => void handleClaimToggle("claim")} disabled={savingAssignment || !agentActionId || agentActionId === selectedConversation.last_agent_id}>{selectedConversation.last_agent_id ? "Transferir" : "Assumir conversa"}</button>
                  {selectedConversation.last_agent_id ? <button type="button" className="fc-wa-ghost-danger" disabled={savingAssignment} onClick={() => void handleClaimToggle("unclaim", selectedConversation.last_agent_id || undefined)}>Liberar</button> : null}</div></section>
              <section className="fc-wa-context-section"><div className="fc-wa-context-section-title"><Clock3 className="h-4 w-4" /><h3>Atividade</h3></div><dl className="fc-wa-context-list">
                <div><dt>Última atividade</dt><dd>{formatDateTime(selectedConversation.last_activity_at)}</dd></div><div><dt>Última mensagem recebida</dt><dd>{formatDateTime(selectedConversation.last_inbound_at)}</dd></div><div><dt>Canal</dt><dd>WhatsApp Business</dd></div></dl></section>
              {botConversationState?.solicitacao_agendamento ? <section className="fc-wa-context-section">
                <h3>Solicitação de agendamento</h3>
                <p>{botConversationState.solicitacao_agendamento.status_equipe ? `Acompanhamento: ${botConversationState.solicitacao_agendamento.status_equipe}` : botConversationState.solicitacao_agendamento.status === "encaminhada" ? "Dados conferidos pelo solicitante — validar agenda" : botConversationState.solicitacao_agendamento.status === "cancelada" ? "Coleta cancelada" : "Coleta em andamento"}</p>
                <p style={{ whiteSpace: "pre-line" }}>{botConversationState.solicitacao_agendamento.resumo}</p>
                {botConversationState.solicitacao_agendamento.preferencia_recebida_em ? <p>Preferência informada em {formatDateTime(botConversationState.solicitacao_agendamento.preferencia_recebida_em)}</p> : null}
                <p>{botConversationState.solicitacao_agendamento.status_equipe ? "Consulte a equipe para os detalhes do horário na agenda." : "Nenhum horário reservado. A equipe confirma o agendamento."}</p>
              </section> : null}
              <DomainContextPanel key={selectedConversation.id} context={domainContext} loading={loadingDomainContext} error={domainContextError}
                onSaveSelection={saveDomainSelection} onReload={reloadDomainContext} />
              <details className="fc-wa-technical-details"><summary>Dados técnicos</summary><span>Conversa #{selectedConversation.id}</span><span>PSID: {selectedConversation.wa_psid || "não informado"}</span></details>
            </div> : <div className="fc-wa-empty"><UserRound className="h-8 w-8" /><strong>Selecione uma conversa</strong><span>Os dados do atendimento aparecerão aqui.</span></div>}</aside>
        </section>

        <details className="fc-wa-team-admin"><summary><Settings className="h-4 w-4" /> Configurar equipe</summary><div className="fc-wa-team-admin-body"><form onSubmit={handleCreateAgent}>
          <label className="fc-wa-field"><span>Nome</span><input value={newAgentName} onChange={(event) => setNewAgentName(event.target.value)} /></label>
          <label className="fc-wa-field"><span>Email</span><input type="email" value={newAgentEmail} onChange={(event) => setNewAgentEmail(event.target.value)} required /></label>
          <label className="fc-wa-field"><span>Perfil</span><select value={newAgentRole} onChange={(event) => setNewAgentRole(event.target.value)}><option value="agent">Atendente</option><option value="supervisor">Supervisor</option></select></label>
          <button className="fc-wa-primary" type="submit">Adicionar atendente</button></form><div className="fc-wa-agent-list"><strong>Equipe {loadingAgents ? "(carregando...)" : ""}</strong>
            {agents.length === 0 ? <p>Nenhum atendente cadastrado.</p> : <ul>{agents.map((agent) => editingAgentId === agent.id ? (
              <li key={agent.id} className="fc-wa-agent-edit"><form onSubmit={handleUpdateAgent}>
                <label className="fc-wa-field"><span>Nome</span><input value={editAgentName} onChange={(event) => setEditAgentName(event.target.value)} /></label>
                <label className="fc-wa-field"><span>Email</span><input type="email" value={editAgentEmail} onChange={(event) => setEditAgentEmail(event.target.value)} required /></label>
                <label className="fc-wa-field"><span>Perfil</span><select value={editAgentRole} onChange={(event) => setEditAgentRole(event.target.value)}><option value="agent">Atendente</option><option value="supervisor">Supervisor</option></select></label>
                <div className="fc-wa-agent-edit-actions">
                  <button className="fc-wa-primary" type="submit" disabled={savingAgentId === agent.id}>Salvar</button>
                  <button type="button" className="fc-wa-icon-button" onClick={cancelEditAgent} aria-label="Cancelar edição"><X className="h-4 w-4" /></button>
                </div></form></li>
            ) : (
              <li key={agent.id}><span className="fc-wa-avatar">{getInitials(agent.name || agent.email || "A")}</span>
                <span>{agent.name || "Sem nome"}<small>{agent.email || "Sem email"} · {agent.active ? "Ativo" : "Inativo"}</small></span>
                <span className="fc-wa-agent-actions">
                  <button type="button" className="fc-wa-icon-button" onClick={() => startEditAgent(agent)} aria-label={`Editar ${agent.name || agent.email || "atendente"}`}><Pencil className="h-3.5 w-3.5" /></button>
                  <button type="button" className={agent.active ? "fc-wa-ghost-danger" : "fc-wa-secondary"} onClick={() => void handleToggleAgentActive(agent)} disabled={savingAgentId === agent.id}>
                    {agent.active ? "Desativar" : "Reativar"}</button>
                </span></li>
            ))}</ul>}</div></div></details>
      </main>
    </DashboardLayout>
  );
}
