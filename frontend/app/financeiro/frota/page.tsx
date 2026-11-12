"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CarFront, Fuel, Plus, RefreshCw, Save, Settings2, Trash2, Waypoints } from "lucide-react";

import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { operationalTodayDateInput } from "@/lib/calendar-date";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";

type FormaRateio = "por_km" | "por_atendimento" | "fixo_mensal" | "hibrido";
type AbaFrota = "custos" | "veiculos" | "telemetria" | "config";

interface ClinicaOption {
  id: number;
  nome: string;
}

interface CustoFrotaItem {
  id: number;
  data_referencia: string;
  categoria: string;
  valor: number;
  forma_rateio: FormaRateio;
  km_referencia?: number | null;
  atendimentos_referencia?: number | null;
  clinica_id?: number | null;
  veiculo_id?: number | null;
  veiculo?: string | null;
  descricao?: string | null;
  observacoes?: string | null;
}

interface CustoFrotaListaResponse {
  total: number;
  items: CustoFrotaItem[];
}

interface RateioResumoResponse {
  total_periodo: number;
  totais_por_rateio: {
    por_km: number;
    por_atendimento: number;
    fixo_mensal: number;
    hibrido: number;
  };
  indices: {
    custo_por_km: number;
    custo_por_atendimento: number;
    custo_hibrido_por_km: number;
    custo_hibrido_por_atendimento: number;
  };
  config_rateio: {
    peso_km: number;
    peso_atendimento: number;
    auto_gerar_depreciacao: boolean;
  };
}

interface VeiculoFrotaItem {
  id: number;
  nome: string;
  placa?: string | null;
  tipo_combustivel?: string | null;
  consumo_km_litro?: number | null;
  valor_aquisicao?: number | null;
  valor_residual?: number | null;
  vida_util_meses?: number | null;
  ativo: boolean;
}

interface VeiculoFrotaListaResponse {
  total: number;
  items: VeiculoFrotaItem[];
}

interface TelemetriaFrotaItem {
  id: number;
  veiculo_id: number;
  competencia: string;
  km_inicial?: number | null;
  km_final?: number | null;
  km_rodado?: number | null;
  litros_consumidos?: number | null;
  valor_combustivel?: number | null;
}

interface TelemetriaFrotaListaResponse {
  total: number;
  items: TelemetriaFrotaItem[];
}

interface ConfigRateioFrotaResponse {
  id: number;
  peso_km: number;
  peso_atendimento: number;
  auto_gerar_depreciacao: boolean;
}

interface DepreciacaoDetalhe {
  veiculo_id: number;
  veiculo_nome: string;
  status: string;
  valor?: number;
}

interface DepreciacaoResponse {
  competencia: string;
  criados: number;
  ignorados: number;
  detalhes: DepreciacaoDetalhe[];
}

const CATEGORIAS_FROTA = [
  "combustivel",
  "pedagio",
  "manutencao_veiculo",
  "seguro_veiculo",
  "ipva_licenciamento",
  "depreciacao_veiculo",
  "outros",
] as const;

const FORMAS_RATEIO: Array<{ id: FormaRateio; label: string }> = [
  { id: "por_km", label: "Por KM" },
  { id: "por_atendimento", label: "Por atendimento" },
  { id: "hibrido", label: "Hibrido" },
  { id: "fixo_mensal", label: "Fixo mensal" },
];

const ABAS: Array<{ id: AbaFrota; label: string }> = [
  { id: "custos", label: "Custos" },
  { id: "veiculos", label: "Veículos" },
  { id: "telemetria", label: "Telemetria" },
  { id: "config", label: "Configuração" },
];

const hojeISO = () => operationalTodayDateInput();
const competenciaAtual = () => hojeISO().slice(0, 7);

const parseNumero = (raw: string): number | null => {
  if (!raw.trim()) return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
};

const formatarNumero = (valor: number, casas = 2): string => {
  const numero = Number.isFinite(valor) ? valor : 0;
  return numero.toLocaleString("pt-BR", {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });
};

const formatarMoeda = (valor: number): string => {
  const numero = Number.isFinite(valor) ? valor : 0;
  return numero.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
};

const labelVeiculo = (item: VeiculoFrotaItem) => {
  const placa = (item.placa || "").trim();
  return placa ? `${item.nome} (${placa})` : item.nome;
};

