"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Building2,
  Clock,
  MapPin,
  RefreshCw,
  Save,
} from "lucide-react";

import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";

type PerfilLogistica = "comercial" | "plantao";

interface ClinicaItem {
  id: number;
  nome: string;
}

interface DeslocamentoItem {
  id: number;
  origem_clinica_id: number;
  destino_clinica_id: number;
  perfil: string;
  distancia_km: number;
  duracao_min: number;
  fonte: string;
  manual_override: boolean;
  observacoes?: string | null;
  updated_at?: string | null;
}

interface MatrizResponse {
  perfil: string;
  total_clinicas: number;
  total_itens: number;
  clinicas: Array<{ id: number; nome: string }>;
  items: DeslocamentoItem[];
}

interface RecalculoResponse {
  ok: boolean;
  updated: number;
  skipped_manual: number;
  profiles: string[];
  total_celulas?: number;
}

interface ParResponse {
  origem: { id: number; nome: string | null };
  destino: { id: number; nome: string | null };
  item: DeslocamentoItem;
}

interface GoogleMapsResumoResponse {
  window_days: number;
  cache_max_age_days: number;
  cache_expires_by_age?: boolean;
  metrics_retention_days: number;
  total_api_calls: number;
  success_rate_percent: number;
  status_counts: Record<string, number>;
  operation_counts: Record<string, number>;
  calls_by_day: Record<string, number>;
  top_pairs: Array<{
    origem_clinica_id: number | null;
    destino_clinica_id: number | null;
    calls: number;
    last_called_at: string | null;
  }>;
  cache: {
    total_rows: number;
    fresh_rows: number;
    stale_rows: number;
    manual_rows: number;
    google_rows: number;
  };
}

const PERFIS: PerfilLogistica[] = ["comercial", "plantao"];

const parseNumero = (value: string): number | null => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
};

