"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import {
  DASHBOARD_SECTIONS,
  loadDashboardSection,
  type DashboardSection,
} from "@/lib/dashboard-loading";
import type { LucideIcon } from "lucide-react";
import { useRoutePerformanceReady } from "@/lib/use-route-performance-ready";
import {
  Activity,
  ArrowRight,
  Calendar,
  Users,
  Building2,
  Stethoscope,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  PawPrint,
  PlusCircle,
  RefreshCw
} from "lucide-react";

interface DashboardStats {
  totalAgendamentos: number;
  agendamentosHoje: number;
  confirmados: number;
  pendentes: number;
  totalPacientes: number;
  totalClinicas: number;
  totalServicos: number;
}

interface AgendamentoHoje {
  id: number;
  paciente: string;
  tutor: string;
  hora: string;
  status: string;
  servico: string;
}

type DashboardTone = "cordis" | "vital" | "ink" | "amber";
type MonitorTone = "ok" | "alert" | "network";
type DashboardSectionState = "loading" | "success" | "failed" | "idle";

const DASHBOARD_SECTION_LABELS: Record<DashboardSection, string> = {
  agenda: "Agenda de hoje",
  pacientes: "Pacientes",
  clinicas: "Clínicas",
  servicos: "Serviços",
};

const createInitialSectionStates = (): Record<DashboardSection, DashboardSectionState> => ({
  agenda: "loading",
  pacientes: "loading",
  clinicas: "loading",
  servicos: "loading",
});

interface DashboardMetric {
  label: string;
  value: number | string;
  Icon: LucideIcon;
  tone: DashboardTone;
  detail: string;
  signal: string;
}

interface QuickAction {
  href: string;
  label: string;
  caption: string;
  Icon: LucideIcon;
  tone: DashboardTone;
  primary?: boolean;
}

const formatLocalDateForApi = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

function EcgTrace({ compact = false, stretched = false }: { compact?: boolean; stretched?: boolean }) {
  return (
    <svg
      viewBox={compact ? "0 0 130 28" : "0 0 620 250"}
      preserveAspectRatio={stretched ? "none" : undefined}
      aria-hidden="true"
    >
      {compact ? (
        <path
          d="M2 16H18C23 16 25 12 30 12C35 12 37 16 42 16H52L56 20L62 5L69 25L76 16H84C93 16 96 10 106 10C116 10 119 16 128 16"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2.5"
        />
      ) : (
        <>
          <defs>
            <linearGradient id="fc-hero-wave" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#fecdd3" />
              <stop offset="52%" stopColor="#ffffff" />
              <stop offset="100%" stopColor="#5eead4" />
            </linearGradient>
          </defs>
          <path
            d="M14 136H66C78 136 83 124 94 124C106 124 112 136 126 136H154L166 154L184 72L206 196L228 136H250C276 136 286 116 316 116C346 116 356 136 382 136H416C428 136 433 124 444 124C456 124 462 136 476 136H504L516 154L534 76L556 190L578 136H592C606 136 612 126 620 126"
            fill="none"
            stroke="url(#fc-hero-wave)"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="10"
          />
          <path
            d="M14 137H604"
            fill="none"
            stroke="rgba(255,255,255,0.14)"
            strokeDasharray="7 22"
            strokeWidth="3"
          />
          <circle cx="184" cy="72" r="8" fill="#14b8a6" />
          <circle cx="534" cy="76" r="8" fill="#14b8a6" />
        </>
      )}
    </svg>
  );
}

function MetricCard({ metric }: { metric: DashboardMetric }) {
  const Icon = metric.Icon;

  return (
    <article className={`fc-metric-tile fc-metric-${metric.tone}`}>
      <div className="fc-metric-icon">
        <Icon className="h-5 w-5" />
      </div>
      <span className="fc-metric-signal">{metric.signal}</span>
      <div className="fc-metric-main">
        <strong>{metric.value}</strong>
        <span>{metric.label}</span>
      </div>
      <p>{metric.detail}</p>
      <div className="fc-mini-wave" aria-hidden="true">
        <EcgTrace compact />
      </div>
    </article>
  );
}