export default function CustosFrotaPage() {
  const router = useRouter();

  const [tab, setTab] = useState<AbaFrota>("custos");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [erro, setErro] = useState("");
  const [sucesso, setSucesso] = useState("");

  const [clinicas, setClinicas] = useState<ClinicaOption[]>([]);
  const [veiculos, setVeiculos] = useState<VeiculoFrotaItem[]>([]);
  const [custos, setCustos] = useState<CustoFrotaItem[]>([]);
  const [telemetria, setTelemetria] = useState<TelemetriaFrotaItem[]>([]);
  const [resumoRateio, setResumoRateio] = useState<RateioResumoResponse | null>(null);

  const [filtroInicio, setFiltroInicio] = useState(hojeISO().slice(0, 8) + "01");
  const [filtroFim, setFiltroFim] = useState(hojeISO());
  const [filtroCategoria, setFiltroCategoria] = useState("");
  const [filtroRateio, setFiltroRateio] = useState("");

  const [kmPeriodo, setKmPeriodo] = useState("0");
  const [atendimentosPeriodo, setAtendimentosPeriodo] = useState("0");

  const [custoIdEdit, setCustoIdEdit] = useState<number | null>(null);
  const [custoForm, setCustoForm] = useState({
    data_referencia: hojeISO(),
    categoria: "combustivel",
    valor: "",
    forma_rateio: "por_km" as FormaRateio,
    clinica_id: "",
    veiculo_id: "",
    km_referencia: "",
    atendimentos_referencia: "",
    descricao: "",
  });

  const [veiculoIdEdit, setVeiculoIdEdit] = useState<number | null>(null);
  const [veiculoForm, setVeiculoForm] = useState({
    nome: "",
    placa: "",
    tipo_combustivel: "",
    consumo_km_litro: "",
    valor_aquisicao: "",
    valor_residual: "",
    vida_util_meses: "",
    ativo: true,
  });

  const [telemetriaIdEdit, setTelemetriaIdEdit] = useState<number | null>(null);
  const [telemetriaFiltroCompetencia, setTelemetriaFiltroCompetencia] = useState(competenciaAtual());
  const [telemetriaFiltroVeiculo, setTelemetriaFiltroVeiculo] = useState("");
  const [telemetriaForm, setTelemetriaForm] = useState({
    veiculo_id: "",
    competencia: competenciaAtual(),
    km_inicial: "",
    km_final: "",
    km_rodado: "",
    litros_consumidos: "",
    valor_combustivel: "",
  });

  const [configRateioId, setConfigRateioId] = useState<number | null>(null);
  const [configForm, setConfigForm] = useState({
    peso_km: "0.7",
    peso_atendimento: "0.3",
    auto_gerar_depreciacao: false,
  });

  const [competenciaDepreciacao, setCompetenciaDepreciacao] = useState(competenciaAtual());
  const [resultadoDepreciacao, setResultadoDepreciacao] = useState<DepreciacaoResponse | null>(null);

  const custoTotal = useMemo(() => custos.reduce((acc, item) => acc + Number(item.valor || 0), 0), [custos]);

  const veiculoMap = useMemo(() => {
    const map = new Map<number, string>();
    veiculos.forEach((item) => map.set(item.id, labelVeiculo(item)));
    return map;
  }, [veiculos]);

  const custosFiltrados = useMemo(
    () => custos.filter((item) => (!filtroCategoria || item.categoria === filtroCategoria) && (!filtroRateio || item.forma_rateio === filtroRateio)),
    [custos, filtroCategoria, filtroRateio]
  );

  const resetMensagens = () => {
    setErro("");
    setSucesso("");
  };

  const carregarClinicas = async (silencioso = false) => {
    try {
      const payload = await loadStableCatalog({
        catalog: "clinicas",
        variant: "limit=1000",
        load: () => api.get("/clinicas?limit=1000").then((response) => response.data),
      });
      const items = Array.isArray(payload?.items) ? payload.items : [];
      setClinicas(items.map((c: { id: number; nome?: string }) => ({ id: Number(c.id), nome: String(c.nome || `Clinica #${c.id}`) })));
    } catch {
      if (!silencioso) setErro("Falha ao carregar clinicas.");
    }
  };

  const carregarVeiculos = async (silencioso = false) => {
    try {
      const response = await api.get<VeiculoFrotaListaResponse>("/financeiro/frota/veiculos", { params: { limit: 1000 } });
      setVeiculos(Array.isArray(response.data?.items) ? response.data.items : []);
    } catch {
      if (!silencioso) setErro("Falha ao carregar veiculos.");
    }
  };

  const carregarCustos = async (silencioso = false) => {
    try {
      const response = await api.get<CustoFrotaListaResponse>("/financeiro/custos-frota", {
        params: { data_inicio: filtroInicio, data_fim: filtroFim, limit: 1000 },
      });
      setCustos(Array.isArray(response.data?.items) ? response.data.items : []);
    } catch {
      if (!silencioso) setErro("Falha ao carregar custos de frota.");
    }
  };

  const carregarTelemetria = async (silencioso = false) => {
    try {
      const params: Record<string, string | number> = { limit: 1000 };
      if (telemetriaFiltroCompetencia) params.competencia = telemetriaFiltroCompetencia;
      if (telemetriaFiltroVeiculo) params.veiculo_id = Number(telemetriaFiltroVeiculo);
      const response = await api.get<TelemetriaFrotaListaResponse>("/financeiro/frota/telemetria", { params });
      setTelemetria(Array.isArray(response.data?.items) ? response.data.items : []);
    } catch {
      if (!silencioso) setErro("Falha ao carregar telemetria.");
    }
  };

  const carregarResumoRateio = async (silencioso = false) => {
    try {
      const response = await api.get<RateioResumoResponse>("/financeiro/custos-frota/rateio-resumo", {
        params: {
          data_inicio: filtroInicio,
          data_fim: filtroFim,
          km_rodado_periodo: Number(kmPeriodo || 0),
          atendimentos_periodo: Number(atendimentosPeriodo || 0),
        },
      });
      setResumoRateio(response.data);
    } catch {
      setResumoRateio(null);
      if (!silencioso) setErro("Falha ao calcular rateio.");
    }
  };

  const carregarConfigRateio = async (silencioso = false) => {
    try {
      const response = await api.get<ConfigRateioFrotaResponse>("/financeiro/frota/rateio-config");
      setConfigRateioId(response.data.id);
      setConfigForm({
        peso_km: String(response.data.peso_km ?? 0.7),
        peso_atendimento: String(response.data.peso_atendimento ?? 0.3),
        auto_gerar_depreciacao: Boolean(response.data.auto_gerar_depreciacao),
      });
    } catch {
      if (!silencioso) setErro("Falha ao carregar configuracao de rateio.");
    }
  };

  const carregarTudo = async () => {
    try {
      setLoading(true);
      resetMensagens();
      await Promise.all([
        carregarClinicas(true),
        carregarVeiculos(true),
        carregarCustos(true),
        carregarTelemetria(true),
        carregarResumoRateio(true),
        carregarConfigRateio(true),
      ]);
    } finally {
      setLoading(false);
    }
  };

  const salvarCusto = async () => {
    const valor = Number(custoForm.valor || 0);
    if (valor <= 0) {
      setErro("Informe valor maior que zero.");
      return;
    }

    const payload = {
      data_referencia: `${custoForm.data_referencia}T00:00:00`,
      categoria: custoForm.categoria,
      valor,
      forma_rateio: custoForm.forma_rateio,
      clinica_id: custoForm.clinica_id ? Number(custoForm.clinica_id) : null,
      veiculo_id: custoForm.veiculo_id ? Number(custoForm.veiculo_id) : null,
      km_referencia: parseNumero(custoForm.km_referencia),
      atendimentos_referencia: parseNumero(custoForm.atendimentos_referencia),
      descricao: custoForm.descricao.trim() || null,
    };

    try {
      setSaving(true);
      resetMensagens();
      if (custoIdEdit) {
        await api.put(`/financeiro/custos-frota/${custoIdEdit}`, payload);
        setSucesso("Custo atualizado.");
      } else {
        await api.post("/financeiro/custos-frota", payload);
        setSucesso("Custo criado.");
      }
      setCustoIdEdit(null);
      setCustoForm({
        data_referencia: hojeISO(),
        categoria: "combustivel",
        valor: "",
        forma_rateio: "por_km",
        clinica_id: "",
        veiculo_id: "",
        km_referencia: "",
        atendimentos_referencia: "",
        descricao: "",
      });
      await Promise.all([carregarCustos(true), carregarResumoRateio(true)]);
    } catch {
      setErro("Falha ao salvar custo.");
    } finally {
      setSaving(false);
    }
  };

  const salvarVeiculo = async () => {
    if (!veiculoForm.nome.trim()) {
      setErro("Informe o nome do veiculo.");
      return;
    }

    const payload = {
      nome: veiculoForm.nome.trim(),
      placa: veiculoForm.placa.trim() || null,
      tipo_combustivel: veiculoForm.tipo_combustivel.trim() || null,
      consumo_km_litro: parseNumero(veiculoForm.consumo_km_litro),
      valor_aquisicao: parseNumero(veiculoForm.valor_aquisicao),
      valor_residual: parseNumero(veiculoForm.valor_residual),
      vida_util_meses: parseNumero(veiculoForm.vida_util_meses),
      ativo: Boolean(veiculoForm.ativo),
    };

    try {
      setSaving(true);
      resetMensagens();
      if (veiculoIdEdit) {
        await api.put(`/financeiro/frota/veiculos/${veiculoIdEdit}`, payload);
        setSucesso("Veiculo atualizado.");
      } else {
        await api.post("/financeiro/frota/veiculos", payload);
        setSucesso("Veiculo cadastrado.");
      }
      setVeiculoIdEdit(null);
      setVeiculoForm({
        nome: "",
        placa: "",
        tipo_combustivel: "",
        consumo_km_litro: "",
        valor_aquisicao: "",
        valor_residual: "",
        vida_util_meses: "",
        ativo: true,
      });
      await Promise.all([carregarVeiculos(true), carregarCustos(true), carregarTelemetria(true)]);
    } catch {
      setErro("Falha ao salvar veiculo.");
    } finally {
      setSaving(false);
    }
  };

  const salvarTelemetria = async () => {
    if (!telemetriaForm.veiculo_id) {
      setErro("Selecione um veiculo.");
      return;
    }

    const payload = {
      veiculo_id: Number(telemetriaForm.veiculo_id),
      competencia: telemetriaForm.competencia,
      km_inicial: parseNumero(telemetriaForm.km_inicial),
      km_final: parseNumero(telemetriaForm.km_final),
      km_rodado: parseNumero(telemetriaForm.km_rodado),
      litros_consumidos: parseNumero(telemetriaForm.litros_consumidos),
      valor_combustivel: parseNumero(telemetriaForm.valor_combustivel),
    };

    try {
      setSaving(true);
      resetMensagens();
      if (telemetriaIdEdit) {
        await api.put(`/financeiro/frota/telemetria/${telemetriaIdEdit}`, {
          competencia: payload.competencia,
          km_inicial: payload.km_inicial,
          km_final: payload.km_final,
          km_rodado: payload.km_rodado,
          litros_consumidos: payload.litros_consumidos,
          valor_combustivel: payload.valor_combustivel,
        });
        setSucesso("Telemetria atualizada.");
      } else {
        await api.post("/financeiro/frota/telemetria", payload);
        setSucesso("Telemetria registrada.");
      }
      setTelemetriaIdEdit(null);
      setTelemetriaForm({
        veiculo_id: "",
        competencia: competenciaAtual(),
        km_inicial: "",
        km_final: "",
        km_rodado: "",
        litros_consumidos: "",
        valor_combustivel: "",
      });
      await carregarTelemetria(true);
    } catch {
      setErro("Falha ao salvar telemetria.");
    } finally {
      setSaving(false);
    }
  };

  const salvarConfigRateio = async () => {
    const pesoKm = Number(configForm.peso_km || 0);
    const pesoAtendimento = Number(configForm.peso_atendimento || 0);
    if (pesoKm < 0 || pesoAtendimento < 0 || pesoKm + pesoAtendimento <= 0) {
      setErro("Pesos invalidos para rateio.");
      return;
    }

    try {
      setSaving(true);
      resetMensagens();
      const response = await api.put<ConfigRateioFrotaResponse>("/financeiro/frota/rateio-config", {
        peso_km: pesoKm,
        peso_atendimento: pesoAtendimento,
        auto_gerar_depreciacao: configForm.auto_gerar_depreciacao,
      });
      setConfigRateioId(response.data.id);
      setConfigForm({
        peso_km: String(response.data.peso_km),
        peso_atendimento: String(response.data.peso_atendimento),
        auto_gerar_depreciacao: Boolean(response.data.auto_gerar_depreciacao),
      });
      setSucesso("Configuracao salva.");
      await carregarResumoRateio(true);
    } catch {
      setErro("Falha ao salvar configuracao.");
    } finally {
      setSaving(false);
    }
  };

  const gerarDepreciacao = async () => {
    if (!/^\d{4}-\d{2}$/.test(competenciaDepreciacao)) {
      setErro("Competencia invalida. Use YYYY-MM.");
      return;
    }

    try {
      setSaving(true);
      resetMensagens();
      const response = await api.post<DepreciacaoResponse>("/financeiro/custos-frota/depreciacao/gerar", null, {
        params: { competencia: competenciaDepreciacao },
      });
      setResultadoDepreciacao(response.data);
      setSucesso("Depreciacao processada.");
      await Promise.all([carregarCustos(true), carregarResumoRateio(true)]);
    } catch {
      setErro("Falha ao gerar depreciacao.");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    void carregarTudo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  useEffect(() => {
    if (!loading) {
      void Promise.all([carregarCustos(true), carregarResumoRateio(true)]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroInicio, filtroFim]);

  useEffect(() => {
    if (!loading) {
      void carregarTelemetria(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [telemetriaFiltroCompetencia, telemetriaFiltroVeiculo]);

  return (
    <DashboardLayout>
      <div className="fc-fleet-page">
        <header className="fc-fleet-header">
          <div>
            <span className="fc-fleet-kicker"><CarFront className="h-4 w-4" />Financeiro e mobilidade</span>
            <h1>Gestão de Frota</h1>
            <p>Custos, veículos, telemetria, rateio híbrido e depreciação mensal.</p>
          </div>
          <button type="button" onClick={() => void carregarTudo()} className="fc-fleet-refresh">
            <RefreshCw className="h-4 w-4" />
            Atualizar dados
          </button>
        </header>

        <section className="fc-fleet-metrics" aria-label="Resumo da frota">
          <div className="fc-fleet-metric fc-fleet-metric-cordis">
            <CarFront className="h-5 w-5" />
            <strong>{formatarMoeda(custoTotal)}</strong>
            <span>Custos no período</span>
          </div>
          <div className="fc-fleet-metric fc-fleet-metric-vital">
            <Fuel className="h-5 w-5" />
            <strong>{veiculos.filter((veiculo) => veiculo.ativo).length}</strong>
            <span>Veículos ativos</span>
          </div>
          <div className="fc-fleet-metric fc-fleet-metric-amber">
            <Waypoints className="h-5 w-5" />
            <strong>{telemetria.length}</strong>
            <span>Registros de telemetria</span>
          </div>
          <div className="fc-fleet-metric fc-fleet-metric-ink">
            <Settings2 className="h-5 w-5" />
            <strong>{Math.round(Number(resumoRateio?.config_rateio?.peso_km || 0) * 100)}%</strong>
            <span>Peso do KM no rateio</span>
          </div>
        </section>

        <nav className="fc-fleet-tabs" role="tablist" aria-label="Áreas da gestão de frota">
          {ABAS.map((aba) => (
            <button
              key={aba.id}
              type="button"
              onClick={() => setTab(aba.id)}
              role="tab"
              aria-selected={tab === aba.id}
              className={`fc-fleet-tab ${tab === aba.id ? "fc-fleet-tab-active" : ""}`}
            >
              {aba.label}
            </button>
          ))}
        </nav>

        {tab === "custos" ? (
          <div className="fc-fleet-view">
            <div className="fc-fleet-filters grid grid-cols-1 gap-3 md:grid-cols-4 xl:grid-cols-6">
              <div>
                <label className="text-xs text-gray-600 block mb-1">Data inicio</label>
                <input type="date" value={filtroInicio} onChange={(e) => setFiltroInicio(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
              </div>
              <div>
                <label className="text-xs text-gray-600 block mb-1">Data fim</label>
                <input type="date" value={filtroFim} onChange={(e) => setFiltroFim(e.target.value)} className="w-full px-3 py-2 border rounded-lg" />
              </div>
              <div>
                <label className="text-xs text-gray-600 block mb-1">Categoria</label>
                <select value={filtroCategoria} onChange={(e) => setFiltroCategoria(e.target.value)} className="w-full px-3 py-2 border rounded-lg">
                  <option value="">Todas</option>
                  {CATEGORIAS_FROTA.map((item) => (<option key={item} value={item}>{item}</option>))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-600 block mb-1">Rateio</label>
                <select value={filtroRateio} onChange={(e) => setFiltroRateio(e.target.value)} className="w-full px-3 py-2 border rounded-lg">
                  <option value="">Todos</option>
                  {FORMAS_RATEIO.map((item) => (<option key={item.id} value={item.id}>{item.label}</option>))}
                </select>
              </div>
              <button type="button" onClick={() => void Promise.all([carregarCustos(), carregarResumoRateio()])} className="px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50">Atualizar custos</button>
              <button type="button" onClick={() => { setCustoIdEdit(null); setCustoForm((prev) => ({ ...prev, valor: "", descricao: "" })); }} className="inline-flex items-center gap-2 px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50"><Plus className="w-4 h-4" />Novo</button>
            </div>

            <div className="fc-fleet-panel fc-fleet-panel-cordis">
              <div className="fc-fleet-panel-title">
                <CarFront className="w-4 h-4 text-blue-600" />
                <h2 className="font-semibold text-gray-900">{custoIdEdit ? `Editar custo #${custoIdEdit}` : "Novo custo de frota"}</h2>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                <input type="date" value={custoForm.data_referencia} onChange={(e) => setCustoForm((prev) => ({ ...prev, data_referencia: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <select value={custoForm.categoria} onChange={(e) => setCustoForm((prev) => ({ ...prev, categoria: e.target.value }))} className="px-3 py-2 border rounded-lg">
                  {CATEGORIAS_FROTA.map((item) => (<option key={item} value={item}>{item}</option>))}
                </select>
                <input type="number" min="0" step="0.01" placeholder="Valor" value={custoForm.valor} onChange={(e) => setCustoForm((prev) => ({ ...prev, valor: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <select value={custoForm.forma_rateio} onChange={(e) => setCustoForm((prev) => ({ ...prev, forma_rateio: e.target.value as FormaRateio }))} className="px-3 py-2 border rounded-lg">
                  {FORMAS_RATEIO.map((item) => (<option key={item.id} value={item.id}>{item.label}</option>))}
                </select>
                <select value={custoForm.clinica_id} onChange={(e) => setCustoForm((prev) => ({ ...prev, clinica_id: e.target.value }))} className="px-3 py-2 border rounded-lg">
                  <option value="">Sem clinica</option>
                  {clinicas.map((item) => (<option key={item.id} value={String(item.id)}>{item.nome}</option>))}
                </select>
                <select value={custoForm.veiculo_id} onChange={(e) => setCustoForm((prev) => ({ ...prev, veiculo_id: e.target.value }))} className="px-3 py-2 border rounded-lg">
                  <option value="">Sem veiculo</option>
                  {veiculos.map((item) => (<option key={item.id} value={String(item.id)}>{labelVeiculo(item)}</option>))}
                </select>
                <input type="number" min="0" step="0.01" placeholder="KM referencia" value={custoForm.km_referencia} onChange={(e) => setCustoForm((prev) => ({ ...prev, km_referencia: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="1" placeholder="Atendimentos" value={custoForm.atendimentos_referencia} onChange={(e) => setCustoForm((prev) => ({ ...prev, atendimentos_referencia: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="text" placeholder="Descricao" value={custoForm.descricao} onChange={(e) => setCustoForm((prev) => ({ ...prev, descricao: e.target.value }))} className="md:col-span-2 xl:col-span-4 px-3 py-2 border rounded-lg" />
              </div>
              <button type="button" onClick={() => void salvarCusto()} disabled={saving} className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-60"><Save className="w-4 h-4" />{saving ? "Salvando..." : "Salvar custo"}</button>
            </div>

            <div className="fc-fleet-panel fc-fleet-panel-vital space-y-3">
              <h2 className="fc-fleet-section-title">Resumo de rateio</h2>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <input type="number" min="0" step="0.01" placeholder="KM periodo" value={kmPeriodo} onChange={(e) => setKmPeriodo(e.target.value)} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="1" placeholder="Atendimentos periodo" value={atendimentosPeriodo} onChange={(e) => setAtendimentosPeriodo(e.target.value)} className="px-3 py-2 border rounded-lg" />
                <button type="button" onClick={() => void carregarResumoRateio()} className="px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50">Recalcular</button>
                <button type="button" onClick={() => setTab("config")} className="px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50">Ir para configuracao</button>
              </div>
              {resumoRateio ? (
                <div className="fc-fleet-summary-grid">
                  <div>Total: <b>{formatarMoeda(resumoRateio.total_periodo)}</b></div>
                  <div>Por KM: <b>{formatarMoeda(resumoRateio.indices.custo_por_km)}</b></div>
                  <div>Por atendimento: <b>{formatarMoeda(resumoRateio.indices.custo_por_atendimento)}</b></div>
                  <div>Híbrido/atend.: <b>{formatarMoeda(resumoRateio.indices.custo_hibrido_por_atendimento)}</b></div>
                </div>
              ) : <p className="text-sm text-gray-500">Sem dados de rateio.</p>}
            </div>

            <div className="fc-fleet-table-panel">
              <div className="fc-fleet-table-heading"><h2>Lançamentos</h2><span>Total: {formatarMoeda(custoTotal)}</span></div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-600"><tr><th className="text-left px-4 py-2">Data</th><th className="text-left px-4 py-2">Categoria</th><th className="text-right px-4 py-2">Valor</th><th className="text-left px-4 py-2">Rateio</th><th className="text-left px-4 py-2">Veiculo</th><th className="text-right px-4 py-2">Acoes</th></tr></thead>
                  <tbody>
                    {custosFiltrados.length === 0 ? (<tr><td colSpan={6} className="px-4 py-6 text-center text-gray-500">Sem lancamentos.</td></tr>) : custosFiltrados.map((item) => (
                      <tr key={item.id} className="border-t">
                        <td className="px-4 py-2">{String(item.data_referencia || "").slice(0, 10)}</td>
                        <td className="px-4 py-2">{item.categoria}</td>
                        <td className="px-4 py-2 text-right">{formatarMoeda(item.valor)}</td>
                        <td className="px-4 py-2">{item.forma_rateio}</td>
                        <td className="px-4 py-2">{item.veiculo_id ? veiculoMap.get(item.veiculo_id) || `Veiculo #${item.veiculo_id}` : "-"}</td>
                        <td className="px-4 py-2 text-right"><div className="inline-flex items-center gap-2"><button type="button" onClick={() => { setCustoIdEdit(item.id); setCustoForm({ data_referencia: String(item.data_referencia || "").slice(0, 10), categoria: item.categoria || "combustivel", valor: String(item.valor || ""), forma_rateio: item.forma_rateio || "por_km", clinica_id: item.clinica_id ? String(item.clinica_id) : "", veiculo_id: item.veiculo_id ? String(item.veiculo_id) : "", km_referencia: item.km_referencia != null ? String(item.km_referencia) : "", atendimentos_referencia: item.atendimentos_referencia != null ? String(item.atendimentos_referencia) : "", descricao: item.descricao || "" }); }} className="px-2 py-1 border rounded text-xs">Editar</button><button type="button" onClick={() => void (async () => { if (!confirm("Remover este custo?")) return; try { await api.delete(`/financeiro/custos-frota/${item.id}`); await Promise.all([carregarCustos(true), carregarResumoRateio(true)]); } catch { setErro("Falha ao remover custo."); } })()} className="inline-flex items-center gap-1 px-2 py-1 border rounded text-xs text-red-700"><Trash2 className="w-3 h-3" />Remover</button></div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : null}

        {tab === "veiculos" ? (
          <div className="fc-fleet-view">
            <div className="fc-fleet-panel fc-fleet-panel-vital">
              <div className="fc-fleet-panel-title"><Fuel className="h-4 w-4" /><h2>{veiculoIdEdit ? `Editar veículo #${veiculoIdEdit}` : "Cadastro de veículo"}</h2></div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                <input type="text" placeholder="Nome" value={veiculoForm.nome} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, nome: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="text" placeholder="Placa" value={veiculoForm.placa} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, placa: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="text" placeholder="Combustivel" value={veiculoForm.tipo_combustivel} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, tipo_combustivel: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="Consumo km/l" value={veiculoForm.consumo_km_litro} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, consumo_km_litro: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="Valor aquisicao" value={veiculoForm.valor_aquisicao} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, valor_aquisicao: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="Valor residual" value={veiculoForm.valor_residual} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, valor_residual: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="1" step="1" placeholder="Vida util meses" value={veiculoForm.vida_util_meses} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, vida_util_meses: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <label className="inline-flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={veiculoForm.ativo} onChange={(e) => setVeiculoForm((prev) => ({ ...prev, ativo: e.target.checked }))} />Ativo</label>
              </div>
              <button type="button" onClick={() => void salvarVeiculo()} disabled={saving} className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-60"><Save className="w-4 h-4" />Salvar veiculo</button>
            </div>

            <div className="fc-fleet-table-panel">
              <div className="fc-fleet-table-heading"><h2>Veículos cadastrados</h2></div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-600"><tr><th className="text-left px-4 py-2">Nome</th><th className="text-left px-4 py-2">Placa</th><th className="text-right px-4 py-2">Consumo</th><th className="text-left px-4 py-2">Status</th><th className="text-right px-4 py-2">Acoes</th></tr></thead>
                  <tbody>
                    {veiculos.length === 0 ? (<tr><td colSpan={5} className="px-4 py-6 text-center text-gray-500">Nenhum veiculo.</td></tr>) : veiculos.map((item) => (
                      <tr key={item.id} className="border-t">
                        <td className="px-4 py-2">{item.nome}</td>
                        <td className="px-4 py-2">{item.placa || "-"}</td>
                        <td className="px-4 py-2 text-right">{item.consumo_km_litro ? formatarNumero(item.consumo_km_litro) : "-"}</td>
                        <td className="px-4 py-2">{item.ativo ? "Ativo" : "Inativo"}</td>
                        <td className="px-4 py-2 text-right"><div className="inline-flex items-center gap-2"><button type="button" onClick={() => { setVeiculoIdEdit(item.id); setVeiculoForm({ nome: item.nome || "", placa: item.placa || "", tipo_combustivel: item.tipo_combustivel || "", consumo_km_litro: item.consumo_km_litro != null ? String(item.consumo_km_litro) : "", valor_aquisicao: item.valor_aquisicao != null ? String(item.valor_aquisicao) : "", valor_residual: item.valor_residual != null ? String(item.valor_residual) : "", vida_util_meses: item.vida_util_meses != null ? String(item.vida_util_meses) : "", ativo: Boolean(item.ativo) }); }} className="px-2 py-1 border rounded text-xs">Editar</button><button type="button" onClick={() => void (async () => { if (!confirm("Desativar veiculo?")) return; try { await api.delete(`/financeiro/frota/veiculos/${item.id}`); await carregarVeiculos(true); } catch { setErro("Falha ao desativar veiculo."); } })()} className="inline-flex items-center gap-1 px-2 py-1 border rounded text-xs text-red-700"><Trash2 className="w-3 h-3" />Desativar</button></div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : null}

        {tab === "telemetria" ? (
          <div className="fc-fleet-view">
            <div className="fc-fleet-filters grid grid-cols-1 gap-3 md:grid-cols-3">
              <input type="month" value={telemetriaFiltroCompetencia} onChange={(e) => setTelemetriaFiltroCompetencia(e.target.value)} className="px-3 py-2 border rounded-lg" />
              <select value={telemetriaFiltroVeiculo} onChange={(e) => setTelemetriaFiltroVeiculo(e.target.value)} className="px-3 py-2 border rounded-lg"><option value="">Todos os veiculos</option>{veiculos.map((item) => (<option key={item.id} value={String(item.id)}>{labelVeiculo(item)}</option>))}</select>
              <button type="button" onClick={() => void carregarTelemetria()} className="px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50">Atualizar telemetria</button>
            </div>

            <div className="fc-fleet-panel fc-fleet-panel-cordis">
              <div className="fc-fleet-panel-title"><Waypoints className="h-4 w-4" /><h2>{telemetriaIdEdit ? `Editar telemetria #${telemetriaIdEdit}` : "Novo registro de telemetria"}</h2></div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                <select value={telemetriaForm.veiculo_id} onChange={(e) => setTelemetriaForm((prev) => ({ ...prev, veiculo_id: e.target.value }))} className="px-3 py-2 border rounded-lg"><option value="">Selecione veiculo</option>{veiculos.map((item) => (<option key={item.id} value={String(item.id)}>{labelVeiculo(item)}</option>))}</select>
                <input type="month" value={telemetriaForm.competencia} onChange={(e) => setTelemetriaForm((prev) => ({ ...prev, competencia: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="KM inicial" value={telemetriaForm.km_inicial} onChange={(e) => setTelemetriaForm((prev) => ({ ...prev, km_inicial: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="KM final" value={telemetriaForm.km_final} onChange={(e) => setTelemetriaForm((prev) => ({ ...prev, km_final: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="KM rodado" value={telemetriaForm.km_rodado} onChange={(e) => setTelemetriaForm((prev) => ({ ...prev, km_rodado: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="Litros" value={telemetriaForm.litros_consumidos} onChange={(e) => setTelemetriaForm((prev) => ({ ...prev, litros_consumidos: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="Valor combustivel" value={telemetriaForm.valor_combustivel} onChange={(e) => setTelemetriaForm((prev) => ({ ...prev, valor_combustivel: e.target.value }))} className="px-3 py-2 border rounded-lg" />
              </div>
              <button type="button" onClick={() => void salvarTelemetria()} disabled={saving} className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-60"><Save className="w-4 h-4" />Salvar telemetria</button>
            </div>

            <div className="fc-fleet-table-panel">
              <div className="fc-fleet-table-heading"><h2>Registros de telemetria</h2></div>
              <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-gray-50 text-gray-600"><tr><th className="text-left px-4 py-2">Veiculo</th><th className="text-left px-4 py-2">Competencia</th><th className="text-right px-4 py-2">KM rodado</th><th className="text-right px-4 py-2">Combustivel</th><th className="text-right px-4 py-2">Acoes</th></tr></thead><tbody>{telemetria.length === 0 ? (<tr><td colSpan={5} className="px-4 py-6 text-center text-gray-500">Sem registros.</td></tr>) : telemetria.map((item) => (<tr key={item.id} className="border-t"><td className="px-4 py-2">{veiculoMap.get(item.veiculo_id) || `Veiculo #${item.veiculo_id}`}</td><td className="px-4 py-2">{item.competencia}</td><td className="px-4 py-2 text-right">{item.km_rodado != null ? formatarNumero(item.km_rodado) : "-"}</td><td className="px-4 py-2 text-right">{item.valor_combustivel != null ? formatarMoeda(item.valor_combustivel) : "-"}</td><td className="px-4 py-2 text-right"><div className="inline-flex items-center gap-2"><button type="button" onClick={() => { setTelemetriaIdEdit(item.id); setTelemetriaForm({ veiculo_id: String(item.veiculo_id), competencia: item.competencia, km_inicial: item.km_inicial != null ? String(item.km_inicial) : "", km_final: item.km_final != null ? String(item.km_final) : "", km_rodado: item.km_rodado != null ? String(item.km_rodado) : "", litros_consumidos: item.litros_consumidos != null ? String(item.litros_consumidos) : "", valor_combustivel: item.valor_combustivel != null ? String(item.valor_combustivel) : "" }); }} className="px-2 py-1 border rounded text-xs">Editar</button><button type="button" onClick={() => void (async () => { if (!confirm("Remover telemetria?")) return; try { await api.delete(`/financeiro/frota/telemetria/${item.id}`); await carregarTelemetria(true); } catch { setErro("Falha ao remover telemetria."); } })()} className="inline-flex items-center gap-1 px-2 py-1 border rounded text-xs text-red-700"><Trash2 className="w-3 h-3" />Remover</button></div></td></tr>))}</tbody></table></div>
            </div>
          </div>
        ) : null}

        {tab === "config" ? (
          <div className="fc-fleet-view">
            <div className="fc-fleet-panel fc-fleet-panel-ink">
              <div className="fc-fleet-panel-title"><Settings2 className="h-4 w-4" /><h2>Configuração de rateio híbrido</h2></div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <input type="number" min="0" step="0.01" placeholder="Peso KM" value={configForm.peso_km} onChange={(e) => setConfigForm((prev) => ({ ...prev, peso_km: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <input type="number" min="0" step="0.01" placeholder="Peso atendimento" value={configForm.peso_atendimento} onChange={(e) => setConfigForm((prev) => ({ ...prev, peso_atendimento: e.target.value }))} className="px-3 py-2 border rounded-lg" />
                <label className="inline-flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={configForm.auto_gerar_depreciacao} onChange={(e) => setConfigForm((prev) => ({ ...prev, auto_gerar_depreciacao: e.target.checked }))} />Auto gerar depreciacao</label>
              </div>
              <button type="button" onClick={() => void salvarConfigRateio()} disabled={saving} className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-60"><Save className="w-4 h-4" />Salvar configuracao</button>
              <p className="mt-2 text-xs text-gray-500">ID configuracao: {configRateioId ?? "-"}</p>
            </div>

            <div className="fc-fleet-panel fc-fleet-panel-amber space-y-3">
              <h2 className="fc-fleet-section-title">Depreciação mensal automática</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <input type="month" value={competenciaDepreciacao} onChange={(e) => setCompetenciaDepreciacao(e.target.value)} className="px-3 py-2 border rounded-lg" />
                <button type="button" onClick={() => void gerarDepreciacao()} disabled={saving} className="px-3 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60">{saving ? "Processando..." : "Gerar depreciacao"}</button>
              </div>
              {resultadoDepreciacao ? (
                <div className="text-sm space-y-2">
                  <p>Competencia: <b>{resultadoDepreciacao.competencia}</b> | Criados: <b>{resultadoDepreciacao.criados}</b> | Ignorados: <b>{resultadoDepreciacao.ignorados}</b></p>
                  <div className="overflow-x-auto border rounded-lg"><table className="w-full text-sm"><thead className="bg-gray-50 text-gray-600"><tr><th className="text-left px-3 py-2">Veiculo</th><th className="text-left px-3 py-2">Status</th><th className="text-right px-3 py-2">Valor</th></tr></thead><tbody>{resultadoDepreciacao.detalhes.map((item, index) => (<tr key={`${item.veiculo_id}-${index}`} className="border-t"><td className="px-3 py-2">{item.veiculo_nome}</td><td className="px-3 py-2">{item.status}</td><td className="px-3 py-2 text-right">{item.valor != null ? formatarMoeda(item.valor) : "-"}</td></tr>))}</tbody></table></div>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {erro ? <div className="fc-fleet-message fc-fleet-message-error">{erro}</div> : null}
        {sucesso ? <div className="fc-fleet-message fc-fleet-message-success">{sucesso}</div> : null}
      </div>
    </DashboardLayout>
  );
}
