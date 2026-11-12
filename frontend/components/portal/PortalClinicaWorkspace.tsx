"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Building2,
  CalendarDays,
  CheckCircle2,
  Download,
  FileCheck2,
  Filter,
  KeyRound,
  LayoutDashboard,
  Loader2,
  LogOut,
  Mail,
  PawPrint,
  RefreshCcw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Stethoscope,
  Users,
  Wallet,
  X,
  XCircle,
} from "lucide-react";

import {
  cancelPortalClinicAgendamento,
  changeClinicPortalPassword,
  createPortalAdminClinicExamDownloadUrls,
  clearPortalSession,
  createPortalExamDownloadUrls,
  downloadPortalAttachment,
  downloadPortalClinicOSRecibo,
  endPortalDeviceTrust,
  getPortalClinicFinanceiro,
  listPortalAdminClinicMirrorExams,
  listPortalClinicAgendamentos,
  listPortalClinicExams,
  loadPortalSession,
  loginClinicPortal,
  logoutClinicPortal,
  portalSessionHasClinicRead,
  refreshClinicPortalSession,
  requestClinicPasswordReset,
  savePortalSession,
  verifyClinicPortalMfa,
  type PortalClinicAuthResponse,
  type PortalClinicaAgendamentoItem,
  type PortalClinicaFinanceiroResponse,
  type PortalClinicaOrdemServicoItem,
  type PortalClinicExamFilters,
  type PortalClinicOperationalItem,
  type PortalClinicOperationalSummary,
  type PortalExamItem,
  type PortalSessionResponse,
} from "@/lib/portal-api";
import { formatPortalDate, formatPortalDateTime, portalDateTimeMillis } from "@/lib/portal-datetime";
import { formatCalendarDate } from "@/lib/calendar-date";

type PortalClinicaWorkspaceProps = {
  mode?: "embedded" | "standalone" | "admin_preview";
  initialSession?: PortalSessionResponse | null;
  onSessionChange?: (session: PortalSessionResponse | null) => void;
  /**
   * Abre o formulario de senha sem encerrar a confianca do computador (RF-019).
   *
   * Quem monta o shell decide como mostrar o formulario; o workspace so avisa que
   * alguem pediu. Sem isso, a unica saida do modo laudos era "Sair deste
   * computador", que revoga a confianca - o gestor precisava derrubar a recepcao
   * para ver o financeiro.
   */
  onPedirLoginPorSenha?: () => void;
  adminPreview?: {
    clinicaId: number;
    clinicaNome?: string | null;
    backHref?: string;
  } | null;
};

type ClinicSortBy = NonNullable<PortalClinicExamFilters["sort_by"]>;
type ClinicSortDir = NonNullable<PortalClinicExamFilters["sort_dir"]>;

type ClinicExamFiltersState = {
  q: string;
  pet: string;
  tutor: string;
  especie: string;
  tipo_exame: string;
  status_exame: string;
  data_inicio: string;
  data_fim: string;
  sort_by: ClinicSortBy;
  sort_dir: ClinicSortDir;
};

const INITIAL_FILTERS: ClinicExamFiltersState = {
  q: "",
  pet: "",
  tutor: "",
  especie: "",
  tipo_exame: "",
  status_exame: "",
  data_inicio: "",
  data_fim: "",
  sort_by: "data",
  sort_dir: "desc",
};

const EMPTY_OPERATIONAL_SUMMARY: PortalClinicOperationalSummary = {
  realizados_hoje: 0,
  em_laudo: 0,
  aguardando_liberacao: 0,
  liberados_hoje: 0,
  sla_horas: 48,
};

const OPERATIONAL_STATUS_LABELS: Record<string, string> = {
  liberado_portal: "Liberado no portal",
  aguardando_liberacao: "Aguardando liberação",
  em_laudo: "Em laudo",
  em_andamento: "Em andamento",
};

type PortalTabId = "visao-geral" | "laudos" | "agenda" | "financeiro";

const PORTAL_TABS: { id: PortalTabId; label: string; somenteSessaoReal: boolean }[] = [
  { id: "visao-geral", label: "Visão geral", somenteSessaoReal: false },
  { id: "laudos", label: "Laudos", somenteSessaoReal: false },
  { id: "agenda", label: "Agenda", somenteSessaoReal: true },
  { id: "financeiro", label: "Financeiro", somenteSessaoReal: true },
];

