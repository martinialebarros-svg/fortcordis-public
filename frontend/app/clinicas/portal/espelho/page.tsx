"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Building2, Eye, Loader2, RefreshCcw } from "lucide-react";
import { useSearchParams } from "next/navigation";

import DashboardLayout from "../../../layout-dashboard";
import PortalClinicaWorkspace from "@/components/portal/PortalClinicaWorkspace";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { getPortalAdminAuthHeaders } from "@/lib/portal-clinic-admin";
import type { PortalAdminClinicAccessOverviewItem, PortalAdminClinicAccessOverviewResponse } from "@/lib/portal-api";

function buildClinicStatusClasses(item: PortalAdminClinicAccessOverviewItem): string {
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

function buildClinicLocation(item: PortalAdminClinicAccessOverviewItem): string {
  const values = [item.cidade, item.estado].filter(Boolean);
  return values.length ? values.join(" / ") : "Localizacao nao informada";
}

export default function PortalClinicMirrorPage() {
  const searchParams = useSearchParams();
  const [overview, setOverview] = useState<PortalAdminClinicAccessOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedClinicId, setSelectedClinicId] = useState("");
  const [error, setError] = useState("");
  const requestedClinicId = searchParams.get("clinica") || "";

  const selectedClinic = useMemo(
    () => overview?.items.find((item) => String(item.clinica_id) === selectedClinicId) || null,
    [overview?.items, selectedClinicId],
  );

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
        if (requestedClinicId && response.data.items.some((item) => String(item.clinica_id) === requestedClinicId)) {
          return requestedClinicId;
        }
        if (currentValue && response.data.items.some((item) => String(item.clinica_id) === currentValue)) {
          return currentValue;
        }
        return response.data.items[0] ? String(response.data.items[0].clinica_id) : "";
      });
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel carregar as clinicas do portal."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadOverview();
  }, [requestedClinicId]);

  return (
    <DashboardLayout>
      <div className="fc-registry-page">
        <header className="fc-registry-header fc-registry-header-network">
          <div>
            <span className="fc-registry-kicker">
              <Eye className="h-4 w-4" />
              Conferência do portal
            </span>
            <h1>Visão espelhada da clínica</h1>
            <p>Abra a mesma experiência da unidade parceira para validar filtros, arquivos e leitura final do portal.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/clinicas/portal"
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            >
              <ArrowLeft className="h-4 w-4" />
              Voltar ao painel
            </Link>
            <button
              type="button"
              onClick={() => void loadOverview()}
              disabled={loading}
              className="fc-registry-primary"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              Atualizar clinicas
            </button>
          </div>
        </header>

        <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
            <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
              Clinica para espelhar
              <select
                value={selectedClinicId}
                onChange={(event) => setSelectedClinicId(event.target.value)}
                disabled={loading || !overview?.items.length}
                className="h-12 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100 disabled:cursor-not-allowed disabled:bg-slate-50"
              >
                <option value="">Selecione a clinica</option>
                {(overview?.items || []).map((item) => (
                  <option key={item.clinica_id} value={String(item.clinica_id)}>
                    {item.clinica_nome}
                  </option>
                ))}
              </select>
            </label>

            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
              {selectedClinic ? (
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Building2 className="h-4 w-4 text-slate-500" />
                      <strong className="text-slate-900">{selectedClinic.clinica_nome}</strong>
                    </div>
                    <p className="mt-2">{buildClinicLocation(selectedClinic)}</p>
                    <p className="mt-1">
                      Login atual: {selectedClinic.login_email || selectedClinic.account?.email_masked || "Não definido"}
                    </p>
                  </div>
                  <span
                    className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${buildClinicStatusClasses(selectedClinic)}`}
                  >
                    {selectedClinic.status_label}
                  </span>
                </div>
              ) : (
                <p>Selecione uma clínica para abrir o espelho do portal parceiro.</p>
              )}
            </div>
          </div>

          {error ? (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          {!loading && !(overview?.items.length || 0) ? (
            <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              Nenhuma clínica ativa foi encontrada para espelhar neste momento.
            </div>
          ) : null}
        </section>

        {selectedClinic ? (
          <div className="mt-6 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
            <PortalClinicaWorkspace
              mode="admin_preview"
              adminPreview={{
                clinicaId: selectedClinic.clinica_id,
                clinicaNome: selectedClinic.clinica_nome,
                backHref: "/clinicas/portal",
              }}
            />
          </div>
        ) : null}
      </div>
    </DashboardLayout>
  );
}