function QuickActionLink({ action }: { action: QuickAction }) {
  const Icon = action.Icon;

  return (
    <Link
      href={action.href}
      className={`group fc-action-command fc-action-command-${action.tone} ${
        action.primary ? "fc-action-command-primary" : ""
      }`}
    >
      <span className="fc-action-icon">
        <Icon className="h-5 w-5" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-black">{action.label}</span>
        <span className="block truncate text-xs font-semibold text-ink-500 group-hover:text-cordis-600">
          {action.caption}
        </span>
      </span>
      <ArrowRight className="h-4 w-4 justify-self-end opacity-40 transition group-hover:translate-x-1 group-hover:opacity-100" />
    </Link>
  );
}

function DashboardLoadingState() {
  return (
    <div className="fc-dashboard-skeleton" role="status" aria-label="Carregando dashboard">
      {[0, 1, 2, 3].map((item) => (
        <span key={item} className="fc-skeleton-card" />
      ))}
    </div>
  );
}

function DashboardErrorState({
  failedSections,
  isRetrying,
  onRetry,
}: {
  failedSections: DashboardSection[];
  isRetrying: boolean;
  onRetry: () => void;
}) {
  const allSectionsFailed = failedSections.length === DASHBOARD_SECTIONS.length;

  return (
    <section className="fc-error-panel" role="alert">
      <div>
        <span>{allSectionsFailed ? "Sincronização interrompida" : "Dados parciais"}</span>
        <h2>
          {allSectionsFailed
            ? "Não foi possível atualizar o painel"
            : "Alguns indicadores não foram atualizados"}
        </h2>
        <p>
          {allSectionsFailed
            ? "Confira a conexão com o servidor e tente sincronizar novamente."
            : `Indisponível agora: ${failedSections.map((section) => DASHBOARD_SECTION_LABELS[section]).join(", ")}.`}
        </p>
      </div>
      <button type="button" onClick={onRetry} disabled={isRetrying}>
        <RefreshCw className="h-4 w-4" />
        {isRetrying ? "Atualizando" : "Tentar novamente"}
      </button>
    </section>
  );
}