function operationalStatusClasses(statusKey: string): string {
  switch (statusKey) {
    case "liberado_portal":
      return "bg-teal-50 text-teal-800";
    case "aguardando_liberacao":
      return "bg-amber-50 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function formatCurrencyBRL(value: number): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

function formatFileSize(value: number | null): string {
  if (!value || value <= 0) {
    return "-";
  }
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${value} B`;
}

function normalizeClinicSession(payload: PortalClinicAuthResponse): PortalSessionResponse {
  if (!payload.access_token || !payload.expires_at || payload.actor_type !== "clinica" || !payload.actor_id) {
    throw new Error("Sessão da clínica retornou incompleta.");
  }
  return {
    access_token: payload.access_token,
    token_type: payload.token_type || "bearer",
    expires_at: payload.expires_at,
    actor_type: "clinica",
    actor_id: payload.actor_id,
    clinica_id: payload.clinica_id ?? payload.actor_id,
    paciente_id: null,
    account_id: payload.account_id ?? null,
    auth_method: payload.auth_method ?? null,
    trusted_session_expires_at: payload.trusted_session_expires_at ?? null,
    scope: payload.scope || [],
    message: payload.message ?? null,
  };
}

function examDateValue(exam: PortalExamItem): string | null {
  return exam.data_exame || exam.data_solicitacao || exam.data_resultado || null;
}

function examExecutionDateValue(exam: PortalExamItem): string | null {
  return exam.data_exame || exam.data_solicitacao || null;
}

function compactFilters(filters: ClinicExamFiltersState): PortalClinicExamFilters {
  return {
    q: filters.q.trim() || undefined,
    pet: filters.pet.trim() || undefined,
    tutor: filters.tutor.trim() || undefined,
    especie: filters.especie.trim() || undefined,
    tipo_exame: filters.tipo_exame.trim() || undefined,
    status_exame: filters.status_exame.trim() || undefined,
    data_inicio: filters.data_inicio || undefined,
    data_fim: filters.data_fim || undefined,
    sort_by: filters.sort_by,
    sort_dir: filters.sort_dir,
    limit: 100,
  };
}

export default function PortalClinicaWorkspace({
  mode = "embedded",
  initialSession = null,
  onSessionChange,
  onPedirLoginPorSenha,
  adminPreview = null,
}: PortalClinicaWorkspaceProps) {
  const isAdminPreview = mode === "admin_preview";
  const previewClinicId = adminPreview?.clinicaId ?? null;
  const [bootstrapping, setBootstrapping] = useState(() => (isAdminPreview ? false : !initialSession));
  const [session, setSession] = useState<PortalSessionResponse | null>(initialSession);
  // Modo laudos (computador confiavel da recepcao) nao carrega `clinic:read`:
  // agenda e financeiro somem por completo, em vez de aparecerem desabilitados -
  // desabilitado sugeriria que basta insistir. O backend confere de todo jeito
  // (docs/specs/portal-escopo-sessao-clinica/); aqui e so nao prometer o que nao ha.
  const temClinicRead = isAdminPreview || portalSessionHasClinicRead(session);
  const modoLaudos = !isAdminPreview && session !== null && !temClinicRead;
  const [encerrandoDispositivo, setEncerrandoDispositivo] = useState(false);
  const [mfaChallengeId, setMfaChallengeId] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberDevice, setRememberDevice] = useState(true);
  const [mfaCode, setMfaCode] = useState("");
  const [showForgotPassword, setShowForgotPassword] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [filters, setFilters] = useState<ClinicExamFiltersState>(INITIAL_FILTERS);
  const [requestLoading, setRequestLoading] = useState(false);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [downloadingAttachmentId, setDownloadingAttachmentId] = useState<number | null>(null);
  const [exams, setExams] = useState<PortalExamItem[]>([]);
  const [operationalSummary, setOperationalSummary] = useState<PortalClinicOperationalSummary>(
    EMPTY_OPERATIONAL_SUMMARY,
  );
  const [operationalItems, setOperationalItems] = useState<PortalClinicOperationalItem[]>([]);
  const [operationalPendingItems, setOperationalPendingItems] = useState<PortalClinicOperationalItem[]>([]);
  const [agendamentos, setAgendamentos] = useState<PortalClinicaAgendamentoItem[]>([]);
  const [agendamentosLoading, setAgendamentosLoading] = useState(false);
  const [agendamentosError, setAgendamentosError] = useState("");
  const [agendamentosMessage, setAgendamentosMessage] = useState("");
  const [confirmandoCancelamentoId, setConfirmandoCancelamentoId] = useState<number | null>(null);
  const [cancelandoId, setCancelandoId] = useState<number | null>(null);
  const [financeiro, setFinanceiro] = useState<PortalClinicaFinanceiroResponse | null>(null);
  const [financeiroLoading, setFinanceiroLoading] = useState(false);
  const [financeiroError, setFinanceiroError] = useState("");
  const [baixandoReciboId, setBaixandoReciboId] = useState<number | null>(null);
  const [clinicName, setClinicName] = useState<string | null>(null);
  const [totalAvailable, setTotalAvailable] = useState(0);
  const [dashboardLoaded, setDashboardLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [abaAtiva, setAbaAtiva] = useState<PortalTabId>("visao-geral");
  const [agendamentosSolicitados, setAgendamentosSolicitados] = useState(false);
  const [financeiroSolicitado, setFinanceiroSolicitado] = useState(false);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [mustChangePasswordDismissed, setMustChangePasswordDismissed] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [senhaAtualInput, setSenhaAtualInput] = useState("");
  const [novaSenhaInput, setNovaSenhaInput] = useState("");
  const [novaSenhaConfirmacaoInput, setNovaSenhaConfirmacaoInput] = useState("");
  const [passwordChangeLoading, setPasswordChangeLoading] = useState(false);
  const [passwordChangeError, setPasswordChangeError] = useState("");
  const previewSession = useMemo<PortalSessionResponse | null>(() => {
    if (!isAdminPreview || !previewClinicId) {
      return null;
    }
    return {
      access_token: "__admin_preview__",
      token_type: "preview",
      expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
      actor_type: "clinica",
      actor_id: previewClinicId,
      clinica_id: previewClinicId,
      paciente_id: null,
      account_id: null,
      auth_method: "admin_preview",
      trusted_session_expires_at: null,
      scope: ["clinic:read", "exam:read", "exam:download"],
      message: null,
    };
  }, [isAdminPreview, previewClinicId]);
  const activeSession = previewSession ?? session;

  const dashboardStats = useMemo(() => {
    const petIds = new Set(exams.map((exam) => exam.paciente_id));
    const attachments = exams.reduce(
      (total, exam) => total + exam.anexos.filter((attachment) => attachment.download_available).length,
      0,
    );
    const latestTimestamp = exams
      .map((exam) => portalDateTimeMillis(examDateValue(exam)))
      .filter((value) => Number.isFinite(value))
      .sort((a, b) => b - a)[0];

    return {
      totalExams: totalAvailable,
      visibleExams: exams.length,
      pets: petIds.size,
      attachments,
      latestDate: latestTimestamp ? formatPortalDate(new Date(latestTimestamp).toISOString()) : "-",
    };
  }, [exams, totalAvailable]);

  async function hydrateClinicSession() {
    const storedSession = loadPortalSession("clinica");
    if (storedSession) {
      setSession(storedSession);
      setBootstrapping(false);
      return;
    }

    try {
      const refreshed = normalizeClinicSession(await refreshClinicPortalSession());
      savePortalSession(refreshed);
      setSession(refreshed);
      setMessage(refreshed.message || "Sessão da clínica restaurada neste computador.");
    } catch {
      clearPortalSession("clinica");
    } finally {
      setBootstrapping(false);
    }
  }

  async function ensureClinicSession(currentSession: PortalSessionResponse | null): Promise<PortalSessionResponse> {
    if (currentSession && portalDateTimeMillis(currentSession.expires_at) > Date.now() + 30_000) {
      return currentSession;
    }

    const refreshed = normalizeClinicSession(await refreshClinicPortalSession());
    savePortalSession(refreshed);
    setSession(refreshed);
    return refreshed;
  }

  async function loadDashboard(
    nextFilters: ClinicExamFiltersState = filters,
    currentSession: PortalSessionResponse | null = session,
  ) {
    setSearchLoading(true);
    setError("");
    setMessage("");

    try {
      let response;
      if (isAdminPreview) {
        if (!previewClinicId) {
          throw new Error("Selecione a clinica que deseja espelhar.");
        }
        response = await listPortalAdminClinicMirrorExams(previewClinicId, compactFilters(nextFilters));
      } else {
        if (!currentSession) {
          throw new Error("Nao foi possivel identificar a sessao da clinica.");
        }
        const usableSession = await ensureClinicSession(currentSession);
        response = await listPortalClinicExams(compactFilters(nextFilters), usableSession.access_token);
      }
      setExams(response.items);
      setOperationalSummary(response.operational_summary ?? EMPTY_OPERATIONAL_SUMMARY);
      setOperationalItems(response.operational_items ?? []);
      const pendingItems = response.operational_pending_items ?? [];
      setOperationalPendingItems(pendingItems);
      if (
        response.operational_summary &&
        pendingItems.length !== response.operational_summary.aguardando_liberacao
      ) {
        console.warn(
          "Portal da clinica: operational_pending_items diverge de operational_summary.aguardando_liberacao",
          { pendingCount: pendingItems.length, summaryCount: response.operational_summary.aguardando_liberacao },
        );
      }
      setClinicName(response.clinica_nome || adminPreview?.clinicaNome || null);
      setTotalAvailable(response.total);
      setMustChangePassword(Boolean(response.must_change_password));
      setDashboardLoaded(true);
      if (response.total === 0) {
        setMessage("Nenhum exame liberado foi encontrado para os filtros aplicados.");
      }
    } catch (err) {
      setExams([]);
      setOperationalSummary(EMPTY_OPERATIONAL_SUMMARY);
      setOperationalItems([]);
      setOperationalPendingItems([]);
      setTotalAvailable(0);
      setError(
        err instanceof Error
          ? err.message
          : isAdminPreview
            ? "Nao foi possivel carregar a visao espelhada da clinica."
            : "Não foi possível carregar o painel da clínica.",
      );
    } finally {
      setSearchLoading(false);
    }
  }

  async function loadAgendamentos(currentSession: PortalSessionResponse | null = session) {
    if (isAdminPreview || !currentSession) {
      return;
    }

    setAgendamentosLoading(true);
    setAgendamentosError("");

    try {
      const usableSession = await ensureClinicSession(currentSession);
      const response = await listPortalClinicAgendamentos(usableSession.access_token);
      setAgendamentos(response.items);
    } catch (err) {
      setAgendamentos([]);
      setAgendamentosError(
        err instanceof Error ? err.message : "Não foi possível carregar os agendamentos da clínica.",
      );
    } finally {
      setAgendamentosLoading(false);
    }
  }

  async function handleCancelarAgendamento(agendamentoId: number) {
    if (!session) {
      return;
    }

    setCancelandoId(agendamentoId);
    setAgendamentosError("");
    setAgendamentosMessage("");

    try {
      const usableSession = await ensureClinicSession(session);
      await cancelPortalClinicAgendamento(agendamentoId, usableSession.access_token);
      setConfirmandoCancelamentoId(null);
      setAgendamentosMessage("Agendamento cancelado com sucesso.");
      await loadAgendamentos(usableSession);
    } catch (err) {
      setAgendamentosError(
        err instanceof Error ? err.message : "Não foi possível cancelar o agendamento.",
      );
    } finally {
      setCancelandoId(null);
    }
  }

  async function loadFinanceiro(currentSession: PortalSessionResponse | null = session) {
    if (isAdminPreview || !currentSession) {
      return;
    }

    setFinanceiroLoading(true);
    setFinanceiroError("");

    try {
      const usableSession = await ensureClinicSession(currentSession);
      const response = await getPortalClinicFinanceiro(usableSession.access_token);
      setFinanceiro(response);
    } catch (err) {
      setFinanceiro(null);
      setFinanceiroError(
        err instanceof Error ? err.message : "Não foi possível carregar o financeiro da clínica.",
      );
    } finally {
      setFinanceiroLoading(false);
    }
  }

  async function handleBaixarRecibo(os: PortalClinicaOrdemServicoItem) {
    if (!session) {
      return;
    }

    setBaixandoReciboId(os.id);
    setFinanceiroError("");

    try {
      const usableSession = await ensureClinicSession(session);
      await downloadPortalClinicOSRecibo(os.id, usableSession.access_token, `recibo_${os.numero_os}.pdf`);
    } catch (err) {
      setFinanceiroError(err instanceof Error ? err.message : "Não foi possível baixar o recibo.");
    } finally {
      setBaixandoReciboId(null);
    }
  }

  async function handleChangePassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      return;
    }
    if (novaSenhaInput !== novaSenhaConfirmacaoInput) {
      setPasswordChangeError("A confirmação da nova senha não confere.");
      return;
    }

    setPasswordChangeLoading(true);
    setPasswordChangeError("");
    try {
      const usableSession = await ensureClinicSession(session);
      await changeClinicPortalPassword(
        {
          senha_atual: senhaAtualInput,
          nova_senha: novaSenhaInput,
          nova_senha_confirmacao: novaSenhaConfirmacaoInput,
        },
        usableSession.access_token,
      );
      setMustChangePassword(false);
      setShowPasswordModal(false);
      setSenhaAtualInput("");
      setNovaSenhaInput("");
      setNovaSenhaConfirmacaoInput("");
      setMessage("Senha atualizada com sucesso.");
    } catch (err) {
      setPasswordChangeError(err instanceof Error ? err.message : "Não foi possível trocar a senha.");
    } finally {
      setPasswordChangeLoading(false);
    }
  }

  useEffect(() => {
    if (isAdminPreview) {
      setBootstrapping(false);
      return;
    }

    if (initialSession) {
      setSession(initialSession);
      setBootstrapping(false);
      return;
    }

    void hydrateClinicSession();
  }, [initialSession, isAdminPreview]);

  useEffect(() => {
    if (isAdminPreview) {
      if (previewClinicId) {
        void loadDashboard(filters, previewSession);
      } else {
        setExams([]);
        setOperationalSummary(EMPTY_OPERATIONAL_SUMMARY);
        setOperationalItems([]);
        setOperationalPendingItems([]);
        setClinicName(null);
        setTotalAvailable(0);
        setDashboardLoaded(false);
      }
      return;
    }

    if (session) {
      void loadDashboard(filters, session);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdminPreview, previewClinicId, session?.access_token]);

  useEffect(() => {
    if (!isAdminPreview && !bootstrapping) {
      onSessionChange?.(session);
    }
  }, [bootstrapping, isAdminPreview, onSessionChange, session]);

  // Agenda/Financeiro so carregam quando a aba correspondente e aberta pela
  // primeira vez (evita puxar dado que a clinica pode nunca chegar a ver).
  useEffect(() => {
    if (isAdminPreview || !session) {
      return;
    }
    // Sem `clinic:read` essas duas chamadas voltariam 403: nem tenta.
    if (!temClinicRead) {
      return;
    }
    if (abaAtiva === "agenda" && !agendamentosSolicitados) {
      setAgendamentosSolicitados(true);
      void loadAgendamentos(session);
    }
    if (abaAtiva === "financeiro" && !financeiroSolicitado) {
      setFinanceiroSolicitado(true);
      void loadFinanceiro(session);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abaAtiva, isAdminPreview, session?.access_token]);

  async function encerrarDispositivo() {
    setEncerrandoDispositivo(true);
    setError("");
    try {
      await endPortalDeviceTrust();
    } catch {
      // O encerramento no backend e idempotente; se falhou, a sessao local ainda
      // deve cair, senao a pessoa continua vendo laudos numa maquina que ela
      // acabou de dizer que nao e mais dela.
    } finally {
      clearPortalSession("clinica");
      setSession(null);
      setEncerrandoDispositivo(false);
      setMessage("Acesso encerrado neste computador.");
    }
  }

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestLoading(true);
    setError("");
    setMessage("");

    try {
      const response = await loginClinicPortal({
        email: email.trim(),
        password,
        remember_device_until_shift_end: rememberDevice,
      });

      if (response.mfa_required) {
        setMfaChallengeId(response.challenge_id || null);
        setMfaCode("");
        setMessage(response.message || "Enviamos um código adicional para o e-mail institucional.");
        return;
      }

      const nextSession = normalizeClinicSession(response);
      savePortalSession(nextSession);
      setSession(nextSession);
      setMfaChallengeId(null);
      setPassword("");
      setMessage(response.message || "Sessão da clínica iniciada com sucesso.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível iniciar a sessão da clínica.");
    } finally {
      setRequestLoading(false);
    }
  }

  async function handleVerifyMfa(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mfaChallengeId) {
      return;
    }

    setVerifyLoading(true);
    setError("");
    setMessage("");

    try {
      const response = await verifyClinicPortalMfa({
        challenge_id: mfaChallengeId,
        codigo: mfaCode.trim(),
        remember_device_until_shift_end: rememberDevice,
      });
      const nextSession = normalizeClinicSession(response);
      savePortalSession(nextSession);
      setSession(nextSession);
      setMfaChallengeId(null);
      setMfaCode("");
      setPassword("");
      setMessage(response.message || "Sessão da clínica iniciada com sucesso.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível confirmar o acesso da clínica.");
    } finally {
      setVerifyLoading(false);
    }
  }

  async function handleForgotPassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestLoading(true);
    setError("");
    setMessage("");

    try {
      const response = await requestClinicPasswordReset({
        email: (resetEmail || email).trim(),
      });
      setMessage(response.message);
      setShowForgotPassword(false);
      setResetEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível iniciar a redefinição de senha.");
    } finally {
      setRequestLoading(false);
    }
  }

  async function handleFilterSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isAdminPreview || session) {
      await loadDashboard(filters, session);
    }
  }

  function updateFilter<K extends keyof ClinicExamFiltersState>(key: K, value: ClinicExamFiltersState[K]) {
    setFilters((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function handleStartDateChange(value: string) {
    setFilters((current) => ({
      ...current,
      data_inicio: value,
      data_fim: !value || !current.data_fim || current.data_fim < value ? value : current.data_fim,
    }));
  }

  async function handleClearFilters() {
    setFilters(INITIAL_FILTERS);
    if (isAdminPreview || session) {
      await loadDashboard(INITIAL_FILTERS, session);
    }
  }

  async function handleLogout() {
    try {
      await logoutClinicPortal(session?.access_token || null);
    } catch {
      // A limpeza local ainda precisa acontecer mesmo se o endpoint falhar.
    } finally {
      clearPortalSession("clinica");
      setSession(null);
      setMfaChallengeId(null);
      setExams([]);
      setClinicName(null);
      setTotalAvailable(0);
      setDashboardLoaded(false);
      setFilters(INITIAL_FILTERS);
      setPassword("");
      setMfaCode("");
      setMessage("Sessão da clínica encerrada neste dispositivo.");
      setError("");
    }
  }

  async function handleDownload(examId: number, attachmentId: number) {
    if (!activeSession) {
      return;
    }

    setDownloadingAttachmentId(attachmentId);
    setError("");
    try {
      const response = isAdminPreview
        ? await createPortalAdminClinicExamDownloadUrls(previewClinicId as number, examId)
        : await createPortalExamDownloadUrls(
            examId,
            (await ensureClinicSession(activeSession)).access_token,
          );
      const item = response.items.find((entry) => entry.anexo_id === attachmentId);
      if (!item) {
        throw new Error("O anexo solicitado não está disponível para download.");
      }
      await downloadPortalAttachment(item);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível baixar o anexo.");
    } finally {
      setDownloadingAttachmentId(null);
    }
  }

  if (activeSession) {
    if (mode !== "standalone" && !isAdminPreview) {
      return null;
    }

    const clinicLabel =
      clinicName ||
      adminPreview?.clinicaNome ||
      (activeSession.clinica_id ? `Clínica #${activeSession.clinica_id}` : "Clínica parceira");
    const isNewClinicWithNoHistory =
      dashboardLoaded && operationalItems.length === 0 && operationalPendingItems.length === 0;

    return (
      <section className="fc-clinic-dashboard min-h-screen bg-[#f6fafb] text-slate-950">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 px-5 py-4 backdrop-blur sm:px-8">
          <div className="mx-auto flex max-w-7xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-teal-700">
                {isAdminPreview ? "Pré-visualização administrativa" : "Ambiente da clínica parceira"}
              </p>
              <h1 className="mt-1 truncate text-2xl font-bold text-slate-950">
                {clinicLabel}
              </h1>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              {!isAdminPreview ? (
                <button
                  type="button"
                  onClick={() => {
                    setPasswordChangeError("");
                    setShowPasswordModal(true);
                  }}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-800 transition hover:bg-slate-50"
                >
                  <Settings className="h-4 w-4" />
                  Configurações
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => void loadDashboard(filters, session)}
                disabled={searchLoading}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-800 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {searchLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                Atualizar
              </button>
              {isAdminPreview ? (
                <Link
                  href={adminPreview?.backHref || "/clinicas/portal"}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-bold text-white transition hover:bg-slate-800"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Voltar à gestão
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-bold text-white transition hover:bg-slate-800"
                >
                  <LogOut className="h-4 w-4" />
                  Sair
                </button>
              )}
            </div>
          </div>
        </header>

        {mustChangePassword && !mustChangePasswordDismissed && !isAdminPreview ? (
          <div className="mx-auto mt-4 flex max-w-7xl flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 px-5 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between sm:px-8">
            <p>
              Esta conta ainda está usando a senha temporária gerada no convite. Troque por uma senha só sua assim
              que possível.
            </p>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                onClick={() => {
                  setPasswordChangeError("");
                  setShowPasswordModal(true);
                }}
                className="inline-flex items-center justify-center rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-bold text-white transition hover:bg-amber-700"
              >
                Trocar senha agora
              </button>
              <button
                type="button"
                onClick={() => setMustChangePasswordDismissed(true)}
                className="inline-flex items-center justify-center rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-bold text-amber-800 transition hover:bg-amber-100"
              >
                Dispensar por agora
              </button>
            </div>
          </div>
        ) : null}

        <main className="mx-auto max-w-7xl px-5 py-6 sm:px-8">
          <section className="fc-clinic-dashboard-hero grid gap-4 lg:grid-cols-[1fr_0.72fr] lg:items-start">
            <div className="fc-clinic-dashboard-hero-copy">
              <p className="fc-clinic-dashboard-hero-kicker inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold uppercase tracking-[0.12em]">
                <LayoutDashboard className="h-4 w-4" />
                Portal da unidade
              </p>
              <h2 className="mt-4 max-w-3xl text-3xl font-bold leading-tight text-slate-950 sm:text-4xl">
                Exames liberados para pacientes atendidos nesta clínica.
              </h2>
            </div>

            <div className="fc-clinic-dashboard-session rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600 shadow-sm">
              <p className="font-bold text-slate-950">
                {isAdminPreview
                  ? "Visao espelhada"
                  : modoLaudos
                    ? "Conectado neste computador"
                    : "Sessão ativa"}
              </p>
              <p className="mt-2">ID da clínica: {activeSession.clinica_id ?? "-"}</p>
              {isAdminPreview ? (
                <p className="mt-1">
                  Conferindo o mesmo painel, filtros e downloads que a unidade parceira enxerga no portal.
                </p>
              ) : (
                <>
                  <p className="mt-1">Válida até {formatPortalDateTime(activeSession.expires_at)}</p>
                  {activeSession.trusted_session_expires_at ? (
                    <p className="mt-1">
                      Acesso neste computador até {formatPortalDateTime(activeSession.trusted_session_expires_at)}
                    </p>
                  ) : null}
                  {modoLaudos ? (
                    <>
                      <p className="mt-2 text-slate-500">
                        Este computador consulta laudos da unidade sem senha. Financeiro e agenda
                        exigem login.
                      </p>
                      {onPedirLoginPorSenha ? (
                        <button
                          type="button"
                          onClick={onPedirLoginPorSenha}
                          className="mt-2 inline-flex text-sm font-semibold text-emerald-800 underline underline-offset-4"
                        >
                          Entrar com senha para ver financeiro e agenda
                        </button>
                      ) : null}
                      {/* Abaixo do login de proposito: encerrar e destrutivo e tira a
                          recepcao do ar, entao nao deve ser a primeira saida a mao. */}
                      <button
                        type="button"
                        onClick={encerrarDispositivo}
                        disabled={encerrandoDispositivo}
                        className="mt-2 block text-sm font-semibold text-rose-700 underline underline-offset-4 disabled:opacity-60"
                      >
                        {encerrandoDispositivo ? "Encerrando..." : "Sair deste computador"}
                      </button>
                    </>
                  ) : null}
                </>
              )}
            </div>
          </section>

          <div
            role="tablist"
            aria-label="Seções do portal da unidade"
            className="mt-6 flex gap-2 overflow-x-auto rounded-lg border border-slate-200 bg-white p-1.5 shadow-sm"
          >
            {PORTAL_TABS.filter(
              (tab) => !tab.somenteSessaoReal || (!isAdminPreview && temClinicRead),
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`portal-tab-${tab.id}`}
                aria-selected={abaAtiva === tab.id}
                aria-controls={`portal-tabpanel-${tab.id}`}
                onClick={() => setAbaAtiva(tab.id)}
                className={`shrink-0 rounded-lg px-4 py-2 text-sm font-bold transition ${
                  abaAtiva === tab.id ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {abaAtiva === "visao-geral" ? (
            <div role="tabpanel" id="portal-tabpanel-visao-geral" aria-labelledby="portal-tab-visao-geral">
          <section className="mt-6 rounded-lg border-2 border-amber-300 bg-amber-50/70 p-4 shadow-sm">
            <div className="flex flex-col gap-3 border-b border-amber-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="inline-flex items-center gap-2 text-sm font-bold uppercase tracking-[0.1em] text-amber-900">
                  <ShieldCheck className="h-4 w-4" />
                  Aguardando liberação
                </p>
                <p className="mt-1 text-sm text-amber-800">
                  Laudo finalizado, na fila para ser publicado no portal.
                </p>
              </div>
              <span className="inline-flex items-center justify-center rounded-lg bg-amber-500 px-4 py-2 text-2xl font-bold text-white">
                {operationalPendingItems.length}
              </span>
            </div>

            {operationalPendingItems.length === 0 ? (
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-dashed border-amber-300 bg-white p-4 text-sm text-amber-900">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                {isNewClinicWithNoHistory
                  ? "Ainda não há exames registrados para esta clínica."
                  : "Nenhum laudo pendente no momento — tudo em dia."}
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                {operationalPendingItems.map((item) => (
                  <article key={item.item_id} className="rounded-lg border border-amber-200 bg-white p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-lg bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-[0.08em] text-amber-800">
                        {item.origem === "laudo" ? "Laudo" : "Exame"}
                      </span>
                    </div>
                    <h3 className="mt-3 text-lg font-bold text-slate-950">{item.tipo_exame}</h3>
                    <dl className="mt-3 grid gap-3 text-sm text-slate-600 md:grid-cols-2 xl:grid-cols-4">
                      <div>
                        <dt className="font-bold text-slate-900">Pet</dt>
                        <dd className="mt-1">{item.paciente_nome || "Não informado"}</dd>
                      </div>
                      <div>
                        <dt className="font-bold text-slate-900">Tutor</dt>
                        <dd className="mt-1">{item.tutor_nome || "Não informado"}</dd>
                      </div>
                      <div>
                        <dt className="font-bold text-slate-900">Data de realização</dt>
                        <dd className="mt-1">{formatCalendarDate(item.data_realizacao || null)}</dd>
                      </div>
                      <div>
                        <dt className="font-bold text-slate-900">Previsão de liberação</dt>
                        <dd className="mt-1">{formatPortalDateTime(item.previsao_liberacao || null)}</dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">
              Resumo da unidade · prazo padrão de até {operationalSummary.sla_horas}h após a realização
            </p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-7">
              {[
                { label: "Exames encontrados", value: dashboardStats.totalExams, icon: FileCheck2 },
                { label: "Pets no resultado", value: dashboardStats.pets, icon: PawPrint },
                { label: "Arquivos disponíveis", value: dashboardStats.attachments, icon: Download },
                { label: "Mais recente", value: dashboardStats.latestDate, icon: CalendarDays },
                { label: "Realizados hoje", value: operationalSummary.realizados_hoje, icon: Stethoscope },
                { label: "Em laudo", value: operationalSummary.em_laudo, icon: FileCheck2 },
                { label: "Liberados hoje", value: operationalSummary.liberados_hoje, icon: CheckCircle2 },
              ].map(({ label, value, icon: Icon }) => (
                <div key={label} className="rounded-lg bg-slate-50 px-3 py-2">
                  <div className="flex items-center gap-2 text-slate-500">
                    <Icon className="h-3.5 w-3.5" />
                    <p className="text-[11px] font-bold uppercase tracking-[0.08em]">{label}</p>
                  </div>
                  <p className="mt-1 text-lg font-bold text-slate-950">{value}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-sm font-bold text-slate-950">Atividade recente da unidade</p>
                <p className="mt-1 text-sm text-slate-500">
                  Últimos exames e laudos movimentados, em qualquer status.
                </p>
              </div>
            </div>

            {operationalItems.length === 0 ? (
              <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                Ainda não há movimentações operacionais recentes para esta clínica.
              </div>
            ) : (
                <div className="mt-4 space-y-3">
                  {operationalItems.map((item) => (
                    <article
                      key={item.item_id}
                      className="rounded-lg border border-slate-200 bg-white p-4"
                    >
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-[0.08em] text-slate-600">
                              {item.origem === "laudo" ? "Laudo" : "Exame"}
                            </span>
                            <span
                              className={`rounded-lg px-2 py-1 text-xs font-bold ${operationalStatusClasses(
                                item.status_key,
                              )}`}
                            >
                              {OPERATIONAL_STATUS_LABELS[item.status_key] || item.status_label}
                            </span>
                          </div>
                          <h3 className="mt-3 text-lg font-bold text-slate-950">{item.tipo_exame}</h3>
                          <dl className="mt-3 grid gap-3 text-sm text-slate-600 md:grid-cols-2 xl:grid-cols-5">
                            <div>
                              <dt className="font-bold text-slate-900">Pet</dt>
                              <dd className="mt-1">{item.paciente_nome || "Não informado"}</dd>
                            </div>
                            <div>
                              <dt className="font-bold text-slate-900">Tutor</dt>
                              <dd className="mt-1">{item.tutor_nome || "Não informado"}</dd>
                            </div>
                            <div>
                              <dt className="font-bold text-slate-900">Espécie</dt>
                              <dd className="mt-1">{item.especie || "Não informada"}</dd>
                            </div>
                            <div>
                              <dt className="font-bold text-slate-900">Data de realização</dt>
                              <dd className="mt-1">{formatCalendarDate(item.data_realizacao || null)}</dd>
                            </div>
                            <div>
                              <dt className="font-bold text-slate-900">
                                {item.data_liberacao ? "Data de liberação" : "Previsão de liberação"}
                              </dt>
                              <dd className="mt-1">
                                {item.data_liberacao
                                  ? formatPortalDateTime(item.data_liberacao)
                                  : formatPortalDateTime(item.previsao_liberacao || null)}
                              </dd>
                            </div>
                          </dl>
                        </div>
                      </div>

                      {item.observacoes ? (
                        <p className="mt-4 border-t border-slate-200 pt-4 text-sm leading-6 text-slate-600">
                          {item.observacoes}
                        </p>
                      ) : null}
                    </article>
                  ))}
                </div>
              )}
          </section>
            </div>
          ) : null}

          {abaAtiva === "agenda" && !isAdminPreview && temClinicRead ? (
            <div role="tabpanel" id="portal-tabpanel-agenda" aria-labelledby="portal-tab-agenda">
            <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="inline-flex items-center gap-2 text-sm font-bold text-slate-950">
                    <CalendarDays className="h-4 w-4" />
                    Agendamentos ativos da unidade
                  </p>
                  <p className="mt-1 text-sm text-slate-500">
                    Agendamentos, reservas e confirmações em aberto para esta clínica.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void loadAgendamentos(session)}
                  disabled={agendamentosLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-800 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {agendamentosLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCcw className="h-4 w-4" />
                  )}
                  Atualizar
                </button>
              </div>

              {agendamentosError ? (
                <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                  {agendamentosError}
                </div>
              ) : null}

              {agendamentosMessage ? (
                <div className="mt-4 rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm text-teal-800">
                  {agendamentosMessage}
                </div>
              ) : null}

              <div className="mt-4">
                {agendamentosLoading && agendamentos.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                    Carregando agendamentos...
                  </div>
                ) : agendamentos.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                    Nenhum agendamento ativo para esta unidade no momento.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {agendamentos.map((agendamento) => (
                      <article key={agendamento.id} className="rounded-lg border border-slate-200 bg-white p-4">
                        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-[0.08em] text-slate-600">
                                {agendamento.status}
                              </span>
                            </div>
                            <h3 className="mt-3 text-lg font-bold text-slate-950">
                              {agendamento.servico_nome || "Atendimento"}
                            </h3>
                            <dl className="mt-3 grid gap-3 text-sm text-slate-600 md:grid-cols-2 xl:grid-cols-4">
                              <div>
                                <dt className="font-bold text-slate-900">Data</dt>
                                <dd className="mt-1">
                                  {formatCalendarDate(agendamento.data || null)}
                                  {agendamento.hora ? ` às ${agendamento.hora}` : ""}
                                </dd>
                              </div>
                              <div>
                                <dt className="font-bold text-slate-900">Pet</dt>
                                <dd className="mt-1">{agendamento.paciente_nome || "Pendente"}</dd>
                              </div>
                              <div>
                                <dt className="font-bold text-slate-900">Tutor</dt>
                                <dd className="mt-1">{agendamento.tutor_nome || "Pendente"}</dd>
                              </div>
                            </dl>
                          </div>

                          {agendamento.pode_cancelar ? (
                            <div className="flex shrink-0 flex-col items-stretch gap-2 sm:items-end">
                              {confirmandoCancelamentoId === agendamento.id ? (
                                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                                  <p className="font-bold">Cancelar este agendamento?</p>
                                  <p className="mt-1 text-xs text-red-700">
                                    Esta ação não pode ser desfeita pelo portal.
                                  </p>
                                  <div className="mt-3 flex gap-2">
                                    <button
                                      type="button"
                                      onClick={() => setConfirmandoCancelamentoId(null)}
                                      disabled={cancelandoId === agendamento.id}
                                      className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50"
                                    >
                                      Voltar
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => void handleCancelarAgendamento(agendamento.id)}
                                      disabled={cancelandoId === agendamento.id}
                                      className="inline-flex items-center gap-1 rounded-md bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                      {cancelandoId === agendamento.id ? (
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                      ) : (
                                        <XCircle className="h-3.5 w-3.5" />
                                      )}
                                      Sim, cancelar
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => setConfirmandoCancelamentoId(agendamento.id)}
                                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-bold text-red-700 transition hover:bg-red-50"
                                >
                                  <XCircle className="h-4 w-4" />
                                  Cancelar
                                </button>
                              )}
                            </div>
                          ) : null}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </section>
            </div>
          ) : null}

          {abaAtiva === "financeiro" && !isAdminPreview && temClinicRead ? (
            <div role="tabpanel" id="portal-tabpanel-financeiro" aria-labelledby="portal-tab-financeiro">
            <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="inline-flex items-center gap-2 text-sm font-bold text-slate-950">
                    <Wallet className="h-4 w-4" />
                    Financeiro da unidade
                  </p>
                  <p className="mt-1 text-sm text-slate-500">
                    Ordens de serviço pendentes e pagas geradas para esta clínica.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void loadFinanceiro(session)}
                  disabled={financeiroLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-800 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {financeiroLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCcw className="h-4 w-4" />
                  )}
                  Atualizar
                </button>
              </div>

              {financeiroError ? (
                <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                  {financeiroError}
                </div>
              ) : null}

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                  <p className="text-xs font-bold uppercase tracking-[0.12em] text-amber-700">Pendente</p>
                  <p className="mt-2 text-2xl font-bold text-amber-900">
                    {formatCurrencyBRL(financeiro?.summary.total_pendente ?? 0)}
                  </p>
                  <p className="mt-1 text-sm text-amber-700">
                    {financeiro?.summary.quantidade_pendente ?? 0} ordem(ns) de serviço
                  </p>
                </div>
                <div className="rounded-lg border border-teal-200 bg-teal-50 p-4">
                  <p className="text-xs font-bold uppercase tracking-[0.12em] text-teal-700">Pago</p>
                  <p className="mt-2 text-2xl font-bold text-teal-900">
                    {formatCurrencyBRL(financeiro?.summary.total_pago ?? 0)}
                  </p>
                  <p className="mt-1 text-sm text-teal-700">
                    {financeiro?.summary.quantidade_pago ?? 0} ordem(ns) de serviço
                  </p>
                </div>
              </div>

              <div className="mt-6">
                <p className="text-sm font-bold text-slate-950">Pendentes</p>
                {!financeiro || financeiro.pendentes.length === 0 ? (
                  <div className="mt-2 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                    Nenhuma ordem de serviço pendente para esta unidade.
                  </div>
                ) : (
                  <div className="mt-2 space-y-2">
                    {financeiro.pendentes.map((os) => (
                      <div
                        key={os.id}
                        className="flex flex-col gap-1 rounded-lg border border-slate-200 bg-white p-3 text-sm sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div>
                          <p className="font-bold text-slate-900">{os.numero_os}</p>
                          <p className="text-slate-500">
                            {os.servico_nome || "Serviço"} · {os.paciente_nome || "Pet não informado"}
                            {os.data_atendimento ? ` · ${formatCalendarDate(os.data_atendimento)}` : ""}
                          </p>
                        </div>
                        <p className="font-bold text-amber-700">{formatCurrencyBRL(os.valor)}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="mt-6">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-bold text-slate-950">Pagas (mais recentes)</p>
                  {financeiro && financeiro.summary.quantidade_pago > financeiro.pagas.length ? (
                    <p className="text-xs text-slate-500">
                      Mostrando {financeiro.pagas.length} de {financeiro.summary.quantidade_pago}
                    </p>
                  ) : null}
                </div>
                {!financeiro || financeiro.pagas.length === 0 ? (
                  <div className="mt-2 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                    Nenhuma ordem de serviço paga registrada ainda.
                  </div>
                ) : (
                  <div className="mt-2 space-y-2">
                    {financeiro.pagas.map((os) => (
                      <div
                        key={os.id}
                        className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div>
                          <p className="font-bold text-slate-900">{os.numero_os}</p>
                          <p className="text-slate-500">
                            {os.servico_nome || "Serviço"} · {os.paciente_nome || "Pet não informado"}
                            {os.data_atendimento ? ` · ${formatCalendarDate(os.data_atendimento)}` : ""}
                          </p>
                        </div>
                        <div className="flex items-center gap-3">
                          <p className="font-bold text-teal-700">{formatCurrencyBRL(os.valor)}</p>
                          <button
                            type="button"
                            onClick={() => void handleBaixarRecibo(os)}
                            disabled={baixandoReciboId === os.id}
                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-teal-300 bg-white px-3 py-1.5 text-xs font-bold text-teal-700 transition hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {baixandoReciboId === os.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Download className="h-3.5 w-3.5" />
                            )}
                            Recibo
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
            </div>
          ) : null}

          {abaAtiva === "laudos" ? (
            <div role="tabpanel" id="portal-tabpanel-laudos" aria-labelledby="portal-tab-laudos">
          <form
            className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
            onSubmit={handleFilterSubmit}
          >
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="inline-flex items-center gap-2 text-sm font-bold text-slate-950">
                  <Filter className="h-4 w-4" />
                  Filtros de busca
                </p>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={() => void handleClearFilters()}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-50"
                >
                  Limpar
                </button>
                <button
                  type="submit"
                  disabled={searchLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-teal-500 px-4 py-2 text-sm font-bold text-slate-950 transition hover:bg-teal-400 disabled:cursor-not-allowed disabled:bg-teal-200"
                >
                  {searchLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  Buscar exames
                </button>
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <label className="block text-sm font-semibold text-slate-800">
                Busca geral
                <input
                  value={filters.q}
                  onChange={(event) => updateFilter("q", event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  placeholder="Pet, tutor ou exame"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-800">
                Pet
                <input
                  value={filters.pet}
                  onChange={(event) => updateFilter("pet", event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  placeholder="Nome do pet"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-800">
                Tutor
                <input
                  value={filters.tutor}
                  onChange={(event) => updateFilter("tutor", event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  placeholder="Nome do tutor"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-800">
                Espécie
                <input
                  value={filters.especie}
                  onChange={(event) => updateFilter("especie", event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  placeholder="Canina, Felina..."
                />
              </label>

              <label className="block text-sm font-semibold text-slate-800">
                Tipo de exame
                <input
                  value={filters.tipo_exame}
                  onChange={(event) => updateFilter("tipo_exame", event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  placeholder="Eco, ECG, US..."
                />
              </label>

              <label className="block text-sm font-semibold text-slate-800">
                Data de realização - De
                <input
                  type="date"
                  value={filters.data_inicio}
                  onChange={(event) => handleStartDateChange(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-800">
                Data de realização - Até
                <input
                  type="date"
                  value={filters.data_fim}
                  onChange={(event) => updateFilter("data_fim", event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-800">
                Ordenação
                <select
                  value={`${filters.sort_by}:${filters.sort_dir}`}
                  onChange={(event) => {
                    const [sortBy, sortDir] = event.target.value.split(":");
                    updateFilter("sort_by", sortBy as ClinicSortBy);
                    updateFilter("sort_dir", sortDir as ClinicSortDir);
                  }}
                  className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                >
                  <option value="data:desc">Mais recentes por realização</option>
                  <option value="data:asc">Mais antigos por realização</option>
                  <option value="tipo_exame:asc">Tipo A-Z</option>
                  <option value="pet:asc">Pet A-Z</option>
                  <option value="tutor:asc">Tutor A-Z</option>
                  <option value="especie:asc">Espécie A-Z</option>
                </select>
              </label>
            </div>
          </form>

          {message ? (
            <div className="mt-4 rounded-lg border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">
              {message}
            </div>
          ) : null}

          {error ? (
            <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
              {error}
            </div>
          ) : null}

          <section className="mt-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="inline-flex items-center gap-2 text-sm font-bold text-slate-950">
                  <SlidersHorizontal className="h-4 w-4" />
                  Exames liberados
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  {totalAvailable} resultado(s) no escopo desta clínica.
                </p>
              </div>
            </div>

            {searchLoading && exams.length === 0 ? (
              <div className="mt-4 rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Carregando exames liberados para a unidade...
                </span>
              </div>
            ) : exams.length === 0 ? (
              <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm leading-6 text-slate-600">
                {dashboardLoaded
                  ? "Nenhum exame liberado foi encontrado para os filtros aplicados."
                  : "Carregando o painel da clínica..."}
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                {exams.map((exam) => (
                  <article key={exam.id} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-[0.08em] text-slate-600">
                            Exame #{exam.id}
                          </span>
                          <span className="rounded-lg bg-teal-50 px-2 py-1 text-xs font-bold text-teal-800">
                            {exam.status || "Status não informado"}
                          </span>
                        </div>
                        <h3 className="mt-3 text-xl font-bold text-slate-950">{exam.tipo_exame}</h3>
                        <dl className="mt-4 grid gap-3 text-sm text-slate-600 md:grid-cols-2 xl:grid-cols-5">
                          <div>
                            <dt className="font-bold text-slate-900">Pet</dt>
                            <dd className="mt-1">{exam.paciente_nome || `Pet #${exam.paciente_id}`}</dd>
                          </div>
                          <div>
                            <dt className="font-bold text-slate-900">Tutor</dt>
                            <dd className="mt-1">{exam.tutor_nome || "Não informado"}</dd>
                          </div>
                          <div>
                            <dt className="font-bold text-slate-900">Espécie</dt>
                            <dd className="mt-1">{exam.especie || "Não informada"}</dd>
                          </div>
                          <div>
                            <dt className="font-bold text-slate-900">Data de realização</dt>
                            <dd className="mt-1">{formatCalendarDate(examExecutionDateValue(exam))}</dd>
                          </div>
                          <div>
                            <dt className="font-bold text-slate-900">Data de liberação</dt>
                            <dd className="mt-1">{formatPortalDate(exam.data_resultado)}</dd>
                          </div>
                        </dl>
                      </div>

                      <div className="text-sm text-slate-600 lg:min-w-56 lg:text-right">
                        <p className="font-bold text-slate-950">{exam.categoria_exame || "Categoria não informada"}</p>
                        <p className="mt-1">{exam.anexos.length} anexo(s)</p>
                      </div>
                    </div>

                    {exam.observacoes ? (
                      <p className="mt-4 border-t border-slate-200 pt-4 text-sm leading-6 text-slate-600">
                        {exam.observacoes}
                      </p>
                    ) : null}

                    <div className="mt-4 flex flex-col gap-2 border-t border-slate-200 pt-4 sm:flex-row sm:flex-wrap">
                      {exam.anexos.length === 0 ? (
                        <span className="inline-flex items-center gap-2 rounded-lg border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-500">
                          <FileCheck2 className="h-4 w-4" />
                          Nenhum arquivo disponível
                        </span>
                      ) : (
                        exam.anexos.map((attachment) => {
                          const isDownloading = downloadingAttachmentId === attachment.anexo_id;
                          return (
                            <button
                              key={attachment.anexo_id}
                              type="button"
                              onClick={() => void handleDownload(exam.id, attachment.anexo_id)}
                              disabled={!attachment.download_available || isDownloading}
                              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                              title={`${attachment.nome_original} - ${formatFileSize(attachment.tamanho)}`}
                            >
                              {isDownloading ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Download className="h-4 w-4" />
                              )}
                              <span className="max-w-52 truncate">
                                {isDownloading ? "Baixando..." : attachment.nome_original}
                              </span>
                            </button>
                          );
                        })
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
            </div>
          ) : null}
        </main>

        {showPasswordModal ? (
          <div
            className="fixed inset-0 z-30 flex items-center justify-center bg-slate-950/60 p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="portal-clinica-trocar-senha-titulo"
          >
            <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
              <div className="flex items-start justify-between gap-4">
                <h2 id="portal-clinica-trocar-senha-titulo" className="text-lg font-bold text-slate-950">
                  Trocar senha
                </h2>
                <button
                  type="button"
                  onClick={() => setShowPasswordModal(false)}
                  aria-label="Fechar"
                  className="rounded-lg p-1 text-slate-500 hover:bg-slate-100"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <form onSubmit={handleChangePassword} className="mt-4 space-y-4">
                <label className="block text-sm font-semibold text-slate-800">
                  Senha atual
                  <input
                    type="password"
                    required
                    value={senhaAtualInput}
                    onChange={(event) => setSenhaAtualInput(event.target.value)}
                    className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  />
                </label>
                <label className="block text-sm font-semibold text-slate-800">
                  Nova senha
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={novaSenhaInput}
                    onChange={(event) => setNovaSenhaInput(event.target.value)}
                    className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  />
                </label>
                <label className="block text-sm font-semibold text-slate-800">
                  Confirmar nova senha
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={novaSenhaConfirmacaoInput}
                    onChange={(event) => setNovaSenhaConfirmacaoInput(event.target.value)}
                    className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                  />
                </label>

                {passwordChangeError ? (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
                    {passwordChangeError}
                  </div>
                ) : null}

                <div className="flex justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => setShowPasswordModal(false)}
                    className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-700 transition hover:bg-slate-50"
                  >
                    Cancelar
                  </button>
                  <button
                    type="submit"
                    disabled={passwordChangeLoading}
                    className="inline-flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-teal-300"
                  >
                    {passwordChangeLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Salvar nova senha
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <aside className="fc-portal-workspace fc-portal-clinic-workspace rounded-lg border border-white/15 bg-white/[0.06] p-5">
      {bootstrapping ? (
        <div className="flex min-h-[320px] items-center justify-center text-sm text-slate-200">
          <span className="inline-flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Validando sessão deste dispositivo...
          </span>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between border-b border-white/15 pb-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-teal-100">
                Acesso da unidade
              </p>
              <h2 className="mt-2 text-xl font-bold text-white">Entrar como clínica parceira</h2>
            </div>
            <span className="rounded-lg bg-teal-300 px-3 py-2 text-xs font-bold text-slate-950">
              convite + senha
            </span>
          </div>

          {!showForgotPassword ? (
            <>
              {!mfaChallengeId ? (
                <form className="mt-5 space-y-4" onSubmit={handleLogin}>
                  <label className="block text-sm font-semibold text-white">
                    E-mail institucional
                    <input
                      required
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      className="mt-2 w-full rounded-lg border border-white/15 bg-slate-950/60 px-3 py-2 text-sm text-white outline-none transition focus:border-teal-300"
                      placeholder="portal@clinica.com"
                    />
                  </label>

                  <label className="block text-sm font-semibold text-white">
                    Senha
                    <input
                      required
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      className="mt-2 w-full rounded-lg border border-white/15 bg-slate-950/60 px-3 py-2 text-sm text-white outline-none transition focus:border-teal-300"
                      placeholder="Sua senha cadastrada"
                    />
                  </label>

                  <label className="flex items-start gap-3 rounded-lg border border-white/10 bg-slate-950/40 p-3 text-sm text-slate-200">
                    <input
                      type="checkbox"
                      checked={rememberDevice}
                      onChange={(event) => setRememberDevice(event.target.checked)}
                      className="mt-1 h-4 w-4 rounded border-white/20 bg-slate-950/60"
                    />
                    <span>
                      Manter acesso neste computador da unidade até o fim do expediente.
                    </span>
                  </label>

                  <button
                    type="submit"
                    disabled={requestLoading}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-teal-400 px-4 py-3 text-sm font-bold text-slate-950 transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:bg-teal-200"
                  >
                    {requestLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Building2 className="h-4 w-4" />}
                    {requestLoading ? "Entrando..." : "Entrar no portal da unidade"}
                  </button>
                </form>
              ) : (
                <form className="mt-5 space-y-4 rounded-lg border border-white/15 bg-slate-950/50 p-4" onSubmit={handleVerifyMfa}>
                  <div className="flex items-start gap-3">
                    <CheckCircle2 className="mt-0.5 h-5 w-5 text-teal-200" />
                    <div>
                      <p className="text-sm font-bold text-white">Confirmação adicional</p>
                      <p className="mt-1 text-sm leading-6 text-slate-300">
                        Enviamos um código para o e-mail institucional da unidade.
                      </p>
                    </div>
                  </div>

                  <label className="block text-sm font-semibold text-white">
                    Código recebido
                    <input
                      required
                      value={mfaCode}
                      onChange={(event) => setMfaCode(event.target.value)}
                      className="mt-2 w-full rounded-lg border border-white/15 bg-slate-950/60 px-3 py-2 text-sm text-white outline-none transition focus:border-teal-300"
                      placeholder="Digite o código de acesso"
                    />
                  </label>

                  <button
                    type="submit"
                    disabled={verifyLoading}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-3 text-sm font-bold text-slate-950 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:bg-slate-300"
                  >
                    {verifyLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                    {verifyLoading ? "Validando..." : "Confirmar acesso"}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setMfaChallengeId(null);
                      setMfaCode("");
                    }}
                    className="w-full rounded-lg border border-white/20 px-4 py-3 text-sm font-bold text-white transition hover:bg-white/10"
                  >
                    Voltar para login
                  </button>
                </form>
              )}

              <div className="mt-5 space-y-3 rounded-lg border border-white/10 bg-slate-950/30 p-4">
                <button
                  type="button"
                  onClick={() => {
                    setShowForgotPassword(true);
                    setResetEmail(email);
                    setError("");
                    setMessage("");
                  }}
                  className="inline-flex items-center gap-2 text-sm font-semibold text-teal-100 transition hover:text-white"
                >
                  <KeyRound className="h-4 w-4" />
                  Esqueci minha senha
                </button>

                <div className="text-sm leading-6 text-slate-300">
                  Recebeu um convite da Fort Cordis? Abra o link enviado para cadastrar o e-mail e a senha da unidade.
                </div>

                <Link
                  href="/clinica-parceira"
                  className="inline-flex items-center gap-2 text-sm font-semibold text-slate-200 transition hover:text-white"
                >
                  <Mail className="h-4 w-4" />
                  Revisar orientações de acesso
                </Link>
              </div>
            </>
          ) : (
            <form className="mt-5 space-y-4" onSubmit={handleForgotPassword}>
              <div className="rounded-lg border border-white/10 bg-slate-950/30 p-4 text-sm leading-6 text-slate-300">
                Enviaremos as instruções de redefinição para o e-mail institucional informado, se houver uma conta ativa para ele.
              </div>

              <label className="block text-sm font-semibold text-white">
                E-mail institucional
                <input
                  required
                  type="email"
                  value={resetEmail}
                  onChange={(event) => setResetEmail(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-white/15 bg-slate-950/60 px-3 py-2 text-sm text-white outline-none transition focus:border-teal-300"
                  placeholder="portal@clinica.com"
                />
              </label>

              <button
                type="submit"
                disabled={requestLoading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-3 text-sm font-bold text-slate-950 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {requestLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                {requestLoading ? "Enviando..." : "Enviar instruções"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setShowForgotPassword(false);
                  setError("");
                }}
                className="w-full rounded-lg border border-white/20 px-4 py-3 text-sm font-bold text-white transition hover:bg-white/10"
              >
                Voltar para login
              </button>
            </form>
          )}
        </>
      )}

      {message ? (
        <div className="mt-4 rounded-lg border border-teal-300/30 bg-teal-400/10 p-3 text-sm text-teal-50">
          {message}
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 rounded-lg border border-rose-300/30 bg-rose-400/10 p-3 text-sm text-rose-50">
          {error}
        </div>
      ) : null}
    </aside>
  );
}