export default function LogisticaPage() {
  const router = useRouter();

  const [loadingClinicas, setLoadingClinicas] = useState(true);
  const [clinicas, setClinicas] = useState<ClinicaItem[]>([]);
  const [erroTela, setErroTela] = useState("");

  const [perfil, setPerfil] = useState<PerfilLogistica>("comercial");
  const [incluirInativas, setIncluirInativas] = useState(false);

  const [origemId, setOrigemId] = useState("");
  const [destinoId, setDestinoId] = useState("");

  const [matrizLoading, setMatrizLoading] = useState(false);
  const [matrizError, setMatrizError] = useState("");
  const [matrizItems, setMatrizItems] = useState<DeslocamentoItem[]>([]);
  const [matrizTotalClinicas, setMatrizTotalClinicas] = useState(0);

  const [consultaLoading, setConsultaLoading] = useState(false);
  const [consultaError, setConsultaError] = useState("");
  const [consultaPar, setConsultaPar] = useState<ParResponse | null>(null);

  const [manualDuracaoMin, setManualDuracaoMin] = useState("30");
  const [manualDistanciaKm, setManualDistanciaKm] = useState("0");
  const [manualObservacoes, setManualObservacoes] = useState("");
  const [manualSaving, setManualSaving] = useState(false);
  const [manualMensagem, setManualMensagem] = useState("");
  const [manualError, setManualError] = useState("");

  const [recalculoClinicaId, setRecalculoClinicaId] = useState("");
  const [recalculoForce, setRecalculoForce] = useState(false);
  const [recalculoLoading, setRecalculoLoading] = useState(false);
  const [recalculoMensagem, setRecalculoMensagem] = useState("");
  const [recalculoError, setRecalculoError] = useState("");
  const [resumoLoading, setResumoLoading] = useState(false);
  const [resumoError, setResumoError] = useState("");
  const [googleMapsResumo, setGoogleMapsResumo] = useState<GoogleMapsResumoResponse | null>(null);

  const clinicaPorId = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of clinicas) {
      map.set(Number(c.id), c.nome);
    }
    return map;
  }, [clinicas]);

  const nomeClinica = (id: number) => clinicaPorId.get(Number(id)) || `Clinica #${id}`;

  const percentualCacheFresco = useMemo(() => {
    const totalGoogle = Number(googleMapsResumo?.cache?.google_rows || 0);
    const fresh = Number(googleMapsResumo?.cache?.fresh_rows || 0);
    if (totalGoogle <= 0) return 0;
    return Math.round((fresh / totalGoogle) * 100);
  }, [googleMapsResumo]);

  const topDiasChamadas = useMemo(() => {
    const entries = Object.entries(googleMapsResumo?.calls_by_day || {});
    return entries.sort((a, b) => b[0].localeCompare(a[0])).slice(0, 7);
  }, [googleMapsResumo]);

  const topOperacoes = useMemo(() => {
    const entries = Object.entries(googleMapsResumo?.operation_counts || {});
    return entries.sort((a, b) => b[1] - a[1]);
  }, [googleMapsResumo]);

  const formatarDataHora = (valor: string | null | undefined) => {
    if (!valor) return "nunca";
    const data = new Date(valor);
    if (Number.isNaN(data.getTime())) return valor;
    return data.toLocaleString("pt-BR");
  };

  const carregarClinicas = async () => {
    try {
      setLoadingClinicas(true);
      const payload = await loadStableCatalog({
        catalog: "clinicas",
        variant: "limit=1000",
        load: () => api.get("/clinicas?limit=1000").then((response) => response.data),
      });
      const items = Array.isArray(payload?.items)
        ? payload.items
        : Array.isArray(payload?.data)
          ? payload.data
          : Array.isArray(payload)
            ? payload
            : [];

      const normalizadas: ClinicaItem[] = items
        .filter((item: any) => Number.isFinite(Number(item?.id)))
        .map((item: any) => ({
          id: Number(item.id),
          nome: String(item.nome || `Clinica #${item.id}`),
        }));

      setClinicas(normalizadas);
      if (!origemId && normalizadas.length > 0) {
        setOrigemId(String(normalizadas[0].id));
      }
      if (!destinoId && normalizadas.length > 1) {
        setDestinoId(String(normalizadas[1].id));
      }
      if (!recalculoClinicaId && normalizadas.length > 0) {
        setRecalculoClinicaId("");
      }
    } catch (error) {
      console.error("Erro ao carregar clinicas para logistica:", error);
      setErroTela("Falha ao carregar clinicas.");
    } finally {
      setLoadingClinicas(false);
    }
  };

  const carregarMatriz = async () => {
    try {
      setMatrizLoading(true);
      setMatrizError("");

      const params = new URLSearchParams();
      params.set("perfil", perfil);
      params.set("incluir_inativas", incluirInativas ? "true" : "false");

      const origem = parseNumero(origemId);
      const destino = parseNumero(destinoId);
      const ids = [origem, destino].filter((id): id is number => id !== null && id > 0);
      const idsUnicos = Array.from(new Set(ids));
      for (const id of idsUnicos) {
        params.append("clinica_ids", String(id));
      }

      const response = await api.get<MatrizResponse>(`/logistica/matriz?${params.toString()}`);
      setMatrizItems(Array.isArray(response?.data?.items) ? response.data.items : []);
      setMatrizTotalClinicas(Number(response?.data?.total_clinicas || 0));
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setMatrizError(typeof detail === "string" ? detail : "Falha ao carregar matriz.");
    } finally {
      setMatrizLoading(false);
    }
  };

  const carregarResumoGoogleMaps = async () => {
    try {
      setResumoLoading(true);
      setResumoError("");
      const params = new URLSearchParams();
      params.set("dias", "30");
      params.set("incluir_inativas", incluirInativas ? "true" : "false");
      const response = await api.get<GoogleMapsResumoResponse>(
        `/logistica/google-maps/resumo?${params.toString()}`
      );
      setGoogleMapsResumo(response.data);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setResumoError(typeof detail === "string" ? detail : "Falha ao carregar monitoramento do Google Maps.");
    } finally {
      setResumoLoading(false);
    }
  };

  const consultarPar = async (recalcular: boolean) => {
    const origem = parseNumero(origemId);
    const destino = parseNumero(destinoId);
    if (!origem || !destino) {
      setConsultaError("Selecione origem e destino.");
      setConsultaPar(null);
      return;
    }

    try {
      setConsultaLoading(true);
      setConsultaError("");
      const params = new URLSearchParams();
      params.set("origem_clinica_id", String(origem));
      params.set("destino_clinica_id", String(destino));
      params.set("perfil", perfil);
      params.set("recalcular", recalcular ? "true" : "false");
      const response = await api.get<ParResponse>(`/logistica/deslocamento?${params.toString()}`);
      setConsultaPar(response.data);
      setManualDuracaoMin(String(response?.data?.item?.duracao_min ?? 30));
      setManualDistanciaKm(String(response?.data?.item?.distancia_km ?? 0));
      setManualObservacoes(response?.data?.item?.observacoes || "");
      await carregarResumoGoogleMaps();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setConsultaError(typeof detail === "string" ? detail : "Falha ao consultar deslocamento.");
      setConsultaPar(null);
    } finally {
      setConsultaLoading(false);
    }
  };

  const salvarAjusteManual = async () => {
    const origem = parseNumero(origemId);
    const destino = parseNumero(destinoId);
    const duracao = parseNumero(manualDuracaoMin);
    const distancia = Number.parseFloat(manualDistanciaKm);

    if (!origem || !destino) {
      setManualError("Selecione origem e destino.");
      return;
    }
    if (origem === destino) {
      setManualError("Origem e destino devem ser diferentes para ajuste manual.");
      return;
    }
    if (!duracao || duracao < 0) {
      setManualError("Duracao deve ser um numero valido maior ou igual a zero.");
      return;
    }
    if (!Number.isFinite(distancia) || distancia < 0) {
      setManualError("Distancia deve ser um numero valido maior ou igual a zero.");
      return;
    }

    try {
      setManualSaving(true);
      setManualError("");
      setManualMensagem("");
      await api.put("/logistica/deslocamento/manual", {
        origem_clinica_id: origem,
        destino_clinica_id: destino,
        perfil,
        distancia_km: distancia,
        duracao_min: duracao,
        observacoes: (manualObservacoes || "").trim() || null,
      });
      setManualMensagem("Ajuste manual salvo.");
      await Promise.all([carregarMatriz(), consultarPar(false)]);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setManualError(typeof detail === "string" ? detail : "Falha ao salvar ajuste manual.");
    } finally {
      setManualSaving(false);
    }
  };

  const recalcularMatriz = async () => {
    const clinicaId = parseNumero(recalculoClinicaId);
    try {
      setRecalculoLoading(true);
      setRecalculoError("");
      setRecalculoMensagem("");

      const payload = {
        clinica_id: clinicaId || null,
        perfis: [perfil],
        force_override: recalculoForce,
        incluir_inativas: incluirInativas,
      };

      const response = await api.post<RecalculoResponse>("/logistica/recalcular", payload);
      const data = response.data;
      const total = Number(data?.updated || 0);
      const skipped = Number(data?.skipped_manual || 0);
      const totalCelulas = Number(data?.total_celulas || 0);
      const extra = totalCelulas > 0 ? ` Total de celulas: ${totalCelulas}.` : "";
      setRecalculoMensagem(`Recalculo concluido. Atualizados: ${total}. Ignorados (manual): ${skipped}.${extra}`);
      await Promise.all([carregarMatriz(), carregarResumoGoogleMaps()]);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setRecalculoError(typeof detail === "string" ? detail : "Falha ao recalcular matriz.");
    } finally {
      setRecalculoLoading(false);
    }
  };

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarClinicas();
  }, [router]);

  useEffect(() => {
    if (loadingClinicas) return;
    carregarMatriz();
    carregarResumoGoogleMaps();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadingClinicas, perfil, incluirInativas, origemId, destinoId]);

  return (
    <DashboardLayout>
      <div className="fc-logistics-page">
        <header className="fc-logistics-header">
          <div>
            <span className="fc-logistics-kicker"><MapPin className="h-4 w-4" />Central de rotas</span>
            <h1>Logística Operacional</h1>
            <p>Tempos, distâncias e cobertura entre clínicas da rede Fort Cordis.</p>
          </div>
          <div className="fc-logistics-profile" role="tablist" aria-label="Perfil de deslocamento">
            {PERFIS.map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={perfil === item}
                onClick={() => setPerfil(item)}
                className={`fc-logistics-profile-tab ${perfil === item ? "fc-logistics-profile-tab-active" : ""}`}
              >
                {item === "comercial" ? "Comercial" : "Plantão"}
              </button>
            ))}
          </div>
        </header>

        {erroTela && (
          <div className="fc-logistics-message fc-logistics-message-error">
            {erroTela}
          </div>
        )}

        <section className="fc-logistics-metrics" aria-label="Resumo logístico">
          <div className="fc-logistics-metric fc-logistics-metric-cordis">
            <Building2 className="h-5 w-5" />
            <strong>{clinicas.length}</strong>
            <span>Clínicas disponíveis</span>
          </div>
          <div className="fc-logistics-metric fc-logistics-metric-vital">
            <MapPin className="h-5 w-5" />
            <strong>{matrizItems.length}</strong>
            <span>Rotas no filtro</span>
          </div>
          <div className="fc-logistics-metric fc-logistics-metric-amber">
            <RefreshCw className="h-5 w-5" />
            <strong>{googleMapsResumo?.total_api_calls ?? 0}</strong>
            <span>Chamadas em 30 dias</span>
          </div>
          <div className="fc-logistics-metric fc-logistics-metric-ink">
            <Clock className="h-5 w-5" />
            <strong>{percentualCacheFresco}%</strong>
            <span>Cache válido</span>
          </div>
        </section>

        <section className="fc-logistics-filters">
          <div className="fc-logistics-filter-copy">
            <span>Rota em foco</span>
            <strong>Selecione origem e destino</strong>
          </div>
          <div>
            <label className="fc-logistics-label">Origem</label>
            <select
              value={origemId}
              onChange={(e) => setOrigemId(e.target.value)}
              className="fc-logistics-control"
              disabled={loadingClinicas}
            >
              <option value="">Selecione...</option>
              {clinicas.map((c) => (
                <option key={`origem-${c.id}`} value={String(c.id)}>
                  {c.nome}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="fc-logistics-label">Destino</label>
            <select
              value={destinoId}
              onChange={(e) => setDestinoId(e.target.value)}
              className="fc-logistics-control"
              disabled={loadingClinicas}
            >
              <option value="">Selecione...</option>
              {clinicas.map((c) => (
                <option key={`destino-${c.id}`} value={String(c.id)}>
                  {c.nome}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button
              type="button"
              onClick={carregarMatriz}
              disabled={matrizLoading}
              className="fc-logistics-button-primary"
            >
              <RefreshCw className="h-4 w-4" />
              Atualizar matriz
            </button>
          </div>
          <div className="fc-logistics-filter-options">
            <label className="fc-logistics-check">
              <input
                type="checkbox"
                checked={incluirInativas}
                onChange={(e) => setIncluirInativas(e.target.checked)}
              />
              Incluir clínicas inativas
            </label>
          </div>
        </section>

        <div className="fc-logistics-workspace">
          <section className="fc-logistics-panel fc-logistics-panel-cordis">
            <div className="fc-logistics-panel-title">
              <MapPin className="h-5 w-5" />
              <div><span>Consulta rápida</span><h2>Deslocamento do par</h2></div>
            </div>

            <div className="fc-logistics-actions">
              <button
                type="button"
                onClick={() => consultarPar(false)}
                disabled={consultaLoading}
                className="fc-logistics-button-primary"
              >
                Consultar
              </button>
              <button
                type="button"
                onClick={() => consultarPar(true)}
                disabled={consultaLoading}
                className="fc-logistics-button-secondary"
              >
                Recalcular par
              </button>
            </div>

            {consultaError && (
              <div className="fc-logistics-message fc-logistics-message-error">
                {consultaError}
              </div>
            )}

            {consultaPar && (
              <div className="fc-logistics-route-result">
                <p className="fc-logistics-route-title">
                  {consultaPar.origem.nome || nomeClinica(consultaPar.origem.id)} -&gt;{" "}
                  {consultaPar.destino.nome || nomeClinica(consultaPar.destino.id)}
                </p>
                <div className="fc-logistics-route-metrics">
                  <div><span>Perfil</span><strong>{consultaPar.item.perfil}</strong></div>
                  <div><span>Duração</span><strong>{consultaPar.item.duracao_min} min</strong></div>
                  <div><span>Distância</span><strong>{consultaPar.item.distancia_km} km</strong></div>
                  <div><span>Fonte</span><strong>{consultaPar.item.fonte}</strong></div>
                </div>
                <small>Ajuste manual: {consultaPar.item.manual_override ? "sim" : "não"}</small>
              </div>
            )}
          </section>

          <section className="fc-logistics-panel fc-logistics-panel-vital">
            <div className="fc-logistics-panel-title">
              <Save className="h-5 w-5" />
              <div><span>Calibração operacional</span><h2>Ajuste manual</h2></div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <label className="fc-logistics-label">Distância (km)</label>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={manualDistanciaKm}
                  onChange={(e) => setManualDistanciaKm(e.target.value)}
                  className="fc-logistics-control"
                />
              </div>
              <div>
                <label className="fc-logistics-label">Duração (min)</label>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={manualDuracaoMin}
                  onChange={(e) => setManualDuracaoMin(e.target.value)}
                  className="fc-logistics-control"
                />
              </div>
              <div className="md:col-span-2">
                <label className="fc-logistics-label">Observações</label>
                <textarea
                  rows={2}
                  value={manualObservacoes}
                  onChange={(e) => setManualObservacoes(e.target.value)}
                  className="fc-logistics-control"
                  placeholder="Opcional"
                />
              </div>
            </div>

            <button
              type="button"
              onClick={salvarAjusteManual}
              disabled={manualSaving}
              className="fc-logistics-button-save"
            >
              <Save className="h-4 w-4" />
              {manualSaving ? "Salvando..." : "Salvar ajuste manual"}
            </button>

            {manualMensagem && (
              <div className="fc-logistics-message fc-logistics-message-success">
                {manualMensagem}
              </div>
            )}
            {manualError && (
              <div className="fc-logistics-message fc-logistics-message-error">
                {manualError}
              </div>
            )}
          </section>
        </div>

        <section className="fc-logistics-panel fc-logistics-panel-ink">
          <div className="fc-logistics-panel-title">
            <RefreshCw className="h-5 w-5" />
            <div><span>Manutenção da base</span><h2>Recálculo da matriz</h2></div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
            <div>
              <label className="fc-logistics-label">Clínica alvo (opcional)</label>
              <select
                value={recalculoClinicaId}
                onChange={(e) => setRecalculoClinicaId(e.target.value)}
                className="fc-logistics-control"
              >
                <option value="">Todas as clinicas</option>
                {clinicas.map((c) => (
                  <option key={`recalc-${c.id}`} value={String(c.id)}>
                    {c.nome}
                  </option>
                ))}
              </select>
            </div>
            <label className="fc-logistics-check">
              <input
                type="checkbox"
                checked={recalculoForce}
                onChange={(e) => setRecalculoForce(e.target.checked)}
              />
              Forçar override (inclui itens manuais)
            </label>
            <button
              type="button"
              onClick={recalcularMatriz}
              disabled={recalculoLoading}
              className="fc-logistics-button-secondary"
            >
              {recalculoLoading ? "Recalculando..." : "Recalcular matriz"}
            </button>
          </div>

          {recalculoMensagem && (
            <div className="fc-logistics-message fc-logistics-message-info">
              {recalculoMensagem}
            </div>
          )}
          {recalculoError && (
            <div className="fc-logistics-message fc-logistics-message-error">
              {recalculoError}
            </div>
          )}
        </section>

        <section className="fc-logistics-monitor">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2">
                <Clock className="h-5 w-5" />
                Monitoramento Google Maps
              </h2>
              <p>
                Janela dos últimos {googleMapsResumo?.window_days || 30} dias com cache de rotas e chamadas reais.
              </p>
            </div>
            <button
              type="button"
              onClick={carregarResumoGoogleMaps}
              disabled={resumoLoading}
              className="fc-logistics-button-monitor"
            >
              <RefreshCw className="h-4 w-4" />
              {resumoLoading ? "Atualizando..." : "Atualizar monitor"}
            </button>
          </div>

          {resumoError && (
            <div className="fc-logistics-message fc-logistics-message-error">
              {resumoError}
            </div>
          )}

          <div className="fc-logistics-monitor-metrics">
            <div className="fc-logistics-monitor-metric fc-logistics-monitor-metric-ink">
              <p className="text-xs uppercase tracking-wide text-slate-500">Chamadas API</p>
              <p className="text-2xl font-semibold text-slate-900">{googleMapsResumo?.total_api_calls ?? 0}</p>
              <p className="text-xs text-slate-600">Retencao de metricas: {googleMapsResumo?.metrics_retention_days ?? 90} dias</p>
            </div>
            <div className="fc-logistics-monitor-metric fc-logistics-monitor-metric-vital">
              <p className="text-xs uppercase tracking-wide text-emerald-600">Taxa de sucesso</p>
              <p className="text-2xl font-semibold text-emerald-900">
                {Number(googleMapsResumo?.success_rate_percent ?? 0).toFixed(1)}%
              </p>
              <p className="text-xs text-emerald-700">
                {Object.entries(googleMapsResumo?.status_counts || {})
                  .map(([status, total]) => `${status}: ${total}`)
                  .join(" | ") || "Sem chamadas registradas"}
              </p>
            </div>
            <div className="fc-logistics-monitor-metric fc-logistics-monitor-metric-cordis">
              <p className="text-xs uppercase tracking-wide text-blue-600">Cache Google</p>
              <p className="text-2xl font-semibold text-blue-900">{googleMapsResumo?.cache?.google_rows ?? 0}</p>
              <p className="text-xs text-blue-700">
                Atuais: {googleMapsResumo?.cache?.fresh_rows ?? 0} | Requerem revisão: {googleMapsResumo?.cache?.stale_rows ?? 0}
              </p>
            </div>
            <div className="fc-logistics-monitor-metric fc-logistics-monitor-metric-amber">
              <p className="text-xs uppercase tracking-wide text-amber-600">Validade</p>
              <p className="text-2xl font-semibold text-amber-900">{percentualCacheFresco}%</p>
              <p className="text-xs text-amber-700">
                {googleMapsResumo?.cache_expires_by_age === false
                  ? "Sem expiração por idade"
                  : `Expira em ${googleMapsResumo?.cache_max_age_days ?? 7} dias`}
              </p>
            </div>
          </div>

          <div className="fc-logistics-monitor-grid">
            <div className="fc-logistics-monitor-list">
              <h3 className="text-sm font-semibold text-gray-900">Operações cobradas</h3>
              {topOperacoes.length === 0 ? (
                <p className="text-sm text-gray-500">Nenhuma chamada registrada ainda.</p>
              ) : (
                <div className="space-y-2">
                  {topOperacoes.map(([operacao, total]) => (
                    <div key={operacao} className="flex items-center justify-between text-sm">
                      <span className="text-gray-700">{operacao}</span>
                      <span className="font-medium text-gray-900">{total}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="fc-logistics-monitor-list">
              <h3 className="text-sm font-semibold text-gray-900">Últimos dias com chamadas</h3>
              {topDiasChamadas.length === 0 ? (
                <p className="text-sm text-gray-500">Sem atividade recente registrada.</p>
              ) : (
                <div className="space-y-2">
                  {topDiasChamadas.map(([dia, total]) => (
                    <div key={dia} className="flex items-center justify-between text-sm">
                      <span className="text-gray-700">{dia}</span>
                      <span className="font-medium text-gray-900">{total}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="fc-logistics-monitor-list">
              <h3 className="text-sm font-semibold text-gray-900">Pares mais consultados</h3>
              {googleMapsResumo?.top_pairs?.length ? (
                <div className="space-y-2">
                  {googleMapsResumo.top_pairs.map((item, index) => (
                    <div key={`${item.origem_clinica_id}-${item.destino_clinica_id}-${index}`} className="fc-logistics-pair-item">
                      <p className="font-medium text-gray-900">
                        {nomeClinica(Number(item.origem_clinica_id || 0))} -&gt;{" "}
                        {nomeClinica(Number(item.destino_clinica_id || 0))}
                      </p>
                      <p className="text-gray-600">Chamadas: {item.calls}</p>
                      <p className="text-gray-500">Ultima vez: {formatarDataHora(item.last_called_at)}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">Nenhum par consultado ainda.</p>
              )}
            </div>
          </div>
        </section>

        <section className="fc-logistics-matrix">
          <div className="fc-logistics-matrix-heading">
            <h2>
              <Building2 className="h-5 w-5" />
              Itens da matriz
            </h2>
            <span>
              Clínicas no filtro: {matrizTotalClinicas} | Itens: {matrizItems.length}
            </span>
          </div>

          {matrizError && (
            <div className="fc-logistics-message fc-logistics-message-error m-4">
              {matrizError}
            </div>
          )}

          {loadingClinicas || matrizLoading ? (
            <div className="fc-logistics-loading"><span />Carregando matriz...</div>
          ) : matrizItems.length === 0 ? (
            <div className="fc-logistics-empty">
              Nenhum item encontrado para o filtro atual.
            </div>
          ) : (
            <div className="fc-logistics-table-scroll">
              <table className="fc-logistics-table">
                <thead>
                  <tr>
                    <th>Origem</th>
                    <th>Destino</th>
                    <th>Perfil</th>
                    <th>Dist. km</th>
                    <th>Duração</th>
                    <th>Fonte</th>
                    <th>Manual</th>
                  </tr>
                </thead>
                <tbody>
                  {matrizItems.map((item) => (
                    <tr key={item.id}>
                      <td>{nomeClinica(item.origem_clinica_id)}</td>
                      <td>{nomeClinica(item.destino_clinica_id)}</td>
                      <td>{item.perfil}</td>
                      <td>{Number(item.distancia_km || 0).toFixed(2)}</td>
                      <td>{item.duracao_min} min</td>
                      <td>{item.fonte}</td>
                      <td>{item.manual_override ? "sim" : "não"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <div className="fc-logistics-alert">
          <AlertCircle className="mt-0.5 h-4 w-4" />
          <div>
            Para ajustes operacionais, salve manualmente os pares mais críticos nos dois sentidos
            (A -&gt; B e B -&gt; A) e em ambos os perfis quando necessário.
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