function EmptyAgendaState() {
  return (
    <div className="fc-empty-stage">
      <div className="fc-empty-visual" aria-hidden="true">
        <div className="fc-empty-badge">
          <Calendar className="h-5 w-5" />
          <span>0</span>
        </div>
        <EcgTrace stretched />
      </div>
      <div>
        <p className="fc-empty-title">Agenda em repouso</p>
        <p className="fc-empty-copy">
          Nenhum agendamento para hoje. Use a agenda para criar o próximo horário clínico.
        </p>
        <Link href="/agenda" className="fc-empty-action">
          <PlusCircle className="h-4 w-4" />
          Criar agendamento
        </Link>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats>({
    totalAgendamentos: 0,
    agendamentosHoje: 0,
    confirmados: 0,
    pendentes: 0,
    totalPacientes: 0,
    totalClinicas: 0,
    totalServicos: 0,
  });
  const [agendamentosHoje, setAgendamentosHoje] = useState<AgendamentoHoje[]>([]);
  const [sectionStates, setSectionStates] = useState<Record<DashboardSection, DashboardSectionState>>(
    createInitialSectionStates
  );
  const activeRequestController = useRef<AbortController | null>(null);

  const carregarDados = useCallback(async (requestedSections: DashboardSection[] = [...DASHBOARD_SECTIONS]) => {
    activeRequestController.current?.abort();
    const controller = new AbortController();
    activeRequestController.current = controller;
    const sections = requestedSections.filter((section, index) => requestedSections.indexOf(section) === index);

    setSectionStates((current) => {
      const next = { ...current };
      sections.forEach((section) => {
        next[section] = "loading";
      });
      return next;
    });

    const hoje = formatLocalDateForApi(new Date());
    const loads = sections.map((section) => {
      const trackResult = (result: Awaited<ReturnType<typeof loadDashboardSection>>) => {
        const status = (result.error as { response?: { status?: number } } | undefined)?.response?.status;
        if (result.status === "failed" && status !== 401) {
          console.error(`Erro ao carregar ${DASHBOARD_SECTION_LABELS[result.section]}:`, result.error);
          setSectionStates((current) => ({ ...current, [result.section]: "failed" }));
        }
        return result;
      };

      if (section === "agenda") {
        return loadDashboardSection({
          section,
          request: api.get(`/agenda?data_inicio=${hoje}T00:00:00&data_fim=${hoje}T23:59:59`, {
            signal: controller.signal,
          }),
          signal: controller.signal,
          onSuccess: (response) => {
            const agendamentos = response.data.items || [];
            const confirmados = agendamentos.filter((item: any) => item.status === "Confirmado").length;
            const pendentes = agendamentos.filter(
              (item: any) => item.status === "Agendado" || item.status === "Reservado"
            ).length;

            setStats((current) => ({
              ...current,
              totalAgendamentos: agendamentos.length,
              agendamentosHoje: agendamentos.length,
              confirmados,
              pendentes,
            }));
            setAgendamentosHoje(
              agendamentos
                .sort((a: any, b: any) => new Date(a.inicio).getTime() - new Date(b.inicio).getTime())
                .slice(0, 5)
                .map((item: any) => ({
                  id: item.id,
                  paciente: item.paciente,
                  tutor: item.tutor,
                  hora: new Date(item.inicio).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }),
                  status: item.status,
                  servico: item.servico,
                }))
            );
            setSectionStates((current) => ({ ...current, agenda: "success" }));
          },
        }).then(trackResult);
      }

      return loadDashboardSection({
        section,
        request: api.get(`/${section}`, { signal: controller.signal }),
        signal: controller.signal,
        onSuccess: (response) => {
          setStats((current) => ({
            ...current,
            [`total${section.charAt(0).toUpperCase()}${section.slice(1)}`]: response.data.total || 0,
          }));
          setSectionStates((current) => ({ ...current, [section]: "success" }));
        },
      }).then(trackResult);
    });

    const results = await Promise.all(loads);
    if (controller.signal.aborted) {
      return;
    }

    const unauthorized = results.some(
      (result) => result.status === "failed" && (result.error as { response?: { status?: number } })?.response?.status === 401
    );
    if (unauthorized) {
      setSectionStates((current) => {
        const next = { ...current };
        sections.forEach((section) => {
          next[section] = "idle";
        });
        return next;
      });
      if (activeRequestController.current === controller) {
        activeRequestController.current = null;
      }
      return;
    }

    if (activeRequestController.current === controller) {
      activeRequestController.current = null;
    }
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined" && !localStorage.getItem("token")) {
      setSectionStates((current) => {
        const next = { ...current };
        DASHBOARD_SECTIONS.forEach((section) => {
          next[section] = "idle";
        });
        return next;
      });
      return;
    }

    void carregarDados();
    return () => activeRequestController.current?.abort();
  }, [carregarDados]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'Confirmado': return <CheckCircle2 className="w-5 h-5 text-vital-600" />;
      case 'Cancelado': return <XCircle className="w-5 h-5 text-cordis-600" />;
      case 'Agendado': return <Clock className="w-5 h-5 text-cordis-600" />;
      case 'Reservado': return <Clock className="w-5 h-5 text-amber-600" />;
      default: return <AlertCircle className="w-5 h-5 text-ink-500" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'Confirmado': return 'border-vital-100 bg-vital-50 text-vital-700';
      case 'Cancelado': return 'border-cordis-100 bg-cordis-50 text-cordis-700';
      case 'Agendado': return 'border-cordis-100 bg-cordis-50 text-cordis-700';
      case 'Reservado': return 'border-amber-100 bg-amber-50 text-amber-700';
      default: return 'border-ink-100 bg-ink-50 text-ink-700';
    }
  };

  const hojeFormatado = new Intl.DateTimeFormat("pt-BR", {
    weekday: "long",
    day: "2-digit",
    month: "short",
  }).format(new Date());

  const isLoading = DASHBOARD_SECTIONS.some((section) => sectionStates[section] === "loading");
  const hasLoadedSection = DASHBOARD_SECTIONS.some((section) => sectionStates[section] === "success");
  const failedSections = DASHBOARD_SECTIONS.filter((section) => sectionStates[section] === "failed");
  const dashboardOutcome = failedSections.length === 0
    ? "ready"
    : failedSections.length === DASHBOARD_SECTIONS.length
      ? "error"
      : "partial";
  useRoutePerformanceReady(isLoading, dashboardOutcome);
  const displayValue = (section: DashboardSection, value: number) =>
    sectionStates[section] === "success" ? value : "—";
  const detailForSection = (section: DashboardSection, defaultDetail: string) => {
    if (sectionStates[section] === "failed") {
      return "Dados indisponíveis — tente novamente";
    }
    if (sectionStates[section] === "loading") {
      return "Atualizando dados";
    }
    return defaultDetail;
  };

  const commandStats: Array<{ label: string; value: number | string; tone: MonitorTone }> = [
    {
      label: "confirmados",
      value: displayValue("agenda", stats.confirmados),
      tone: "ok",
    },
    {
      label: "pendentes",
      value: displayValue("agenda", stats.pendentes),
      tone: "alert",
    },
    {
      label: "clinicas",
      value: displayValue("clinicas", stats.totalClinicas),
      tone: "network",
    },
  ];

  const boardMetrics: DashboardMetric[] = [
    {
      label: "Agendamentos hoje",
      value: displayValue("agenda", stats.agendamentosHoje),
      Icon: Calendar,
      tone: "cordis",
      detail: detailForSection("agenda", `${stats.confirmados} confirmados / ${stats.pendentes} pendentes`),
      signal: "Dia clínico",
    },
    {
      label: "Pacientes",
      value: displayValue("pacientes", stats.totalPacientes),
      Icon: Users,
      tone: "vital",
      detail: detailForSection("pacientes", "Total cadastrados"),
      signal: "Carteira ativa",
    },
    {
      label: "Clínicas",
      value: displayValue("clinicas", stats.totalClinicas),
      Icon: Building2,
      tone: "ink",
      detail: detailForSection("clinicas", "Parceiras ativas"),
      signal: "Rede assistida",
    },
    {
      label: "Serviços",
      value: displayValue("servicos", stats.totalServicos),
      Icon: Stethoscope,
      tone: "amber",
      detail: detailForSection("servicos", "Disponíveis"),
      signal: "Catálogo",
    },
  ];

  const quickActions: QuickAction[] = [
    {
      href: "/agenda",
      label: "Criar agendamento",
      caption: "Novo horário clínico",
      Icon: PlusCircle,
      tone: "cordis",
      primary: true,
    },
    {
      href: "/agenda",
      label: "Ver agenda",
      caption: "Agenda do dia",
      Icon: Calendar,
      tone: "cordis",
    },
    {
      href: "/pacientes",
      label: "Pacientes",
      caption: "Base clínica",
      Icon: Users,
      tone: "vital",
    },
    {
      href: "/clinicas",
      label: "Clínicas",
      caption: "Rede parceira",
      Icon: Building2,
      tone: "ink",
    },
    {
      href: "/servicos",
      label: "Serviços",
      caption: "Catálogo",
      Icon: Stethoscope,
      tone: "amber",
    },
  ];

  return (
    <DashboardLayout>
      <div className="fc-page fc-dashboard-page">
        <section className="fc-dashboard-hero" aria-label="Resumo operacional Fort Cordis">
          <div className="fc-hero-copy">
            <div className="fc-hero-brand">
              <div className="fc-hero-brand-card">
                <img
                  src="/brand/fortcordis-logo-oficial.png"
                  alt="Fort Cordis"
                  className="fc-command-seal"
                />
                <div>
                  <span>Fort Cordis</span>
                  <small>Cardiologia veterinária</small>
                </div>
              </div>
            </div>

            <div className="fc-hero-kicker">
              <Activity className="h-4 w-4" />
              Central clínica
            </div>
            <h1 className="fc-hero-title">Painel operacional Fort Cordis</h1>
            <p className="fc-hero-subtitle">Agenda, pacientes e rede de atendimento em uma leitura rápida.</p>
            <div className="fc-hero-tags">
              <span>
                <Clock className="h-4 w-4" />
                {hojeFormatado}
              </span>
              <span>
                <PawPrint className="h-4 w-4" />
                {isLoading ? "Sincronizando" : "Operação local"}
              </span>
            </div>
          </div>

          <div className="fc-heart-console" aria-label="ECG operacional e indicadores de status">
            <div className="fc-monitor-topline">
              <span>ECG operacional</span>
              <span>ao vivo</span>
            </div>
            <div className="fc-monitor-screen">
              <EcgTrace />
            </div>
            <div className="fc-monitor-footer">
              {commandStats.map((item) => (
                <div key={item.label} className={`fc-monitor-chip fc-monitor-chip-${item.tone}`}>
                  <strong>{item.value}</strong>
                  <span>{item.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="fc-today-orbit">
            <span>Hoje</span>
            <div className="fc-today-summary">
              <strong>{displayValue("agenda", stats.agendamentosHoje)}</strong>
              <small>eventos clínicos</small>
            </div>
            <div className="fc-today-breakdown">
              <span>{displayValue("agenda", stats.confirmados)} confirmados</span>
              <span>{displayValue("agenda", stats.pendentes)} pendentes</span>
              <span>{displayValue("clinicas", stats.totalClinicas)} clínicas</span>
            </div>
          </div>
        </section>

        {isLoading && !hasLoadedSection && failedSections.length === 0 ? (
          <DashboardLoadingState />
        ) : (
          <>
            {failedSections.length > 0 && (
              <DashboardErrorState
                failedSections={failedSections}
                isRetrying={isLoading}
                onRetry={() => void carregarDados(failedSections)}
              />
            )}
            <section className="fc-metric-ribbon" aria-label="Indicadores principais">
              {boardMetrics.map((metric) => (
                <MetricCard key={metric.label} metric={metric} />
              ))}
            </section>

            <div className="fc-dashboard-workbench">
              <section className="fc-agenda-theater">
                <div className="fc-section-heading">
                  <div>
                    <span>Agenda de hoje</span>
                    <h2>Fluxo clínico</h2>
                  </div>
                  <div className="fc-section-actions">
                    <strong>{sectionStates.agenda === "success" ? agendamentosHoje.length : "—"}</strong>
                    <Link href="/agenda" className="fc-section-button">Abrir agenda</Link>
                  </div>
                </div>
                <div className="fc-agenda-stage">
                  {sectionStates.agenda === "loading" ? (
                    <div className="fc-empty-stage" role="status">
                      <p className="fc-empty-title">Atualizando agenda</p>
                      <p className="fc-empty-copy">Buscando os horários clínicos de hoje.</p>
                    </div>
                  ) : sectionStates.agenda === "failed" ? (
                    <div className="fc-empty-stage" role="alert">
                      <p className="fc-empty-title">Agenda indisponível no momento</p>
                      <p className="fc-empty-copy">Os demais indicadores continuam disponíveis.</p>
                      <button
                        type="button"
                        className="fc-empty-action"
                        onClick={() => void carregarDados(["agenda"])}
                        disabled={isLoading}
                      >
                        <RefreshCw className="h-4 w-4" />
                        Tentar atualizar agenda
                      </button>
                    </div>
                  ) : agendamentosHoje.length === 0 ? (
                    <EmptyAgendaState />
                  ) : (
                    <div className="fc-timeline">
                      {agendamentosHoje.map((ag) => (
                        <div key={ag.id} className="fc-timeline-row">
                          <div className="fc-timeline-time">{ag.hora}</div>
                          <div className="fc-timeline-dot">
                            {getStatusIcon(ag.status)}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="truncate font-medium text-ink-900">{ag.paciente}</p>
                            <p className="truncate text-sm text-ink-500">{ag.tutor}</p>
                            {ag.servico && (
                              <p className="text-xs text-ink-400">{ag.servico}</p>
                            )}
                          </div>
                          <div className="text-right">
                            <span className={`rounded-full border px-2 py-1 text-xs ${getStatusColor(ag.status)}`}>
                              {ag.status}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>

              <section className="fc-action-dock">
                <div className="fc-section-heading">
                  <div>
                    <span>Ações rápidas</span>
                    <h2>Atalhos</h2>
                  </div>
                </div>
                <div className="fc-action-list">
                  {quickActions.map((action) => (
                    <QuickActionLink key={`${action.href}-${action.label}`} action={action} />
                  ))}
                </div>
              </section>
            </div>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
