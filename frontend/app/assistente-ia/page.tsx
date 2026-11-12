"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  BrainCircuit,
  Building2,
  CalendarClock,
  CalendarPlus,
  CalendarSearch,
  Check,
  CheckCircle2,
  Clock3,
  ClipboardList,
  Copy,
  Database,
  ExternalLink,
  Loader2,
  FileHeart,
  FlaskConical,
  History,
  Lightbulb,
  Mic,
  MessageCircle,
  MessageSquare,
  Plus,
  ReceiptText,
  Radar,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  Target,
  Play,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  X,
  XCircle,
} from "lucide-react";

import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { montarLinkWhatsAppReserva } from "@/lib/agenda-reserva-manual";
import { formatarWhatsAppVisual } from "@/lib/clinica-whatsapp";

type ToolTrace = {
  name: string;
  ok: boolean;
  summary: string;
};

type AssistantMessage = {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  tools?: ToolTrace[];
  pending_action_id?: string | null;
  created_at?: string | null;
};

type PendingAction = {
  id: string;
  conversation_id: string;
  type: string;
  status: "pending" | "rejected" | "executed" | "invalidated" | "expired" | string;
  arguments: {
    agendamento_id?: number;
    motivo?: string;
    tipo?: "agendamento" | "reserva";
    destinatario_mensagem?: "clinica" | "tutor";
    observacoes?: string | null;
  };
  target: {
    agendamento_id?: number;
    inicio?: string | null;
    status?: string;
    clinica_nome?: string;
    servico_nome?: string;
    paciente_primeiro_nome?: string | null;
    paciente_nome?: string | null;
    tutor_nome?: string | null;
    tipo?: "agendamento" | "reserva";
    reserva_expira_em?: string | null;
    destinatario_mensagem?: {
      tipo?: "clinica" | "tutor";
      nome?: string | null;
      telefones?: string[];
    };
    data?: string;
    antes?: AgendaWindow;
    depois?: AgendaWindow;
    motivo?: string | null;
  };
  result?: {
    message?: string;
    reason?: string;
    agendamento?: {
      id?: number;
      status?: string;
      inicio?: string | null;
    };
    comunicacao?: {
      destinatario_tipo?: "clinica" | "tutor";
      destinatario_nome?: string | null;
      telefones?: string[];
      mensagem?: string;
      envio_manual?: boolean;
    };
    agenda_excecao?: {
      data?: string;
      ativo?: boolean;
      inicio?: string;
      fim?: string;
      motivo?: string | null;
    };
  } | null;
  expires_at?: string | null;
};

type AgendaWindow = {
  data?: string;
  ativo?: boolean;
  inicio?: string;
  fim?: string;
  motivo?: string | null;
  fonte?: string;
};

type Conversation = {
  id: string;
  title: string;
  active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  messages?: AssistantMessage[];
  pending_actions?: PendingAction[];
};

type AssistantStatus = {
  enabled: boolean;
  configured: boolean;
  model: string;
  admin_only: boolean;
  voice?: {
    enabled: boolean;
    model: string;
    max_seconds: number;
    review_before_send: boolean;
    audio_persisted: boolean;
  };
};

type ExecutiveSummary = {
  date: string;
  agenda: { total: number; by_status: Record<string, number>; reservations_expiring_6h: number };
  finance: { month_revenue: number; overdue_count: number; overdue_total: number };
  pending_approvals: number;
  alerts: Array<{ level: string; message: string }>;
};

type SupervisedMemory = {
  id: string;
  title: string;
  content: string;
  category: string;
  source: string;
  status: string;
  current_version: number;
  created_at?: string | null;
};

type LearningSuggestion = {
  id: string;
  feedback_id?: number | null;
  target_memory_id?: string | null;
  title: string;
  content: string;
  category: string;
  source: string;
  source_context: { user_request?: string | null; assistant_response?: string | null; feedback_comment?: string | null };
  impact: { scope?: string; applies_after_approval?: boolean; operational_writes?: boolean };
  status: "pending" | "approved" | "rejected" | string;
  memory_id?: string | null;
  regression_case_id?: string | null;
  created_at?: string | null;
};

type MemoryVersion = {
  id: number;
  memory_id: string;
  version: number;
  title: string;
  content: string;
  category: string;
  change_type: "create" | "update" | "rollback" | string;
  created_at?: string | null;
};

type RegressionCase = {
  id: string;
  learning_id?: string | null;
  memory_id: string;
  type: string;
  prompt: string;
  expectation: { version?: number; content_sha256?: string };
  status: string;
  last_status?: "passed" | "failed" | null;
  verified_at?: string | null;
};

type KnowledgeDocument = {
  id: string;
  title: string;
  category: string;
  source?: string | null;
  status: string;
  semantic_enabled: boolean;
  semantic_status: "disabled" | "queued" | "indexing" | "ready" | "error" | string;
  embedding_model?: string | null;
  semantic_error?: string | null;
  indexed_at?: string | null;
  created_at?: string | null;
};

type RadarOutput = {
  date: string;
  generated_at: string;
  alerts: Array<{
    key: string;
    level: "ok" | "info" | "attention" | "critical" | string;
    title: string;
    evidence: string;
    recommendation: string;
  }>;
  indicators: {
    revenue: {
      current_period: number;
      previous_comparable_period: number;
      change_percent?: number | null;
      comparable_days: number;
    };
    appointments: {
      last_7_days: number;
      previous_7_days: number;
      cancelled_last_7_days: number;
      cancelled_previous_7_days: number;
    };
    overdue: { count: number; total: number };
    reservations_expiring_6h: number;
    pending_approvals: number;
  };
  safety: string;
};

type AutonomousExecution = {
  id: string;
  mission_id?: string | null;
  type: string;
  source: string;
  status: "queued" | "running" | "completed" | "error" | string;
  output?: Record<string, unknown> | null;
  error?: string | null;
  created_at?: string | null;
  finished_at?: string | null;
};

type AssistantMission = {
  id: string;
  title: string;
  type: "radar" | "executive_summary" | "billing_trend" | "overdue_debts" | "clinic_360" | "eval_lab";
  config: { months?: number; clinic?: string | null; overdue_only?: boolean; period_days?: number };
  recurrence: "daily" | "weekly";
  local_time: string;
  weekdays: number[];
  enabled: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
};

type ClinicalDraft = {
  id: string;
  report_id: number;
  title: string;
  content: string;
  alerts: string[];
  status: string;
  created_at?: string | null;
  official_report_modified: boolean;
};

type AssistantMetrics = {
  period_days: number;
  assistant_responses: number;
  tokens: number;
  average_latency_ms?: number | null;
  feedback: { positive: number; negative: number };
  actions: Record<string, number>;
};

type Clinic360MissionTemplate = {
  title: string;
  type: "clinic_360";
  config: { clinic: string; period_days: number };
  recurrence: "weekly";
  local_time: string;
  weekdays: number[];
  enabled: boolean;
  read_only: boolean;
};

type Clinic360ActionPlanStep = {
  id: string;
  kind: "read_only_mission" | "contact_draft" | "operational_review";
  title: string;
  description: string;
  cta: string;
  prompt?: string | null;
  mission_template?: Clinic360MissionTemplate | null;
  requires_admin_approval: boolean;
  external_send: boolean;
  automatic_business_write: boolean;
};

type Clinic360ActionPlanItem = {
  id: string;
  source_alert: string;
  priority: "critical" | "high";
  title: string;
  objective: string;
  evidence: string;
  steps: Clinic360ActionPlanStep[];
};

type Clinic360Profile = {
  clinic: {
    id: number;
    name: string;
    active: boolean;
    city?: string | null;
    state?: string | null;
    region?: string | null;
    address?: string | null;
    contact: { phone?: string | null; whatsapps: string[]; email?: string | null };
  };
  period: {
    days: number;
    current: { start: string; end: string };
    previous: { start: string; end: string };
  };
  appointments: {
    total: number;
    previous_total: number;
    change_percent?: number | null;
    realized: number;
    cancelled: number;
    no_show: number;
    cancellation_rate: number;
    no_show_rate: number;
    by_status: Record<string, number>;
    top_services: Array<{ service_id: number; name: string; appointments: number }>;
    last_appointment_at?: string | null;
    next_appointment_at?: string | null;
  };
  finance: {
    revenue: number;
    previous_revenue: number;
    revenue_change_percent?: number | null;
    receipts: number;
    average_ticket: number;
    fees: number;
    service_order_production: number;
    service_orders: number;
  };
  debts: {
    pending_service_orders: { count: number; total: number };
    pending_receivables: { count: number; total: number };
    overdue_receivables: { count: number; total: number };
    estimated_total_without_deduplication: number;
    warning: string;
  };
  relationship: {
    last_activity_at?: string | null;
    days_since_activity?: number | null;
    approved_preferences: Array<{ id: string; title: string; content: string; category: string }>;
  };
  alerts: Array<{ key: string; level: string; title: string; evidence: string }>;
  action_plan: {
    status: "attention" | "healthy";
    items?: Clinic360ActionPlanItem[];
    items_count?: number;
    requires_admin_approval: boolean;
    automatic_execution: boolean;
    external_send?: boolean;
    safety?: string;
  };
  attention_score: number;
  ranking?: { revenue: number; attention: number };
  provenance: {
    generated_at: string;
    data_through: string;
    read_only: boolean;
    contains_patient_or_tutor_data: boolean;
    method: string;
    sources: Array<{ key: string; label: string; record_count: number; last_updated_at?: string | null; mode: string }>;
  };
};

type Clinics360Portfolio = {
  period: Clinic360Profile["period"];
  portfolio: {
    clinics: number;
    with_alerts: number;
    revenue: number;
    appointments: number;
    overdue_receivables: number;
  };
  items: Clinic360Profile[];
  provenance: { generated_at: string; data_through: string; read_only: boolean; contains_patient_or_tutor_data: boolean };
};

type Clinics360Comparison = {
  items: Clinic360Profile[];
  insights: Array<{ key: string; label: string; clinic_id: number; clinic_name: string; value: number }>;
};

type WorkspaceView = "chat" | "clinics" | "radar" | "brief" | "missions" | "approvals" | "learning" | "memory" | "knowledge" | "evaluations" | "clinical";
type VoiceState = "idle" | "recording" | "transcribing" | "review";

const EXAMPLES = [
  {
    icon: BarChart3,
    text: "Verifique a dinâmica de faturamento dos últimos 5 meses.",
  },
  {
    icon: Trash2,
    text: "Localize e prepare a exclusão do agendamento registrado hoje às 10h na Animal Care.",
  },
  {
    icon: CalendarSearch,
    text: "Verifique disponibilidade de horário para ecocardiograma na Vet World.",
  },
  {
    icon: CalendarPlus,
    text: "Reserve amanhã às 10h um ecocardiograma na Animal Care e deixe a mensagem pronta para a clínica.",
  },
  {
    icon: CalendarClock,
    text: "Deixe a agenda aberta amanhã até as 18h.",
  },
  {
    icon: ReceiptText,
    text: "Emita um relatório de débitos pendentes na Vet Plus.",
  },
  {
    icon: Building2,
    text: "Mostre a visão 360 da Animal Care e explique o que merece atenção.",
  },
];

const WORKSPACE_VIEWS: Array<{ id: WorkspaceView; label: string; icon: typeof BrainCircuit }> = [
  { id: "chat", label: "Conversa", icon: MessageSquare },
  { id: "clinics", label: "Clínicas 360", icon: Building2 },
  { id: "radar", label: "Radar", icon: Radar },
  { id: "brief", label: "Resumo diário", icon: BarChart3 },
  { id: "missions", label: "Missões", icon: Target },
  { id: "approvals", label: "Aprovações", icon: ClipboardList },
  { id: "learning", label: "Aprendizados", icon: Lightbulb },
  { id: "memory", label: "Memória", icon: BrainCircuit },
  { id: "knowledge", label: "Conhecimento", icon: BookOpen },
  { id: "evaluations", label: "Avaliações", icon: FlaskConical },
  { id: "clinical", label: "Rascunhos clínicos", icon: FileHeart },
];

function roleName(role: unknown): string {
  if (typeof role === "string") return role;
  if (typeof role === "object" && role !== null && "nome" in role) {
    return String((role as { nome?: unknown }).nome || "");
  }
  return "";
}

function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "userMessage" in error) {
    return String((error as { userMessage?: unknown }).userMessage || fallback);
  }
  return fallback;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "horário não informado";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(parsed);
}

function formatDateOnly(value?: string | null): string {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return value || "data não informada";
  return `${match[3]}/${match[2]}/${match[1]}`;
}

