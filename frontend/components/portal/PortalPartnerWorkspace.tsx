"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  CheckCircle2,
  Download,
  FileCheck2,
  Filter,
  HeartPulse,
  KeyRound,
  Loader2,
  LogOut,
  Mail,
  PawPrint,
  RefreshCcw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Stethoscope,
} from "lucide-react";

import {
  clearPortalSession,
  createPortalExamDownloadUrls,
  downloadPortalAttachment,
  listPortalPartnerExams,
  loadPortalSession,
  loginPartnerPortal,
  logoutPartnerPortal,
  refreshPartnerPortalSession,
  requestPartnerPasswordReset,
  savePortalSession,
  verifyPartnerPortalMfa,
  type PortalClinicExamFilters,
  type PortalExamItem,
  type PortalPartnerAuthResponse,
  type PortalSessionResponse,
} from "@/lib/portal-api";
import { formatPortalDate, formatPortalDateTime, portalDateTimeMillis } from "@/lib/portal-datetime";
import { formatCalendarDate } from "@/lib/calendar-date";

type PortalPartnerWorkspaceProps = {
  mode?: "embedded" | "standalone";
  initialSession?: PortalSessionResponse | null;
  onSessionChange?: (session: PortalSessionResponse | null) => void;
};

type PartnerSortBy = NonNullable<PortalClinicExamFilters["sort_by"]>;
type PartnerSortDir = NonNullable<PortalClinicExamFilters["sort_dir"]>;

type PartnerExamFiltersState = {
  q: string;
  pet: string;
  tutor: string;
  especie: string;
  tipo_exame: string;
  status_exame: string;
  data_inicio: string;
  data_fim: string;
  sort_by: PartnerSortBy;
  sort_dir: PartnerSortDir;
};

