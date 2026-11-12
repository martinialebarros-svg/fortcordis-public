"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Building2,
  CheckCircle2,
  Copy,
  ExternalLink,
  KeyRound,
  Loader2,
  Mail,
  MessageCircle,
  Pencil,
  RefreshCcw,
  Save,
  Search,
  ShieldCheck,
  Stethoscope,
  Undo2,
  UserPlus,
  UsersRound,
} from "lucide-react";

import DashboardLayout from "../../../layout-dashboard";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { listarTodasClinicas } from "@/lib/clinicas";
import {
  buildClinicWhatsappLink,
  buildPartnerInviteMessage,
  getPortalAdminAuthHeaders,
} from "@/lib/portal-clinic-admin";
import { createPortalPartnerInvite } from "@/lib/portal-api";
import {
  buildClinicLinksPayload,
  clinicLinksFromPartner,
  resumoDoVinculo,
  toggleClinicBroadcast,
  toggleClinicLink,
} from "@/lib/portal-partner-clinic-links";
import type {
  PortalAdminClinicInviteResponse,
  PortalPartnerClinicLinkPayload,
  PortalPartnerProfile,
  PortalPartnerProfileCreatePayload,
  PortalPartnerProfileListResponse,
  PortalPartnerProfileUpdatePayload,
  PortalPartnerType,
} from "@/lib/portal-api";
import { formatPortalDateTime } from "@/lib/portal-datetime";

type ClinicaOption = {
  id: number;
  nome: string;
  telefone?: string | null;
  whatsapps?: string[];
  email?: string | null;
  cidade?: string | null;
  estado?: string | null;
  observacoes?: string | null;
  ativo?: boolean;
};

type PartnerFormState = {
  tipo: PortalPartnerType;
  clinica_id: string;
  /** Clinicas em que o veterinario atende, com o interruptor de difusao de cada uma. */
  clinicas_vinculadas: PortalPartnerClinicLinkPayload[];
  nome_exibicao: string;
  email_login: string;
  telefone: string;
  whatsapp: string;
  cidade_base: string;
  estado_base: string;
  crmv: string;
  cpf_documento: string;
  area_atuacao: string;
  observacoes: string;
  ativo: boolean;
};

type TypeFilter = "all" | PortalPartnerType;
type ActiveFilter = "all" | "active" | "inactive";

function emptyForm(tipo: PortalPartnerType = "veterinario"): PartnerFormState {
  return {
    tipo,
    clinica_id: "",
    clinicas_vinculadas: [],
    nome_exibicao: "",
    email_login: "",
    telefone: "",
    whatsapp: "",
    cidade_base: "",
    estado_base: "",
    crmv: "",
    cpf_documento: "",
    area_atuacao: "",
    observacoes: "",
    ativo: true,
  };
}

function cleanValue(value: string): string | undefined {
  const normalized = value.trim();
  return normalized || undefined;
}

function firstClinicWhatsapp(clinica: ClinicaOption | null | undefined): string {
  return clinica?.whatsapps?.find((item) => item?.trim()) || clinica?.telefone?.trim() || "";
}

function partnerTypeClasses(tipo: PortalPartnerType): string {
  return tipo === "veterinario"
    ? "border-teal-200 bg-teal-50 text-teal-800"
    : "border-rose-200 bg-rose-50 text-rose-800";
}

function activeClasses(ativo: boolean): string {
  return ativo
    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
    : "border-slate-200 bg-slate-100 text-slate-700";
}

function buildPartnerLocation(partner: PortalPartnerProfile): string {
  const values = [partner.cidade_base, partner.estado_base].filter(Boolean);
  return values.length ? values.join(" / ") : "Base nao informada";
}

