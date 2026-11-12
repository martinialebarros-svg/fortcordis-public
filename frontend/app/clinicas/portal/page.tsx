"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUpRight,
  Building2,
  CheckCircle2,
  DoorClosed,
  Copy,
  Download,
  ExternalLink,
  KeyRound,
  ListRestart,
  Link2,
  Loader2,
  Mail,
  MessageCircle,
  RefreshCcw,
  Search,
  Send,
  ShieldCheck,
  TriangleAlert,
  UserMinus,
  UsersRound,
} from "lucide-react";

import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import {
  formatarWhatsAppVisual,
  normalizarWhatsappsParaApi,
} from "@/lib/clinica-whatsapp";
import { buildClinicInviteMessage, getPortalAdminAuthHeaders } from "@/lib/portal-clinic-admin";
import { formatPortalDateTime, portalDateTimeMillis } from "@/lib/portal-datetime";
import type {
  PortalAdminClinicAccessOverviewItem,
  PortalAdminClinicAccessOverviewResponse,
  PortalAdminClinicInviteResponse,
  PortalAdminClinicTimelineEvent,
} from "@/lib/portal-api";

type StatusFilter =
  | "all"
  | "active"
  | "invited_pending"
  | "needs_email"
  | "not_invited"
  | "locked"
  | "pending_verification";

type InviteRequestParams = {
  clinicaId: number;
  clinicaNome: string;
  deliveryTarget: string;
  inviteEmail: string;
  expiresInHours: string;
  senhaTemporaria: boolean;
  responsavelNome: string;
};

type QuickView =
  | "all"
  | "needs_attention"
  | "never_accessed"
  | "expired_invites"
  | "recent_downloads"
  | "inactive_30d"
  | "first_download_completed";
type TimelineTone = PortalAdminClinicTimelineEvent["tone"];

const STATUS_FILTER_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "Todas as clinicas" },
  { value: "active", label: "Cadastro concluido" },
  { value: "invited_pending", label: "Convite pendente" },
  { value: "needs_email", label: "Precisam informar email" },
  { value: "not_invited", label: "Sem convite" },
  { value: "pending_verification", label: "Cadastro pendente" },
  { value: "locked", label: "Conta bloqueada" },
];

function hasRecentDownload(item: PortalAdminClinicAccessOverviewItem, days = 7): boolean {
  const timestamp = portalDateTimeMillis(item.last_download_at);
  if (!Number.isFinite(timestamp)) {
    return false;
  }
  return timestamp >= Date.now() - days * 24 * 60 * 60 * 1000;
}

function hasFirstDownload(item: PortalAdminClinicAccessOverviewItem): boolean {
  return Boolean(item.first_download_at);
}

function getLatestPortalActivityMillis(item: PortalAdminClinicAccessOverviewItem): number {
  const explicitTimestamp = portalDateTimeMillis(item.last_access_at);
  if (Number.isFinite(explicitTimestamp)) {
    return explicitTimestamp;
  }

  const timestamps = [
    portalDateTimeMillis(item.account?.last_login_at),
    portalDateTimeMillis(item.last_download_at),
  ].filter((value) => Number.isFinite(value));

  return timestamps.length > 0 ? Math.max(...timestamps) : Number.NaN;
}

function hasNeverAccessed(item: PortalAdminClinicAccessOverviewItem): boolean {
  return !item.account?.last_login_at && item.active_session_count === 0 && item.download_count === 0;
}

function isInactiveForDays(item: PortalAdminClinicAccessOverviewItem, days = 30): boolean {
  if (item.status_key !== "active") {
    return false;
  }

  if (typeof item.days_since_last_activity === "number") {
    return item.days_since_last_activity >= days;
  }

  const latestActivity = getLatestPortalActivityMillis(item);
  if (!Number.isFinite(latestActivity)) {
    return true;
  }

  return latestActivity < Date.now() - days * 24 * 60 * 60 * 1000;
}

function getInactivityAlert(item: PortalAdminClinicAccessOverviewItem): {
  tone: TimelineTone;
  title: string;
  description: string;
} | null {
  if (item.status_key !== "active") {
    return null;
  }

  const inactiveDays = item.days_since_last_activity;
  if (typeof inactiveDays !== "number" || inactiveDays < 30) {
    return null;
  }

  if (inactiveDays >= 60) {
    return {
      tone: "danger",
      title: `Sem acesso ha ${inactiveDays} dias`,
      description: "Vale revisar se a unidade perdeu o acesso, se precisa de novo convite ou se o relacionamento esfriou.",
    };
  }

  return {
    tone: "warning",
    title: `Sem acesso ha ${inactiveDays} dias`,
    description: "Bom momento para retomar o contato e incentivar o uso do portal pela equipe da clinica.",
  };
}

function formatPercent(numerator: number, denominator: number): string {
  if (!denominator) {
    return "0%";
  }

  return `${Math.round((numerator / denominator) * 100)}%`;
}