const INITIAL_FILTERS: PartnerExamFiltersState = {
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

function normalizePartnerSession(payload: PortalPartnerAuthResponse): PortalSessionResponse {
  if (!payload.access_token || !payload.expires_at || payload.actor_type !== "parceiro" || !payload.actor_id) {
    throw new Error("Sessão do parceiro retornou incompleta.");
  }

  return {
    access_token: payload.access_token,
    token_type: payload.token_type || "bearer",
    expires_at: payload.expires_at,
    actor_type: "parceiro",
    actor_id: payload.actor_id,
    clinica_id: payload.clinica_id ?? null,
    partner_id: payload.partner_id ?? payload.actor_id,
    partner_nome: payload.partner_nome ?? null,
    partner_tipo: payload.partner_tipo ?? null,
    partner_tipo_label: payload.partner_tipo_label ?? null,
    paciente_id: null,
    account_id: payload.account_id ?? null,
    auth_method: payload.auth_method ?? null,
    trusted_session_expires_at: payload.trusted_session_expires_at ?? null,
    scope: payload.scope || [],
    message: payload.message ?? null,
  };
}

function compactFilters(filters: PartnerExamFiltersState): PortalClinicExamFilters {
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

function examDateValue(exam: PortalExamItem): string | null {
  return exam.data_exame || exam.data_solicitacao || exam.data_resultado || null;
}

function examExecutionDateValue(exam: PortalExamItem): string | null {
  return exam.data_exame || exam.data_solicitacao || null;
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

export default function PortalPartnerWorkspace({
  mode = "embedded",
  initialSession = null,
  onSessionChange,
}: PortalPartnerWorkspaceProps) {
  const [bootstrapping, setBootstrapping] = useState(!initialSession);
  const [session, setSession] = useState<PortalSessionResponse | null>(initialSession);
  const [mfaChallengeId, setMfaChallengeId] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberDevice, setRememberDevice] = useState(true);
  const [mfaCode, setMfaCode] = useState("");
  const [showForgotPassword, setShowForgotPassword] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [filters, setFilters] = useState<PartnerExamFiltersState>(INITIAL_FILTERS);
  const [requestLoading, setRequestLoading] = useState(false);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [downloadingAttachmentId, setDownloadingAttachmentId] = useState<number | null>(null);
  const [exams, setExams] = useState<PortalExamItem[]>([]);
  const [totalAvailable, setTotalAvailable] = useState(0);
  const [partnerName, setPartnerName] = useState<string | null>(initialSession?.partner_nome ?? null);
  const [partnerTypeLabel, setPartnerTypeLabel] = useState<string | null>(initialSession?.partner_tipo_label ?? null);
  const [dashboardLoaded, setDashboardLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const activeSession = session;

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

  async function hydratePartnerSession() {
    const storedSession = loadPortalSession("parceiro");
    if (storedSession) {
      setSession(storedSession);
      setPartnerName(storedSession.partner_nome || null);
      setPartnerTypeLabel(storedSession.partner_tipo_label || null);
      setBootstrapping(false);
      return;
    }

    try {
      const refreshed = normalizePartnerSession(await refreshPartnerPortalSession());
      savePortalSession(refreshed);
      setSession(refreshed);
      setPartnerName(refreshed.partner_nome || null);
      setPartnerTypeLabel(refreshed.partner_tipo_label || null);
      setMessage(refreshed.message || "Sessão do parceiro restaurada neste computador.");
    } catch {
      clearPortalSession("parceiro");
    } finally {
      setBootstrapping(false);
    }
  }

  async function ensurePartnerSession(currentSession: PortalSessionResponse | null): Promise<PortalSessionResponse> {
    if (currentSession && portalDateTimeMillis(currentSession.expires_at) > Date.now() + 60_000) {
      return currentSession;
    }
    const refreshed = normalizePartnerSession(await refreshPartnerPortalSession());
    savePortalSession(refreshed);
    setSession(refreshed);
    setPartnerName(refreshed.partner_nome || null);
    setPartnerTypeLabel(refreshed.partner_tipo_label || null);
    onSessionChange?.(refreshed);
    return refreshed;
  }

  async function loadDashboard(
    nextFilters: PartnerExamFiltersState = filters,
    currentSession: PortalSessionResponse | null = session,
  ) {
    setSearchLoading(true);
    setError("");
    try {
      if (!currentSession) {
        throw new Error("Nao foi possivel identificar a sessao do parceiro.");
      }
      const usableSession = await ensurePartnerSession(currentSession);
      const response = await listPortalPartnerExams(compactFilters(nextFilters), usableSession.access_token);
      setExams(response.items || []);
      setTotalAvailable(response.total || 0);
      setPartnerName(response.partner_nome || usableSession.partner_nome || null);
      setPartnerTypeLabel(response.partner_tipo_label || usableSession.partner_tipo_label || null);
      setDashboardLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar o painel do parceiro.");
    } finally {
      setSearchLoading(false);
    }
  }

  useEffect(() => {
    if (!initialSession) {
      void hydratePartnerSession();
      return;
    }
    setBootstrapping(false);
  }, [initialSession]);

  useEffect(() => {
    if (!session) {
      return;
    }
    void loadDashboard(filters, session);
  }, [session?.access_token]);

  useEffect(() => {
    onSessionChange?.(session);
  }, [onSessionChange, session]);

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestLoading(true);
    setError("");
    setMessage("");

    try {
      const response = await loginPartnerPortal({
        email: email.trim(),
        password,
        remember_device_until_shift_end: rememberDevice,
      });

      if (response.mfa_required && response.challenge_id) {
        setMfaChallengeId(response.challenge_id);
        setMessage(response.message || "Enviamos um código adicional para o seu e-mail.");
        setRequestLoading(false);
        return;
      }

      const nextSession = normalizePartnerSession(response);
      savePortalSession(nextSession);
      setSession(nextSession);
      setPartnerName(nextSession.partner_nome || null);
      setPartnerTypeLabel(nextSession.partner_tipo_label || null);
      setPassword("");
      setMfaCode("");
      setMessage(response.message || "Sessão do parceiro iniciada com sucesso.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível iniciar a sessão do parceiro.");
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
      const response = await verifyPartnerPortalMfa({
        challenge_id: mfaChallengeId,
        codigo: mfaCode.trim(),
        remember_device_until_shift_end: rememberDevice,
      });
      const nextSession = normalizePartnerSession(response);
      savePortalSession(nextSession);
      setSession(nextSession);
      setPartnerName(nextSession.partner_nome || null);
      setPartnerTypeLabel(nextSession.partner_tipo_label || null);
      setMfaChallengeId(null);
      setMfaCode("");
      setPassword("");
      setMessage(response.message || "Sessão do parceiro iniciada com sucesso.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível confirmar o acesso do parceiro.");
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
      const response = await requestPartnerPasswordReset({ email: resetEmail.trim() });
      setMessage(response.message);
      setShowForgotPassword(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível processar a redefinição.");
    } finally {
      setRequestLoading(false);
    }
  }

  function updateFilter<K extends keyof PartnerExamFiltersState>(key: K, value: PartnerExamFiltersState[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  async function handleSearchSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await loadDashboard(filters, activeSession);
  }

  async function handleClearFilters() {
    setFilters(INITIAL_FILTERS);
    await loadDashboard(INITIAL_FILTERS, activeSession);
  }

  async function handleLogout() {
    setRequestLoading(true);
    setError("");
    setMessage("");

    try {
      await logoutPartnerPortal(session?.access_token || null);
    } catch {
      // ignore logout transport failures and clear local session anyway
    } finally {
      clearPortalSession("parceiro");
      setSession(null);
      setPartnerName(null);
      setPartnerTypeLabel(null);
      setExams([]);
      setTotalAvailable(0);
      setDashboardLoaded(false);
      setMfaChallengeId(null);
      setMfaCode("");
      setRequestLoading(false);
      setMessage("Sessão do parceiro encerrada neste dispositivo.");
    }
  }

  async function handleDownload(examId: number, attachmentId: number) {
    if (!activeSession) {
      setError("Sua sessão expirou. Entre novamente para baixar o arquivo.");
      return;
    }

    setDownloadingAttachmentId(attachmentId);
    setError("");
    try {
      const response = await createPortalExamDownloadUrls(examId, (await ensurePartnerSession(activeSession)).access_token);
      const item = response.items.find((entry) => entry.anexo_id === attachmentId);
      if (!item) {
        throw new Error("Arquivo não disponível para download.");
      }
      await downloadPortalAttachment(item);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível baixar o arquivo.");
    } finally {
      setDownloadingAttachmentId(null);
    }
  }

  if (activeSession) {
    const partnerLabel =
      partnerName ||
      activeSession.partner_nome ||
      (activeSession.partner_id ? `Parceiro #${activeSession.partner_id}` : "Parceiro externo");
    const environmentLabel = partnerTypeLabel || activeSession.partner_tipo_label || "Veterinário parceiro";

    return (
      <section className="fc-clinic-dashboard min-h-screen bg-[#f6fafb] text-slate-950">
        <main className="mx-auto max-w-[1360px] px-4 py-6 sm:px-6 xl:px-8">
          <div className="flex flex-col gap-4 border-b border-slate-200 bg-white px-4 py-5 shadow-sm sm:rounded-2xl sm:px-6 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm font-bold uppercase tracking-[0.24em] text-teal-700">Ambiente do veterinário parceiro</p>
              <h1 className="mt-2 text-4xl font-black uppercase tracking-tight text-slate-950">{partnerLabel}</h1>
              <p className="mt-2 text-sm text-slate-600">{environmentLabel}</p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void loadDashboard(filters, activeSession)}
                disabled={searchLoading}
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-bold text-slate-800 transition hover:border-slate-400 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {searchLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                Atualizar
              </button>

              <button
                type="button"
                onClick={() => void handleLogout()}
                disabled={requestLoading}
                className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-slate-950 px-4 py-3 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {requestLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
                Sair
              </button>
            </div>
          </div>

          <section className="mt-6 grid gap-4 lg:grid-cols-[1fr_0.72fr] lg:items-start">
            <div className="rounded-2xl bg-[linear-gradient(120deg,#531126_0%,#131920_52%,#0f8d87_100%)] p-6 text-white shadow-sm">
              <p className="inline-flex items-center gap-2 rounded-lg bg-white/12 px-3 py-2 text-xs font-bold uppercase tracking-[0.12em] text-teal-50">
                <HeartPulse className="h-4 w-4" />
                Portal do parceiro
              </p>
              <h2 className="mt-6 text-4xl font-black tracking-tight">Exames liberados para você no portal.</h2>
              <p className="mt-4 max-w-2xl text-base leading-7 text-white/82">
                Consulte os casos liberados para você, filtre por pet ou tutor e baixe rapidamente os arquivos disponibilizados pela Fort Cordis.
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600 shadow-sm">
              <p className="text-sm font-bold text-slate-950">Sessão ativa</p>
              <p className="mt-3">Perfil: {environmentLabel}</p>
              <p className="mt-2">ID do parceiro: {activeSession.partner_id ?? activeSession.actor_id}</p>
              {activeSession.clinica_id ? <p className="mt-2">Clínica vinculada: #{activeSession.clinica_id}</p> : null}
              <p className="mt-2">Valida até {formatPortalDateTime(activeSession.expires_at)}</p>
              {activeSession.trusted_session_expires_at ? (
                <p className="mt-2">Acesso mantido neste computador até {formatPortalDateTime(activeSession.trusted_session_expires_at)}</p>
              ) : null}
            </div>
          </section>

          <section className="mt-6 grid gap-4 lg:grid-cols-4">
            {[
              {
                label: "Exames encontrados",
                value: dashboardStats.totalExams,
                detail: `${dashboardStats.visibleExams} exibidos agora`,
                icon: FileCheck2,
              },
              {
                label: "Pets no resultado",
                value: dashboardStats.pets,
                detail: "liberados para você",
                icon: PawPrint,
              },
              {
                label: "Arquivos disponíveis",
                value: dashboardStats.attachments,
                detail: "PDFs e anexos liberados",
                icon: Download,
              },
              {
                label: "Mais recente",
                value: dashboardStats.latestDate,
                detail: "por data de realização",
                icon: CalendarDays,
              },
            ].map(({ label, value, detail, icon: Icon }) => (
              <article key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-bold uppercase tracking-[0.22em] text-slate-500">{label}</p>
                    <p className="mt-4 text-4xl font-black tracking-tight text-slate-950">{value}</p>
                    <p className="mt-2 text-sm text-slate-500">{detail}</p>
                  </div>
                  <span className="rounded-xl bg-slate-100 p-3 text-slate-600">
                    <Icon className="h-6 w-6" />
                  </span>
                </div>
              </article>
            ))}
          </section>

          <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-2 border-b border-slate-200 pb-5 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="inline-flex items-center gap-2 text-sm font-bold text-slate-950">
                  <Filter className="h-4 w-4" />
                  Filtros de busca
                </p>
                <p className="mt-2 text-sm text-slate-500">Pesquise por pet, tutor, tipo de exame ou período de realização.</p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void handleClearFilters()}
                  className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-bold text-slate-700 transition hover:border-slate-400 hover:text-slate-950"
                >
                  Limpar
                </button>
                <button
                  type="submit"
                  form="partner-search-form"
                  disabled={searchLoading}
                  className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-teal-500 px-4 py-3 text-sm font-bold text-slate-950 transition hover:bg-teal-400 disabled:cursor-not-allowed disabled:bg-teal-200"
                >
                  {searchLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  Buscar exames
                </button>
              </div>
            </div>

            <form id="partner-search-form" className="mt-5 grid gap-4 lg:grid-cols-4" onSubmit={handleSearchSubmit}>
              <label className="block text-sm font-semibold text-slate-900 lg:col-span-1">
                Busca geral
                <input
                  type="text"
                  value={filters.q}
                  onChange={(event) => updateFilter("q", event.target.value)}
                  placeholder="Pet, tutor ou exame"
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Pet
                <input
                  type="text"
                  value={filters.pet}
                  onChange={(event) => updateFilter("pet", event.target.value)}
                  placeholder="Nome do pet"
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Tutor
                <input
                  type="text"
                  value={filters.tutor}
                  onChange={(event) => updateFilter("tutor", event.target.value)}
                  placeholder="Nome do tutor"
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Espécie
                <input
                  type="text"
                  value={filters.especie}
                  onChange={(event) => updateFilter("especie", event.target.value)}
                  placeholder="Canina, Felina..."
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Tipo de exame
                <input
                  type="text"
                  value={filters.tipo_exame}
                  onChange={(event) => updateFilter("tipo_exame", event.target.value)}
                  placeholder="Eco, Eletro, PA..."
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Data de realização - De
                <input
                  type="date"
                  value={filters.data_inicio}
                  onChange={(event) => updateFilter("data_inicio", event.target.value)}
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Data de realização - Até
                <input
                  type="date"
                  value={filters.data_fim}
                  onChange={(event) => updateFilter("data_fim", event.target.value)}
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Ordenação
                <select
                  value={`${filters.sort_by}:${filters.sort_dir}`}
                  onChange={(event) => {
                    const [sortBy, sortDir] = event.target.value.split(":");
                    updateFilter("sort_by", sortBy as PartnerSortBy);
                    updateFilter("sort_dir", sortDir as PartnerSortDir);
                  }}
                  className="mt-2 h-12 w-full rounded-xl border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition focus:border-teal-500"
                >
                  <option value="data:desc">Mais recentes por realização</option>
                  <option value="data:asc">Mais antigas por realização</option>
                  <option value="pet:asc">Pet de A a Z</option>
                  <option value="tutor:asc">Tutor de A a Z</option>
                  <option value="tipo_exame:asc">Tipo de exame</option>
                </select>
              </label>
            </form>
          </section>

          {message ? (
            <div className="mt-4 rounded-xl border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">
              {message}
            </div>
          ) : null}

          {error ? (
            <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
              {error}
            </div>
          ) : null}

          <section className="mt-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="inline-flex items-center gap-2 text-sm font-bold text-slate-950">
                  <SlidersHorizontal className="h-4 w-4" />
                  Exames liberados
                </p>
                <p className="mt-1 text-sm text-slate-500">{totalAvailable} resultado(s) liberado(s) para você.</p>
              </div>
            </div>

            {searchLoading && exams.length === 0 ? (
              <div className="mt-4 rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Carregando exames liberados para o parceiro...
                </span>
              </div>
            ) : exams.length === 0 ? (
              <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm leading-6 text-slate-600">
                {dashboardLoaded ? "Nenhum exame liberado foi encontrado para os filtros aplicados." : "Carregando o painel do parceiro..."}
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
                              {isDownloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                              <span className="max-w-52 truncate">{isDownloading ? "Baixando..." : attachment.nome_original}</span>
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
        </main>
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
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-teal-100">Acesso do parceiro</p>
              <h2 className="mt-2 text-xl font-bold text-white">Entrar como veterinário parceiro</h2>
            </div>
            <span className="rounded-lg bg-teal-300 px-3 py-2 text-xs font-bold text-slate-950">convite + senha</span>
          </div>

          {!showForgotPassword ? (
            <>
              {!mfaChallengeId ? (
                <form className="mt-5 space-y-4" onSubmit={handleLogin}>
                  <label className="block text-sm font-semibold text-white">
                    E-mail de acesso
                    <input
                      required
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      className="mt-2 w-full rounded-lg border border-white/15 bg-slate-950/60 px-3 py-2 text-sm text-white outline-none transition focus:border-teal-300"
                      placeholder="seuemail@dominio.com"
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
                    <span>Manter acesso neste computador até o fim do expediente.</span>
                  </label>

                  <button
                    type="submit"
                    disabled={requestLoading}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-teal-400 px-4 py-3 text-sm font-bold text-slate-950 transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:bg-teal-200"
                  >
                    {requestLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Stethoscope className="h-4 w-4" />}
                    {requestLoading ? "Entrando..." : "Entrar no portal do parceiro"}
                  </button>
                </form>
              ) : (
                <form className="mt-5 space-y-4 rounded-lg border border-white/15 bg-slate-950/50 p-4" onSubmit={handleVerifyMfa}>
                  <div className="flex items-start gap-3">
                    <CheckCircle2 className="mt-0.5 h-5 w-5 text-teal-200" />
                    <div>
                      <p className="text-sm font-bold text-white">Confirmação adicional</p>
                      <p className="mt-1 text-sm leading-6 text-slate-300">Enviamos um código para o e-mail cadastrado do parceiro.</p>
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
                  Recebeu um convite da Fort Cordis? Abra o link enviado para cadastrar sua senha e concluir a ativação.
                </div>

                <div className="inline-flex items-center gap-2 text-sm font-semibold text-slate-200">
                  <Mail className="h-4 w-4" />
                  Use sempre o e-mail profissional cadastrado para este acesso.
                </div>
              </div>
            </>
          ) : (
            <form className="mt-5 space-y-4" onSubmit={handleForgotPassword}>
              <div className="rounded-lg border border-white/10 bg-slate-950/30 p-4 text-sm leading-6 text-slate-300">
                Enviaremos as instruções de redefinição para o e-mail informado, se houver uma conta ativa de parceiro vinculada a ele.
              </div>

              <label className="block text-sm font-semibold text-white">
                E-mail de acesso
                <input
                  required
                  type="email"
                  value={resetEmail}
                  onChange={(event) => setResetEmail(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-white/15 bg-slate-950/60 px-3 py-2 text-sm text-white outline-none transition focus:border-teal-300"
                  placeholder="seuemail@dominio.com"
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
                  setMessage("");
                }}
                className="w-full rounded-lg border border-white/20 px-4 py-3 text-sm font-bold text-white transition hover:bg-white/10"
              >
                Voltar para login
              </button>
            </form>
          )}

          {message ? (
            <div className="mt-4 rounded-lg border border-teal-300/40 bg-teal-200/10 p-3 text-sm text-teal-50">
              {message}
            </div>
          ) : null}

          {error ? (
            <div className="mt-4 rounded-lg border border-rose-300/40 bg-rose-200/10 p-3 text-sm text-rose-50">
              {error}
            </div>
          ) : null}
        </>
      )}
    </aside>
  );
}