export default function PortalExternalPartnersPage() {
  const [partners, setPartners] = useState<PortalPartnerProfile[]>([]);
  const [clinics, setClinics] = useState<ClinicaOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoadingKey, setActionLoadingKey] = useState("");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("all");
  const [editingPartnerId, setEditingPartnerId] = useState<number | null>(null);
  const [form, setForm] = useState<PartnerFormState>(() => emptyForm("veterinario"));
  const [generatedInvite, setGeneratedInvite] = useState<PortalAdminClinicInviteResponse | null>(null);
  const [generatedInvitePartnerId, setGeneratedInvitePartnerId] = useState<number | null>(null);
  const [generatedInvitePartnerName, setGeneratedInvitePartnerName] = useState("");
  const [generatedInviteWhatsapp, setGeneratedInviteWhatsapp] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const editingPartner = useMemo(
    () => partners.find((item) => item.id === editingPartnerId) || null,
    [editingPartnerId, partners],
  );

  const linkedClinicIds = useMemo(
    () =>
      new Set(
        partners
          .filter((item) => item.tipo === "clinica" && item.clinica_id)
          .map((item) => item.clinica_id as number),
      ),
    [partners],
  );

  const clinicOptions = useMemo(() => {
    return clinics
      .filter((clinic) => clinic.ativo !== false)
      .filter((clinic) => {
        if (editingPartner?.tipo === "clinica" && editingPartner.clinica_id === clinic.id) {
          return true;
        }
        return !linkedClinicIds.has(clinic.id);
      })
      .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  }, [clinics, editingPartner?.clinica_id, editingPartner?.tipo, linkedClinicIds]);

  // O veterinario pode atender em qualquer clinica ativa, inclusive nas que ja
  // sao parceiras do portal por conta propria — por isso nao reusa clinicOptions.
  const clinicasParaVinculo = useMemo(
    () =>
      clinics
        .filter((clinic) => clinic.ativo !== false)
        .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR")),
    [clinics],
  );

  const selectedClinic = useMemo(
    () => clinicOptions.find((item) => String(item.id) === form.clinica_id) || null,
    [clinicOptions, form.clinica_id],
  );

  const generatedInvitePartner = useMemo(
    () => partners.find((item) => item.id === generatedInvitePartnerId) || null,
    [generatedInvitePartnerId, partners],
  );

  const generatedInviteMessage = useMemo(() => {
    if (!generatedInvite?.activation_url || !generatedInvitePartnerName) {
      return "";
    }
    return buildPartnerInviteMessage({
      partnerNome: generatedInvitePartnerName,
      activationUrl: generatedInvite.activation_url,
      accessMode: generatedInvite.access_mode,
      expiresAt: generatedInvite.expires_at,
      accountEmailMasked: generatedInvite.account_email_masked,
    });
  }, [generatedInvite, generatedInvitePartnerName]);

  const metrics = useMemo(() => {
    const activeCount = partners.filter((item) => item.ativo).length;
    const clinicCount = partners.filter((item) => item.tipo === "clinica").length;
    const vetCount = partners.filter((item) => item.tipo === "veterinario").length;
    const withEmailCount = partners.filter((item) => Boolean(item.email_login?.trim())).length;
    return {
      total: partners.length,
      active: activeCount,
      clinicCount,
      vetCount,
      withEmailCount,
    };
  }, [partners]);

  const filteredPartners = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return partners.filter((partner) => {
      if (typeFilter !== "all" && partner.tipo !== typeFilter) {
        return false;
      }
      if (activeFilter === "active" && !partner.ativo) {
        return false;
      }
      if (activeFilter === "inactive" && partner.ativo) {
        return false;
      }
      if (!normalizedSearch) {
        return true;
      }
      const haystack = [
        partner.nome_exibicao,
        partner.tipo_label,
        partner.clinica_nome,
        partner.email_login,
        partner.telefone,
        partner.whatsapp,
        partner.cidade_base,
        partner.estado_base,
        partner.area_atuacao,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [activeFilter, partners, search, typeFilter]);

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [partnerResponse, clinicItems] = await Promise.all([
        api.get<PortalPartnerProfileListResponse>("/portal/parceiros", {
          headers: getPortalAdminAuthHeaders(),
        }),
        listarTodasClinicas<ClinicaOption>(),
      ]);
      setPartners(partnerResponse.data.items || []);
      setClinics(clinicItems);
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel carregar os parceiros externos."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  function handleTypeChange(tipo: PortalPartnerType) {
    setForm((current) => ({
      ...emptyForm(tipo),
      ativo: current.ativo,
    }));
    setEditingPartnerId(null);
    setMessage("");
    setError("");
  }

  function startCreateMode(tipo: PortalPartnerType = "veterinario") {
    setEditingPartnerId(null);
    setForm(emptyForm(tipo));
    setMessage("");
    setError("");
  }

  function fillFormFromClinic(clinic: ClinicaOption) {
    setForm((current) => ({
      ...current,
      clinica_id: String(clinic.id),
      nome_exibicao: clinic.nome || "",
      email_login: clinic.email || "",
      telefone: clinic.telefone || "",
      whatsapp: firstClinicWhatsapp(clinic),
      cidade_base: clinic.cidade || "",
      estado_base: clinic.estado || "",
      observacoes: clinic.observacoes || "",
    }));
  }

  function startEditMode(partner: PortalPartnerProfile) {
    setEditingPartnerId(partner.id);
    setForm({
      tipo: partner.tipo,
      clinica_id: partner.clinica_id ? String(partner.clinica_id) : "",
      clinicas_vinculadas: clinicLinksFromPartner(partner.clinicas_vinculadas),
      nome_exibicao: partner.nome_exibicao || "",
      email_login: partner.email_login || "",
      telefone: partner.telefone || "",
      whatsapp: partner.whatsapp || "",
      cidade_base: partner.cidade_base || "",
      estado_base: partner.estado_base || "",
      crmv: partner.crmv || "",
      cpf_documento: partner.cpf_documento || "",
      area_atuacao: partner.area_atuacao || "",
      observacoes: partner.observacoes || "",
      ativo: partner.ativo,
    });
    setMessage("");
    setError("");
  }

  function handleFieldChange<Key extends keyof PartnerFormState>(field: Key, value: PartnerFormState[Key]) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function handleToggleClinicLink(clinicaId: number) {
    setForm((current) => ({
      ...current,
      clinicas_vinculadas: toggleClinicLink(current.clinicas_vinculadas, clinicaId),
    }));
  }

  function handleToggleClinicBroadcast(clinicaId: number) {
    setForm((current) => ({
      ...current,
      clinicas_vinculadas: toggleClinicBroadcast(current.clinicas_vinculadas, clinicaId),
    }));
  }

  function buildCreatePayload(): PortalPartnerProfileCreatePayload {
    return {
      tipo: form.tipo,
      clinica_id: form.tipo === "clinica" && form.clinica_id ? Number(form.clinica_id) : undefined,
      clinicas_vinculadas: buildClinicLinksPayload(form.tipo, form.clinicas_vinculadas),
      nome_exibicao: cleanValue(form.nome_exibicao),
      email_login: cleanValue(form.email_login),
      telefone: cleanValue(form.telefone),
      whatsapp: cleanValue(form.whatsapp),
      cidade_base: cleanValue(form.cidade_base),
      estado_base: cleanValue(form.estado_base),
      crmv: cleanValue(form.crmv),
      cpf_documento: cleanValue(form.cpf_documento),
      area_atuacao: cleanValue(form.area_atuacao),
      observacoes: cleanValue(form.observacoes),
      ativo: form.ativo,
    };
  }

  function buildUpdatePayload(): PortalPartnerProfileUpdatePayload {
    return {
      clinicas_vinculadas: buildClinicLinksPayload(form.tipo, form.clinicas_vinculadas),
      nome_exibicao: cleanValue(form.nome_exibicao),
      email_login: cleanValue(form.email_login),
      telefone: cleanValue(form.telefone),
      whatsapp: cleanValue(form.whatsapp),
      cidade_base: cleanValue(form.cidade_base),
      estado_base: cleanValue(form.estado_base),
      crmv: cleanValue(form.crmv),
      cpf_documento: cleanValue(form.cpf_documento),
      area_atuacao: cleanValue(form.area_atuacao),
      observacoes: cleanValue(form.observacoes),
      ativo: form.ativo,
    };
  }

  async function handleSubmit() {
    if (form.tipo === "clinica" && !form.clinica_id) {
      setError("Selecione a clínica que será vinculada ao portal.");
      setMessage("");
      return;
    }

    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      if (editingPartnerId) {
        await api.patch(
          `/portal/parceiros/${editingPartnerId}`,
          buildUpdatePayload(),
          { headers: getPortalAdminAuthHeaders() },
        );
        setMessage("Parceiro externo atualizado com sucesso.");
      } else {
        await api.post(
          "/portal/parceiros",
          buildCreatePayload(),
          { headers: getPortalAdminAuthHeaders() },
        );
        setMessage(
          form.tipo === "veterinario"
            ? "Veterinário parceiro cadastrado com sucesso."
            : "Clínica parceira vinculada ao portal com sucesso.",
        );
      }

      await loadData();
      startCreateMode(form.tipo);
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel salvar o parceiro externo."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggleActive(partner: PortalPartnerProfile) {
    setActionLoadingKey(`toggle-${partner.id}`);
    setError("");
    setMessage("");
    try {
      await api.patch(
        `/portal/parceiros/${partner.id}`,
        { ativo: !partner.ativo },
        { headers: getPortalAdminAuthHeaders() },
      );
      setMessage(
        !partner.ativo
          ? `${partner.nome_exibicao} foi reativado para o portal.`
          : `${partner.nome_exibicao} foi marcado como inativo no portal.`,
      );
      await loadData();
      if (editingPartnerId === partner.id) {
        setEditingPartnerId(null);
        setForm(emptyForm("veterinario"));
      }
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel atualizar o status do parceiro."));
    } finally {
      setActionLoadingKey("");
    }
  }

  async function handleGenerateInvite(partner: PortalPartnerProfile) {
    if (partner.tipo !== "veterinario") {
      setError("O convite individual está disponível apenas para veterinários parceiros.");
      setMessage("");
      return;
    }
    if (!partner.ativo) {
      setError("Reative o parceiro antes de gerar o convite de acesso.");
      setMessage("");
      return;
    }
    if (!partner.email_login?.trim() || !partner.whatsapp?.trim()) {
      startEditMode(partner);
      setError("Preencha o e-mail de login e o WhatsApp do parceiro para gerar o convite.");
      setMessage("");
      return;
    }

    setActionLoadingKey(`invite-${partner.id}`);
    setError("");
    setMessage("");
    try {
      const response = await createPortalPartnerInvite(partner.id, {
        delivery_channel: "whatsapp",
        delivery_target: partner.whatsapp.trim(),
        expires_in_hours: 72,
        allow_manual_copy: true,
      });
      setGeneratedInvite(response);
      setGeneratedInvitePartnerId(partner.id);
      setGeneratedInvitePartnerName(partner.nome_exibicao);
      setGeneratedInviteWhatsapp(partner.whatsapp.trim());
      setMessage(
        response.access_mode === "login"
          ? response.delivery_status === "sent"
            ? `Acesso reenviado para ${partner.nome_exibicao}.`
            : `Acesso atualizado para ${partner.nome_exibicao}. Copie a mensagem pronta abaixo.`
          : response.delivery_status === "sent"
            ? `Convite enviado para ${partner.nome_exibicao}.`
            : `Convite gerado para ${partner.nome_exibicao}. Copie a mensagem pronta abaixo.`,
      );
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel gerar o convite do parceiro."));
    } finally {
      setActionLoadingKey("");
    }
  }

  async function handleCopyInviteLink() {
    if (!generatedInvite?.activation_url) {
      return;
    }
    try {
      await navigator.clipboard.writeText(generatedInvite.activation_url);
      setMessage(generatedInvite.access_mode === "login" ? "Link de acesso copiado." : "Link de ativação copiado.");
    } catch {
      setError("Nao foi possivel copiar o link automaticamente.");
    }
  }

  async function handleCopyInviteMessage() {
    if (!generatedInviteMessage) {
      return;
    }
    try {
      await navigator.clipboard.writeText(generatedInviteMessage);
      setMessage("Mensagem do parceiro copiada.");
    } catch {
      setError("Nao foi possivel copiar a mensagem automaticamente.");
    }
  }

  function handleOpenPartnerWhatsapp() {
    if (!generatedInviteMessage || !generatedInviteWhatsapp) {
      return;
    }
    window.open(buildClinicWhatsappLink(generatedInviteWhatsapp, generatedInviteMessage), "_blank", "noopener,noreferrer");
  }

  return (
    <DashboardLayout>
      <div className="fc-registry-page">
        <header className="fc-registry-header fc-registry-header-network">
          <div>
            <span className="fc-registry-kicker">
              <UsersRound className="h-4 w-4" />
              Portal de parceiros
            </span>
            <h1>Parceiros externos do portal</h1>
            <p>
              Cadastre, visualize e mantenha a base de clínicas vinculadas e veterinários parceiros que receberão acesso ao portal.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/clinicas/portal"
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            >
              <ArrowLeft className="h-4 w-4" />
              Voltar ao portal
            </Link>
            <button
              type="button"
              onClick={() => void loadData()}
              disabled={loading}
              className="fc-registry-primary"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              Atualizar parceiros
            </button>
          </div>
        </header>

        <section className="fc-registry-metrics" aria-label="Resumo dos parceiros externos">
          <div className="fc-registry-metric fc-registry-metric-cordis">
            <div className="fc-registry-metric-icon">
              <UsersRound className="h-5 w-5" />
            </div>
            <div>
              <strong>{metrics.total}</strong>
              <span>Perfis no portal</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-vital">
            <div className="fc-registry-metric-icon">
              <Stethoscope className="h-5 w-5" />
            </div>
            <div>
              <strong>{metrics.vetCount}</strong>
              <span>Veterinários parceiros</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-ink">
            <div className="fc-registry-metric-icon">
              <Building2 className="h-5 w-5" />
            </div>
            <div>
              <strong>{metrics.clinicCount}</strong>
              <span>Clínicas vinculadas</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-vital">
            <div className="fc-registry-metric-icon">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div>
              <strong>{metrics.active}</strong>
              <span>Parceiros ativos</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-cordis">
            <div className="fc-registry-metric-icon">
              <Mail className="h-5 w-5" />
            </div>
            <div>
              <strong>{metrics.withEmailCount}</strong>
              <span>Com email de login</span>
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col gap-3 border-b border-slate-100 pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-teal-700">
                  <UserPlus className="h-4 w-4" />
                  Cadastro do parceiro
                </span>
                <h2 className="mt-2 text-xl font-semibold text-slate-950">
                  {editingPartner ? "Editar parceiro externo" : "Novo parceiro externo"}
                </h2>
                <p className="mt-2 text-sm text-slate-500">
                  Comece por veterinário parceiro quando o encaminhamento for volante. Use clínica vinculada quando houver unidade fixa responsável pelo acesso.
                </p>
              </div>

              {editingPartner ? (
                <button
                  type="button"
                  onClick={() => startCreateMode("veterinario")}
                  className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                >
                  <Undo2 className="h-4 w-4" />
                  Cancelar edição
                </button>
              ) : null}
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              {(["veterinario", "clinica"] as PortalPartnerType[]).map((tipo) => {
                const active = form.tipo === tipo;
                return (
                  <button
                    key={tipo}
                    type="button"
                    onClick={() => handleTypeChange(tipo)}
                    className={`inline-flex items-center gap-2 rounded-2xl border px-4 py-2 text-sm font-medium transition ${
                      active
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:text-slate-900"
                    }`}
                  >
                    {tipo === "veterinario" ? <Stethoscope className="h-4 w-4" /> : <Building2 className="h-4 w-4" />}
                    {tipo === "veterinario" ? "Veterinário parceiro" : "Clínica vinculada"}
                  </button>
                );
              })}
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2">
              {form.tipo === "clinica" ? (
                <>
                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 md:col-span-2">
                    Clínica operacional vinculada
                    <select
                      value={form.clinica_id}
                      onChange={(event) => {
                        const value = event.target.value;
                        if (!value) {
                          handleFieldChange("clinica_id", "");
                          return;
                        }
                        const clinic = clinicOptions.find((item) => String(item.id) === value) || null;
                        if (!clinic) {
                          handleFieldChange("clinica_id", value);
                          return;
                        }
                        fillFormFromClinic(clinic);
                      }}
                      disabled={Boolean(editingPartner)}
                      className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100 disabled:cursor-not-allowed disabled:bg-slate-50"
                    >
                      <option value="">Selecione a clínica</option>
                      {clinicOptions.map((clinic) => (
                        <option key={clinic.id} value={String(clinic.id)}>
                          {clinic.nome}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Nome exibido no portal
                    <input
                      type="text"
                      value={form.nome_exibicao}
                      onChange={(event) => handleFieldChange("nome_exibicao", event.target.value)}
                      placeholder="Nome que aparecerá no portal"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Email de login
                    <input
                      type="email"
                      value={form.email_login}
                      onChange={(event) => handleFieldChange("email_login", event.target.value)}
                      placeholder="portal@clinica.com"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Telefone
                    <input
                      type="text"
                      value={form.telefone}
                      onChange={(event) => handleFieldChange("telefone", event.target.value)}
                      placeholder="85999990000"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    WhatsApp
                    <input
                      type="text"
                      value={form.whatsapp}
                      onChange={(event) => handleFieldChange("whatsapp", event.target.value)}
                      placeholder="85999990000"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Cidade base
                    <input
                      type="text"
                      value={form.cidade_base}
                      onChange={(event) => handleFieldChange("cidade_base", event.target.value)}
                      placeholder="Fortaleza"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Estado base
                    <input
                      type="text"
                      value={form.estado_base}
                      onChange={(event) => handleFieldChange("estado_base", event.target.value)}
                      placeholder="CE"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm uppercase text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>
                </>
              ) : (
                <>
                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Nome exibido
                    <input
                      type="text"
                      value={form.nome_exibicao}
                      onChange={(event) => handleFieldChange("nome_exibicao", event.target.value)}
                      placeholder="Dra. Carla Soares"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Email de login
                    <input
                      type="email"
                      value={form.email_login}
                      onChange={(event) => handleFieldChange("email_login", event.target.value)}
                      placeholder="cardio@vetparceiro.com"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Telefone
                    <input
                      type="text"
                      value={form.telefone}
                      onChange={(event) => handleFieldChange("telefone", event.target.value)}
                      placeholder="85999990000"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    WhatsApp
                    <input
                      type="text"
                      value={form.whatsapp}
                      onChange={(event) => handleFieldChange("whatsapp", event.target.value)}
                      placeholder="85999990000"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Cidade base
                    <input
                      type="text"
                      value={form.cidade_base}
                      onChange={(event) => handleFieldChange("cidade_base", event.target.value)}
                      placeholder="Fortaleza"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    Estado base
                    <input
                      type="text"
                      value={form.estado_base}
                      onChange={(event) => handleFieldChange("estado_base", event.target.value)}
                      placeholder="CE"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm uppercase text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    CRMV
                    <input
                      type="text"
                      value={form.crmv}
                      onChange={(event) => handleFieldChange("crmv", event.target.value)}
                      placeholder="12345"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                    CPF
                    <input
                      type="text"
                      value={form.cpf_documento}
                      onChange={(event) => handleFieldChange("cpf_documento", event.target.value)}
                      placeholder="000.000.000-00"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 md:col-span-2">
                    Área de atuação
                    <input
                      type="text"
                      value={form.area_atuacao}
                      onChange={(event) => handleFieldChange("area_atuacao", event.target.value)}
                      placeholder="Cardiologia volante, telemedicina, apoio domiciliar"
                      className="h-12 rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                    />
                  </label>

                  <div className="flex flex-col gap-3 text-sm md:col-span-2">
                    <div>
                      <p className="font-medium text-slate-700">Clínicas em que atende</p>
                      <p className="mt-1 text-xs text-slate-500">
                        Marque todas as clínicas onde este veterinário trabalha. Ligue &ldquo;receber todos
                        os laudos&rdquo; na clínica em que ele deve ser avisado de todo paciente, sem precisar
                        ser nomeado no laudo — use na clínica onde ele é o único parceiro. Desligado, o
                        vínculo apenas deixa o nome dele no topo do seletor do laudo daquela clínica.
                      </p>
                    </div>

                    {clinicasParaVinculo.length === 0 ? (
                      <p className="rounded-2xl border border-dashed border-slate-200 px-4 py-3 text-xs text-slate-500">
                        Nenhuma clínica cadastrada para vincular.
                      </p>
                    ) : (
                      <div className="max-h-72 space-y-2 overflow-y-auto rounded-2xl border border-slate-200 p-2">
                        {clinicasParaVinculo.map((clinic) => {
                          const vinculo = form.clinicas_vinculadas.find(
                            (item) => item.clinica_id === clinic.id,
                          );
                          const vinculada = Boolean(vinculo);
                          return (
                            <div
                              key={clinic.id}
                              className={`rounded-xl border px-3 py-2 transition ${
                                vinculada ? "border-teal-200 bg-teal-50" : "border-slate-200 bg-white"
                              }`}
                            >
                              <label className="flex items-center gap-3 text-sm text-slate-800">
                                <input
                                  type="checkbox"
                                  checked={vinculada}
                                  onChange={() => handleToggleClinicLink(clinic.id)}
                                  className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                                />
                                <span className="font-medium">{clinic.nome}</span>
                                {clinic.cidade ? (
                                  <span className="text-xs text-slate-500">
                                    {clinic.cidade}
                                    {clinic.estado ? `/${clinic.estado}` : ""}
                                  </span>
                                ) : null}
                              </label>

                              {vinculada ? (
                                <label className="mt-2 ml-7 flex items-center gap-2 text-xs text-slate-600">
                                  <input
                                    type="checkbox"
                                    checked={Boolean(vinculo?.receber_todos_laudos)}
                                    onChange={() => handleToggleClinicBroadcast(clinic.id)}
                                    className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                                  />
                                  Receber todos os laudos desta clínica (WhatsApp e email)
                                </label>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </>
              )}

              <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 md:col-span-2">
                Observações
                <textarea
                  value={form.observacoes}
                  onChange={(event) => handleFieldChange("observacoes", event.target.value)}
                  placeholder="Observações operacionais úteis para o relacionamento com este parceiro."
                  rows={4}
                  className="rounded-2xl border border-slate-200 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                />
              </label>

              <label className="inline-flex items-center gap-3 text-sm font-medium text-slate-700 md:col-span-2">
                <input
                  type="checkbox"
                  checked={form.ativo}
                  onChange={(event) => handleFieldChange("ativo", event.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                />
                Manter este parceiro ativo no portal
              </label>
            </div>

            {selectedClinic && form.tipo === "clinica" ? (
              <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                <div className="flex items-center gap-2 text-slate-900">
                  <Building2 className="h-4 w-4 text-slate-500" />
                  <strong>{selectedClinic.nome}</strong>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <p>Email base: {selectedClinic.email || "Não informado"}</p>
                  <p>WhatsApp base: {firstClinicWhatsapp(selectedClinic) || "Não informado"}</p>
                  <p>Telefone base: {selectedClinic.telefone || "Não informado"}</p>
                  <p>
                    Localização: {[selectedClinic.cidade, selectedClinic.estado].filter(Boolean).join(" / ") || "Não informada"}
                  </p>
                </div>
              </div>
            ) : null}

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={submitting}
                className="inline-flex items-center gap-2 rounded-2xl bg-teal-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {editingPartner ? "Salvar ajustes" : "Cadastrar parceiro"}
              </button>
              <button
                type="button"
                onClick={() => startCreateMode(form.tipo)}
                disabled={submitting}
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-70"
              >
                <Undo2 className="h-4 w-4" />
                Limpar formulário
              </button>
            </div>

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

          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col gap-3 border-b border-slate-100 pb-5">
              <div>
                <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
                  <ShieldCheck className="h-4 w-4" />
                  Leitura operacional
                </span>
                <h2 className="mt-2 text-xl font-semibold text-slate-950">Como usar esta base</h2>
              </div>
              <div className="grid gap-3">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                  <p className="font-semibold text-slate-900">Clínica vinculada</p>
                  <p className="mt-1">
                    Use quando existir uma unidade fixa responsável pelos laudos e pelo acesso institucional ao portal.
                  </p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                  <p className="font-semibold text-slate-900">Veterinário parceiro</p>
                  <p className="mt-1">
                    Use quando o profissional encaminha pacientes de forma volante, domiciliar ou por telemedicina, sem depender de endereço fixo de atendimento.
                  </p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
                  <p className="font-semibold text-slate-900">Próxima etapa desta frente</p>
                  <p className="mt-1">
                    O veterinário parceiro já pode receber convite individual por WhatsApp, ativar senha própria e acessar apenas os casos liberados no seu escopo.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Convite do parceiro</p>
              {generatedInvite ? (
                <div className="mt-3 space-y-4">
                  <div className="rounded-2xl border border-white bg-white px-4 py-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-800">
                        {generatedInvite.access_mode === "login" ? "Acesso ativo" : "Ativação inicial"}
                      </span>
                      <span className="rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                        {generatedInvite.delivery_status === "sent" ? "Enviado" : "Cópia manual"}
                      </span>
                    </div>
                    <p className="mt-3 font-semibold text-slate-950">{generatedInvitePartnerName}</p>
                    <p className="mt-2 text-slate-600">
                      {generatedInvite.account_email_masked || generatedInvitePartner?.email_login || "Email não informado"}
                    </p>
                    {generatedInvite.expires_at ? (
                      <p className="mt-2 text-slate-500">Expira em {formatPortalDateTime(generatedInvite.expires_at)}</p>
                    ) : (
                      <p className="mt-2 text-slate-500">Link de entrada pronto para reutilização.</p>
                    )}
                    <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Link pronto</p>
                      <p className="mt-2 break-all text-sm text-slate-900">{generatedInvite.activation_url}</p>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={() => void handleCopyInviteLink()}
                      className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                    >
                      <Copy className="h-4 w-4" />
                      Copiar link
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleCopyInviteMessage()}
                      className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                    >
                      <MessageCircle className="h-4 w-4" />
                      Copiar mensagem
                    </button>
                    <button
                      type="button"
                      onClick={handleOpenPartnerWhatsapp}
                      className="inline-flex items-center gap-2 rounded-2xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-teal-700"
                    >
                      <ExternalLink className="h-4 w-4" />
                      Abrir WhatsApp
                    </button>
                  </div>
                </div>
              ) : (
                <p className="mt-3">
                  Use o botão <span className="font-semibold text-slate-900">Gerar convite</span> em um veterinário parceiro ativo para preparar o link de ativação, a mensagem pronta e o atalho de envio.
                </p>
              )}
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setTypeFilter("all")}
                className={`rounded-2xl border px-4 py-3 text-left text-sm font-medium transition ${
                  typeFilter === "all"
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:text-slate-900"
                }`}
              >
                Todos os tipos
              </button>
              <button
                type="button"
                onClick={() => setTypeFilter("veterinario")}
                className={`rounded-2xl border px-4 py-3 text-left text-sm font-medium transition ${
                  typeFilter === "veterinario"
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:text-slate-900"
                }`}
              >
                Veterinários parceiros
              </button>
              <button
                type="button"
                onClick={() => setTypeFilter("clinica")}
                className={`rounded-2xl border px-4 py-3 text-left text-sm font-medium transition ${
                  typeFilter === "clinica"
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:text-slate-900"
                }`}
              >
                Clínicas vinculadas
              </button>
              <button
                type="button"
                onClick={() => setActiveFilter((current) => (current === "active" ? "all" : "active"))}
                className={`rounded-2xl border px-4 py-3 text-left text-sm font-medium transition ${
                  activeFilter === "active"
                    ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:text-slate-900"
                }`}
              >
                Somente ativos
              </button>
            </div>
          </div>
        </section>

        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 border-b border-slate-100 pb-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
                <UsersRound className="h-4 w-4" />
                Base atual
              </span>
              <h2 className="mt-2 text-xl font-semibold text-slate-950">Parceiros já cadastrados</h2>
              <p className="mt-2 text-sm text-slate-500">
                Filtre por tipo, status e busca geral para localizar rapidamente quem já está preparado para as próximas etapas do portal.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px_180px]">
              <label className="relative flex items-center">
                <Search className="pointer-events-none absolute left-4 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Buscar por nome, email, cidade ou clínica"
                  className="h-12 w-full rounded-2xl border border-slate-200 pl-11 pr-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
                />
              </label>

              <select
                value={typeFilter}
                onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}
                className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
              >
                <option value="all">Todos os tipos</option>
                <option value="clinica">Clínicas</option>
                <option value="veterinario">Veterinários</option>
              </select>

              <select
                value={activeFilter}
                onChange={(event) => setActiveFilter(event.target.value as ActiveFilter)}
                className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
              >
                <option value="all">Todos os status</option>
                <option value="active">Somente ativos</option>
                <option value="inactive">Somente inativos</option>
              </select>
            </div>
          </div>

          {loading ? (
            <div className="mt-6 flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
              <Loader2 className="h-4 w-4 animate-spin" />
              Carregando parceiros externos...
            </div>
          ) : filteredPartners.length === 0 ? (
            <div className="mt-6 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
              Nenhum parceiro externo encontrado com os filtros atuais.
            </div>
          ) : (
            <div className="mt-6 grid gap-4">
              {filteredPartners.map((partner) => {
                const isEditing = editingPartnerId === partner.id;
                return (
                  <article
                    key={partner.id}
                    className={`rounded-3xl border px-5 py-5 transition ${
                      isEditing ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white"
                    }`}
                  >
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div className="space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-600">
                            Parceiro #{partner.id}
                          </span>
                          <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${partnerTypeClasses(partner.tipo)}`}>
                            {partner.tipo === "veterinario" ? (
                              <Stethoscope className="mr-1.5 h-3.5 w-3.5" />
                            ) : (
                              <Building2 className="mr-1.5 h-3.5 w-3.5" />
                            )}
                            {partner.tipo_label}
                          </span>
                          <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${activeClasses(partner.ativo)}`}>
                            {partner.ativo ? "Ativo" : "Inativo"}
                          </span>
                        </div>

                        <div>
                          <h3 className="text-xl font-semibold text-slate-950">{partner.nome_exibicao}</h3>
                          <p className="mt-1 text-sm text-slate-500">
                            {partner.clinica_nome
                              ? `Vinculado à clínica ${partner.clinica_nome}.`
                              : partner.area_atuacao || "Base preparada para fluxo de convite e acesso do portal."}
                          </p>
                        </div>

                        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Email</p>
                            <p className="mt-2 break-all text-slate-900">{partner.email_login || "Não informado"}</p>
                          </div>
                          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Contato</p>
                            <p className="mt-2 text-slate-900">{partner.whatsapp || partner.telefone || "Não informado"}</p>
                          </div>
                          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Base</p>
                            <p className="mt-2 text-slate-900">{buildPartnerLocation(partner)}</p>
                          </div>
                          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Atuação</p>
                            <p className="mt-2 text-slate-900">{partner.area_atuacao || partner.crmv || "Operação geral"}</p>
                          </div>
                        </div>

                        {partner.clinicas_vinculadas?.length ? (
                          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                              Clínicas em que atende
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2">
                              {partner.clinicas_vinculadas.map((link) => (
                                <span
                                  key={link.clinica_id}
                                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
                                    link.receber_todos_laudos
                                      ? "border-teal-200 bg-teal-50 text-teal-800"
                                      : "border-slate-200 bg-slate-50 text-slate-700"
                                  }`}
                                  title={resumoDoVinculo(link)}
                                >
                                  <Building2 className="h-3.5 w-3.5" />
                                  {link.clinica_nome || `Clínica ${link.clinica_id}`}
                                  {link.receber_todos_laudos ? " · recebe todos" : ""}
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : null}

                        {partner.observacoes ? (
                          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Observações</p>
                            <p className="mt-2 text-slate-700">{partner.observacoes}</p>
                          </div>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap items-center gap-3 lg:max-w-[240px] lg:justify-end">
                        {partner.tipo === "veterinario" ? (
                          <button
                            type="button"
                            onClick={() => void handleGenerateInvite(partner)}
                            disabled={actionLoadingKey === `invite-${partner.id}`}
                            className="inline-flex items-center gap-2 rounded-2xl bg-slate-950 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
                          >
                            {actionLoadingKey === `invite-${partner.id}` ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <KeyRound className="h-4 w-4" />
                            )}
                            Gerar convite
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => startEditMode(partner)}
                          className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
                        >
                          <Pencil className="h-4 w-4" />
                          Editar
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleToggleActive(partner)}
                          disabled={actionLoadingKey === `toggle-${partner.id}`}
                          className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-70"
                        >
                          {actionLoadingKey === `toggle-${partner.id}` ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : partner.ativo ? (
                            <ShieldCheck className="h-4 w-4" />
                          ) : (
                            <CheckCircle2 className="h-4 w-4" />
                          )}
                          {partner.ativo ? "Marcar inativo" : "Reativar"}
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