function csvEscape(value: unknown): string {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

function needsOperationalAttention(item: PortalAdminClinicAccessOverviewItem): boolean {
  return (
    item.needs_email_definition ||
    item.status_key === "not_invited" ||
    item.status_key === "invite_expired" ||
    item.status_key === "pending_verification" ||
    item.status_key === "locked"
  );
}

function buildStatusClasses(item: PortalAdminClinicAccessOverviewItem): string {
  if (item.needs_email_definition || item.status_key === "needs_email") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  if (item.status_key === "active") {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (item.status_key === "invited_pending" || item.status_key === "pending_verification") {
    return "border-sky-200 bg-sky-50 text-sky-800";
  }
  if (item.status_key === "locked" || item.status_key === "account_revoked" || item.status_key === "invite_revoked") {
    return "border-rose-200 bg-rose-50 text-rose-800";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function buildStatusDescription(item: PortalAdminClinicAccessOverviewItem): string {
  if (item.account?.email_masked) {
    return `Login atual: ${item.account.email_masked}`;
  }
  if (item.invite_account_email_masked) {
    return `Email previsto: ${item.invite_account_email_masked}`;
  }
  if (item.contato_email) {
    return `Contato cadastrado: ${item.contato_email}`;
  }
  return "Email institucional ainda nao definido.";
}

function buildClinicLocation(item: PortalAdminClinicAccessOverviewItem): string {
  const values = [item.cidade, item.estado].filter(Boolean);
  return values.length ? values.join(" / ") : "Localizacao nao informada";
}

function buildTimelineToneClasses(tone: TimelineTone): string {
  if (tone === "success") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  if (tone === "danger") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function TimelineIcon({ eventType, tone }: { eventType: string; tone: TimelineTone }) {
  if (eventType === "download") {
    return <Download className="h-4 w-4" />;
  }
  if (eventType.startsWith("invite")) {
    return <KeyRound className="h-4 w-4" />;
  }
  if (eventType === "account_revoked") {
    return <UserMinus className="h-4 w-4" />;
  }
  if (tone === "success") {
    return <CheckCircle2 className="h-4 w-4" />;
  }
  if (tone === "warning" || tone === "danger") {
    return <TriangleAlert className="h-4 w-4" />;
  }
  return <Mail className="h-4 w-4" />;
}

function buildQuickInviteLabel(item: PortalAdminClinicAccessOverviewItem): string {
  if (item.invite?.status === "pending" || item.invite?.status === "expired" || item.invite?.status === "revoked") {
    return "Reenviar convite";
  }
  if (item.account) {
    return "Atualizar acesso";
  }
  return "Enviar convite";
}

function matchesStatusFilter(item: PortalAdminClinicAccessOverviewItem, statusFilter: StatusFilter): boolean {
  if (statusFilter === "all") {
    return true;
  }
  if (statusFilter === "needs_email") {
    return item.needs_email_definition;
  }
  return item.status_key === statusFilter;
}

function getSuggestedClinic(items: PortalAdminClinicAccessOverviewItem[]): PortalAdminClinicAccessOverviewItem | null {
  return (
    items.find((item) => item.needs_email_definition) ||
    items.find((item) => item.status_key === "not_invited") ||
    items.find((item) => item.status_key === "invited_pending") ||
    items[0] ||
    null
  );
}

export default function PortalClinicManagementPage() {
  const inviteComposerRef = useRef<HTMLDivElement | null>(null);
  const [overview, setOverview] = useState<PortalAdminClinicAccessOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoadingKey, setActionLoadingKey] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [quickView, setQuickView] = useState<QuickView>("all");
  const [firstDownloadOnly, setFirstDownloadOnly] = useState(false);
  const [selectedClinicId, setSelectedClinicId] = useState("");
  const [deliveryTarget, setDeliveryTarget] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [expiresInHours, setExpiresInHours] = useState("72");
  const [senhaTemporaria, setSenhaTemporaria] = useState(false);
  const [responsavelNome, setResponsavelNome] = useState("");
  const [generatedInvite, setGeneratedInvite] = useState<PortalAdminClinicInviteResponse | null>(null);
  const [generatedClinicName, setGeneratedClinicName] = useState("");
  const [lastInviteRequest, setLastInviteRequest] = useState<InviteRequestParams | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selectedClinic = useMemo(
    () => overview?.items.find((item) => String(item.clinica_id) === selectedClinicId) || null,
    [overview?.items, selectedClinicId],
  );

  const inviteMessage = useMemo(() => {
    if (!generatedInvite?.activation_url || !generatedClinicName) {
      return "";
    }
    return buildClinicInviteMessage({
      clinicaNome: generatedClinicName,
      activationUrl: generatedInvite.activation_url,
      accessMode: generatedInvite.access_mode,
      expiresAt: generatedInvite.expires_at,
      accountEmailMasked: generatedInvite.account_email_masked,
    });
  }, [generatedClinicName, generatedInvite]);

  const filteredItems = useMemo(() => {
    const baseItems = overview?.items || [];
    const normalizedSearch = search.trim().toLowerCase();

    return baseItems.filter((item) => {
      if (quickView === "needs_attention" && !needsOperationalAttention(item)) {
        return false;
      }
      if (quickView === "never_accessed" && !hasNeverAccessed(item)) {
        return false;
      }
      if (quickView === "expired_invites" && item.status_key !== "invite_expired") {
        return false;
      }
      if (quickView === "recent_downloads" && !hasRecentDownload(item)) {
        return false;
      }
      if (quickView === "inactive_30d" && !isInactiveForDays(item, 30)) {
        return false;
      }
      if (quickView === "first_download_completed" && !hasFirstDownload(item)) {
        return false;
      }
      if (!matchesStatusFilter(item, statusFilter)) {
        return false;
      }
      if (firstDownloadOnly && !hasFirstDownload(item)) {
        return false;
      }
      if (!normalizedSearch) {
        return true;
      }

      const haystack = [
        item.clinica_nome,
        item.contato_email,
        item.contato_whatsapp,
        item.login_email,
        item.cidade,
        item.estado,
        item.account?.email_masked,
        item.invite_account_email_masked,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return haystack.includes(normalizedSearch);
    });
  }, [firstDownloadOnly, overview?.items, quickView, search, statusFilter]);

  const pendingOperationalItems = useMemo(
    () => (overview?.items || []).filter((item) => needsOperationalAttention(item)).length,
    [overview?.items],
  );

  const managementQueue = useMemo(() => {
    const items = overview?.items || [];
    return {
      needsAttention: items.filter((item) => needsOperationalAttention(item)).length,
      neverAccessed: items.filter((item) => hasNeverAccessed(item)).length,
      expiredInvites: items.filter((item) => item.status_key === "invite_expired").length,
      recentDownloads: items.filter((item) => hasRecentDownload(item)).length,
      inactive30d: items.filter((item) => isInactiveForDays(item, 30)).length,
      firstDownloadCompleted: items.filter((item) => hasFirstDownload(item)).length,
    };
  }, [overview?.items]);

  const adoptionMetrics = useMemo(() => {
    const items = overview?.items || [];
    const totalClinics = items.length;
    const activeAccounts = items.filter((item) => item.status_key === "active").length;
    const inactive30d = items.filter((item) => isInactiveForDays(item, 30)).length;
    const activeWithRecentActivity = items.filter(
      (item) => item.status_key === "active" && !isInactiveForDays(item, 30),
    ).length;

    return {
      adoptionRateLabel: formatPercent(activeAccounts, totalClinics),
      inactive30d,
      activeWithRecentActivity,
      activeAccounts,
    };
  }, [overview?.items]);

  async function loadOverview() {
    setLoading(true);
    setError("");
    try {
      const response = await api.get<PortalAdminClinicAccessOverviewResponse>(
        "/portal/admin/clinicas/acessos/painel",
        { headers: getPortalAdminAuthHeaders() },
      );
      setOverview(response.data);
      setSelectedClinicId((currentValue) => {
        if (currentValue && response.data.items.some((item) => String(item.clinica_id) === currentValue)) {
          return currentValue;
        }
        const suggestedClinic = getSuggestedClinic(response.data.items);
        return suggestedClinic ? String(suggestedClinic.clinica_id) : "";
      });
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel carregar a gestao do portal."));
    } finally {
      setLoading(false);
    }
  }

  function focusInviteComposer(item: PortalAdminClinicAccessOverviewItem) {
    setSelectedClinicId(String(item.clinica_id));
    setDeliveryTarget(formatarWhatsAppVisual(item.contato_whatsapp));
    setInviteEmail(item.login_email || item.contato_email || "");
    setMessage("");
    setError("");
    inviteComposerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  useEffect(() => {
    void loadOverview();
  }, []);

  useEffect(() => {
    if (!selectedClinic) {
      return;
    }
    setDeliveryTarget(formatarWhatsAppVisual(selectedClinic.contato_whatsapp));
    setInviteEmail(selectedClinic.login_email || selectedClinic.contato_email || "");
  }, [selectedClinic]);

  async function handleGenerateInvite(overrides?: InviteRequestParams) {
    const clinicaId = overrides?.clinicaId ?? selectedClinic?.clinica_id;
    const clinicaNome = overrides?.clinicaNome ?? selectedClinic?.clinica_nome;
    if (!clinicaId || !clinicaNome) {
      setError("Selecione a clinica que vai receber o convite.");
      return;
    }
    const requestDeliveryTarget = overrides?.deliveryTarget ?? deliveryTarget;
    if (!requestDeliveryTarget.trim()) {
      setError("Informe o WhatsApp da clinica para envio do convite.");
      return;
    }
    const normalizedDeliveryTarget = normalizarWhatsappsParaApi([requestDeliveryTarget])[0] || "";
    const requestInviteEmail = (overrides?.inviteEmail ?? inviteEmail).trim();
    if (!requestInviteEmail) {
      setError("Informe o email institucional que sera usado pela clinica no login.");
      return;
    }
    const requestSenhaTemporaria = overrides?.senhaTemporaria ?? senhaTemporaria;
    const requestResponsavelNome = (overrides?.responsavelNome ?? responsavelNome).trim();
    if (requestSenhaTemporaria && !requestResponsavelNome) {
      setError("Informe o nome do responsavel na clinica para gerar a senha temporaria.");
      return;
    }
    const requestExpiresInHours = overrides?.expiresInHours ?? expiresInHours;

    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      const response = await api.post<PortalAdminClinicInviteResponse>(
        `/portal/admin/clinicas/${clinicaId}/convites`,
        {
          delivery_channel: "whatsapp",
          delivery_target: normalizedDeliveryTarget,
          account_email: requestInviteEmail,
          expires_in_hours: Number.parseInt(requestExpiresInHours, 10) || 72,
          allow_manual_copy: true,
          senha_temporaria: requestSenhaTemporaria,
          responsavel_nome: requestSenhaTemporaria ? requestResponsavelNome : undefined,
        },
        { headers: getPortalAdminAuthHeaders() },
      );
      setGeneratedInvite(response.data);
      setGeneratedClinicName(clinicaNome);
      setLastInviteRequest({
        clinicaId,
        clinicaNome,
        deliveryTarget: normalizedDeliveryTarget,
        inviteEmail: requestInviteEmail,
        expiresInHours: requestExpiresInHours,
        senhaTemporaria: requestSenhaTemporaria,
        responsavelNome: requestResponsavelNome,
      });
      setMessage(
        response.data.access_mode === "login"
          ? response.data.delivery_status === "sent"
            ? "Acesso reenviado com sucesso. O link e a mensagem continuam disponiveis abaixo."
            : "Acesso pronto. Copie a mensagem e encaminhe pelo WhatsApp da clinica."
          : response.data.access_mode === "temporary_password"
            ? "Conta criada com senha temporaria. Copie a senha agora - ela nao aparece de novo."
            : response.data.delivery_status === "sent"
              ? "Convite enviado com sucesso. O link e a mensagem continuam disponiveis abaixo."
              : "Convite gerado. Copie a mensagem e encaminhe pelo WhatsApp da clinica.",
      );
      if (response.data.access_mode === "activation" || response.data.access_mode === "temporary_password") {
        setResponsavelNome("");
      }
      await loadOverview();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel gerar o convite da clinica."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopyLink() {
    if (!generatedInvite?.activation_url) {
      return;
    }
    try {
      await navigator.clipboard.writeText(generatedInvite.activation_url);
      setMessage(generatedInvite.access_mode === "login" ? "Link de acesso copiado." : "Link de ativacao copiado.");
    } catch {
      setError("Nao foi possivel copiar o link automaticamente.");
    }
  }

  async function handleCopySenhaTemporaria() {
    if (!generatedInvite?.senha_temporaria) {
      return;
    }
    try {
      await navigator.clipboard.writeText(generatedInvite.senha_temporaria);
      setMessage("Senha temporaria copiada.");
    } catch {
      setError("Nao foi possivel copiar a senha automaticamente.");
    }
  }

  async function handleCopyMessage() {
    if (!inviteMessage) {
      return;
    }
    try {
      await navigator.clipboard.writeText(inviteMessage);
      setMessage("Mensagem do convite copiada.");
    } catch {
      setError("Nao foi possivel copiar a mensagem automaticamente.");
    }
  }

  async function handleResendWhatsapp() {
    if (!lastInviteRequest) {
      return;
    }
    await handleGenerateInvite(lastInviteRequest);
  }

  function handleResetFilters() {
    setSearch("");
    setStatusFilter("all");
    setQuickView("all");
    setFirstDownloadOnly(false);
  }

  async function handleQuickInvite(item: PortalAdminClinicAccessOverviewItem) {
    const deliveryTargetValue = (item.contato_whatsapp || "").trim();
    const inviteEmailValue = (item.login_email || item.contato_email || "").trim();

    if (!deliveryTargetValue || !inviteEmailValue) {
      focusInviteComposer(item);
      setError("Preencha WhatsApp e email institucional da clinica para gerar ou reenviar o convite.");
      setMessage("");
      return;
    }

    setActionLoadingKey(`quick-invite-${item.clinica_id}`);
    setError("");
    setMessage("");
    try {
      const response = await api.post<PortalAdminClinicInviteResponse>(
        `/portal/admin/clinicas/${item.clinica_id}/convites`,
        {
          delivery_channel: "whatsapp",
          delivery_target: deliveryTargetValue,
          account_email: inviteEmailValue,
          expires_in_hours: Number.parseInt(expiresInHours, 10) || 72,
          allow_manual_copy: true,
        },
        { headers: getPortalAdminAuthHeaders() },
      );
      setSelectedClinicId(String(item.clinica_id));
      setDeliveryTarget(deliveryTargetValue);
      setInviteEmail(inviteEmailValue);
      setGeneratedInvite(response.data);
      setGeneratedClinicName(item.clinica_nome);
      setMessage(
        response.data.access_mode === "login"
          ? response.data.delivery_status === "sent"
            ? `Acesso reenviado para ${item.clinica_nome}.`
            : `Acesso atualizado para ${item.clinica_nome}. Copie a mensagem pronta abaixo.`
          : response.data.delivery_status === "sent"
            ? `Convite reenviado para ${item.clinica_nome}.`
            : `Convite atualizado para ${item.clinica_nome}. Copie a mensagem pronta abaixo.`,
      );
      inviteComposerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      await loadOverview();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel gerar o convite rapido da clinica."));
    } finally {
      setActionLoadingKey("");
    }
  }

  function handleExportCsv() {
    if (!filteredItems.length) {
      setError("Nao ha clinicas visiveis para exportar.");
      return;
    }

    const header = [
      "clinica_id",
      "clinica_nome",
      "status",
      "status_chave",
      "contato_email",
      "contato_whatsapp",
      "email_login",
      "cidade",
      "estado",
      "convite_status",
      "convite_criado_em",
      "convite_expira_em",
      "sessoes_ativas",
      "downloads_total",
      "primeiro_download",
      "ultimo_login",
      "ultimo_download",
      "ultimo_acesso_portal",
      "dias_sem_atividade",
      "fez_primeiro_download",
      "precisa_informar_email",
    ];

    const rows = filteredItems.map((item) => {
      const latestActivityMillis = getLatestPortalActivityMillis(item);
      const latestActivity =
        Number.isFinite(latestActivityMillis)
          ? formatPortalDateTime(new Date(latestActivityMillis).toISOString())
          : "";

      return [
        item.clinica_id,
        item.clinica_nome,
        item.status_label,
        item.status_key,
        item.contato_email || "",
        item.contato_whatsapp || "",
        item.login_email || item.account?.email_masked || item.invite_account_email_masked || "",
        item.cidade || "",
        item.estado || "",
        item.invite?.status || "",
        item.invite?.created_at ? formatPortalDateTime(item.invite.created_at) : "",
        item.invite?.expires_at ? formatPortalDateTime(item.invite.expires_at) : "",
        item.active_session_count,
        item.download_count,
        item.first_download_at ? formatPortalDateTime(item.first_download_at) : "",
        item.account?.last_login_at ? formatPortalDateTime(item.account.last_login_at) : "",
        item.last_download_at ? formatPortalDateTime(item.last_download_at) : "",
        latestActivity,
        typeof item.days_since_last_activity === "number" ? item.days_since_last_activity : "",
        hasFirstDownload(item) ? "sim" : "nao",
        item.needs_email_definition ? "sim" : "nao",
      ];
    });

    const csvContent = `\uFEFF${[header, ...rows]
      .map((columns) => columns.map((value) => csvEscape(value)).join(";"))
      .join("\n")}`;
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `portal-clinicas-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setMessage("CSV exportado com a visao filtrada atual.");
    setError("");
  }

  async function handleRevokeInvite(item: PortalAdminClinicAccessOverviewItem) {
    if (!item.invite || item.invite.status !== "pending") {
      return;
    }
    if (!window.confirm(`Revogar o convite pendente da clinica ${item.clinica_nome}?`)) {
      return;
    }

    setActionLoadingKey(`invite-${item.clinica_id}`);
    setError("");
    setMessage("");
    try {
      await api.post(
        `/portal/admin/clinicas/${item.clinica_id}/convites/${item.invite.id}/revogar`,
        { reason: "convite revogado pela gestao do portal" },
        { headers: getPortalAdminAuthHeaders() },
      );
      setMessage(`Convite da clinica ${item.clinica_nome} revogado.`);
      await loadOverview();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel revogar o convite da clinica."));
    } finally {
      setActionLoadingKey("");
    }
  }

  async function handleRevokeSessions(item: PortalAdminClinicAccessOverviewItem) {
    if (item.active_session_count <= 0) {
      return;
    }
    if (!window.confirm(`Encerrar as sessoes ativas da clinica ${item.clinica_nome}?`)) {
      return;
    }

    setActionLoadingKey(`sessions-${item.clinica_id}`);
    setError("");
    setMessage("");
    try {
      const response = await api.post<{ revoked_count: number }>(
        "/portal/admin/clinica-sessions/revogar",
        {
          clinica_id: item.clinica_id,
          reason: "sessoes revogadas pela gestao do portal",
        },
        { headers: getPortalAdminAuthHeaders() },
      );
      setMessage(`Sessoes encerradas para ${item.clinica_nome}: ${response.data.revoked_count}.`);
      await loadOverview();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel encerrar as sessoes da clinica."));
    } finally {
      setActionLoadingKey("");
    }
  }

  async function handleRevokeAccount(item: PortalAdminClinicAccessOverviewItem) {
    if (!item.account) {
      return;
    }
    if (
      !window.confirm(
        `Revogar a conta de acesso da clinica ${item.clinica_nome}? As sessoes atuais tambem serao encerradas.`,
      )
    ) {
      return;
    }

    setActionLoadingKey(`account-${item.clinica_id}`);
    setError("");
    setMessage("");
    try {
      await api.post(
        `/portal/admin/clinica-accounts/${item.account.id}/revogar`,
        {
          reason: "conta revogada pela gestao do portal",
          revoke_sessions: true,
        },
        { headers: getPortalAdminAuthHeaders() },
      );
      setMessage(`Conta de acesso revogada para ${item.clinica_nome}.`);
      await loadOverview();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel revogar a conta da clinica."));
    } finally {
      setActionLoadingKey("");
    }
  }

  return (
    <DashboardLayout>
      <div className="fc-registry-page">
        <header className="fc-registry-header fc-registry-header-network">
          <div>
            <span className="fc-registry-kicker">
              <ShieldCheck className="h-4 w-4" />
              Gestao do portal
            </span>
            <h1>Portal das clinicas parceiras</h1>
            <p>
              Convites, cadastros concluidos, pendencias de email e downloads de laudos em uma visao unica.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/clinicas/portal/parceiros"
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            >
              <UsersRound className="h-4 w-4" />
              Parceiros externos
            </Link>
            <Link
              href={selectedClinicId ? `/clinicas/portal/espelho?clinica=${selectedClinicId}` : "/clinicas/portal/espelho"}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            >
              <ExternalLink className="h-4 w-4" />
              Ver espelho da clínica
            </Link>
            <Link
              href="/clinicas"
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            >
              <Building2 className="h-4 w-4" />
              Ver clinicas
            </Link>
            <button
              type="button"
              onClick={() => void loadOverview()}
              disabled={loading}
              className="fc-registry-primary"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              Atualizar painel
            </button>
          </div>
        </header>

        <section className="fc-registry-metrics" aria-label="Resumo de acessos do portal">
          <div className="fc-registry-metric fc-registry-metric-cordis">
            <div className="fc-registry-metric-icon">
              <Building2 className="h-5 w-5" />
            </div>
            <div>
              <strong>{overview?.metrics.total_clinicas ?? 0}</strong>
              <span>Clinicas mapeadas</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-vital">
            <div className="fc-registry-metric-icon">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div>
              <strong>{overview?.metrics.contas_ativas ?? 0}</strong>
              <span>Cadastros concluidos</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-ink">
            <div className="fc-registry-metric-icon">
              <TriangleAlert className="h-5 w-5" />
            </div>
            <div>
              <strong>{overview?.metrics.convites_pendentes ?? 0}</strong>
              <span>Convites pendentes</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-cordis">
            <div className="fc-registry-metric-icon">
              <Mail className="h-5 w-5" />
            </div>
            <div>
              <strong>{overview?.metrics.clinicas_precisam_email ?? 0}</strong>
              <span>Precisam informar email</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-vital">
            <div className="fc-registry-metric-icon">
              <UsersRound className="h-5 w-5" />
            </div>
            <div>
              <strong>{overview?.metrics.sessoes_ativas ?? 0}</strong>
              <span>Sessoes ativas</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-ink">
            <div className="fc-registry-metric-icon">
              <Download className="h-5 w-5" />
            </div>
            <div>
              <strong>{overview?.metrics.downloads_ultimos_30_dias ?? 0}</strong>
              <span>Downloads em 30 dias</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-cordis">
            <div className="fc-registry-metric-icon">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <strong>{adoptionMetrics.adoptionRateLabel}</strong>
              <span>Taxa de adesao</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-ink">
            <div className="fc-registry-metric-icon">
              <TriangleAlert className="h-5 w-5" />
            </div>
            <div>
              <strong>{adoptionMetrics.inactive30d}</strong>
              <span>Sem acesso ha 30 dias</span>
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <div
            ref={inviteComposerRef}
            className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"
          >
            <div className="flex flex-col gap-2 border-b border-slate-100 pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-teal-700">
                  <KeyRound className="h-4 w-4" />
                  Envio de convite
                </span>
                <h2 className="mt-2 text-xl font-semibold text-slate-950">Convidar ou reenviar acesso da clinica</h2>
                <p className="mt-2 max-w-2xl text-sm text-slate-500">
                  Defina o email institucional de login, gere o fluxo correto para a unidade e acompanhe o retorno da clinica.
                  Cada email recebe convite e login proprios: e possivel convidar mais de um gestor por clinica.
                </p>
              </div>
              {overview?.generated_at ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  Atualizado em {formatPortalDateTime(overview.generated_at)}
                </div>
              ) : null}
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2">
              <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 md:col-span-2">
                Clinica
                <select
                  value={selectedClinicId}
                  onChange={(event) => setSelectedClinicId(event.target.value)}
                  className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                >
                  <option value="">Selecione a clinica</option>
                  {(overview?.items || []).map((item) => (
                    <option key={item.clinica_id} value={String(item.clinica_id)}>
                      {item.clinica_nome}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                WhatsApp da clinica
                <input
                  type="tel"
                  value={deliveryTarget}
                  onChange={(event) => setDeliveryTarget(formatarWhatsAppVisual(event.target.value))}
                  placeholder="(00) 00000-0000"
                  inputMode="tel"
                  autoComplete="tel"
                  maxLength={15}
                  className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                />
              </label>

              <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                <span className="flex items-center justify-between gap-2">
                  Email institucional de login
                  {selectedClinic && (selectedClinic.active_accounts_count || 0) > 0 ? (
                    <button
                      type="button"
                      onClick={() => setInviteEmail("")}
                      className="text-xs font-semibold text-teal-700 hover:text-teal-800"
                    >
                      + Convidar novo gestor
                    </button>
                  ) : null}
                </span>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(event) => setInviteEmail(event.target.value)}
                  placeholder="portal@clinica.com"
                  className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                />
              </label>

              <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 md:max-w-[220px]">
                Validade do convite (horas)
                <input
                  type="number"
                  min="1"
                  max="240"
                  step="1"
                  value={expiresInHours}
                  onChange={(event) => setExpiresInHours(event.target.value)}
                  className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                />
              </label>
            </div>

            <label className="mt-4 flex items-start gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={senhaTemporaria}
                onChange={(event) => setSenhaTemporaria(event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
              />
              <span>
                Gerar senha temporaria (recomendado para quem tem menos familiaridade com sistemas) - a conta ja
                nasce ativa, sem a clinica precisar criar a propria senha.
              </span>
            </label>

            {senhaTemporaria ? (
              <label className="mt-3 flex flex-col gap-2 text-sm font-medium text-slate-700 md:max-w-xs">
                Nome do responsavel na clinica
                <input
                  type="text"
                  value={responsavelNome}
                  onChange={(event) => setResponsavelNome(event.target.value)}
                  placeholder="Nome de quem vai usar o portal"
                  className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                />
              </label>
            ) : null}

            {selectedClinic ? (
              <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <strong className="text-slate-900">{selectedClinic.clinica_nome}</strong>
                    <p className="mt-1">{buildClinicLocation(selectedClinic)}</p>
                  </div>
                  <span
                    className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${buildStatusClasses(selectedClinic)}`}
                  >
                    {selectedClinic.status_label}
                  </span>
                </div>
                <p className="mt-3">
                  {selectedClinic.needs_email_definition
                    ? "Esta unidade ainda precisa informar o email institucional que sera usado no login."
                    : buildStatusDescription(selectedClinic)}
                </p>
                {selectedClinic.active_accounts_count > 1 ? (
                  <p className="mt-1 text-xs text-slate-500">
                    {selectedClinic.active_accounts_count} gestores com acesso nesta unidade. Para ver e gerenciar cada um,
                    abra o cadastro da clinica.
                  </p>
                ) : null}
              </div>
            ) : null}

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void handleGenerateInvite()}
                disabled={submitting}
                className="inline-flex items-center gap-2 rounded-2xl bg-teal-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageCircle className="h-4 w-4" />}
                Gerar convite
              </button>
              <p className="text-sm text-slate-500">
                Clinicas novas recebem um link de ativacao. Clinicas ja ativas recebem o link normal de entrada no portal.
              </p>
            </div>

            {generatedInvite ? (
              <div className="mt-6 rounded-3xl border border-teal-100 bg-teal-50/70 p-5">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-slate-950">
                      {generatedInvite.access_mode === "login" ? "Acesso pronto para reenvio" : "Convite pronto para envio"}
                    </h3>
                    <p className="mt-1 text-sm text-slate-600">
                      {generatedInvite.access_mode === "login"
                        ? `${generatedClinicName} • entrada normal do portal`
                        : `${generatedClinicName} • expira em ${formatPortalDateTime(generatedInvite.expires_at)}`}
                    </p>
                  </div>
                  <span className="inline-flex items-center rounded-full border border-teal-200 bg-white px-3 py-1 text-xs font-semibold text-teal-700">
                    {generatedInvite.delivery_status === "sent" ? "Enviado" : "Copia manual"}
                  </span>
                </div>

                {generatedInvite.access_mode === "temporary_password" && generatedInvite.senha_temporaria ? (
                  <div className="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-3">
                    <p className="text-xs font-bold uppercase tracking-wide text-amber-800">
                      Senha temporaria - so aparece agora, anote ou copie antes de sair desta tela
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      <code className="rounded bg-white px-2 py-1 font-mono text-base text-amber-950">
                        {generatedInvite.senha_temporaria}
                      </code>
                      <button
                        type="button"
                        onClick={() => void handleCopySenhaTemporaria()}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-bold text-amber-900 hover:bg-amber-100"
                      >
                        <Copy className="w-3.5 h-3.5" />
                        Copiar senha
                      </button>
                    </div>
                  </div>
                ) : null}

                <div className="mt-4 grid gap-4">
                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    {generatedInvite.access_mode === "login" ? "Link de acesso" : "Link de ativacao"}
                    <input
                      type="text"
                      value={generatedInvite.activation_url}
                      readOnly
                      className="h-12 rounded-2xl border border-teal-200 bg-white px-4 text-sm text-slate-900"
                    />
                  </label>
                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Texto pronto para WhatsApp
                    <textarea
                      value={inviteMessage}
                      readOnly
                      rows={7}
                      className="rounded-2xl border border-teal-200 bg-white px-4 py-3 text-sm text-slate-900"
                    />
                  </label>
                </div>

                <div className="mt-4 flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => void handleCopyLink()}
                    className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                  >
                    <Link2 className="h-4 w-4" />
                    Copiar link
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleCopyMessage()}
                    className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                  >
                    <Copy className="h-4 w-4" />
                    Copiar mensagem
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleResendWhatsapp()}
                    disabled={submitting || !lastInviteRequest}
                    className="inline-flex items-center gap-2 rounded-2xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    Reenviar pelo WhatsApp
                  </button>
                </div>
              </div>
            ) : null}

            {message ? (
              <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                {message}
              </div>
            ) : null}
            {error ? (
              <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            ) : null}
          </div>

          <aside className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
              <TriangleAlert className="h-4 w-4" />
              Fila de gestao
            </span>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Prioridades rapidas do portal</h2>
            <p className="mt-2 text-sm text-slate-500">
              Atalhos para o que normalmente pede acao primeiro no acompanhamento das clinicas.
            </p>

            <div className="mt-5 grid gap-3">
              <button
                type="button"
                onClick={() => setQuickView("needs_attention")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  quickView === "needs_attention"
                    ? "border-amber-300 bg-amber-50"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Pedem acao agora</p>
                    <p className="mt-1 text-sm text-slate-500">Email faltando, convite expirado, sem convite ou cadastro travado.</p>
                  </div>
                  <strong className="text-2xl font-semibold text-slate-950">{managementQueue.needsAttention}</strong>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setQuickView("never_accessed")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  quickView === "never_accessed"
                    ? "border-slate-300 bg-slate-100"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Nunca acessaram</p>
                    <p className="mt-1 text-sm text-slate-500">Unidades sem login registrado e sem download no portal.</p>
                  </div>
                  <strong className="text-2xl font-semibold text-slate-950">{managementQueue.neverAccessed}</strong>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setQuickView("expired_invites")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  quickView === "expired_invites"
                    ? "border-rose-300 bg-rose-50"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Convites expirados</p>
                    <p className="mt-1 text-sm text-slate-500">Boas candidatas para reenvio rapido do link.</p>
                  </div>
                  <strong className="text-2xl font-semibold text-slate-950">{managementQueue.expiredInvites}</strong>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setQuickView("recent_downloads")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  quickView === "recent_downloads"
                    ? "border-emerald-300 bg-emerald-50"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Downloads nos ultimos 7 dias</p>
                    <p className="mt-1 text-sm text-slate-500">Mostra clinicas com uso recente do portal.</p>
                  </div>
                  <strong className="text-2xl font-semibold text-slate-950">{managementQueue.recentDownloads}</strong>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setQuickView("inactive_30d")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  quickView === "inactive_30d"
                    ? "border-amber-300 bg-amber-50"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Sem acesso ha 30+ dias</p>
                    <p className="mt-1 text-sm text-slate-500">Mostra clinicas ativas que esfriaram no uso do portal.</p>
                  </div>
                  <strong className="text-2xl font-semibold text-slate-950">{managementQueue.inactive30d}</strong>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setQuickView("first_download_completed")}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  quickView === "first_download_completed"
                    ? "border-emerald-300 bg-emerald-50"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Primeiro download concluido</p>
                    <p className="mt-1 text-sm text-slate-500">Ajuda a enxergar clinicas que ja aderiram de verdade ao portal.</p>
                  </div>
                  <strong className="text-2xl font-semibold text-slate-950">{managementQueue.firstDownloadCompleted}</strong>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setQuickView("all")}
                className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
              >
                Voltar para visao completa
              </button>
            </div>

            <div className="mt-6 border-t border-slate-100 pt-6">
            <div className="mb-6 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Adesao e recorrencia</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-2xl font-semibold text-slate-950">{adoptionMetrics.adoptionRateLabel}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    {adoptionMetrics.activeAccounts} de {(overview?.items || []).length} clinicas com cadastro concluido.
                  </p>
                </div>
                <div>
                  <p className="text-2xl font-semibold text-slate-950">{adoptionMetrics.activeWithRecentActivity}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    Clinicas ativas com login ou download recente nos ultimos 30 dias.
                  </p>
                </div>
              </div>
            </div>
            <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
              <Download className="h-4 w-4" />
              Laudos baixados
            </span>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Ultimos downloads pelas clinicas</h2>
            <p className="mt-2 text-sm text-slate-500">
              Aqui voce acompanha quem acessou arquivo liberado no portal e quando isso aconteceu.
            </p>

            <div className="mt-5 space-y-3">
              {(overview?.recent_downloads || []).length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                  Ainda nao ha downloads auditados de clinicas neste painel.
                </div>
              ) : (
                overview?.recent_downloads.map((downloadEvent) => (
                  <div
                    key={downloadEvent.audit_event_id}
                    className="rounded-2xl border border-slate-200 px-4 py-4"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-semibold text-slate-900">{downloadEvent.clinica_nome}</h3>
                          {downloadEvent.is_first_download ? (
                            <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-700">
                              Primeiro download
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-sm text-slate-600">
                          {downloadEvent.paciente_nome || "Pet nao identificado"}
                          {downloadEvent.tutor_nome ? ` • Tutor ${downloadEvent.tutor_nome}` : ""}
                        </p>
                      </div>
                      <span className="text-xs font-medium text-slate-500">
                        {formatPortalDateTime(downloadEvent.downloaded_at)}
                      </span>
                    </div>
                    <div className="mt-3 space-y-1 text-sm text-slate-600">
                      <p>Exame: {downloadEvent.tipo_exame || "Nao informado"}</p>
                      <p>Arquivo: {downloadEvent.anexo_nome || "Anexo portal"}</p>
                      {downloadEvent.account_email_masked ? (
                        <p>Conta: {downloadEvent.account_email_masked}</p>
                      ) : null}
                    </div>
                  </div>
                ))
              )}
            </div>
            </div>
          </aside>
        </section>

        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
                <Search className="h-4 w-4" />
                Vista panoramica
              </span>
              <h2 className="mt-2 text-xl font-semibold text-slate-950">Clinicas e status de acesso</h2>
              <p className="mt-2 text-sm text-slate-500">
                Filtre por etapa do onboarding, encontre pendencias e acompanhe a adesao ao portal.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                {filteredItems.length} clinica(s) visiveis • {pendingOperationalItems} pedem acao agora
              </div>
              <button
                type="button"
                onClick={handleExportCsv}
                disabled={!filteredItems.length}
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Download className="h-4 w-4" />
                Exportar CSV
              </button>
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_240px_auto]">
            <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Buscar por clinica, email, WhatsApp ou cidade"
                className="w-full bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400"
              />
            </label>

            <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
              Status
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
                className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
              >
                {STATUS_FILTER_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="inline-flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={firstDownloadOnly}
                onChange={(event) => setFirstDownloadOnly(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
              />
              Mostrar apenas clinicas com primeiro download concluido
            </label>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {[
              { value: "all" as const, label: "Todos" },
              { value: "needs_attention" as const, label: "Pedem acao" },
              { value: "never_accessed" as const, label: "Nunca acessaram" },
              { value: "expired_invites" as const, label: "Convites expirados" },
              { value: "recent_downloads" as const, label: "Downloads recentes" },
              { value: "inactive_30d" as const, label: "Sem acesso ha 30+ dias" },
              { value: "first_download_completed" as const, label: "Primeiro download" },
            ].map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setQuickView(option.value)}
                className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
                  quickView === option.value
                    ? "border-teal-300 bg-teal-50 text-teal-800"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900"
                }`}
              >
                {option.label}
              </button>
            ))}
            <button
              type="button"
              onClick={handleResetFilters}
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
            >
              <ListRestart className="h-4 w-4" />
              Limpar filtros
            </button>
          </div>

          <div className="mt-6 space-y-4">
            {loading ? (
              <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-5 text-sm text-slate-600">
                <Loader2 className="h-4 w-4 animate-spin" />
                Carregando panorama do portal...
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-sm text-slate-500">
                Nenhuma clinica corresponde aos filtros aplicados.
              </div>
            ) : (
              filteredItems.map((item) => (
                <article
                  key={item.clinica_id}
                  className={`rounded-3xl border px-5 py-5 transition ${
                    selectedClinicId === String(item.clinica_id)
                      ? "border-teal-300 bg-teal-50/40"
                      : "border-slate-200 bg-white"
                  }`}
                >
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,0.9fr)_auto]">
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-start gap-3">
                        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
                          <Building2 className="h-5 w-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-lg font-semibold text-slate-950">{item.clinica_nome}</h3>
                            <span className="text-sm text-slate-400">Clinica #{item.clinica_id}</span>
                          </div>
                          <p className="mt-1 text-sm text-slate-500">{buildClinicLocation(item)}</p>
                        </div>
                        <span
                          className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${buildStatusClasses(item)}`}
                        >
                          {item.status_label}
                        </span>
                      </div>

                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Contato</p>
                          <p className="mt-2 text-sm text-slate-700">{item.contato_email || "Sem email"}</p>
                          <p className="mt-1 text-sm text-slate-500">{item.contato_whatsapp || "Sem WhatsApp"}</p>
                        </div>
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Conta</p>
                          <p className="mt-2 text-sm text-slate-700">
                            {item.login_email || item.account?.email_masked || item.invite_account_email_masked || "Nao definida"}
                          </p>
                          <p className="mt-1 text-sm text-slate-500">
                            Ultimo login: {formatPortalDateTime(item.account?.last_login_at)}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Convite</p>
                          <p className="mt-2 text-sm text-slate-700">
                            {item.invite ? `Status ${item.invite.status}` : "Sem convite recente"}
                          </p>
                          <p className="mt-1 text-sm text-slate-500">
                            Expira: {formatPortalDateTime(item.invite?.expires_at)}
                          </p>
                          <p className="mt-1 text-sm text-slate-500">
                            Criado: {formatPortalDateTime(item.invite?.created_at)}
                          </p>
                        </div>
                      </div>

                      {item.needs_email_definition ? (
                        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                          Esta clinica ainda precisa informar o email institucional que sera usado no login.
                        </div>
                      ) : null}

                      {getInactivityAlert(item) ? (
                        <div
                          className={`rounded-2xl border px-4 py-3 text-sm ${buildTimelineToneClasses(getInactivityAlert(item)?.tone || "warning")}`}
                        >
                          <p className="font-semibold">{getInactivityAlert(item)?.title}</p>
                          <p className="mt-1">{getInactivityAlert(item)?.description}</p>
                        </div>
                      ) : null}

                      <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                              Linha do tempo do portal
                            </p>
                            <p className="mt-1 text-sm text-slate-500">
                              Convites, ativacao, revogacoes e downloads auditados desta clinica.
                            </p>
                          </div>
                          <span className="text-xs font-medium text-slate-500">
                            {item.timeline.length} evento(s)
                          </span>
                        </div>

                        <div className="mt-4 space-y-3">
                          {item.timeline.length === 0 ? (
                            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-500">
                              Nenhum evento relevante do portal foi auditado para esta clinica ainda.
                            </div>
                          ) : (
                            item.timeline.map((event) => (
                              <div
                                key={event.event_id}
                                className="flex gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
                              >
                                <div
                                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border ${buildTimelineToneClasses(event.tone)}`}
                                >
                                  <TimelineIcon eventType={event.event_type} tone={event.tone} />
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <p className="text-sm font-semibold text-slate-900">{event.title}</p>
                                    <span className="text-xs font-medium text-slate-500">
                                      {formatPortalDateTime(event.occurred_at)}
                                    </span>
                                  </div>
                                  {event.description ? (
                                    <p className="mt-1 text-sm text-slate-500">{event.description}</p>
                                  ) : null}
                                </div>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Downloads</p>
                        <p className="mt-2 text-2xl font-semibold text-slate-950">{item.download_count}</p>
                        <p className="mt-1 text-sm text-slate-500">Primeiro: {formatPortalDateTime(item.first_download_at)}</p>
                        <p className="mt-1 text-sm text-slate-500">Ultimo: {formatPortalDateTime(item.last_download_at)}</p>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Sessoes abertas</p>
                        <p className="mt-2 text-2xl font-semibold text-slate-950">{item.active_session_count}</p>
                        <p className="mt-1 text-sm text-slate-500">Acessos ainda validos</p>
                        <p className="mt-1 text-sm text-slate-500">
                          {item.active_accounts_count} gestor{item.active_accounts_count === 1 ? "" : "es"} com acesso
                        </p>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Situacao</p>
                        <p className="mt-2 text-sm font-medium text-slate-900">{item.status_label}</p>
                        <p className="mt-1 text-sm text-slate-500">Ultimo acesso: {formatPortalDateTime(item.last_access_at)}</p>
                        <p className="mt-1 text-sm text-slate-500">
                          {typeof item.days_since_last_activity === "number"
                            ? `${item.days_since_last_activity} dia(s) sem atividade`
                            : buildStatusDescription(item)}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-col gap-3 xl:min-w-[220px]">
                      <button
                        type="button"
                        onClick={() => void handleQuickInvite(item)}
                        disabled={actionLoadingKey === `quick-invite-${item.clinica_id}`}
                        className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        {actionLoadingKey === `quick-invite-${item.clinica_id}` ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <MessageCircle className="h-4 w-4" />
                        )}
                        {buildQuickInviteLabel(item)}
                      </button>
                      <button
                        type="button"
                        onClick={() => focusInviteComposer(item)}
                        className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                      >
                        <Mail className="h-4 w-4" />
                        Editar convite
                      </button>
                      <Link
                        href={`/clinicas/portal/espelho?clinica=${item.clinica_id}`}
                        className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Ver portal da clínica
                      </Link>
                      <Link
                        href={`/clinicas/${item.clinica_id}`}
                        className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                      >
                        <ArrowUpRight className="h-4 w-4" />
                        Abrir cadastro
                      </Link>
                      {item.invite?.status === "pending" ? (
                        <button
                          type="button"
                          onClick={() => void handleRevokeInvite(item)}
                          disabled={actionLoadingKey === `invite-${item.clinica_id}`}
                          className="inline-flex items-center justify-center gap-2 rounded-2xl border border-rose-200 bg-white px-4 py-3 text-sm font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-70"
                        >
                          {actionLoadingKey === `invite-${item.clinica_id}` ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <KeyRound className="h-4 w-4" />
                          )}
                          Revogar convite
                        </button>
                      ) : null}
                      {item.active_session_count > 0 ? (
                        <button
                          type="button"
                          onClick={() => void handleRevokeSessions(item)}
                          disabled={actionLoadingKey === `sessions-${item.clinica_id}`}
                          className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-70"
                        >
                          {actionLoadingKey === `sessions-${item.clinica_id}` ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <DoorClosed className="h-4 w-4" />
                          )}
                          Encerrar sessoes
                        </button>
                      ) : null}
                      {item.account ? (
                        <button
                          type="button"
                          onClick={() => void handleRevokeAccount(item)}
                          disabled={actionLoadingKey === `account-${item.clinica_id}`}
                          className="inline-flex items-center justify-center gap-2 rounded-2xl border border-rose-200 bg-white px-4 py-3 text-sm font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-70"
                        >
                          {actionLoadingKey === `account-${item.clinica_id}` ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <UserMinus className="h-4 w-4" />
                          )}
                          Revogar conta
                        </button>
                      ) : null}
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </DashboardLayout>
  );
}