function formatMoney(value?: number | null): string {
  return `R$ ${Number(value || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatChange(value?: number | null): string {
  if (value == null) return "sem base anterior";
  return `${value > 0 ? "+" : ""}${value.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

function formatAgendaWindow(value?: AgendaWindow): string {
  if (!value) return "Não informado";
  if (!value.ativo) return "Agenda fechada";
  return `${value.inicio || "?"} às ${value.fim || "?"}`;
}

function actionStatus(action: PendingAction): { label: string; className: string; Icon: typeof Clock3 } {
  if (action.status === "executed") {
    return { label: "Executada", className: "bg-vital-50 text-vital-700", Icon: CheckCircle2 };
  }
  if (action.status === "rejected") {
    return { label: "Rejeitada", className: "bg-ink-50 text-ink-600", Icon: XCircle };
  }
  if (action.status === "invalidated" || action.status === "expired") {
    return { label: action.status === "expired" ? "Expirada" : "Invalidada", className: "bg-amber-50 text-amber-800", Icon: AlertTriangle };
  }
  return { label: "Aguardando sua confirmação", className: "bg-amber-50 text-amber-800", Icon: Clock3 };
}

const MISSION_LABELS: Record<AssistantMission["type"], string> = {
  radar: "Radar proativo",
  executive_summary: "Resumo executivo",
  billing_trend: "Tendência de faturamento",
  overdue_debts: "Débitos pendentes por clínica",
  clinic_360: "Clínica 360 recorrente",
  eval_lab: "Laboratório de avaliações",
};

const WEEKDAY_LABELS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

export default function AssistenteIAPage() {
  const router = useRouter();
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const voiceTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [view, setView] = useState<WorkspaceView>("chat");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [input, setInput] = useState("");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [voiceNotice, setVoiceNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [decidingActionId, setDecidingActionId] = useState<string | null>(null);
  const [selectedWhatsapps, setSelectedWhatsapps] = useState<Record<string, string>>({});
  const [copiedActionId, setCopiedActionId] = useState<string | null>(null);
  const [executiveSummary, setExecutiveSummary] = useState<ExecutiveSummary | null>(null);
  const [radarExecution, setRadarExecution] = useState<AutonomousExecution | null>(null);
  const [missions, setMissions] = useState<AssistantMission[]>([]);
  const [executions, setExecutions] = useState<AutonomousExecution[]>([]);
  const [evaluationRuns, setEvaluationRuns] = useState<AutonomousExecution[]>([]);
  const [approvalInbox, setApprovalInbox] = useState<PendingAction[]>([]);
  const [memories, setMemories] = useState<SupervisedMemory[]>([]);
  const [learnings, setLearnings] = useState<LearningSuggestion[]>([]);
  const [learningCounts, setLearningCounts] = useState({ pending: 0, approved: 0, rejected: 0 });
  const [regressionCases, setRegressionCases] = useState<RegressionCase[]>([]);
  const [memoryVersions, setMemoryVersions] = useState<Record<string, MemoryVersion[]>>({});
  const [expandedMemoryId, setExpandedMemoryId] = useState<string | null>(null);
  const [learningEdits, setLearningEdits] = useState<Record<string, { titulo: string; conteudo: string; categoria: string }>>({});
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [clinicalDrafts, setClinicalDrafts] = useState<ClinicalDraft[]>([]);
  const [metrics, setMetrics] = useState<AssistantMetrics | null>(null);
  const [clinics360, setClinics360] = useState<Clinics360Portfolio | null>(null);
  const [clinic360Period, setClinic360Period] = useState(90);
  const [clinic360Search, setClinic360Search] = useState("");
  const [selectedClinic360, setSelectedClinic360] = useState<Clinic360Profile | null>(null);
  const [selectedClinicIds, setSelectedClinicIds] = useState<number[]>([]);
  const [clinics360Comparison, setClinics360Comparison] = useState<Clinics360Comparison | null>(null);
  const [clinics360Loading, setClinics360Loading] = useState(false);
  const [planMissionReview, setPlanMissionReview] = useState<{ clinicName: string; step: Clinic360ActionPlanStep } | null>(null);
  const [planNotice, setPlanNotice] = useState("");
  const [managementLoading, setManagementLoading] = useState(false);
  const [autonomyAction, setAutonomyAction] = useState<string | null>(null);
  const [feedbackSent, setFeedbackSent] = useState<Record<string, "positive" | "negative">>({});
  const [feedbackDraft, setFeedbackDraft] = useState<{ messageId: number; correcao: string; categoria: string; comentario: string } | null>(null);
  const [memoryForm, setMemoryForm] = useState({ titulo: "", conteudo: "", categoria: "operacao", memoria_alvo_id: "" });
  const [documentForm, setDocumentForm] = useState({ titulo: "", conteudo: "", categoria: "manual", fonte: "", indexar_semanticamente: false });
  const [missionForm, setMissionForm] = useState({
    titulo: "Radar diário da gestão",
    tipo: "radar" as AssistantMission["type"],
    recorrencia: "daily" as AssistantMission["recurrence"],
    horario_local: "07:00",
    dias_semana: [0] as number[],
    clinic: "",
    months: 5,
  });
  const [error, setError] = useState("");

  const refreshConversations = async () => {
    const response = await api.get("/assistente-ia/conversas");
    setConversations(Array.isArray(response.data?.items) ? response.data.items : []);
  };

  const refreshManagement = async () => {
    setManagementLoading(true);
    try {
      const results = await Promise.allSettled([
        api.get("/assistente-ia/resumo-executivo"),
        api.get("/assistente-ia/acoes"),
        api.get("/assistente-ia/memorias"),
        api.get("/assistente-ia/conhecimento"),
        api.get("/assistente-ia/rascunhos-clinicos"),
        api.get("/assistente-ia/metricas"),
        api.get("/assistente-ia/radar"),
        api.get("/assistente-ia/missoes"),
        api.get("/assistente-ia/execucoes?limit=30"),
        api.get("/assistente-ia/avaliacoes"),
        api.get("/assistente-ia/aprendizados"),
        api.get("/assistente-ia/aprendizados/regressoes"),
        api.get(`/assistente-ia/clinicas-360?periodo_dias=${clinic360Period}`),
      ]);
      if (results[0].status === "fulfilled") setExecutiveSummary(results[0].value.data);
      if (results[1].status === "fulfilled") setApprovalInbox(Array.isArray(results[1].value.data?.items) ? results[1].value.data.items : []);
      if (results[2].status === "fulfilled") setMemories(Array.isArray(results[2].value.data?.items) ? results[2].value.data.items : []);
      if (results[3].status === "fulfilled") setDocuments(Array.isArray(results[3].value.data?.items) ? results[3].value.data.items : []);
      if (results[4].status === "fulfilled") setClinicalDrafts(Array.isArray(results[4].value.data?.items) ? results[4].value.data.items : []);
      if (results[5].status === "fulfilled") setMetrics(results[5].value.data);
      if (results[6].status === "fulfilled") setRadarExecution(results[6].value.data?.execution || null);
      if (results[7].status === "fulfilled") setMissions(Array.isArray(results[7].value.data?.items) ? results[7].value.data.items : []);
      if (results[8].status === "fulfilled") setExecutions(Array.isArray(results[8].value.data?.items) ? results[8].value.data.items : []);
      if (results[9].status === "fulfilled") setEvaluationRuns(Array.isArray(results[9].value.data?.items) ? results[9].value.data.items : []);
      if (results[10].status === "fulfilled") {
        setLearnings(Array.isArray(results[10].value.data?.items) ? results[10].value.data.items : []);
        setLearningCounts(results[10].value.data?.counts || { pending: 0, approved: 0, rejected: 0 });
      }
      if (results[11].status === "fulfilled") setRegressionCases(Array.isArray(results[11].value.data?.items) ? results[11].value.data.items : []);
      if (results[12].status === "fulfilled") setClinics360(results[12].value.data as Clinics360Portfolio);
    } finally {
      setManagementLoading(false);
    }
  };

  const refreshClinics360 = async (periodDays = clinic360Period) => {
    setClinics360Loading(true);
    setError("");
    try {
      const response = await api.get(`/assistente-ia/clinicas-360?periodo_dias=${periodDays}`);
      setClinics360(response.data as Clinics360Portfolio);
      setSelectedClinic360(null);
      setClinics360Comparison(null);
      setPlanMissionReview(null);
      setPlanNotice("");
    } catch (clinicsError) {
      setError(errorMessage(clinicsError, "Não foi possível atualizar o mapa das clínicas."));
    } finally {
      setClinics360Loading(false);
    }
  };

  const openClinic360 = async (clinicId: number) => {
    setClinics360Loading(true);
    setError("");
    try {
      const response = await api.get(`/assistente-ia/clinicas-360/${clinicId}?periodo_dias=${clinic360Period}`);
      setSelectedClinic360(response.data?.profile as Clinic360Profile);
      setPlanMissionReview(null);
      setPlanNotice("");
    } catch (clinicError) {
      setError(errorMessage(clinicError, "Não foi possível abrir o perfil da clínica."));
    } finally {
      setClinics360Loading(false);
    }
  };

  const toggleClinicComparison = (clinicId: number) => {
    setSelectedClinicIds((current) => {
      if (current.includes(clinicId)) return current.filter((item) => item !== clinicId);
      if (current.length >= 5) return current;
      return [...current, clinicId];
    });
    setClinics360Comparison(null);
  };

  const compareSelectedClinics = async () => {
    if (selectedClinicIds.length < 2) return;
    setClinics360Loading(true);
    setError("");
    try {
      const params = new URLSearchParams({ periodo_dias: String(clinic360Period) });
      selectedClinicIds.forEach((clinicId) => params.append("clinica_ids", String(clinicId)));
      const response = await api.get(`/assistente-ia/clinicas-360/comparar?${params.toString()}`);
      setClinics360Comparison(response.data as Clinics360Comparison);
    } catch (comparisonError) {
      setError(errorMessage(comparisonError, "Não foi possível comparar as clínicas selecionadas."));
    } finally {
      setClinics360Loading(false);
    }
  };

  const openActionPlanPrompt = (prompt?: string | null) => {
    if (!prompt) return;
    setInput(prompt);
    setView("chat");
  };

  const approvePlanMission = async () => {
    const template = planMissionReview?.step.mission_template;
    if (!template) return;
    setAutonomyAction(`plan-mission-${planMissionReview.step.id}`);
    setError("");
    setPlanNotice("");
    try {
      await api.post("/assistente-ia/missoes", {
        titulo: template.title,
        tipo: template.type,
        configuracao: template.config,
        recorrencia: template.recurrence,
        horario_local: template.local_time,
        dias_semana: template.weekdays,
        enabled: template.enabled,
      });
      setPlanNotice(`Missão somente de leitura criada para ${planMissionReview.clinicName}.`);
      setPlanMissionReview(null);
      await refreshManagement();
    } catch (missionError) {
      setError(errorMessage(missionError, "Não foi possível criar a missão sugerida."));
    } finally {
      setAutonomyAction(null);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const initialize = async () => {
      try {
        const me = await api.get("/auth/me");
        const roles = Array.isArray(me.data?.papeis) ? me.data.papeis : [];
        const isAdmin = roles.some((role: unknown) => roleName(role).toLowerCase() === "admin");
        if (!isAdmin) {
          if (!cancelled) setAuthorized(false);
          router.replace("/dashboard");
          return;
        }
        const [statusResponse, conversationsResponse] = await Promise.all([
          api.get("/assistente-ia/status"),
          api.get("/assistente-ia/conversas"),
        ]);
        if (cancelled) return;
        setAuthorized(true);
        setStatus(statusResponse.data);
        setConversations(
          Array.isArray(conversationsResponse.data?.items) ? conversationsResponse.data.items : [],
        );
        void refreshManagement();
      } catch (initializationError) {
        if (cancelled) return;
        setAuthorized(false);
        setError(errorMessage(initializationError, "Não foi possível iniciar a Mente FortCordis."));
      }
    };
    void initialize();
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pendingActions, loading]);

  useEffect(() => {
    setVoiceSupported(
      Boolean(
        typeof window !== "undefined"
        && typeof navigator.mediaDevices?.getUserMedia === "function"
        && typeof window.MediaRecorder !== "undefined",
      ),
    );
    return () => {
      if (voiceTimeoutRef.current) clearTimeout(voiceTimeoutRef.current);
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const startConversation = () => {
    setConversationId(null);
    setMessages([]);
    setPendingActions([]);
    setInput("");
    setVoiceState("idle");
    setVoiceNotice("");
    setSelectedWhatsapps({});
    setCopiedActionId(null);
    setError("");
  };

  const openConversation = async (id: string) => {
    if (loading || loadingHistory) return;
    setLoadingHistory(true);
    setError("");
    try {
      const response = await api.get(`/assistente-ia/conversas/${id}`);
      const conversation = response.data as Conversation;
      setConversationId(conversation.id);
      setMessages(Array.isArray(conversation.messages) ? conversation.messages : []);
      setPendingActions(Array.isArray(conversation.pending_actions) ? conversation.pending_actions : []);
    } catch (historyError) {
      setError(errorMessage(historyError, "Não foi possível carregar esta conversa."));
    } finally {
      setLoadingHistory(false);
    }
  };

  const releaseVoiceResources = () => {
    if (voiceTimeoutRef.current) {
      clearTimeout(voiceTimeoutRef.current);
      voiceTimeoutRef.current = null;
    }
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    mediaRecorderRef.current = null;
  };

  const transcribeVoiceBlob = async (blob: Blob) => {
    if (!blob.size) {
      setVoiceState("idle");
      setVoiceNotice("");
      setError("Nenhum áudio foi capturado. Tente gravar novamente.");
      return;
    }
    setVoiceState("transcribing");
    setVoiceNotice("Transcrevendo o comando de voz...");
    setError("");
    try {
      const contentType = String(blob.type || "audio/webm").split(";", 1)[0];
      const extension = contentType.includes("mp4") || contentType.includes("m4a")
        ? "m4a"
        : contentType.includes("ogg")
          ? "ogg"
          : contentType.includes("wav")
            ? "wav"
            : "webm";
      const formData = new FormData();
      formData.append("arquivo", blob, `comando-voz.${extension}`);
      const response = await api.post("/assistente-ia/voz/transcrever", formData);
      const transcript = String(response.data?.transcript || "").trim();
      if (!transcript) throw new Error("Transcrição vazia");
      setInput(transcript);
      setVoiceState("review");
      setVoiceNotice("Comando transcrito. Revise se puder e toque em enviar.");
    } catch (voiceError) {
      setVoiceState("idle");
      setVoiceNotice("");
      setError(errorMessage(voiceError, "Não foi possível transcrever o comando de voz."));
    }
  };

  const startVoiceRecording = async () => {
    if (!voiceSupported || voiceState === "transcribing" || loading) return;
    setError("");
    setVoiceNotice("Solicitando acesso ao microfone...");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      const preferredTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
        "audio/ogg;codecs=opus",
      ];
      const mimeType = preferredTypes.find((item) => MediaRecorder.isTypeSupported(item));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: BlobPart[] = [];
      let recordingFailed = false;
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      recorder.onerror = () => {
        recordingFailed = true;
        releaseVoiceResources();
        setVoiceState("idle");
        setVoiceNotice("");
        setError("A gravação foi interrompida. Tente novamente.");
      };
      recorder.onstop = () => {
        if (recordingFailed) return;
        const recordedType = String(recorder.mimeType || mimeType || "audio/webm");
        const blob = new Blob(chunks, { type: recordedType });
        releaseVoiceResources();
        void transcribeVoiceBlob(blob);
      };
      recorder.start(250);
      setVoiceState("recording");
      setVoiceNotice("Ouvindo. Toque novamente para parar e transcrever.");
      const maxSeconds = Math.max(10, Number(status?.voice?.max_seconds || 60));
      voiceTimeoutRef.current = setTimeout(() => {
        if (recorder.state !== "inactive") recorder.stop();
      }, maxSeconds * 1000);
    } catch (voiceError) {
      releaseVoiceResources();
      setVoiceState("idle");
      setVoiceNotice("");
      setError(
        errorMessage(
          voiceError,
          "Não foi possível acessar o microfone. Verifique a permissão do navegador.",
        ),
      );
    }
  };

  const stopVoiceRecording = () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    setVoiceState("transcribing");
    setVoiceNotice("Finalizando a gravação...");
    recorder.stop();
  };

  const sendMessage = async () => {
    const cleanInput = input.trim();
    if (!cleanInput || loading || !status?.enabled || !status?.configured) return;

    const optimisticId = `local-${Date.now()}`;
    setMessages((current) => [
      ...current,
      { id: optimisticId, role: "user", content: cleanInput },
    ]);
    setInput("");
    setVoiceState("idle");
    setVoiceNotice("");
    setError("");
    setLoading(true);

    try {
      const response = await api.post("/assistente-ia/chat", {
        mensagem: cleanInput,
        conversa_id: conversationId,
      });
      const data = response.data;
      const newConversationId = String(data.conversation?.id || conversationId || "");
      setConversationId(newConversationId || null);
      setMessages((current) => [
        ...current.filter((message) => message.id !== optimisticId),
        data.user_message,
        data.assistant_message,
      ]);
      if (Array.isArray(data.pending_actions) && data.pending_actions.length > 0) {
        setPendingActions((current) => {
          const map = new Map(current.map((action) => [action.id, action]));
          data.pending_actions.forEach((action: PendingAction) => map.set(action.id, action));
          return Array.from(map.values());
        });
      }
      await refreshConversations();
    } catch (sendError) {
      const responseHeaders = (
        sendError as { response?: { headers?: Record<string, unknown> } }
      ).response?.headers;
      const recoveredConversationId = String(
        responseHeaders?.["x-assistente-conversation-id"] || "",
      ).trim();
      if (recoveredConversationId) setConversationId(recoveredConversationId);
      setMessages((current) => current.filter((message) => message.id !== optimisticId));
      setInput(cleanInput);
      setError(errorMessage(sendError, "A Mente FortCordis não conseguiu concluir a solicitação."));
    } finally {
      setLoading(false);
    }
  };

  const decideAction = async (actionId: string, decision: "approve" | "reject") => {
    setDecidingActionId(actionId);
    setError("");
    try {
      const response = await api.post(`/assistente-ia/acoes/${actionId}/decisao`, {
        decisao: decision,
        observacao: decision === "approve" ? "Confirmado na Mente FortCordis" : "Rejeitado na Mente FortCordis",
      });
      const updated = response.data?.action as PendingAction;
      setPendingActions((current) => current.map((action) => (action.id === updated.id ? updated : action)));
      setApprovalInbox((current) => current.filter((action) => action.id !== updated.id));
      void refreshManagement();
    } catch (decisionError) {
      setError(errorMessage(decisionError, "Não foi possível processar esta confirmação."));
      if (conversationId) await openConversation(conversationId);
    } finally {
      setDecidingActionId(null);
    }
  };

  const submitFeedback = async (message: AssistantMessage, rating: "positive" | "negative") => {
    if (typeof message.id !== "number" || feedbackSent[String(message.id)]) return;
    if (rating === "negative") {
      setFeedbackDraft({ messageId: message.id, correcao: "", categoria: "correcao", comentario: "" });
      return;
    }
    try {
      await api.post("/assistente-ia/feedbacks", {
        mensagem_id: message.id,
        avaliacao: rating,
        categoria: "util",
        comentario: null,
        correcao_esperada: null,
      });
      setFeedbackSent((current) => ({ ...current, [String(message.id)]: rating }));
      void refreshManagement();
    } catch (feedbackError) {
      setError(errorMessage(feedbackError, "Não foi possível registrar sua avaliação."));
    }
  };

  const submitCorrection = async () => {
    if (!feedbackDraft?.correcao.trim()) return;
    try {
      await api.post("/assistente-ia/feedbacks", {
        mensagem_id: feedbackDraft.messageId,
        avaliacao: "negative",
        categoria: feedbackDraft.categoria.trim() || "correcao",
        comentario: feedbackDraft.comentario.trim() || null,
        correcao_esperada: feedbackDraft.correcao.trim(),
      });
      setFeedbackSent((current) => ({ ...current, [String(feedbackDraft.messageId)]: "negative" }));
      setFeedbackDraft(null);
      setView("learning");
      await refreshManagement();
    } catch (feedbackError) {
      setError(errorMessage(feedbackError, "Não foi possível criar a sugestão de aprendizado."));
    }
  };

  const submitMemory = async () => {
    if (!memoryForm.titulo.trim() || !memoryForm.conteudo.trim()) return;
    try {
      await api.post("/assistente-ia/aprendizados", {
        ...memoryForm,
        memoria_alvo_id: memoryForm.memoria_alvo_id || null,
      });
      setMemoryForm({ titulo: "", conteudo: "", categoria: "operacao", memoria_alvo_id: "" });
      await refreshManagement();
    } catch (memoryError) {
      setError(errorMessage(memoryError, "Não foi possível propor o aprendizado."));
    }
  };

  const decideLearning = async (learning: LearningSuggestion, decision: "approve" | "reject") => {
    const edit = learningEdits[learning.id] || {
      titulo: learning.title,
      conteudo: learning.content,
      categoria: learning.category,
    };
    setAutonomyAction(`learning-${learning.id}`);
    setError("");
    try {
      await api.post(`/assistente-ia/aprendizados/${learning.id}/decisao`, {
        decisao: decision,
        ...(decision === "approve" ? edit : {}),
      });
      setLearningEdits((current) => {
        const next = { ...current };
        delete next[learning.id];
        return next;
      });
      await refreshManagement();
    } catch (learningError) {
      setError(errorMessage(learningError, "Não foi possível decidir este aprendizado."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const proposeMemoryAdjustment = (memory: SupervisedMemory) => {
    setMemoryForm({
      titulo: memory.title,
      conteudo: memory.content,
      categoria: memory.category,
      memoria_alvo_id: memory.id,
    });
    setView("learning");
  };

  const toggleMemoryVersions = async (memoryId: string) => {
    if (expandedMemoryId === memoryId) {
      setExpandedMemoryId(null);
      return;
    }
    setExpandedMemoryId(memoryId);
    if (memoryVersions[memoryId]) return;
    try {
      const response = await api.get(`/assistente-ia/memorias/${memoryId}/versoes`);
      setMemoryVersions((current) => ({
        ...current,
        [memoryId]: Array.isArray(response.data?.items) ? response.data.items : [],
      }));
    } catch (versionError) {
      setError(errorMessage(versionError, "Não foi possível carregar o histórico da memória."));
    }
  };

  const rollbackMemory = async (memoryId: string, version: number) => {
    setAutonomyAction(`rollback-${memoryId}-${version}`);
    setError("");
    try {
      await api.post(`/assistente-ia/memorias/${memoryId}/reverter`, { versao: version });
      setMemoryVersions((current) => {
        const next = { ...current };
        delete next[memoryId];
        return next;
      });
      await refreshManagement();
      await toggleMemoryVersions(memoryId);
    } catch (versionError) {
      setError(errorMessage(versionError, "Não foi possível restaurar esta versão."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const decideMemory = async (memoryId: string, decision: "approve" | "reject") => {
    try {
      await api.post(`/assistente-ia/memorias/${memoryId}/decisao`, { decisao: decision });
      await refreshManagement();
    } catch (memoryError) {
      setError(errorMessage(memoryError, "Não foi possível decidir esta memória."));
    }
  };

  const submitDocument = async () => {
    if (!documentForm.titulo.trim() || documentForm.conteudo.trim().length < 20) return;
    if (documentForm.indexar_semanticamente && !documentForm.fonte.trim()) {
      setError("Informe a fonte do documento antes de ativar a memória semântica.");
      return;
    }
    try {
      await api.post("/assistente-ia/conhecimento", documentForm);
      setDocumentForm({ titulo: "", conteudo: "", categoria: "manual", fonte: "", indexar_semanticamente: false });
      await refreshManagement();
    } catch (documentError) {
      setError(errorMessage(documentError, "Não foi possível incluir o documento."));
    }
  };

  const runRadar = async () => {
    setAutonomyAction("radar");
    setError("");
    try {
      const response = await api.post("/assistente-ia/radar/executar");
      setRadarExecution(response.data?.execution || null);
      await refreshManagement();
    } catch (radarError) {
      setError(errorMessage(radarError, "Não foi possível atualizar o radar."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const submitMission = async () => {
    if (!missionForm.titulo.trim()) return;
    setAutonomyAction("create-mission");
    setError("");
    const configuration = missionForm.tipo === "billing_trend"
      ? { months: missionForm.months, clinic: missionForm.clinic.trim() || null }
      : missionForm.tipo === "overdue_debts"
        ? { clinic: missionForm.clinic.trim(), overdue_only: true }
        : missionForm.tipo === "clinic_360"
          ? { clinic: missionForm.clinic.trim(), period_days: clinic360Period }
        : {};
    try {
      await api.post("/assistente-ia/missoes", {
        titulo: missionForm.titulo,
        tipo: missionForm.tipo,
        configuracao: configuration,
        recorrencia: missionForm.recorrencia,
        horario_local: missionForm.horario_local,
        dias_semana: missionForm.recorrencia === "weekly" ? missionForm.dias_semana : [],
        enabled: true,
      });
      await refreshManagement();
    } catch (missionError) {
      setError(errorMessage(missionError, "Não foi possível criar a missão."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const toggleMission = async (mission: AssistantMission) => {
    setAutonomyAction(`toggle-${mission.id}`);
    setError("");
    try {
      await api.patch(`/assistente-ia/missoes/${mission.id}`, { enabled: !mission.enabled });
      await refreshManagement();
    } catch (missionError) {
      setError(errorMessage(missionError, "Não foi possível alterar a missão."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const runMission = async (mission: AssistantMission) => {
    setAutonomyAction(`run-${mission.id}`);
    setError("");
    try {
      await api.post(`/assistente-ia/missoes/${mission.id}/executar`);
      await refreshManagement();
    } catch (missionError) {
      setError(errorMessage(missionError, "Não foi possível enfileirar a missão."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const runEvaluation = async () => {
    setAutonomyAction("evaluation");
    setError("");
    try {
      await api.post("/assistente-ia/avaliacoes/executar");
      await refreshManagement();
    } catch (evaluationError) {
      setError(errorMessage(evaluationError, "Não foi possível iniciar o laboratório."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const reindexDocument = async (documentId: string) => {
    setAutonomyAction(`index-${documentId}`);
    setError("");
    try {
      await api.post(`/assistente-ia/conhecimento/${documentId}/reindexar`);
      await refreshManagement();
    } catch (indexError) {
      setError(errorMessage(indexError, "Não foi possível iniciar a indexação semântica."));
    } finally {
      setAutonomyAction(null);
    }
  };

  const copyCommunication = async (action: PendingAction) => {
    const message = String(action.result?.comunicacao?.mensagem || "");
    if (!message) return;
    try {
      await navigator.clipboard.writeText(message);
      setCopiedActionId(action.id);
      window.setTimeout(() => setCopiedActionId((current) => (current === action.id ? null : current)), 1800);
    } catch {
      setError("Não foi possível copiar a mensagem automaticamente.");
    }
  };

  const openWhatsApp = (action: PendingAction) => {
    const communication = action.result?.comunicacao;
    const message = String(communication?.mensagem || "");
    const phones = Array.isArray(communication?.telefones) ? communication.telefones.filter(Boolean) : [];
    const selectedPhone = selectedWhatsapps[action.id] || phones[0] || "";
    if (!message) return;
    window.open(montarLinkWhatsAppReserva(selectedPhone, message), "_blank", "noopener,noreferrer");
  };

  if (authorized !== true) {
    return (
      <DashboardLayout>
        <div className="flex min-h-screen items-center justify-center bg-shell px-6">
          <div className="flex items-center gap-3 text-ink-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            {error || "Validando acesso administrativo..."}
          </div>
        </div>
      </DashboardLayout>
    );
  }

  const assistantReady = Boolean(status?.enabled && status?.configured);
  const radarOutput = radarExecution?.output as unknown as RadarOutput | undefined;
  const filteredClinics360 = (clinics360?.items || []).filter((item) => {
    const query = clinic360Search.trim().toLocaleLowerCase("pt-BR");
    if (!query) return true;
    return [item.clinic.name, item.clinic.city, item.clinic.region]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase("pt-BR").includes(query));
  });

  return (
    <DashboardLayout>
      <div className="min-h-screen min-w-0 overflow-x-hidden bg-shell p-4 sm:p-6 lg:p-8">
        <div className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-5">
          <header className="overflow-hidden rounded-3xl bg-gradient-to-br from-ink-900 via-ink-700 to-vital-900 p-6 text-white shadow-fort-card sm:p-8">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
              <div className="max-w-3xl">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-vital-100">
                  <BrainCircuit className="h-5 w-5" />
                  Inteligência de gestão exclusiva do administrador
                </div>
                <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Mente FortCordis</h1>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-white/70 sm:text-base">
                  Consulte a operação em linguagem natural. A IA usa ferramentas delimitadas do sistema,
                  mantém o histórico e pede sua confirmação antes de criar, reservar, excluir ou alterar o funcionamento da agenda.
                </p>
              </div>
              <div className="flex items-center gap-2 rounded-2xl bg-white/10 px-4 py-3 text-sm backdrop-blur">
                <span className={`h-2.5 w-2.5 rounded-full ${assistantReady ? "bg-emerald-400" : "bg-amber-400"}`} />
                {assistantReady ? `Pronta · ${status?.model}` : "Configuração pendente no backend"}
              </div>
            </div>
          </header>

          {!assistantReady ? (
            <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p className="font-semibold">A interface está pronta, mas a credencial ainda não chegou ao processo do backend.</p>
                <p className="mt-1 text-amber-800">Configure OPENAI_API_KEY no ambiente do servidor para liberar as conversas.</p>
              </div>
            </div>
          ) : null}

          <nav className="flex gap-2 overflow-x-auto rounded-2xl border border-ink-100 bg-white p-2 shadow-sm">
            {WORKSPACE_VIEWS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setView(id)}
                className={`flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold transition ${
                  view === id ? "bg-ink-900 text-white" : "text-ink-500 hover:bg-ink-50 hover:text-ink-900"
                }`}
              >
                <Icon className="h-4 w-4" /> {label}
                {id === "approvals" && approvalInbox.length > 0 ? (
                  <span className="rounded-full bg-cordis-500 px-1.5 py-0.5 text-[10px] text-white">{approvalInbox.length}</span>
                ) : null}
                {id === "learning" && learningCounts.pending > 0 ? (
                  <span className="rounded-full bg-amber-400 px-1.5 py-0.5 text-[10px] text-ink-900">{learningCounts.pending}</span>
                ) : null}
                {id === "memory" && memories.some((item) => item.status === "pending") ? (
                  <span className="h-2 w-2 rounded-full bg-amber-400" />
                ) : null}
              </button>
            ))}
            <button
              type="button"
              onClick={() => void refreshManagement()}
              className="ml-auto flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold text-ink-500 hover:bg-ink-50"
            >
              <RefreshCw className={`h-4 w-4 ${managementLoading ? "animate-spin" : ""}`} /> Atualizar
            </button>
          </nav>

          {view !== "chat" ? (
            <section className="min-h-[620px] rounded-3xl border border-ink-100 bg-white p-5 shadow-fort-card sm:p-7">
              {error ? (
                <div className="mb-5 flex items-start gap-2 rounded-xl bg-cordis-50 px-3 py-2 text-sm text-cordis-700">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
                </div>
              ) : null}

              {view === "clinics" ? (
                <div className="space-y-6">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-3">
                        <Building2 className="h-7 w-7 text-cordis-600" />
                        <h2 className="text-2xl font-bold text-ink-900">Mapa operacional · Clínicas 360</h2>
                      </div>
                      <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-500">
                        Uma leitura viva de relacionamento, agenda, faturamento e pendências por clínica, com comparação e origem de cada indicador.
                      </p>
                      <p className="mt-2 flex items-center gap-2 text-xs font-semibold text-vital-700">
                        <ShieldCheck className="h-4 w-4" /> Somente leitura · sem dados de pacientes ou tutores
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <select
                        value={clinic360Period}
                        onChange={(event) => {
                          const period = Number(event.target.value);
                          setClinic360Period(period);
                          void refreshClinics360(period);
                        }}
                        className="rounded-xl border border-ink-200 bg-white px-3 py-2.5 text-sm font-semibold text-ink-700"
                      >
                        <option value={30}>Últimos 30 dias</option>
                        <option value={90}>Últimos 90 dias</option>
                        <option value={180}>Últimos 180 dias</option>
                        <option value={365}>Últimos 365 dias</option>
                      </select>
                      <button
                        type="button"
                        onClick={() => void refreshClinics360()}
                        disabled={clinics360Loading}
                        className="flex items-center gap-2 rounded-xl bg-ink-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
                      >
                        <RefreshCw className={`h-4 w-4 ${clinics360Loading ? "animate-spin" : ""}`} /> Atualizar
                      </button>
                    </div>
                  </div>

                  {clinics360 ? (
                    <>
                      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        {[
                          { label: "Clínicas ativas", value: clinics360.portfolio.clinics, detail: `${clinics360.portfolio.with_alerts} pedem atenção` },
                          { label: "Faturamento", value: formatMoney(clinics360.portfolio.revenue), detail: `${clinic360Period} dias` },
                          { label: "Agendamentos", value: clinics360.portfolio.appointments, detail: "no período atual" },
                          { label: "Contas vencidas", value: formatMoney(clinics360.portfolio.overdue_receivables), detail: `dados até ${formatDateOnly(clinics360.provenance.data_through)}` },
                        ].map((item) => (
                          <div key={item.label} className="rounded-2xl border border-ink-100 p-5">
                            <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">{item.label}</p>
                            <p className="mt-2 text-2xl font-bold text-ink-900">{item.value}</p>
                            <p className="mt-1 text-xs text-ink-500">{item.detail}</p>
                          </div>
                        ))}
                      </div>

                      <div className="grid gap-5 xl:grid-cols-[390px_minmax(0,1fr)]">
                        <aside className="rounded-2xl border border-ink-100 bg-ink-50/60 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <h3 className="font-semibold text-ink-900">Portfólio</h3>
                            <span className="text-xs text-ink-400">selecione até 5</span>
                          </div>
                          <input
                            value={clinic360Search}
                            onChange={(event) => setClinic360Search(event.target.value)}
                            placeholder="Buscar clínica, cidade ou região"
                            className="mt-3 w-full rounded-xl border border-ink-200 bg-white px-3 py-2.5 text-sm"
                          />
                          <div className="mt-3 max-h-[640px] space-y-2 overflow-y-auto pr-1">
                            {filteredClinics360.map((profile) => {
                              const selected = selectedClinicIds.includes(profile.clinic.id);
                              const active = selectedClinic360?.clinic.id === profile.clinic.id;
                              return (
                                <div key={profile.clinic.id} className={`rounded-xl border bg-white p-3 transition ${active ? "border-cordis-300 ring-2 ring-cordis-50" : "border-ink-100"}`}>
                                  <div className="flex items-start gap-3">
                                    <input
                                      type="checkbox"
                                      checked={selected}
                                      onChange={() => toggleClinicComparison(profile.clinic.id)}
                                      aria-label={`Selecionar ${profile.clinic.name} para comparação`}
                                      className="mt-1 h-4 w-4 rounded border-ink-300 text-cordis-600"
                                    />
                                    <button type="button" onClick={() => void openClinic360(profile.clinic.id)} className="min-w-0 flex-1 text-left">
                                      <div className="flex items-start justify-between gap-2">
                                        <div>
                                          <p className="truncate font-semibold text-ink-900">{profile.clinic.name}</p>
                                          <p className="mt-0.5 text-xs text-ink-400">{profile.clinic.city || "Cidade não informada"} · #{profile.ranking?.revenue || "—"} em faturamento</p>
                                        </div>
                                        {profile.attention_score > 0 ? <span className="rounded-full bg-amber-50 px-2 py-1 text-[10px] font-bold text-amber-700">{profile.attention_score} alerta</span> : <CheckCircle2 className="h-4 w-4 text-vital-600" />}
                                      </div>
                                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                                        <span className="text-ink-500"><strong className="text-ink-800">{formatMoney(profile.finance.revenue)}</strong><br />faturamento</span>
                                        <span className="text-ink-500"><strong className="text-ink-800">{profile.appointments.total}</strong><br />agendamentos</span>
                                      </div>
                                    </button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                          <button
                            type="button"
                            onClick={() => void compareSelectedClinics()}
                            disabled={selectedClinicIds.length < 2 || clinics360Loading}
                            className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-cordis-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
                          >
                            {clinics360Loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <BarChart3 className="h-4 w-4" />}
                            Comparar {selectedClinicIds.length || ""} clínica(s)
                          </button>
                        </aside>

                        <div className="space-y-5">
                          {clinics360Comparison ? (
                            <div className="rounded-2xl border border-cordis-100 bg-cordis-50/40 p-5">
                              <div className="flex items-center justify-between gap-3">
                                <h3 className="text-lg font-bold text-ink-900">Comparativo selecionado</h3>
                                <button type="button" onClick={() => setClinics360Comparison(null)} className="rounded-lg p-1.5 text-ink-400 hover:bg-white"><X className="h-4 w-4" /></button>
                              </div>
                              <div className="mt-4 overflow-x-auto">
                                <table className="min-w-full text-left text-sm">
                                  <thead className="text-xs uppercase tracking-wide text-ink-400"><tr><th className="pb-3 pr-5">Clínica</th><th className="pb-3 pr-5">Faturamento</th><th className="pb-3 pr-5">Variação</th><th className="pb-3 pr-5">Agenda</th><th className="pb-3 pr-5">Cancelamento</th><th className="pb-3">Vencido</th></tr></thead>
                                  <tbody className="divide-y divide-cordis-100">
                                    {clinics360Comparison.items.map((profile) => (
                                      <tr key={profile.clinic.id}>
                                        <td className="py-3 pr-5 font-semibold text-ink-900">{profile.clinic.name}</td>
                                        <td className="py-3 pr-5 text-ink-700">{formatMoney(profile.finance.revenue)}</td>
                                        <td className={`py-3 pr-5 font-semibold ${(profile.finance.revenue_change_percent || 0) < 0 ? "text-cordis-700" : "text-vital-700"}`}>{formatChange(profile.finance.revenue_change_percent)}</td>
                                        <td className="py-3 pr-5 text-ink-700">{profile.appointments.total}</td>
                                        <td className="py-3 pr-5 text-ink-700">{profile.appointments.cancellation_rate.toLocaleString("pt-BR")}%</td>
                                        <td className="py-3 text-ink-700">{formatMoney(profile.debts.overdue_receivables.total)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                                {clinics360Comparison.insights.map((insight) => <div key={insight.key} className="rounded-xl bg-white p-3 text-xs text-ink-500"><p>{insight.label}</p><p className="mt-1 font-semibold text-ink-900">{insight.clinic_name}</p></div>)}
                              </div>
                            </div>
                          ) : null}

                          {selectedClinic360 ? (
                            <div className="space-y-5">
                              <div className="flex flex-wrap items-start justify-between gap-3">
                                <div>
                                  <h3 className="text-2xl font-bold text-ink-900">{selectedClinic360.clinic.name}</h3>
                                  <p className="mt-1 text-sm text-ink-500">{[selectedClinic360.clinic.address, selectedClinic360.clinic.region].filter(Boolean).join(" · ") || "Localização não informada"}</p>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setInput(`Analise a visão 360 da ${selectedClinic360.clinic.name} e recomende o próximo passo gerencial.`);
                                    setView("chat");
                                  }}
                                  className="flex items-center gap-2 rounded-xl border border-ink-200 px-4 py-2.5 text-sm font-semibold text-ink-700 hover:bg-ink-50"
                                >
                                  <MessageSquare className="h-4 w-4" /> Conversar sobre esta clínica
                                </button>
                              </div>

                              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                                <div className="rounded-2xl border border-ink-100 p-4"><p className="text-xs text-ink-400">Faturamento</p><p className="mt-1 text-xl font-bold text-ink-900">{formatMoney(selectedClinic360.finance.revenue)}</p><p className={`mt-1 text-xs font-semibold ${(selectedClinic360.finance.revenue_change_percent || 0) < 0 ? "text-cordis-700" : "text-vital-700"}`}>{formatChange(selectedClinic360.finance.revenue_change_percent)} vs. período anterior</p></div>
                                <div className="rounded-2xl border border-ink-100 p-4"><p className="text-xs text-ink-400">Agenda</p><p className="mt-1 text-xl font-bold text-ink-900">{selectedClinic360.appointments.total}</p><p className="mt-1 text-xs text-ink-500">{selectedClinic360.appointments.realized} realizados · {selectedClinic360.appointments.no_show} faltas</p></div>
                                <div className="rounded-2xl border border-ink-100 p-4"><p className="text-xs text-ink-400">Cancelamentos</p><p className="mt-1 text-xl font-bold text-ink-900">{selectedClinic360.appointments.cancellation_rate.toLocaleString("pt-BR")}%</p><p className="mt-1 text-xs text-ink-500">{selectedClinic360.appointments.cancelled} no período</p></div>
                                <div className="rounded-2xl border border-ink-100 p-4"><p className="text-xs text-ink-400">Vencido</p><p className="mt-1 text-xl font-bold text-ink-900">{formatMoney(selectedClinic360.debts.overdue_receivables.total)}</p><p className="mt-1 text-xs text-ink-500">{selectedClinic360.debts.overdue_receivables.count} conta(s)</p></div>
                              </div>

                              {selectedClinic360.alerts.length > 0 ? (
                                <div className="space-y-2">
                                  {selectedClinic360.alerts.map((alert) => <div key={alert.key} className={`flex items-start gap-3 rounded-xl border p-4 ${alert.level === "critical" ? "border-cordis-200 bg-cordis-50" : "border-amber-200 bg-amber-50"}`}><AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${alert.level === "critical" ? "text-cordis-600" : "text-amber-600"}`} /><div><p className="text-sm font-semibold text-ink-900">{alert.title}</p><p className="mt-1 text-xs leading-5 text-ink-600">{alert.evidence}</p></div></div>)}
                                </div>
                              ) : <div className="flex items-center gap-2 rounded-xl bg-vital-50 p-4 text-sm font-semibold text-vital-800"><CheckCircle2 className="h-4 w-4" /> Nenhum alerta determinístico para o período.</div>}

                              {(selectedClinic360.action_plan?.items || []).length > 0 ? (
                                <section className="space-y-4 rounded-2xl border border-cordis-100 bg-gradient-to-br from-white to-cordis-50/40 p-5">
                                  <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div>
                                      <div className="flex items-center gap-2"><Target className="h-5 w-5 text-cordis-600" /><h4 className="text-lg font-bold text-ink-900">Planos de ação sugeridos</h4></div>
                                      <p className="mt-1 max-w-3xl text-xs leading-5 text-ink-500">Cada plano nasce de um alerta e separa monitoramento, contato e eventual ajuste operacional.</p>
                                    </div>
                                    <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">Nada é executado automaticamente</span>
                                  </div>

                                  {planNotice ? <div className="flex items-center gap-2 rounded-xl bg-vital-50 p-3 text-sm font-semibold text-vital-800"><CheckCircle2 className="h-4 w-4" /> {planNotice}</div> : null}

                                  {planMissionReview?.step.mission_template ? (
                                    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                                      <div className="flex items-start gap-3">
                                        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
                                        <div className="min-w-0 flex-1">
                                          <p className="font-semibold text-ink-900">Confirme a criação da missão</p>
                                          <p className="mt-1 text-sm text-ink-600">{planMissionReview.step.mission_template.title}</p>
                                          <p className="mt-1 text-xs leading-5 text-ink-500">Semanal, às {planMissionReview.step.mission_template.local_time}. Ela somente consulta o perfil 360; não envia mensagens nem altera dados operacionais.</p>
                                          <div className="mt-4 flex flex-wrap justify-end gap-2">
                                            <button type="button" onClick={() => setPlanMissionReview(null)} className="rounded-xl border border-ink-200 bg-white px-4 py-2 text-sm font-semibold text-ink-700">Cancelar</button>
                                            <button type="button" onClick={() => void approvePlanMission()} disabled={autonomyAction === `plan-mission-${planMissionReview.step.id}`} className="flex items-center gap-2 rounded-xl bg-cordis-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
                                              {autonomyAction === `plan-mission-${planMissionReview.step.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Aprovar e criar missão
                                            </button>
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                  ) : null}

                                  <div className="space-y-4">
                                    {(selectedClinic360.action_plan?.items || []).map((plan) => (
                                      <article key={plan.id} className="rounded-2xl border border-ink-100 bg-white p-4">
                                        <div className="flex flex-wrap items-start justify-between gap-3">
                                          <div><p className="font-semibold text-ink-900">{plan.title}</p><p className="mt-1 text-sm leading-6 text-ink-600">{plan.objective}</p></div>
                                          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${plan.priority === "critical" ? "bg-cordis-50 text-cordis-700" : "bg-amber-50 text-amber-800"}`}>{plan.priority === "critical" ? "Prioridade crítica" : "Alta prioridade"}</span>
                                        </div>
                                        <p className="mt-3 rounded-xl bg-ink-50 px-3 py-2 text-xs leading-5 text-ink-500"><strong className="text-ink-700">Evidência:</strong> {plan.evidence}</p>
                                        <div className="mt-4 grid gap-3 lg:grid-cols-3">
                                          {plan.steps.map((step) => {
                                            const Icon = step.kind === "read_only_mission" ? Target : step.kind === "contact_draft" ? MessageCircle : RefreshCw;
                                            const missionExists = Boolean(step.mission_template && missions.some((mission) => (
                                              mission.type === "clinic_360"
                                              && mission.config.clinic?.trim().toLocaleLowerCase("pt-BR") === step.mission_template?.config.clinic.trim().toLocaleLowerCase("pt-BR")
                                              && mission.config.period_days === step.mission_template?.config.period_days
                                            )));
                                            return (
                                              <div key={step.id} className="flex flex-col rounded-xl border border-ink-100 p-3">
                                                <div className="flex items-center gap-2"><Icon className="h-4 w-4 text-cordis-600" /><p className="text-sm font-semibold text-ink-900">{step.title}</p></div>
                                                <p className="mt-2 flex-1 text-xs leading-5 text-ink-500">{step.description}</p>
                                                <button
                                                  type="button"
                                                  onClick={() => step.kind === "read_only_mission" ? setPlanMissionReview({ clinicName: selectedClinic360.clinic.name, step }) : openActionPlanPrompt(step.prompt)}
                                                  disabled={missionExists}
                                                  className="mt-3 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50 disabled:cursor-not-allowed disabled:bg-ink-50 disabled:text-ink-400"
                                                >
                                                  {missionExists ? "Missão já criada" : step.cta}
                                                </button>
                                              </div>
                                            );
                                          })}
                                        </div>
                                      </article>
                                    ))}
                                  </div>

                                  <p className="flex items-start gap-2 text-xs leading-5 text-vital-700"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" /> {selectedClinic360.action_plan?.safety || "Sugestões aguardam sua decisão e não executam ações automaticamente."}</p>
                                </section>
                              ) : null}

                              <div className="grid gap-4 lg:grid-cols-2">
                                <div className="rounded-2xl bg-ink-50 p-5">
                                  <h4 className="font-semibold text-ink-900">Serviços e relacionamento</h4>
                                  <div className="mt-3 space-y-2 text-sm text-ink-600">
                                    {selectedClinic360.appointments.top_services.map((service) => <div key={service.service_id} className="flex justify-between rounded-xl bg-white px-3 py-2"><span>{service.name}</span><strong className="text-ink-900">{service.appointments}</strong></div>)}
                                    {selectedClinic360.appointments.top_services.length === 0 ? <p className="text-ink-400">Sem serviços no período.</p> : null}
                                  </div>
                                  <p className="mt-4 text-xs text-ink-500">Última atividade: {selectedClinic360.relationship.last_activity_at ? formatDateTime(selectedClinic360.relationship.last_activity_at) : "não localizada"}</p>
                                  <p className="mt-1 text-xs text-ink-500">Próximo agendamento: {selectedClinic360.appointments.next_appointment_at ? formatDateTime(selectedClinic360.appointments.next_appointment_at) : "não localizado"}</p>
                                </div>
                                <div className="rounded-2xl bg-ink-50 p-5">
                                  <h4 className="font-semibold text-ink-900">Preferências aprovadas</h4>
                                  <div className="mt-3 space-y-2">
                                    {selectedClinic360.relationship.approved_preferences.map((memory) => <div key={memory.id} className="rounded-xl bg-white p-3"><p className="text-sm font-semibold text-ink-900">{memory.title}</p><p className="mt-1 text-xs leading-5 text-ink-500">{memory.content}</p></div>)}
                                    {selectedClinic360.relationship.approved_preferences.length === 0 ? <p className="text-sm text-ink-400">Nenhuma preferência aprovada vinculada a esta clínica.</p> : null}
                                  </div>
                                </div>
                              </div>

                              <details className="rounded-2xl border border-ink-100 p-5">
                                <summary className="cursor-pointer text-sm font-semibold text-ink-800">Fontes, atualização e limitações</summary>
                                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                                  {selectedClinic360.provenance.sources.map((source) => <div key={source.key} className="rounded-xl bg-ink-50 p-3 text-xs text-ink-500"><p className="font-semibold text-ink-800">{source.label}</p><p className="mt-1">{source.record_count} registro(s) · {source.last_updated_at ? formatDateTime(source.last_updated_at) : "sem atualização registrada"}</p></div>)}
                                </div>
                                <p className="mt-3 text-xs leading-5 text-ink-500">{selectedClinic360.provenance.method} {selectedClinic360.debts.warning}</p>
                              </details>
                            </div>
                          ) : (
                            <div className="flex min-h-[360px] items-center justify-center rounded-2xl border border-dashed border-ink-200 bg-ink-50/40 p-8 text-center">
                              <div><Building2 className="mx-auto h-9 w-9 text-ink-300" /><p className="mt-3 font-semibold text-ink-700">Abra uma clínica para ver o perfil completo</p><p className="mt-1 text-sm text-ink-400">Ou marque duas ou mais para comparar lado a lado.</p></div>
                            </div>
                          )}
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="flex min-h-[300px] items-center justify-center text-sm text-ink-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Montando o mapa operacional...</div>
                  )}
                </div>
              ) : null}

              {view === "radar" ? (
                <div className="space-y-6">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-3"><Radar className="h-7 w-7 text-cordis-600" /><h2 className="text-2xl font-bold text-ink-900">Radar proativo</h2></div>
                      <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-500">Compara faturamento, agenda, cancelamentos, débitos e pendências para chamar sua atenção antes que virem problemas.</p>
                    </div>
                    <button type="button" onClick={() => void runRadar()} disabled={autonomyAction === "radar"} className="flex items-center gap-2 rounded-xl bg-cordis-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60">
                      {autonomyAction === "radar" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Atualizar radar
                    </button>
                  </div>
                  {radarOutput ? (
                    <>
                      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        <div className="rounded-2xl border border-ink-100 p-5"><p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Faturamento comparável</p><p className="mt-2 text-2xl font-bold text-ink-900">{radarOutput.indicators.revenue.change_percent == null ? "—" : `${radarOutput.indicators.revenue.change_percent > 0 ? "+" : ""}${radarOutput.indicators.revenue.change_percent}%`}</p><p className="mt-1 text-xs text-ink-500">R$ {radarOutput.indicators.revenue.current_period.toLocaleString("pt-BR", { minimumFractionDigits: 2 })} no período atual</p></div>
                        <div className="rounded-2xl border border-ink-100 p-5"><p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Agenda · 7 dias</p><p className="mt-2 text-2xl font-bold text-ink-900">{radarOutput.indicators.appointments.last_7_days}</p><p className="mt-1 text-xs text-ink-500">anterior: {radarOutput.indicators.appointments.previous_7_days}</p></div>
                        <div className="rounded-2xl border border-ink-100 p-5"><p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Cancelamentos</p><p className="mt-2 text-2xl font-bold text-ink-900">{radarOutput.indicators.appointments.cancelled_last_7_days}</p><p className="mt-1 text-xs text-ink-500">anterior: {radarOutput.indicators.appointments.cancelled_previous_7_days}</p></div>
                        <div className="rounded-2xl border border-ink-100 p-5"><p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Débitos vencidos</p><p className="mt-2 text-2xl font-bold text-ink-900">R$ {radarOutput.indicators.overdue.total.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}</p><p className="mt-1 text-xs text-ink-500">{radarOutput.indicators.overdue.count} conta(s)</p></div>
                      </div>
                      <div className="space-y-3">
                        {radarOutput.alerts.map((alert) => (
                          <article key={alert.key} className={`rounded-2xl border p-5 ${alert.level === "critical" ? "border-cordis-200 bg-cordis-50" : alert.level === "ok" ? "border-vital-100 bg-vital-50" : "border-amber-200 bg-amber-50/60"}`}>
                            <div className="flex items-start gap-3"><AlertTriangle className={`mt-0.5 h-5 w-5 shrink-0 ${alert.level === "ok" ? "text-vital-600" : alert.level === "critical" ? "text-cordis-600" : "text-amber-600"}`} /><div><h3 className="font-semibold text-ink-900">{alert.title}</h3><p className="mt-1 text-sm leading-6 text-ink-600">{alert.evidence}</p><p className="mt-2 text-sm font-medium text-ink-800">Próximo passo: {alert.recommendation}</p></div></div>
                          </article>
                        ))}
                      </div>
                      <p className="flex items-center gap-2 text-xs font-semibold text-vital-700"><ShieldCheck className="h-4 w-4" /> {radarOutput.safety}</p>
                    </>
                  ) : (
                    <div className="rounded-2xl bg-ink-50 p-6 text-sm text-ink-600">O Radar ainda não possui uma leitura. Clique em “Atualizar radar” ou crie uma missão recorrente.</div>
                  )}
                </div>
              ) : null}

              {view === "brief" ? (
                <div className="space-y-6">
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <div><h2 className="text-2xl font-bold text-ink-900">Resumo executivo diário</h2><p className="mt-1 text-sm text-ink-500">Leitura consolidada da operação em {formatDateOnly(executiveSummary?.date)}.</p></div>
                    <span className="rounded-full bg-vital-50 px-3 py-1 text-xs font-semibold text-vital-700">Atualização sob demanda</span>
                  </div>
                  {executiveSummary ? (
                    <>
                      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        {[
                          { label: "Agenda do dia", value: executiveSummary.agenda.total, detail: `${executiveSummary.agenda.reservations_expiring_6h} reserva(s) próximas do prazo`, icon: CalendarClock },
                          { label: "Faturamento no mês", value: `R$ ${executiveSummary.finance.month_revenue.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`, detail: "entradas recebidas", icon: BarChart3 },
                          { label: "Débitos vencidos", value: executiveSummary.finance.overdue_count, detail: `R$ ${executiveSummary.finance.overdue_total.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`, icon: ReceiptText },
                          { label: "Aprovações", value: executiveSummary.pending_approvals, detail: "ações aguardando decisão", icon: ClipboardList },
                        ].map(({ label, value, detail, icon: Icon }) => (
                          <div key={label} className="rounded-2xl border border-ink-100 p-5"><Icon className="h-5 w-5 text-cordis-600" /><p className="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-400">{label}</p><p className="mt-1 text-2xl font-bold text-ink-900">{value}</p><p className="mt-1 text-xs text-ink-500">{detail}</p></div>
                        ))}
                      </div>
                      <div className="grid gap-5 lg:grid-cols-2">
                        <div className="rounded-2xl bg-ink-50 p-5"><h3 className="font-semibold text-ink-900">Alertas e prioridades</h3><div className="mt-3 space-y-2">{executiveSummary.alerts.map((alert, index) => <div key={`${alert.message}-${index}`} className="flex items-start gap-2 rounded-xl bg-white p-3 text-sm text-ink-700"><AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${alert.level === "ok" ? "text-vital-600" : "text-amber-600"}`} />{alert.message}</div>)}</div></div>
                        <div className="rounded-2xl bg-ink-50 p-5"><h3 className="font-semibold text-ink-900">Qualidade da Mente · {metrics?.period_days || 30} dias</h3><dl className="mt-3 grid grid-cols-2 gap-3 text-sm"><div className="rounded-xl bg-white p-3"><dt className="text-ink-400">Respostas</dt><dd className="mt-1 text-xl font-bold text-ink-900">{metrics?.assistant_responses || 0}</dd></div><div className="rounded-xl bg-white p-3"><dt className="text-ink-400">Latência média</dt><dd className="mt-1 text-xl font-bold text-ink-900">{metrics?.average_latency_ms ? `${(metrics.average_latency_ms / 1000).toFixed(1)}s` : "—"}</dd></div><div className="rounded-xl bg-white p-3"><dt className="text-ink-400">Úteis</dt><dd className="mt-1 text-xl font-bold text-vital-700">{metrics?.feedback.positive || 0}</dd></div><div className="rounded-xl bg-white p-3"><dt className="text-ink-400">A corrigir</dt><dd className="mt-1 text-xl font-bold text-cordis-700">{metrics?.feedback.negative || 0}</dd></div></dl></div>
                      </div>
                    </>
                  ) : <p className="text-sm text-ink-400">Carregando a leitura executiva...</p>}
                </div>
              ) : null}

              {view === "missions" ? (
                <div className="grid gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
                  <div>
                    <div className="flex items-center gap-3"><Target className="h-7 w-7 text-cordis-600" /><h2 className="text-2xl font-bold text-ink-900">Missões recorrentes</h2></div>
                    <p className="mt-2 text-sm leading-6 text-ink-500">A Mente executa apenas consultas permitidas. Missões nunca criam, apagam ou alteram dados operacionais.</p>
                    <div className="mt-5 space-y-3 rounded-2xl bg-ink-50 p-4">
                      <input value={missionForm.titulo} onChange={(event) => setMissionForm((current) => ({ ...current, titulo: event.target.value }))} placeholder="Nome da missão" className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" />
                      <select value={missionForm.tipo} onChange={(event) => setMissionForm((current) => ({ ...current, tipo: event.target.value as AssistantMission["type"], titulo: MISSION_LABELS[event.target.value as AssistantMission["type"]] }))} className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm">
                        {Object.entries(MISSION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                      {missionForm.tipo === "billing_trend" ? <div className="grid grid-cols-2 gap-2"><input type="number" min={2} max={24} value={missionForm.months} onChange={(event) => setMissionForm((current) => ({ ...current, months: Number(event.target.value) || 5 }))} className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /><input value={missionForm.clinic} onChange={(event) => setMissionForm((current) => ({ ...current, clinic: event.target.value }))} placeholder="Clínica opcional" className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /></div> : null}
                      {missionForm.tipo === "overdue_debts" || missionForm.tipo === "clinic_360" ? <input value={missionForm.clinic} onChange={(event) => setMissionForm((current) => ({ ...current, clinic: event.target.value }))} placeholder="Clínica obrigatória" className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /> : null}
                      <div className="grid grid-cols-2 gap-2"><select value={missionForm.recorrencia} onChange={(event) => setMissionForm((current) => ({ ...current, recorrencia: event.target.value as AssistantMission["recurrence"] }))} className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm"><option value="daily">Todos os dias</option><option value="weekly">Semanal</option></select><input type="time" value={missionForm.horario_local} onChange={(event) => setMissionForm((current) => ({ ...current, horario_local: event.target.value }))} className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /></div>
                      {missionForm.recorrencia === "weekly" ? <div className="flex flex-wrap gap-1.5">{WEEKDAY_LABELS.map((label, index) => <button key={label} type="button" onClick={() => setMissionForm((current) => ({ ...current, dias_semana: current.dias_semana.includes(index) ? current.dias_semana.filter((day) => day !== index) : [...current.dias_semana, index] }))} className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold ${missionForm.dias_semana.includes(index) ? "bg-ink-900 text-white" : "bg-white text-ink-500"}`}>{label}</button>)}</div> : null}
                      <button type="button" onClick={() => void submitMission()} disabled={autonomyAction === "create-mission" || (["overdue_debts", "clinic_360"] as AssistantMission["type"][]).includes(missionForm.tipo) && !missionForm.clinic.trim()} className="flex w-full items-center justify-center gap-2 rounded-xl bg-cordis-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{autonomyAction === "create-mission" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Criar missão</button>
                    </div>
                  </div>
                  <div className="space-y-3">
                    {missions.map((mission) => {
                      const recentExecution = executions.find((item) => item.mission_id === mission.id);
                      return <article key={mission.id} className="rounded-2xl border border-ink-100 p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-ink-900">{mission.title}</p><p className="mt-1 text-xs text-ink-400">{MISSION_LABELS[mission.type]} · {mission.recurrence === "daily" ? "diária" : `semanal (${mission.weekdays.map((day) => WEEKDAY_LABELS[day]).join(", ")})`} às {mission.local_time}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${mission.enabled ? "bg-vital-50 text-vital-700" : "bg-ink-50 text-ink-500"}`}>{mission.enabled ? "Ativa" : "Pausada"}</span></div><div className="mt-4 grid gap-2 text-xs text-ink-500 sm:grid-cols-2"><p>Próxima: {mission.enabled ? formatDateTime(mission.next_run_at) : "pausada"}</p><p>Última: {mission.last_run_at ? formatDateTime(mission.last_run_at) : "ainda não executada"}</p></div>{recentExecution ? <div className="mt-3 rounded-xl bg-ink-50 px-3 py-2 text-xs text-ink-600">Execução mais recente: <strong>{recentExecution.status === "completed" ? "concluída" : recentExecution.status === "error" ? "falhou" : "na fila/processando"}</strong>{recentExecution.error ? ` · ${recentExecution.error}` : ""}</div> : null}<div className="mt-4 flex justify-end gap-2"><button type="button" onClick={() => void toggleMission(mission)} disabled={autonomyAction === `toggle-${mission.id}`} className="rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-600">{mission.enabled ? "Pausar" : "Ativar"}</button><button type="button" onClick={() => void runMission(mission)} disabled={autonomyAction === `run-${mission.id}`} className="flex items-center gap-2 rounded-lg bg-ink-900 px-3 py-2 text-xs font-semibold text-white">{autonomyAction === `run-${mission.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Executar agora</button></div></article>;
                    })}
                    {missions.length === 0 ? <div className="rounded-2xl bg-ink-50 p-5 text-sm text-ink-500">Nenhuma missão criada. Comece pelo Radar diário da gestão.</div> : null}
                  </div>
                </div>
              ) : null}

              {view === "approvals" ? (
                <div><h2 className="text-2xl font-bold text-ink-900">Caixa central de aprovações</h2><p className="mt-1 text-sm text-ink-500">Todas as ações propostas pela Mente, independentemente da conversa.</p><div className="mt-6 space-y-4">{approvalInbox.length === 0 ? <div className="rounded-2xl bg-vital-50 p-5 text-sm text-vital-800">Nenhuma ação aguardando sua decisão.</div> : approvalInbox.map((action) => <div key={action.id} className="rounded-2xl border border-amber-200 bg-amber-50/50 p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-ink-900">{action.type.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-ink-500">Expira em {formatDateTime(action.expires_at)}</p></div><span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">Requer confirmação</span></div><pre className="mt-4 max-h-52 overflow-auto whitespace-pre-wrap rounded-xl bg-white p-4 text-xs leading-5 text-ink-600">{JSON.stringify(action.target, null, 2)}</pre><div className="mt-4 flex justify-end gap-2"><button type="button" onClick={() => void decideAction(action.id, "reject")} className="rounded-xl border border-ink-200 bg-white px-4 py-2 text-sm font-semibold text-ink-700">Rejeitar</button><button type="button" onClick={() => void decideAction(action.id, "approve")} className="rounded-xl bg-cordis-600 px-4 py-2 text-sm font-semibold text-white">Confirmar ação</button></div></div>)}</div></div>
              ) : null}

              {view === "learning" ? (
                <div className="space-y-7">
                  <div className="flex items-start gap-3">
                    <Lightbulb className="h-7 w-7 text-amber-500" />
                    <div>
                      <h2 className="text-2xl font-bold text-ink-900">Aprendizado contínuo supervisionado</h2>
                      <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-500">Correções e novas regras entram como sugestões. A memória ativa só muda depois da sua aprovação, com versão e regressão automática.</p>
                    </div>
                  </div>
                  <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
                    <div className="space-y-3 rounded-2xl bg-ink-50 p-4">
                      <p className="text-sm font-semibold text-ink-800">Propor aprendizado</p>
                      <select value={memoryForm.memoria_alvo_id} onChange={(event) => setMemoryForm((current) => ({ ...current, memoria_alvo_id: event.target.value }))} className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm">
                        <option value="">Criar uma nova memória</option>
                        {memories.filter((memory) => memory.status === "approved").map((memory) => <option key={memory.id} value={memory.id}>Ajustar: {memory.title}</option>)}
                      </select>
                      <input value={memoryForm.titulo} onChange={(event) => setMemoryForm((current) => ({ ...current, titulo: event.target.value }))} placeholder="Título da regra ou preferência" className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" />
                      <input value={memoryForm.categoria} onChange={(event) => setMemoryForm((current) => ({ ...current, categoria: event.target.value }))} placeholder="Categoria" className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" />
                      <textarea value={memoryForm.conteudo} onChange={(event) => setMemoryForm((current) => ({ ...current, conteudo: event.target.value }))} rows={6} placeholder="Ex.: sempre priorizamos..." className="w-full resize-y rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" />
                      <button type="button" onClick={() => void submitMemory()} className="flex w-full items-center justify-center gap-2 rounded-xl bg-cordis-600 px-4 py-2.5 text-sm font-semibold text-white"><Save className="h-4 w-4" /> Enviar para revisão</button>
                      <p className="text-xs leading-5 text-ink-400">Escopo global da gestão, sem escrita operacional e sem aplicação automática.</p>
                    </div>
                    <div className="space-y-4">
                      <div className="grid grid-cols-3 gap-3 text-center text-xs"><div className="rounded-xl bg-amber-50 p-3 text-amber-800"><strong className="block text-xl">{learningCounts.pending}</strong>Pendentes</div><div className="rounded-xl bg-vital-50 p-3 text-vital-800"><strong className="block text-xl">{learningCounts.approved}</strong>Aprovados</div><div className="rounded-xl bg-ink-50 p-3 text-ink-600"><strong className="block text-xl">{learningCounts.rejected}</strong>Rejeitados</div></div>
                      {learnings.map((learning) => {
                        const edit = learningEdits[learning.id] || { titulo: learning.title, conteudo: learning.content, categoria: learning.category };
                        return <article key={learning.id} className={`rounded-2xl border p-4 ${learning.status === "pending" ? "border-amber-200 bg-amber-50/30" : "border-ink-100"}`}>
                          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-ink-400">{learning.source === "feedback" ? "Correção a partir de feedback" : learning.target_memory_id ? "Ajuste de memória" : "Nova memória"}</p><p className="mt-1 text-xs text-ink-400">{formatDateTime(learning.created_at)}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${learning.status === "approved" ? "bg-vital-50 text-vital-700" : learning.status === "pending" ? "bg-amber-100 text-amber-800" : "bg-ink-100 text-ink-600"}`}>{learning.status === "approved" ? "Aprovado" : learning.status === "pending" ? "Aguardando você" : "Rejeitado"}</span></div>
                          {learning.status === "pending" ? <div className="mt-4 space-y-3"><input value={edit.titulo} onChange={(event) => setLearningEdits((current) => ({ ...current, [learning.id]: { ...edit, titulo: event.target.value } }))} className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm font-semibold" /><div className="grid gap-2 sm:grid-cols-[160px_1fr]"><input value={edit.categoria} onChange={(event) => setLearningEdits((current) => ({ ...current, [learning.id]: { ...edit, categoria: event.target.value } }))} className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /><textarea value={edit.conteudo} onChange={(event) => setLearningEdits((current) => ({ ...current, [learning.id]: { ...edit, conteudo: event.target.value } }))} rows={4} className="resize-y rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm leading-6" /></div>{learning.source_context?.user_request ? <details className="rounded-xl bg-white p-3 text-xs text-ink-500"><summary className="cursor-pointer font-semibold">Ver solicitação e resposta que originaram a correção</summary><p className="mt-2"><strong>Solicitação:</strong> {learning.source_context.user_request}</p><p className="mt-2"><strong>Resposta:</strong> {learning.source_context.assistant_response}</p></details> : null}<div className="flex justify-end gap-2"><button type="button" onClick={() => void decideLearning(learning, "reject")} disabled={autonomyAction === `learning-${learning.id}`} className="rounded-lg border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-600">Rejeitar</button><button type="button" onClick={() => void decideLearning(learning, "approve")} disabled={autonomyAction === `learning-${learning.id}`} className="rounded-lg bg-vital-600 px-3 py-2 text-xs font-semibold text-white">Aprovar e versionar</button></div></div> : <><p className="mt-3 font-semibold text-ink-900">{learning.title}</p><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-600">{learning.content}</p></>}
                        </article>;
                      })}
                      {learnings.length === 0 ? <div className="rounded-2xl bg-ink-50 p-5 text-sm text-ink-500">Nenhum aprendizado sugerido ainda.</div> : null}
                    </div>
                  </div>
                  <div><h3 className="flex items-center gap-2 font-semibold text-ink-900"><FlaskConical className="h-4 w-4 text-cordis-600" /> Contratos de regressão ativos</h3><div className="mt-3 grid gap-3 lg:grid-cols-2">{regressionCases.map((item) => <div key={item.id} className="rounded-xl border border-ink-100 p-3 text-xs text-ink-600"><div className="flex items-start justify-between gap-2"><strong>{item.prompt}</strong><span className={`rounded-full px-2 py-0.5 font-semibold ${item.last_status === "failed" ? "bg-cordis-50 text-cordis-700" : item.last_status === "passed" ? "bg-vital-50 text-vital-700" : "bg-ink-50 text-ink-500"}`}>{item.last_status === "passed" ? "Passou" : item.last_status === "failed" ? "Falhou" : "Ainda não executado"}</span></div><p className="mt-2 text-ink-400">Memória v{item.expectation.version || "?"}{item.verified_at ? ` · verificada ${formatDateTime(item.verified_at)}` : ""}</p></div>)}{regressionCases.length === 0 ? <p className="text-sm text-ink-400">Os contratos aparecem após o primeiro aprendizado aprovado.</p> : null}</div></div>
                </div>
              ) : null}

              {view === "memory" ? (
                <div><div className="flex items-start gap-3"><BrainCircuit className="h-7 w-7 text-cordis-600" /><div><h2 className="text-2xl font-bold text-ink-900">Memória ativa e versionada</h2><p className="mt-1 text-sm leading-6 text-ink-500">Somente conteúdos aprovados orientam a Mente. Cada alteração preserva o histórico e pode ser revertida.</p></div></div><div className="mt-6 space-y-3">{memories.map((memory) => <article key={memory.id} className="rounded-2xl border border-ink-100 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-ink-900">{memory.title}</p><p className="mt-1 text-xs text-ink-400">{memory.category} · origem {memory.source} · versão {memory.current_version || 1}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${memory.status === "approved" ? "bg-vital-50 text-vital-700" : memory.status === "pending" ? "bg-amber-50 text-amber-800" : "bg-ink-50 text-ink-500"}`}>{memory.status === "approved" ? "Ativa" : memory.status === "pending" ? "Legado aguardando revisão" : "Rejeitada"}</span></div><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink-600">{memory.content}</p><div className="mt-4 flex flex-wrap justify-end gap-2">{memory.status === "pending" ? <><button type="button" onClick={() => void decideMemory(memory.id, "reject")} className="rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-600">Rejeitar</button><button type="button" onClick={() => void decideMemory(memory.id, "approve")} className="rounded-lg bg-vital-600 px-3 py-2 text-xs font-semibold text-white">Aprovar legado</button></> : <><button type="button" onClick={() => proposeMemoryAdjustment(memory)} className="flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-600"><Lightbulb className="h-3.5 w-3.5" /> Propor ajuste</button><button type="button" onClick={() => void toggleMemoryVersions(memory.id)} className="flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-600"><History className="h-3.5 w-3.5" /> Histórico</button></>}</div>{expandedMemoryId === memory.id ? <div className="mt-4 space-y-2 border-t border-ink-100 pt-4">{(memoryVersions[memory.id] || []).map((version) => <div key={version.id} className="flex flex-wrap items-start justify-between gap-3 rounded-xl bg-ink-50 p-3"><div><p className="text-sm font-semibold text-ink-800">Versão {version.version} · {version.change_type === "rollback" ? "restauração" : version.change_type === "update" ? "ajuste" : "criação"}</p><p className="mt-1 max-w-2xl text-xs text-ink-500">{version.content}</p></div>{version.version !== (memory.current_version || 1) ? <button type="button" onClick={() => void rollbackMemory(memory.id, version.version)} disabled={autonomyAction === `rollback-${memory.id}-${version.version}`} className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-ink-600 shadow-sm"><RotateCcw className="h-3.5 w-3.5" /> Restaurar como nova versão</button> : <span className="rounded-full bg-vital-100 px-2 py-1 text-xs font-semibold text-vital-700">Atual</span>}</div>)}{!memoryVersions[memory.id] ? <p className="text-xs text-ink-400">Carregando histórico...</p> : null}</div> : null}</article>)}{memories.length === 0 ? <p className="text-sm text-ink-400">Nenhuma memória aprovada ainda.</p> : null}</div></div>
              ) : null}

              {view === "knowledge" ? (
                <div className="grid gap-6 lg:grid-cols-[420px_minmax(0,1fr)]"><div><h2 className="text-2xl font-bold text-ink-900">Memória semântica com fontes</h2><p className="mt-1 text-sm leading-6 text-ink-500">Adicione manuais, modelos e procedimentos. A busca híbrida combina palavras e significado, sempre citando a fonte cadastrada.</p><div className="mt-5 space-y-3 rounded-2xl bg-ink-50 p-4"><input value={documentForm.titulo} onChange={(event) => setDocumentForm((current) => ({ ...current, titulo: event.target.value }))} placeholder="Título do documento" className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /><div className="grid grid-cols-2 gap-2"><input value={documentForm.categoria} onChange={(event) => setDocumentForm((current) => ({ ...current, categoria: event.target.value }))} placeholder="Categoria" className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /><input value={documentForm.fonte} onChange={(event) => setDocumentForm((current) => ({ ...current, fonte: event.target.value }))} placeholder="Fonte recomendada" className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /></div><textarea value={documentForm.conteudo} onChange={(event) => setDocumentForm((current) => ({ ...current, conteudo: event.target.value }))} rows={12} placeholder="Cole aqui o conteúdo..." className="w-full resize-y rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm" /><label className="flex items-start gap-3 rounded-xl border border-vital-100 bg-white p-3 text-xs leading-5 text-ink-600"><input type="checkbox" checked={documentForm.indexar_semanticamente} onChange={(event) => setDocumentForm((current) => ({ ...current, indexar_semanticamente: event.target.checked }))} className="mt-1" /><span><strong className="block text-ink-800">Ativar memória semântica</strong>O texto será enviado à OpenAI apenas para gerar vetores; os vetores e os trechos permanecem no banco da FortCordis.</span></label><button type="button" onClick={() => void submitDocument()} className="flex w-full items-center justify-center gap-2 rounded-xl bg-cordis-600 px-4 py-2.5 text-sm font-semibold text-white"><Database className="h-4 w-4" /> Incluir na base</button></div></div><div className="space-y-3">{documents.map((document) => <div key={document.id} className="flex items-start gap-3 rounded-2xl border border-ink-100 p-4"><BookOpen className="mt-0.5 h-5 w-5 shrink-0 text-cordis-600" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-semibold text-ink-900">{document.title}</p><p className="mt-1 text-xs text-ink-400">{document.category}{document.source ? ` · fonte: ${document.source}` : " · fonte não informada"}</p></div><span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${document.semantic_status === "ready" ? "bg-vital-50 text-vital-700" : document.semantic_status === "error" ? "bg-cordis-50 text-cordis-700" : document.semantic_status === "queued" || document.semantic_status === "indexing" ? "bg-amber-50 text-amber-800" : "bg-ink-50 text-ink-500"}`}>{document.semantic_status === "ready" ? "Semântica pronta" : document.semantic_status === "error" ? "Falha na indexação" : document.semantic_status === "queued" ? "Na fila" : document.semantic_status === "indexing" ? "Indexando" : "Busca por palavras"}</span></div>{document.semantic_error ? <p className="mt-2 text-xs text-cordis-700">{document.semantic_error}</p> : null}{document.semantic_status !== "queued" && document.semantic_status !== "indexing" ? <button type="button" onClick={() => void reindexDocument(document.id)} disabled={autonomyAction === `index-${document.id}`} className="mt-3 flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-600 disabled:opacity-50">{autonomyAction === `index-${document.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} {document.semantic_status === "ready" ? "Reindexar" : "Ativar semântica"}</button> : null}</div></div>)}{documents.length === 0 ? <p className="text-sm text-ink-400">Nenhum documento ativo na base interna.</p> : null}</div></div>
              ) : null}

              {view === "evaluations" ? (
                <div className="space-y-6">
                  <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-3"><FlaskConical className="h-7 w-7 text-cordis-600" /><h2 className="text-2xl font-bold text-ink-900">Laboratório automático de avaliações</h2></div><p className="mt-2 max-w-2xl text-sm leading-6 text-ink-500">Executa casos versionados contra o modelo atual e mede o roteamento. As ferramentas reais nunca são chamadas durante o teste.</p></div><button type="button" onClick={() => void runEvaluation()} disabled={autonomyAction === "evaluation" || evaluationRuns.some((item) => item.status === "queued" || item.status === "running")} className="flex items-center gap-2 rounded-xl bg-cordis-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{autonomyAction === "evaluation" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Executar avaliação</button></div>
                  <div className="space-y-3">
                    {evaluationRuns.map((run) => {
                      const output = run.output as { dataset_version?: string; model?: string; total?: number; passed?: number; failed?: number; score_percent?: number; cases?: Array<{ id: string; expected_tool: string; selected_tools: string[]; passed: boolean; error?: string | null }>; safety?: string } | null | undefined;
                      return <article key={run.id} className="rounded-2xl border border-ink-100 p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-ink-900">Avaliação de {formatDateTime(run.created_at)}</p><p className="mt-1 text-xs text-ink-400">{output?.model || status?.model} · dataset {output?.dataset_version || "versionado"}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${run.status === "completed" ? "bg-vital-50 text-vital-700" : run.status === "error" ? "bg-cordis-50 text-cordis-700" : "bg-amber-50 text-amber-800"}`}>{run.status === "completed" ? "Concluída" : run.status === "error" ? "Falhou" : "Na fila/processando"}</span></div>{output ? <><div className="mt-4 grid grid-cols-3 gap-3"><div className="rounded-xl bg-ink-50 p-3"><p className="text-xs text-ink-400">Nota</p><p className="mt-1 text-xl font-bold text-ink-900">{output.score_percent ?? 0}%</p></div><div className="rounded-xl bg-vital-50 p-3"><p className="text-xs text-vital-700">Aprovados</p><p className="mt-1 text-xl font-bold text-vital-800">{output.passed ?? 0}</p></div><div className="rounded-xl bg-cordis-50 p-3"><p className="text-xs text-cordis-700">Falhas</p><p className="mt-1 text-xl font-bold text-cordis-800">{output.failed ?? 0}</p></div></div>{(output.cases || []).some((item) => !item.passed) ? <div className="mt-4 space-y-2">{(output.cases || []).filter((item) => !item.passed).map((item) => <div key={item.id} className="rounded-xl bg-cordis-50 p-3 text-xs text-cordis-800"><strong>{item.id}</strong>: esperava {item.expected_tool}; escolheu {item.selected_tools.join(", ") || "nenhuma"}{item.error ? ` · ${item.error}` : ""}</div>)}</div> : <p className="mt-4 flex items-center gap-2 text-sm font-semibold text-vital-700"><CheckCircle2 className="h-4 w-4" /> Todos os casos escolheram a ferramenta esperada.</p>}<p className="mt-4 flex items-center gap-2 text-xs text-ink-500"><ShieldCheck className="h-4 w-4 text-vital-600" /> {output.safety}</p></> : run.error ? <p className="mt-4 text-sm text-cordis-700">{run.error}</p> : <p className="mt-4 text-sm text-ink-500">Aguardando o worker seguro concluir os casos.</p>}</article>;
                    })}
                    {evaluationRuns.length === 0 ? <div className="rounded-2xl bg-ink-50 p-5 text-sm text-ink-500">Nenhuma avaliação executada. Você também pode criar uma missão semanal para este laboratório.</div> : null}
                  </div>
                </div>
              ) : null}

              {view === "clinical" ? (
                <div><div className="flex items-start gap-3"><FileHeart className="h-7 w-7 text-cordis-600" /><div><h2 className="text-2xl font-bold text-ink-900">Rascunhos clínicos assistidos</h2><p className="mt-1 text-sm text-ink-500">Conteúdo separado do laudo oficial. A finalização continua exclusivamente humana.</p></div></div><div className="mt-6 grid gap-4 lg:grid-cols-2">{clinicalDrafts.map((draft) => <article key={draft.id} className="rounded-2xl border border-ink-100 p-5"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-ink-900">{draft.title}</p><p className="mt-1 text-xs text-ink-400">Laudo #{draft.report_id} · {formatDateTime(draft.created_at)}</p></div><span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">Rascunho</span></div><p className="mt-4 max-h-48 overflow-auto whitespace-pre-wrap text-sm leading-6 text-ink-600">{draft.content}</p>{draft.alerts.length > 0 ? <div className="mt-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{draft.alerts.map((alert) => <p key={alert}>• {alert}</p>)}</div> : null}<div className="mt-4 flex items-center gap-2 text-xs font-semibold text-vital-700"><ShieldCheck className="h-4 w-4" /> Laudo oficial não modificado</div></article>)}{clinicalDrafts.length === 0 ? <div className="rounded-2xl bg-ink-50 p-5 text-sm text-ink-500">Peça na conversa: “Ajude a elaborar o laudo #...”</div> : null}</div></div>
              ) : null}
            </section>
          ) : (
          <div className="grid min-h-[680px] w-full min-w-0 grid-cols-[minmax(0,1fr)] overflow-hidden rounded-3xl border border-ink-100 bg-white shadow-fort-card lg:grid-cols-[280px_minmax(0,1fr)]">
            <aside className="min-w-0 border-b border-ink-100 bg-ink-50/60 p-4 lg:border-b-0 lg:border-r">
              <button
                type="button"
                onClick={startConversation}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-cordis-600 px-4 py-3 text-sm font-semibold text-white shadow-fort-soft transition hover:bg-cordis-700"
              >
                <Plus className="h-4 w-4" /> Nova conversa
              </button>
              <div className="mt-5 flex items-center gap-2 px-2 text-xs font-bold uppercase tracking-[0.15em] text-ink-400">
                <MessageSquare className="h-3.5 w-3.5" /> Histórico
              </div>
              <div className="mt-2 max-h-64 space-y-1 overflow-y-auto lg:max-h-[540px]">
                {conversations.length === 0 ? (
                  <p className="px-2 py-4 text-sm leading-5 text-ink-400">As conversas aparecerão aqui.</p>
                ) : (
                  conversations.map((conversation) => (
                    <button
                      type="button"
                      key={conversation.id}
                      onClick={() => void openConversation(conversation.id)}
                      className={`w-full rounded-xl px-3 py-3 text-left transition ${
                        conversationId === conversation.id
                          ? "bg-white text-ink-900 shadow-sm ring-1 ring-ink-100"
                          : "text-ink-600 hover:bg-white/70"
                      }`}
                    >
                      <span className="block truncate text-sm font-medium">{conversation.title}</span>
                      {conversation.updated_at ? (
                        <span className="mt-1 block text-xs text-ink-400">{formatDateTime(conversation.updated_at)}</span>
                      ) : null}
                    </button>
                  ))
                )}
              </div>
              <div className="mt-5 min-w-0 break-words rounded-2xl border border-vital-100 bg-vital-50 p-4 text-xs leading-5 text-vital-900">
                <div className="mb-1 flex items-center gap-2 font-semibold">
                  <ShieldCheck className="h-4 w-4" /> Controle administrativo
                </div>
                Consultas são automáticas. Alterações operacionais exigem confirmação e deixam registro de auditoria.
              </div>
            </aside>

            <section className="flex min-h-[680px] w-full min-w-0 flex-col">
              <div className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-6">
                {loadingHistory ? (
                  <div className="flex h-full items-center justify-center gap-2 text-sm text-ink-400">
                    <Loader2 className="h-5 w-5 animate-spin" /> Carregando conversa...
                  </div>
                ) : messages.length === 0 ? (
                  <div className="mx-auto flex min-h-[480px] w-full min-w-0 max-w-3xl flex-col justify-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-cordis-50 text-cordis-600">
                      <Sparkles className="h-7 w-7" />
                    </div>
                    <h2 className="mt-5 break-words text-center text-xl font-bold text-ink-900 sm:text-2xl">Como posso ajudar na gestão hoje?</h2>
                    <p className="mx-auto mt-2 max-w-xl break-words text-center text-sm leading-6 text-ink-500">
                      Comece por um destes exemplos ou escreva sua solicitação com clínica, período e serviço quando souber.
                    </p>
                    <div className="mt-7 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                      {EXAMPLES.map(({ icon: Icon, text }) => (
                        <button
                          type="button"
                          key={text}
                          onClick={() => setInput(text)}
                          className="group flex w-full min-w-0 items-start gap-3 rounded-2xl border border-ink-100 p-4 text-left text-sm leading-5 text-ink-700 transition hover:-translate-y-0.5 hover:border-cordis-200 hover:bg-cordis-50/50 hover:shadow-sm"
                        >
                          <Icon className="mt-0.5 h-5 w-5 shrink-0 text-cordis-500" />
                          <span className="min-w-0 whitespace-normal break-words">{text}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="mx-auto max-w-3xl space-y-5">
                    {messages.map((message) => (
                      <div
                        key={message.id}
                        className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-6 sm:max-w-[78%] ${
                            message.role === "user"
                              ? "rounded-br-md bg-ink-900 text-white"
                              : "rounded-bl-md border border-ink-100 bg-ink-50 text-ink-800"
                          }`}
                        >
                          <p className="whitespace-pre-wrap break-words">{message.content}</p>
                          {Array.isArray(message.tools) && message.tools.length > 0 ? (
                            <div className="mt-3 border-t border-ink-100 pt-2">
                              {message.tools.map((tool, index) => (
                                <div key={`${tool.name}-${index}`} className="flex items-center gap-2 text-xs text-ink-400">
                                  {tool.ok ? <Check className="h-3.5 w-3.5 text-vital-600" /> : <X className="h-3.5 w-3.5 text-cordis-600" />}
                                  {tool.summary}
                                </div>
                              ))}
                            </div>
                          ) : null}
                          {message.role === "assistant" && typeof message.id === "number" ? (
                            <div className="mt-3 flex items-center gap-1 border-t border-ink-100 pt-2 text-xs text-ink-400">
                              <span className="mr-1">Esta resposta ajudou?</span>
                              <button
                                type="button"
                                aria-label="Resposta útil"
                                onClick={() => void submitFeedback(message, "positive")}
                                className={`rounded-lg p-1.5 transition hover:bg-vital-50 hover:text-vital-700 ${feedbackSent[String(message.id)] === "positive" ? "bg-vital-50 text-vital-700" : ""}`}
                              >
                                <ThumbsUp className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                aria-label="Resposta precisa de correção"
                                onClick={() => void submitFeedback(message, "negative")}
                                className={`rounded-lg p-1.5 transition hover:bg-cordis-50 hover:text-cordis-700 ${feedbackSent[String(message.id)] === "negative" ? "bg-cordis-50 text-cordis-700" : ""}`}
                              >
                                <ThumbsDown className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          ) : null}
                          {typeof message.id === "number" && feedbackDraft?.messageId === message.id ? (
                            <div className="mt-3 space-y-2 rounded-xl border border-cordis-100 bg-white p-3">
                              <p className="text-xs font-semibold text-ink-800">Ensine o que deveria ser diferente</p>
                              <textarea autoFocus value={feedbackDraft.correcao} onChange={(event) => setFeedbackDraft((current) => current ? { ...current, correcao: event.target.value } : current)} rows={4} placeholder="Escreva a resposta, regra ou comportamento correto..." className="w-full resize-y rounded-lg border border-ink-200 px-3 py-2 text-xs leading-5" />
                              <div className="grid gap-2 sm:grid-cols-2"><input value={feedbackDraft.categoria} onChange={(event) => setFeedbackDraft((current) => current ? { ...current, categoria: event.target.value } : current)} placeholder="Categoria" className="rounded-lg border border-ink-200 px-3 py-2 text-xs" /><input value={feedbackDraft.comentario} onChange={(event) => setFeedbackDraft((current) => current ? { ...current, comentario: event.target.value } : current)} placeholder="Comentário opcional" className="rounded-lg border border-ink-200 px-3 py-2 text-xs" /></div>
                              <div className="flex items-center justify-between gap-3"><p className="text-[11px] leading-4 text-ink-400">Isso criará uma sugestão pendente; a Mente ainda não aprenderá até você aprovar.</p><div className="flex shrink-0 gap-2"><button type="button" onClick={() => setFeedbackDraft(null)} className="rounded-lg px-3 py-2 text-xs font-semibold text-ink-500">Cancelar</button><button type="button" onClick={() => void submitCorrection()} disabled={!feedbackDraft.correcao.trim()} className="rounded-lg bg-cordis-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">Criar sugestão</button></div></div>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))}

                    {pendingActions.map((action) => {
                      const badge = actionStatus(action);
                      const BadgeIcon = badge.Icon;
                      const isDeciding = decidingActionId === action.id;
                      const isCreation = action.type === "create_appointment";
                      const isAgendaException = action.type === "update_agenda_exception";
                      const isDelete = action.type === "delete_appointment";
                      const isNewOperational = !isCreation && !isAgendaException && !isDelete;
                      const isReservation = action.target.tipo === "reserva" || action.arguments.tipo === "reserva";
                      const actionTitles: Record<string, string> = {
                        reschedule_appointment: "Remarcação de agendamento",
                        cancel_appointment: "Cancelamento de agendamento",
                        create_agenda_block: "Bloqueio de slot da agenda",
                        release_agenda_block: "Liberação de bloqueio",
                        update_clinic_whatsapps: "Atualização de WhatsApps da clínica",
                        attach_patient_to_reservation: "Vincular paciente à reserva",
                      };
                      const ActionIcon = isAgendaException ? CalendarClock : isCreation ? CalendarPlus : isDelete ? Trash2 : ShieldCheck;
                      const communication = action.result?.comunicacao;
                      const phones = Array.isArray(communication?.telefones)
                        ? communication.telefones.filter(Boolean)
                        : [];
                      const selectedPhone = selectedWhatsapps[action.id] || phones[0] || "";
                      return (
                        <div key={action.id} className="rounded-2xl border border-amber-200 bg-amber-50/60 p-5 shadow-sm">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                              <p className="flex items-center gap-2 font-semibold text-ink-900">
                                <ActionIcon className="h-4 w-4 text-cordis-600" />
                                {isAgendaException
                                  ? "Funcionamento excepcional da agenda"
                                  : isCreation
                                    ? isReservation ? "Reserva de horário" : "Novo agendamento"
                                    : isDelete ? "Exclusão de agendamento" : actionTitles[action.type] || "Ação operacional"}
                              </p>
                              <p className="mt-1 text-sm text-ink-500">Esta ação não é executada sem a sua decisão.</p>
                            </div>
                            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${badge.className}`}>
                              <BadgeIcon className="h-3.5 w-3.5" /> {badge.label}
                            </span>
                          </div>
                          <dl className="mt-4 grid gap-3 rounded-xl bg-white p-4 text-sm sm:grid-cols-2">
                            {isNewOperational ? (
                              <div className="sm:col-span-2">
                                <dt className="text-xs text-ink-400">Alteração preparada</dt>
                                <dd><pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-ink-50 p-3 text-xs leading-5 text-ink-700">{JSON.stringify(action.target, null, 2)}</pre></dd>
                              </div>
                            ) : isAgendaException ? (
                              <>
                                <div><dt className="text-xs text-ink-400">Data</dt><dd className="font-medium text-ink-800">{formatDateOnly(action.target.data)}</dd></div>
                                <div><dt className="text-xs text-ink-400">Origem atual</dt><dd className="font-medium text-ink-800">{action.target.antes?.fonte === "excecao" ? "Exceção existente" : action.target.antes?.fonte === "feriado" ? "Feriado" : "Rotina semanal"}</dd></div>
                                <div><dt className="text-xs text-ink-400">Funcionamento atual</dt><dd className="font-medium text-ink-800">{formatAgendaWindow(action.target.antes)}</dd></div>
                                <div><dt className="text-xs text-ink-400">Após confirmar</dt><dd className="font-medium text-ink-800">{formatAgendaWindow(action.target.depois)}</dd></div>
                                <div className="sm:col-span-2"><dt className="text-xs text-ink-400">Motivo</dt><dd className="font-medium text-ink-800">{action.target.motivo || "Ajuste solicitado pelo administrador"}</dd></div>
                              </>
                            ) : (
                              <>
                                <div><dt className="text-xs text-ink-400">Clínica</dt><dd className="font-medium text-ink-800">{action.target.clinica_nome || "Não informada"}</dd></div>
                                <div><dt className="text-xs text-ink-400">Data e hora</dt><dd className="font-medium text-ink-800">{formatDateTime(action.target.inicio)}</dd></div>
                                <div><dt className="text-xs text-ink-400">Serviço</dt><dd className="font-medium text-ink-800">{action.target.servico_nome || "Não informado"}</dd></div>
                                <div><dt className="text-xs text-ink-400">Paciente</dt><dd className="font-medium text-ink-800">{action.target.paciente_nome || action.target.paciente_primeiro_nome || (isReservation ? "Pendente" : "Não informado")}</dd></div>
                                {isCreation ? (
                                  <>
                                    <div><dt className="text-xs text-ink-400">Tutor</dt><dd className="font-medium text-ink-800">{action.target.tutor_nome || "Pendente"}</dd></div>
                                    <div><dt className="text-xs text-ink-400">Mensagem para</dt><dd className="font-medium text-ink-800">{action.target.destinatario_mensagem?.nome || "Não informado"}</dd></div>
                                    {isReservation ? (
                                      <div className="sm:col-span-2"><dt className="text-xs text-ink-400">Prazo de confirmação</dt><dd className="font-medium text-ink-800">{formatDateTime(action.target.reserva_expira_em)}</dd></div>
                                    ) : null}
                                    {action.arguments.observacoes ? (
                                      <div className="sm:col-span-2"><dt className="text-xs text-ink-400">Observações</dt><dd className="font-medium text-ink-800">{action.arguments.observacoes}</dd></div>
                                    ) : null}
                                  </>
                                ) : (
                                  <div className="sm:col-span-2"><dt className="text-xs text-ink-400">Motivo</dt><dd className="font-medium text-ink-800">{action.arguments.motivo || "Não informado"}</dd></div>
                                )}
                              </>
                            )}
                          </dl>
                          {action.status === "pending" ? (
                            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
                              <button
                                type="button"
                                disabled={isDeciding}
                                onClick={() => void decideAction(action.id, "reject")}
                                className="rounded-xl border border-ink-200 bg-white px-4 py-2.5 text-sm font-semibold text-ink-700 transition hover:bg-ink-50 disabled:opacity-60"
                              >
                                Rejeitar
                              </button>
                              <button
                                type="button"
                                disabled={isDeciding}
                                onClick={() => void decideAction(action.id, "approve")}
                                className="flex items-center justify-center gap-2 rounded-xl bg-cordis-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-cordis-700 disabled:opacity-60"
                              >
                                {isDeciding ? <Loader2 className="h-4 w-4 animate-spin" /> : <ActionIcon className="h-4 w-4" />}
                                {isAgendaException
                                  ? "Confirmar funcionamento"
                                  : isCreation
                                    ? isReservation ? "Confirmar reserva" : "Confirmar agendamento"
                                    : isDelete ? "Confirmar exclusão" : "Confirmar ação"}
                              </button>
                            </div>
                          ) : null}
                          {action.status === "executed" && action.result?.message ? (
                            <div className="mt-4 flex items-start gap-2 rounded-xl border border-vital-100 bg-vital-50 p-3 text-sm text-vital-800">
                              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                              <span>{action.result.message}{action.result.agendamento?.id ? ` Código #${action.result.agendamento.id}.` : ""}</span>
                            </div>
                          ) : null}
                          {action.status === "executed" && communication?.mensagem ? (
                            <div className="mt-4 rounded-xl border border-emerald-100 bg-white p-4">
                              <div className="flex items-start gap-3">
                                <MessageCircle className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
                                <div className="min-w-0 flex-1">
                                  <p className="text-sm font-semibold text-ink-900">Mensagem pronta para envio manual</p>
                                  <p className="mt-1 text-xs text-ink-500">
                                    {communication.destinatario_nome || "Destinatário"}
                                    {phones.length > 0 ? ` · ${phones.map(formatarWhatsAppVisual).join(" / ")}` : " · sem WhatsApp cadastrado"}
                                  </p>
                                </div>
                              </div>
                              <pre className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg bg-ink-50 p-3 font-sans text-xs leading-5 text-ink-700">
                                {communication.mensagem}
                              </pre>
                              {phones.length > 1 ? (
                                <label className="mt-3 block text-xs font-medium text-ink-600">
                                  Número para abrir
                                  <select
                                    value={selectedPhone}
                                    onChange={(event) => setSelectedWhatsapps((current) => ({ ...current, [action.id]: event.target.value }))}
                                    className="mt-1 w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-800 outline-none focus:border-cordis-300"
                                  >
                                    {phones.map((phone) => (
                                      <option key={phone} value={phone}>{formatarWhatsAppVisual(phone)}</option>
                                    ))}
                                  </select>
                                </label>
                              ) : null}
                              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:justify-end">
                                <button
                                  type="button"
                                  onClick={() => void copyCommunication(action)}
                                  className="flex items-center justify-center gap-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm font-semibold text-ink-700 transition hover:bg-ink-50"
                                >
                                  {copiedActionId === action.id ? <Check className="h-4 w-4 text-vital-600" /> : <Copy className="h-4 w-4" />}
                                  {copiedActionId === action.id ? "Copiada" : "Copiar mensagem"}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => openWhatsApp(action)}
                                  className="flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700"
                                >
                                  <ExternalLink className="h-4 w-4" /> Abrir WhatsApp
                                </button>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}

                    {loading ? (
                      <div className="flex items-center gap-3 text-sm text-ink-400">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-vital-50 text-vital-600">
                          <Loader2 className="h-4 w-4 animate-spin" />
                        </div>
                        Consultando as ferramentas do FortCordis...
                      </div>
                    ) : null}
                    <div ref={bottomRef} />
                  </div>
                )}
              </div>

              <div className="border-t border-ink-100 bg-white p-4 sm:p-5">
                {error ? (
                  <div className="mb-3 flex items-start gap-2 rounded-xl bg-cordis-50 px-3 py-2 text-sm text-cordis-700">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
                  </div>
                ) : null}
                <div className="mx-auto max-w-3xl">
                  <div className="flex items-end gap-2 rounded-2xl border border-ink-200 bg-white p-2 shadow-sm focus-within:border-cordis-300 focus-within:ring-4 focus-within:ring-cordis-50">
                    <button
                      type="button"
                      onClick={() => {
                        if (voiceState === "recording") stopVoiceRecording();
                        else void startVoiceRecording();
                      }}
                      disabled={!assistantReady || loading || voiceState === "transcribing" || !voiceSupported}
                      aria-label={voiceState === "recording" ? "Parar gravação e transcrever" : "Gravar comando de voz"}
                      title={voiceSupported ? "Gravar comando de voz" : "Comandos de voz não são suportados neste navegador"}
                      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition disabled:cursor-not-allowed disabled:bg-ink-100 disabled:text-ink-300 ${
                        voiceState === "recording"
                          ? "animate-pulse bg-red-600 text-white hover:bg-red-700"
                          : "bg-vital-50 text-vital-700 hover:bg-vital-100"
                      }`}
                    >
                      {voiceState === "transcribing"
                        ? <Loader2 className="h-5 w-5 animate-spin" />
                        : voiceState === "recording"
                          ? <Square className="h-4 w-4 fill-current" />
                          : <Mic className="h-5 w-5" />}
                    </button>
                    <textarea
                      value={input}
                      onChange={(event) => setInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey) {
                          event.preventDefault();
                          void sendMessage();
                        }
                      }}
                      rows={2}
                      disabled={!assistantReady || loading}
                      placeholder="Ex.: analise o faturamento dos últimos cinco meses..."
                      className="max-h-40 min-h-[48px] min-w-0 flex-1 resize-none border-0 bg-transparent px-3 py-2 text-sm text-ink-900 outline-none placeholder:text-ink-400 disabled:cursor-not-allowed"
                    />
                    <button
                      type="button"
                      onClick={() => void sendMessage()}
                      disabled={!input.trim() || !assistantReady || loading}
                      aria-label="Enviar mensagem"
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cordis-600 text-white transition hover:bg-cordis-700 disabled:cursor-not-allowed disabled:bg-ink-200"
                    >
                      {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
                    </button>
                  </div>
                  {voiceNotice ? (
                    <p
                      role="status"
                      className={`mt-2 text-center text-xs font-medium ${
                        voiceState === "recording" ? "text-red-700" : "text-vital-700"
                      }`}
                    >
                      {voiceNotice}
                    </p>
                  ) : null}
                  <p className="mt-2 text-center text-[11px] leading-4 text-ink-400">
                    A voz apenas transcreve o pedido e não guarda o áudio. Use a tela somente quando for seguro; ações reais continuam exigindo sua confirmação.
                  </p>
                </div>
              </div>
            </section>
          </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
