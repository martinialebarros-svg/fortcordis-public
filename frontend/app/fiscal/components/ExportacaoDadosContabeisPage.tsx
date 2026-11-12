"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { formatCalendarDate, operationalTodayDateInput } from "@/lib/calendar-date";
import {
  AlertCircle,
  ArrowLeft,
  CheckSquare,
  Download,
  File,
  FileSpreadsheet,
  FileText,
  Loader2,
  Search,
  Square,
} from "lucide-react";

interface ClinicaItem {
  id: number;
  nome: string;
  razao_social?: string | null;
  cnpj?: string | null;
  atividade_cnae?: string | null;
  endereco?: string | null;
  numero?: string | null;
  complemento?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  estado?: string | null;
  cep?: string | null;
  telefone?: string | null;
  email?: string | null;
  qtd_os?: number;
  valor_total?: number;
  dados_fiscais_completos?: boolean;
  campos_fiscais_pendentes?: string[];
}
interface ClinicaListResponse {
  items: ClinicaItem[];
}
interface CNPJData {
  razao_social: string | null;
  cnpj: string | null;
  logradouro: string | null;
  numero: string | null;
  complemento: string | null;
  bairro: string | null;
  municipio: string | null;
  uf: string | null;
  cep: string | null;
  telefone: string | null;
  email: string | null;
  cnae_principal: string | null;
  error: string | null;
}
interface OSItem {
  os_id: number;
  numero_os: string;
  data_atendimento: string | null;
  valor_final: number;
  status_os: string;
  paciente_nome: string;
  tutor_nome: string;
  servico_nome: string;
  clinica_nome: string | null;
}
interface HistoricoClinica {
  clinica_id: number | null;
  nome: string;
  quantidade_os: number;
  valor_total: number;
}
interface HistoricoEmissaoItem {
  id: number;
  formato: ExportFormat;
  modo: string;
  tipo_emissao: TipoEmissao;
  data_inicio: string | null;
  data_fim: string | null;
  quantidade_os: number;
  valor_total: number;
  clinicas: HistoricoClinica[];
  descricao_servico: string | null;
  arquivo_nome: string | null;
  usuario_nome: string | null;
  emitido_em: string;
}
interface HistoricoEmissaoResponse {
  total: number;
  items: HistoricoEmissaoItem[];
}
interface DadosTomador {
  tipo_cliente: "PF" | "PJ";
  cliente_nome: string;
  cliente_documento: string;
  cliente_endereco: string;
  cliente_bairro: string;
  cliente_cidade: string;
  cliente_estado: string;
  cliente_cep: string;
  cliente_telefone: string;
  cliente_email: string;
  atividade_cnae: string;
  descricao_servico: string;
  natureza_operacao: string;
  aliquota_iss: number;
}

type ExportFormat = "csv" | "xlsx" | "pdf";
type Modo = "single" | "multi";
type TipoEmissao = "fechamento_periodo" | "por_servico";
const FISCAL_PAGE_SIZE = 500;
const DESC_SERVICO_PADRAO_ANTIGA = "Servicos veterinarios prestados conforme ordens de servico selecionadas.";
const TOMADOR_STORAGE_PREFIX = "fiscal_tomador_clinica_v1_";

const DEFAULT_TOMADOR: DadosTomador = {
  tipo_cliente: "PJ",
  cliente_nome: "",
  cliente_documento: "",
  cliente_endereco: "",
  cliente_bairro: "",
  cliente_cidade: "",
  cliente_estado: "",
  cliente_cep: "",
  cliente_telefone: "",
  cliente_email: "",
  atividade_cnae: "",
  descricao_servico: DESC_SERVICO_PADRAO_ANTIGA,
  natureza_operacao: "Tributacao no municipio",
  aliquota_iss: 5,
};

function fmtDate(v: string | null) {
  return formatCalendarDate(v);
}
function fmtMoney(v: number) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);
}
function fmtCnpj(v: string) {
  const d = v.replace(/\D/g, "").slice(0, 14);
  return d.replace(/^(\d{2})(\d)/, "$1.$2").replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d)/, ".$1/$2").replace(/(\d{4})(\d)/, "$1-$2");
}
function fmtCpf(v: string) {
  const d = v.replace(/\D/g, "").slice(0, 11);
  return d.replace(/^(\d{3})(\d)/, "$1.$2").replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d)/, ".$1-$2");
}
function fmtDoc(v: string, t: "PF" | "PJ") {
  return t === "PJ" ? fmtCnpj(v) : fmtCpf(v);
}
function txt(v?: string | null) {
  return String(v || "").trim();
}
function isoToBrDate(v: string) {
  const text = String(v || "").trim();
  const parts = text.split("-");
  if (parts.length === 3 && parts[0] && parts[1] && parts[2]) return `${parts[2]}/${parts[1]}/${parts[0]}`;
  return text;
}
function descricaoServicoPeriodo(inicio: string, fim: string) {
  if (!inicio || !fim) return "";
  return `Servicos veterinarios prestados no periodo de ${isoToBrDate(inicio)} a ${isoToBrDate(fim)}.`;
}
function anyDateToBr(v: string | null) {
  if (!v) return "";
  const text = String(v).trim();
  const yyyyMmDd = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (yyyyMmDd) return `${yyyyMmDd[3]}/${yyyyMmDd[2]}/${yyyyMmDd[1]}`;
  const formatted = formatCalendarDate(text, "");
  if (formatted) return formatted;
  return text;
}
function fmtDateTime(v: string | null) {
  const text = String(v || "").trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (match) return `${match[3]}/${match[2]}/${match[1]} ${match[4]}:${match[5]}`;
  return anyDateToBr(v);
}
function descricaoServicoDataUnica(dataAtendimento: string | null) {
  const data = anyDateToBr(dataAtendimento);
  if (!data) return "";
  return `Servicos veterinarios prestados na data de ${data}.`;
}
function monthPeriod() {
  const today = operationalTodayDateInput();
  const [year, month] = today.split("-");
  const lastDay = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  return {
    inicio: `${year}-${month}-01`,
    fim: `${year}-${month}-${String(lastDay).padStart(2, "0")}`,
  };
}

function normalizeApiError(err: any, fallback: string) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first?.msg === "string" && first.msg.trim()) return first.msg;
    return fallback;
  }
  if (detail && typeof detail === "object" && typeof detail.message === "string" && detail.message.trim()) {
    return detail.message;
  }
  if (typeof err?.message === "string" && err.message.trim()) return err.message;
  return fallback;
}

function parseJsonSafe(value: string) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

async function extractApiErrorDetail(err: any) {
  const data = err?.response?.data;
  if (!data) return null;

  if (data instanceof Blob) {
    const text = (await data.text()).trim();
    if (!text) return null;
    const parsed = parseJsonSafe(text);
    if (parsed && typeof parsed === "object") {
      return "detail" in parsed ? (parsed as any).detail : parsed;
    }
    return text;
  }

  if (typeof data === "string") {
    const text = data.trim();
    if (!text) return null;
    const parsed = parseJsonSafe(text);
    if (parsed && typeof parsed === "object") {
      return "detail" in parsed ? (parsed as any).detail : parsed;
    }
    return text;
  }

  if (typeof data === "object") {
    return "detail" in data ? data.detail : data;
  }

  return null;
}

function getTomadorStorageKey(clinicaId: number): string {
  return `${TOMADOR_STORAGE_PREFIX}${clinicaId}`;
}

function loadTomadorDraft(clinicaId: number): Partial<DadosTomador> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(getTomadorStorageKey(clinicaId));
    if (!raw) return null;
    const parsed = parseJsonSafe(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed as Partial<DadosTomador>;
  } catch {
    return null;
  }
}

function saveTomadorDraft(clinicaId: number, tomador: DadosTomador): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(getTomadorStorageKey(clinicaId), JSON.stringify(tomador));
  } catch {
    // Ignora erro de storage para nao interromper o fluxo da tela.
  }
}

export default function ExportacaoDadosContabeisPage({ embedded = false }: { embedded?: boolean }) {
  const router = useRouter();
  const period = monthPeriod();

  const [modo, setModo] = useState<Modo>("single");
  const [clinicas, setClinicas] = useState<ClinicaItem[]>([]);
  const [loadingClinicas, setLoadingClinicas] = useState(true);
  const [somenteClinicasCompletas, setSomenteClinicasCompletas] = useState(true);
  const [clinicaId, setClinicaId] = useState("");
  const [clinicasSel, setClinicasSel] = useState<Set<number>>(new Set());
  const [dataInicio, setDataInicio] = useState(period.inicio);
  const [dataFim, setDataFim] = useState(period.fim);
  const [search, setSearch] = useState("");
  const [tomador, setTomador] = useState<DadosTomador>(DEFAULT_TOMADOR);
  const [loadingCnpj, setLoadingCnpj] = useState(false);
  const [results, setResults] = useState<OSItem[]>([]);
  const [loadingResults, setLoadingResults] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [format, setFormat] = useState<ExportFormat>("xlsx");
  const [tipoEmissao, setTipoEmissao] = useState<TipoEmissao>("fechamento_periodo");
  const [exporting, setExporting] = useState(false);
  const [historico, setHistorico] = useState<HistoricoEmissaoItem[]>([]);
  const [loadingHistorico, setLoadingHistorico] = useState(true);
  const [autosaveStatus, setAutosaveStatus] = useState("");
  const [autosaving, setAutosaving] = useState(false);
  const lastSavedClinicPayloadRef = useRef<Record<number, string>>({});

  const clinicaEstaCompleta = (clinica: ClinicaItem) => clinica.dados_fiscais_completos === true;
  const camposPendentesDaClinica = (clinica: ClinicaItem) =>
    Array.isArray(clinica.campos_fiscais_pendentes) ? clinica.campos_fiscais_pendentes : [];

  const carregarHistorico = useCallback(async () => {
    setLoadingHistorico(true);
    try {
      const response = await api.get<HistoricoEmissaoResponse>("/fiscal/relatorios-emissoes?limit=20");
      setHistorico(Array.isArray(response.data?.items) ? response.data.items : []);
    } catch {
      setHistorico([]);
    } finally {
      setLoadingHistorico(false);
    }
  }, []);

  function buildTomadorFromClinica(clinica: ClinicaItem): DadosTomador {
    const enderecoBase = txt(clinica.endereco);
    const numeroBase = txt(clinica.numero);
    const enderecoComNumero = numeroBase && enderecoBase && !enderecoBase.includes(numeroBase)
      ? `${enderecoBase}, ${numeroBase}`
      : (enderecoBase || numeroBase);
    return {
      ...DEFAULT_TOMADOR,
      tipo_cliente: "PJ",
      cliente_nome: txt(clinica.razao_social) || txt(clinica.nome),
      cliente_documento: txt(clinica.cnpj) ? fmtCnpj(txt(clinica.cnpj)) : "",
      cliente_endereco: enderecoComNumero,
      cliente_bairro: txt(clinica.bairro),
      cliente_cidade: txt(clinica.cidade),
      cliente_estado: txt(clinica.estado),
      cliente_cep: txt(clinica.cep),
      cliente_telefone: txt(clinica.telefone),
      cliente_email: txt(clinica.email),
      atividade_cnae: txt(clinica.atividade_cnae),
    };
  }

  function buildClinicaPayloadFromTomador(clinica: ClinicaItem, dados: DadosTomador) {
    const documentoLimpo = txt(dados.cliente_documento);
    const enderecoDigitado = txt(dados.cliente_endereco);
    const numeroClinica = txt(clinica.numero);
    const complementoClinica = txt(clinica.complemento);
    return {
      nome: txt(clinica.nome) || txt(dados.cliente_nome) || "Clinica",
      razao_social: txt(dados.cliente_nome) || txt(clinica.razao_social),
      cnpj: dados.tipo_cliente === "PJ" ? documentoLimpo : txt(clinica.cnpj),
      telefone: txt(dados.cliente_telefone),
      email: txt(dados.cliente_email),
      atividade_cnae: txt(dados.atividade_cnae),
      endereco: enderecoDigitado,
      numero: numeroClinica && !enderecoDigitado.includes(numeroClinica) ? numeroClinica : "",
      complemento: complementoClinica && !enderecoDigitado.includes(complementoClinica) ? complementoClinica : "",
      bairro: txt(dados.cliente_bairro),
      cidade: txt(dados.cliente_cidade),
      estado: txt(dados.cliente_estado).toUpperCase(),
      cep: txt(dados.cliente_cep),
    };
  }

  useEffect(() => {
    const descricaoAuto = descricaoServicoPeriodo(dataInicio, dataFim);
    if (!descricaoAuto) return;
    setTomador((prev) => {
      const atual = String(prev.descricao_servico || "").trim();
      const ehDescricaoAutomaticaPeriodo = atual.startsWith("Servicos veterinarios prestados no periodo de ");
      const ehDescricaoPadraoAntiga = !atual || atual === DESC_SERVICO_PADRAO_ANTIGA;
      if (!ehDescricaoAutomaticaPeriodo && !ehDescricaoPadraoAntiga) return prev;
      if (atual === descricaoAuto) return prev;
      return { ...prev, descricao_servico: descricaoAuto };
    });
  }, [dataInicio, dataFim]);

  useEffect(() => {
    if (autosaving || !autosaveStatus) return;
    const timer = window.setTimeout(() => setAutosaveStatus(""), 2200);
    return () => window.clearTimeout(timer);
  }, [autosaving, autosaveStatus]);

  useEffect(() => {
    (async () => {
      setResults([]);
      setSelected(new Set());
      setSearchDone(false);
      if (!dataInicio || !dataFim || dataInicio > dataFim) {
        setClinicas([]);
        setClinicasSel(new Set());
        setLoadingClinicas(false);
        return;
      }
      setLoadingClinicas(true);
      try {
        const params = new URLSearchParams({
          data_inicio: dataInicio,
          data_fim: dataFim,
          somente_completas: String(modo === "multi" && somenteClinicasCompletas),
        });
        const r = await api.get<ClinicaListResponse>(`/fiscal/clinicas-com-os?${params.toString()}`);
        const items = Array.isArray(r.data?.items) ? r.data.items : [];
        setClinicas(items);
        setClinicaId((current) => {
          if (!current || items.some((item) => String(item.id) === current)) return current;
          setTomador(DEFAULT_TOMADOR);
          return "";
        });
      } finally {
        setLoadingClinicas(false);
      }
    })();
  }, [dataInicio, dataFim, modo, somenteClinicasCompletas]);

  useEffect(() => {
    if (modo !== "multi") return;
    setClinicasSel(new Set(clinicas.filter((clinica) => clinica.dados_fiscais_completos === true).map((clinica) => clinica.id)));
  }, [clinicas, modo]);

  useEffect(() => {
    void carregarHistorico();
  }, [carregarHistorico]);

  function onChangeClinica(v: string) {
    setClinicaId(v);
    setAutosaveStatus("");
    const c = clinicas.find((x) => String(x.id) === v);
    if (!c) return setTomador(DEFAULT_TOMADOR);

    const baseTomador = buildTomadorFromClinica(c);
    const draft = loadTomadorDraft(c.id);
    const mergedTomador: DadosTomador = { ...baseTomador, ...(draft || {}) };
    setTomador(mergedTomador);
    lastSavedClinicPayloadRef.current[c.id] = JSON.stringify(buildClinicaPayloadFromTomador(c, baseTomador));
  }

  async function persistirDadosFiscaisDaClinica(clinica: ClinicaItem, cnpjData: CNPJData) {
    const payload = {
      nome: txt(clinica.nome),
      razao_social: txt(cnpjData.razao_social) || txt(clinica.razao_social),
      cnpj: txt(cnpjData.cnpj) ? fmtCnpj(txt(cnpjData.cnpj)) : txt(clinica.cnpj),
      telefone: txt(cnpjData.telefone) || txt(clinica.telefone),
      email: txt(cnpjData.email) || txt(clinica.email),
      atividade_cnae: txt(cnpjData.cnae_principal) || txt(clinica.atividade_cnae),
      endereco: txt(cnpjData.logradouro) || txt(clinica.endereco),
      numero: txt(cnpjData.numero) || txt(clinica.numero),
      complemento: txt(cnpjData.complemento) || txt(clinica.complemento),
      bairro: txt(cnpjData.bairro) || txt(clinica.bairro),
      cidade: txt(cnpjData.municipio) || txt(clinica.cidade),
      estado: txt(cnpjData.uf) || txt(clinica.estado),
      cep: txt(cnpjData.cep) || txt(clinica.cep),
    };

    const resp = await api.put(`/clinicas/${clinica.id}`, payload);
    const updated = (resp.data || {}) as ClinicaItem;
    setClinicas((prev) => prev.map((item) => (item.id === clinica.id ? { ...item, ...updated } : item)));
  }

  async function autoSalvarTomadorNoBlur(campo: string) {
    if (modo !== "single" || !clinicaId) return;
    const selectedClinicId = Number(clinicaId);
    if (Number.isNaN(selectedClinicId)) return;

    saveTomadorDraft(selectedClinicId, tomador);
    const clinicaSelecionada = clinicas.find((x) => x.id === selectedClinicId);
    if (!clinicaSelecionada) return;

    const payload = buildClinicaPayloadFromTomador(clinicaSelecionada, tomador);
    const assinatura = JSON.stringify(payload);
    if (lastSavedClinicPayloadRef.current[selectedClinicId] === assinatura) return;

    setAutosaving(true);
    setAutosaveStatus(`Salvando ${campo}...`);
    try {
      const resp = await api.put(`/clinicas/${selectedClinicId}`, payload);
      const updated = (resp.data || {}) as ClinicaItem;
      setClinicas((prev) => prev.map((item) => (item.id === selectedClinicId ? { ...item, ...updated } : item)));
      lastSavedClinicPayloadRef.current[selectedClinicId] = assinatura;
      setAutosaveStatus("Dados salvos automaticamente.");
    } catch (err: any) {
      setAutosaveStatus("");
      alert(normalizeApiError(err, `Nao foi possivel salvar automaticamente o campo "${campo}".`));
    } finally {
      setAutosaving(false);
    }
  }

  function onBlurSalvar(campo: string) {
    return () => {
      void autoSalvarTomadorNoBlur(campo);
    };
  }

  async function buscarCnpj() {
    if (tomador.tipo_cliente !== "PJ") return;
    const cnpj = tomador.cliente_documento.replace(/\D/g, "");
    if (cnpj.length < 14) return alert("Informe um CNPJ valido para consulta.");
    setLoadingCnpj(true);
    try {
      const clinicaSelecionada = clinicas.find((x) => String(x.id) === clinicaId);
      const r = await api.get<CNPJData>(`/fiscal/consulta-cnpj/${cnpj}`);
      const d = r.data;
      if (d.error) return alert(d.error);
      const e = `${d.logradouro || ""}${d.numero ? `, ${d.numero}` : ""}${d.complemento ? ` - ${d.complemento}` : ""}`.trim();
      const novoTomador: DadosTomador = {
        ...tomador,
        cliente_nome: d.razao_social || tomador.cliente_nome,
        cliente_documento: d.cnpj ? fmtCnpj(d.cnpj) : tomador.cliente_documento,
        cliente_endereco: e,
        cliente_bairro: d.bairro || "",
        cliente_cidade: d.municipio || "",
        cliente_estado: d.uf || "",
        cliente_cep: d.cep || "",
        cliente_telefone: d.telefone || "",
        cliente_email: d.email || "",
        atividade_cnae: d.cnae_principal || tomador.atividade_cnae,
      };
      setTomador(novoTomador);

      const selectedClinicId = Number(clinicaId);
      if (!Number.isNaN(selectedClinicId) && selectedClinicId > 0) {
        saveTomadorDraft(selectedClinicId, novoTomador);
      }

      if (clinicaSelecionada && modo === "single") {
        try {
          await persistirDadosFiscaisDaClinica(clinicaSelecionada, d);
          const payloadAtualizado = buildClinicaPayloadFromTomador(clinicaSelecionada, novoTomador);
          lastSavedClinicPayloadRef.current[clinicaSelecionada.id] = JSON.stringify(payloadAtualizado);
          setAutosaveStatus("Dados da clinica atualizados automaticamente.");
        } catch (err) {
          alert(normalizeApiError(err, "Nao foi possivel salvar automaticamente os dados fiscais na clinica."));
        }
      }
    } finally {
      setLoadingCnpj(false);
    }
  }

  async function buscarOsFiscalPorClinicas(clinicaIds: number[]): Promise<OSItem[]> {
    const searchTerm = search.trim().toLowerCase();
    const acc: OSItem[] = [];
    let skip = 0;
    while (true) {
      const params = new URLSearchParams({
        data_inicio: dataInicio,
        data_fim: dataFim,
        limit: String(FISCAL_PAGE_SIZE),
        skip: String(skip),
      });
      for (const id of clinicaIds) params.append("clinica_ids", String(id));
      if (searchTerm) params.set("search", searchTerm);
      const resp = await api.get(`/fiscal/os-para-fiscal?${params.toString()}`);
      const rows = Array.isArray(resp.data?.items) ? (resp.data.items as OSItem[]) : [];
      const total = Number(resp.data?.total || 0);
      if (!rows.length) break;
      acc.push(...rows);
      if (rows.length < FISCAL_PAGE_SIZE) break;
      if (total > 0 && acc.length >= total) break;
      skip += FISCAL_PAGE_SIZE;
    }
    return acc;
  }

  async function buscarOs() {
    const ids = modo === "single" ? (clinicaId ? [Number(clinicaId)] : []) : Array.from(clinicasSel);
    if (!ids.length) return alert("Selecione pelo menos uma clinica.");
    if (!dataInicio || !dataFim || dataInicio > dataFim) return alert("Periodo invalido.");
    setLoadingResults(true);
    setSearchDone(true);
    try {
      const items = await buscarOsFiscalPorClinicas(ids);
      setResults(items);
      setSelected(new Set());
    } catch (err: any) {
      alert(normalizeApiError(err, "Nao foi possivel carregar as ordens de servico para os filtros selecionados."));
      setResults([]);
      setSelected(new Set());
    } finally {
      setLoadingResults(false);
    }
  }

  async function exportar() {
    if (!selected.size) return alert("Selecione pelo menos uma OS.");
    if (modo === "single" && (!tomador.cliente_nome.trim() || !tomador.cliente_documento.trim())) {
      return alert("Preencha nome e documento do tomador.");
    }
    setExporting(true);
    try {
      const descricaoAuto = descricaoServicoPeriodo(dataInicio, dataFim);
      const osSelecionadas = results.filter((row) => selected.has(row.os_id));
      const descricaoAutoUnica = osSelecionadas.length === 1
        ? descricaoServicoDataUnica(osSelecionadas[0].data_atendimento)
        : "";
      const descricaoAutoFinal = descricaoAutoUnica || descricaoAuto;
      const descricaoAtual = String(tomador.descricao_servico || "").trim();
      const ehDescricaoAutomaticaPeriodo = descricaoAtual.startsWith("Servicos veterinarios prestados no periodo de ");
      const ehDescricaoAutomaticaUnica = descricaoAtual.startsWith("Servicos veterinarios prestados na data de ");
      const ehDescricaoPadraoAntiga = !descricaoAtual || descricaoAtual === DESC_SERVICO_PADRAO_ANTIGA;
      const descricaoFinal = (descricaoAutoFinal && (ehDescricaoAutomaticaPeriodo || ehDescricaoAutomaticaUnica || ehDescricaoPadraoAntiga))
        ? descricaoAutoFinal
        : descricaoAtual;

      const dadosTomador =
        modo === "single"
          ? {
              ...tomador,
              descricao_servico: descricaoFinal,
              data_referencia_nf: dataFim,
              aliquota_iss: Number(tomador.aliquota_iss),
            }
          : {
              atividade_cnae: tomador.atividade_cnae,
              descricao_servico: descricaoFinal,
              natureza_operacao: tomador.natureza_operacao,
              data_referencia_nf: dataFim,
              aliquota_iss: Number(tomador.aliquota_iss),
            };
      const payload = {
        os_ids: Array.from(selected),
        formato: format,
        dados_tomador: dadosTomador,
        modo_multiclinica: modo === "multi",
        tipo_emissao: tipoEmissao,
        data_inicio: dataInicio,
        data_fim: dataFim,
      };
      const r = await api.post("/fiscal/os/exportar-lote", payload, { responseType: "blob" });
      const type = format === "pdf" ? "application/pdf" : format === "csv" ? "text/csv;charset=utf-8" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
      const blob = new Blob([r.data], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `dados_contabeis_${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
      void carregarHistorico();
    } catch (err: any) {
      const detail = await extractApiErrorDetail(err);
      if (detail && typeof detail === "object" && Array.isArray((detail as any).clinicas) && (detail as any).clinicas.length) {
        const message = String((detail as any).message || "Existem clinicas com dados incompletos para exportacao.");
        const list = (detail as any).clinicas
          .map((c: any) => `- ${c.clinica_nome || "Clinica sem nome"}: ${Array.isArray(c.faltando) ? c.faltando.join(", ") : "dados faltando"}`)
          .join("\n");
        alert(`${message}\n\nCampos faltando por clinica:\n${list}`);
      } else if (typeof detail === "string" && detail.trim()) {
        alert(detail);
      } else if (detail && typeof detail === "object" && typeof (detail as any).message === "string" && (detail as any).message.trim()) {
        alert((detail as any).message);
      } else {
        alert(normalizeApiError(err, "Erro ao exportar dados."));
      }
    } finally {
      setExporting(false);
    }
  }

  const rowsSel = useMemo(() => results.filter((x) => selected.has(x.os_id)), [results, selected]);
  const totalSel = useMemo(() => rowsSel.reduce((a, b) => a + Number(b.valor_final || 0), 0), [rowsSel]);
  const totalClinicasSel = useMemo(
    () => clinicas.filter((clinica) => clinicasSel.has(clinica.id)).reduce((total, clinica) => total + Number(clinica.valor_total || 0), 0),
    [clinicas, clinicasSel],
  );
  const totalResumo = results.length > 0 ? totalSel : totalClinicasSel;
  const rotuloTotalResumo = results.length > 0 ? "Total das OS selecionadas" : "Total das clínicas selecionadas";

  const content = (
      <div className="fc-fiscal-page">
        <header className="fc-fiscal-header">
          <div className="fc-fiscal-header-copy">
            <button onClick={() => router.back()} className="fc-fiscal-back" title="Voltar" aria-label="Voltar">
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-fiscal-kicker"><FileSpreadsheet className="h-4 w-4" />Conformidade contábil</span>
              <h1>Exportação Fiscal</h1>
              <p>Consolide serviços por período e clínica para envio à contabilidade.</p>
            </div>
          </div>
        </header>

        <section className="fc-fiscal-metrics" aria-label="Resumo da exportação">
          <div className="fc-fiscal-metric fc-fiscal-metric-cordis"><FileSpreadsheet className="h-5 w-5" /><strong>{clinicas.length}</strong><span>Clínicas no período</span></div>
          <div className="fc-fiscal-metric fc-fiscal-metric-vital"><FileText className="h-5 w-5" /><strong>{results.length}</strong><span>OS consolidadas</span></div>
          <div className="fc-fiscal-metric fc-fiscal-metric-amber"><CheckSquare className="h-5 w-5" /><strong>{selected.size}</strong><span>OS selecionadas</span></div>
          <div className="fc-fiscal-metric fc-fiscal-metric-ink"><Download className="h-5 w-5" /><strong>{fmtMoney(totalResumo)}</strong><span>{rotuloTotalResumo}</span></div>
        </section>

        <section className="fc-fiscal-scope">
          <div className="fc-fiscal-section-heading">
            <div><span>Etapa 1</span><h2>Escopo da consolidação</h2></div>
            <div className="fc-fiscal-mode-tabs" role="tablist" aria-label="Modo de exportação">
              <button type="button" role="tab" aria-selected={modo === "single"} onClick={() => setModo("single")} className={`fc-fiscal-mode-tab ${modo === "single" ? "fc-fiscal-mode-tab-active" : ""}`}>Uma clínica</button>
              <button type="button" role="tab" aria-selected={modo === "multi"} onClick={() => { if (clinicaId) setClinicasSel((s) => new Set([...s, Number(clinicaId)])); setModo("multi"); }} className={`fc-fiscal-mode-tab ${modo === "multi" ? "fc-fiscal-mode-tab-active" : ""}`}>Multiclínica</button>
            </div>
          </div>
          {modo === "single" ? (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="md:col-span-2"><label className="block text-sm mb-1">Clínica *</label><select value={clinicaId} onChange={(e) => onChangeClinica(e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" disabled={loadingClinicas}><option value="">{loadingClinicas ? "Carregando..." : clinicas.length ? "Selecione" : "Nenhuma clínica com OS no período"}</option>{clinicas.map((c) => <option key={c.id} value={c.id}>{c.nome} ({Number(c.qtd_os || 0)} OS - {fmtMoney(Number(c.valor_total || 0))})</option>)}</select></div>
              <div><label className="block text-sm mb-1">Data inicial *</label><input type="date" value={dataInicio} onChange={(e) => setDataInicio(e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
              <div><label className="block text-sm mb-1">Data final *</label><input type="date" value={dataFim} onChange={(e) => setDataFim(e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="md:col-span-2">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                  <label className="block text-sm">Clínicas *</label>
                  <label className="inline-flex items-center gap-2 text-xs text-emerald-800 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={somenteClinicasCompletas}
                      onChange={(event) => setSomenteClinicasCompletas(event.target.checked)}
                    />
                    Mostrar somente cadastros fiscais completos
                  </label>
                </div>
                <div className="fc-fiscal-clinic-list">{loadingClinicas ? <p className="text-sm text-gray-500 px-1 py-2">Carregando...</p> : clinicas.length ? clinicas.map((c) => {
                  const completa = clinicaEstaCompleta(c);
                  const pendentes = camposPendentesDaClinica(c);
                  return <label key={c.id} className={`flex items-center justify-between gap-3 text-sm ${completa ? "" : "opacity-65"}`}>
                    <span className="flex min-w-0 items-center gap-2"><input type="checkbox" checked={clinicasSel.has(c.id)} disabled={!completa} onChange={() => {
                      if (!completa) return;
                      setClinicasSel((s) => { const n = new Set(s); n.has(c.id) ? n.delete(c.id) : n.add(c.id); return n; });
                    }} />
                    <span className="min-w-0"><span>{c.nome}</span>{!completa && <span className="block text-xs text-amber-700">Pendente: {pendentes.join(", ") || "dados fiscais"}</span>}</span></span>
                    <span className="shrink-0 text-xs text-gray-500">{Number(c.qtd_os || 0)} OS | {fmtMoney(Number(c.valor_total || 0))}</span>
                  </label>;
                }) : <p className="text-sm text-gray-500 px-1 py-2">{somenteClinicasCompletas ? "Nenhuma clínica com cadastro fiscal completo no período." : "Nenhuma clínica com OS no período."}</p>}</div>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
                  <p className="text-xs text-emerald-900">{clinicasSel.size} de {clinicas.length} selecionada(s)</p>
                  <p className="text-sm font-semibold text-emerald-900">Serviços das clínicas marcadas: {fmtMoney(totalClinicasSel)}</p>
                </div>
              </div>
              <div className="space-y-3"><div><label className="block text-sm mb-1">Data inicial *</label><input type="date" value={dataInicio} onChange={(e) => setDataInicio(e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div><div><label className="block text-sm mb-1">Data final *</label><input type="date" value={dataFim} onChange={(e) => setDataFim(e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div></div>
            </div>
          )}
          <div className="fc-fiscal-search-row">
            <input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && buscarOs()} placeholder="Filtrar OS por número, paciente, tutor ou serviço" className="flex-1 px-3 py-2 border rounded-lg text-sm" />
            <button onClick={buscarOs} disabled={loadingResults} className="fc-fiscal-primary">{loadingResults ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}Consolidar período</button>
          </div>
        </section>

        <section className="fc-fiscal-tomador">
          <div className="fc-fiscal-section-heading"><div><span>Etapa 2</span><h2>{modo === "single" ? "Dados do tomador" : "Parâmetros fiscais do lote"}</h2></div></div>
          {modo === "single" && clinicaId && (autosaving || autosaveStatus) && (
            <p className={`text-xs mb-3 ${autosaving ? "text-blue-700" : "text-emerald-700"}`}>
              {autosaving ? "Salvando automaticamente..." : autosaveStatus}
            </p>
          )}
          {modo === "multi" && <p className="text-sm text-blue-700 bg-blue-50 rounded p-3 mb-3">No modo multiclínica, os dados cadastrais vêm de cada clínica. O filtro padrão mostra apenas cadastros completos; a API continua protegendo a exportação contra dados pendentes.</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {modo === "single" && (
              <>
                <div>
                  <label className="block text-sm mb-1">Tipo cliente</label>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setTomador((p) => ({ ...p, tipo_cliente: "PJ", cliente_documento: fmtCnpj(p.cliente_documento) }))}
                      className={`px-3 py-1.5 rounded-lg text-sm ${tomador.tipo_cliente === "PJ" ? "bg-blue-100 text-blue-700 border border-blue-300" : "bg-gray-50 border border-gray-200"}`}
                    >
                      PJ
                    </button>
                    <button
                      type="button"
                      onClick={() => setTomador((p) => ({ ...p, tipo_cliente: "PF", cliente_documento: fmtCpf(p.cliente_documento) }))}
                      className={`px-3 py-1.5 rounded-lg text-sm ${tomador.tipo_cliente === "PF" ? "bg-purple-100 text-purple-700 border border-purple-300" : "bg-gray-50 border border-gray-200"}`}
                    >
                      PF
                    </button>
                  </div>
                </div>
                <div>
                  <label className="block text-sm mb-1">{tomador.tipo_cliente === "PJ" ? "Razao social *" : "Nome *"}</label>
                  <input
                    value={tomador.cliente_nome}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_nome: e.target.value }))}
                    onBlur={onBlurSalvar("razao social")}
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm mb-1">{tomador.tipo_cliente === "PJ" ? "CNPJ *" : "CPF *"}</label>
                  <div className="flex gap-2">
                    <input
                      value={tomador.cliente_documento}
                      onChange={(e) => setTomador((p) => ({ ...p, cliente_documento: fmtDoc(e.target.value, p.tipo_cliente) }))}
                      onBlur={onBlurSalvar(tomador.tipo_cliente === "PJ" ? "cnpj" : "cpf")}
                      className="flex-1 px-3 py-2 border rounded-lg text-sm"
                    />
                    {tomador.tipo_cliente === "PJ" && (
                      <button onClick={buscarCnpj} disabled={loadingCnpj} className="px-3 py-2 bg-blue-50 text-blue-600 rounded-lg text-sm">
                        {loadingCnpj ? <Loader2 className="w-4 h-4 animate-spin" /> : "Buscar"}
                      </button>
                    )}
                  </div>
                </div>
                <div className="md:col-span-2">
                  <label className="block text-sm mb-1">Endereco</label>
                  <input
                    value={tomador.cliente_endereco}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_endereco: e.target.value }))}
                    onBlur={onBlurSalvar("endereco")}
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm mb-1">Bairro</label>
                  <input
                    value={tomador.cliente_bairro}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_bairro: e.target.value }))}
                    onBlur={onBlurSalvar("bairro")}
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <input
                    placeholder="Cidade"
                    value={tomador.cliente_cidade}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_cidade: e.target.value }))}
                    onBlur={onBlurSalvar("cidade")}
                    className="col-span-2 px-3 py-2 border rounded-lg text-sm"
                  />
                  <input
                    placeholder="UF"
                    value={tomador.cliente_estado}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_estado: e.target.value.toUpperCase() }))}
                    onBlur={onBlurSalvar("uf")}
                    className="px-3 py-2 border rounded-lg text-sm uppercase"
                    maxLength={2}
                  />
                </div>
                <div>
                  <label className="block text-sm mb-1">CEP</label>
                  <input
                    value={tomador.cliente_cep}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_cep: e.target.value }))}
                    onBlur={onBlurSalvar("cep")}
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm mb-1">Telefone</label>
                  <input
                    value={tomador.cliente_telefone}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_telefone: e.target.value }))}
                    onBlur={onBlurSalvar("telefone")}
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm mb-1">Email</label>
                  <input
                    value={tomador.cliente_email}
                    onChange={(e) => setTomador((p) => ({ ...p, cliente_email: e.target.value }))}
                    onBlur={onBlurSalvar("email")}
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
              </>
            )}
            <div>
              <label className="block text-sm mb-1">Atividade</label>
              <input
                value={tomador.atividade_cnae}
                onChange={(e) => setTomador((p) => ({ ...p, atividade_cnae: e.target.value }))}
                onBlur={onBlurSalvar("atividade")}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="block text-sm mb-1">Aliquota ISS (%)</label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={tomador.aliquota_iss}
                onChange={(e) => setTomador((p) => ({ ...p, aliquota_iss: Number(e.target.value || 0) }))}
                onBlur={onBlurSalvar("aliquota ISS")}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm mb-1">Descricao do servico</label>
              <input
                value={tomador.descricao_servico}
                onChange={(e) => setTomador((p) => ({ ...p, descricao_servico: e.target.value }))}
                onBlur={onBlurSalvar("descricao do servico")}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm mb-1">Natureza da operacao</label>
              <select
                value={tomador.natureza_operacao}
                onChange={(e) => setTomador((p) => ({ ...p, natureza_operacao: e.target.value }))}
                onBlur={onBlurSalvar("natureza da operacao")}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              >
                <option>Tributacao no municipio</option>
                <option>Tributacao fora do municipio</option>
                <option>Isenta</option>
                <option>Imune</option>
                <option>Nao tributavel</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm mb-1">Como esta emissão será registrada?</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <button type="button" onClick={() => setTipoEmissao("fechamento_periodo")} className={`rounded-lg border px-3 py-2 text-left text-sm ${tipoEmissao === "fechamento_periodo" ? "border-blue-400 bg-blue-50 text-blue-800" : "border-gray-200 bg-white text-gray-700"}`}>
                  <strong className="block">Fechamento do período</strong><span className="text-xs">Para consolidar os serviços de uma clínica no mês ou período escolhido.</span>
                </button>
                <button type="button" onClick={() => setTipoEmissao("por_servico")} className={`rounded-lg border px-3 py-2 text-left text-sm ${tipoEmissao === "por_servico" ? "border-blue-400 bg-blue-50 text-blue-800" : "border-gray-200 bg-white text-gray-700"}`}>
                  <strong className="block">Conforme os serviços</strong><span className="text-xs">Para registrar a emissão à medida que os serviços são prestados.</span>
                </button>
              </div>
            </div>
          </div>
        </section>

        {results.length > 0 && (
          <>
            <section className="fc-fiscal-results">
              <div className="fc-fiscal-results-heading">
                <button onClick={() => setSelected(selected.size === results.length ? new Set() : new Set(results.map((r) => r.os_id)))} className="flex items-center gap-2 text-sm text-blue-600">{selected.size === results.length ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}{selected.size === results.length ? "Desmarcar" : "Selecionar"} todas ({results.length})</button>
                <p className="text-sm">{selected.size} selecionada(s) | Total {fmtMoney(totalSel)}</p>
              </div>
              <div className="fc-fiscal-table-scroll">
                <table className="fc-fiscal-table">
                  <thead className="bg-gray-50"><tr><th className="px-3 py-2" /><th className="px-3 py-2 text-left">Clinica</th><th className="px-3 py-2 text-left">OS</th><th className="px-3 py-2 text-left">Data</th><th className="px-3 py-2 text-left">Paciente</th><th className="px-3 py-2 text-left">Tutor</th><th className="px-3 py-2 text-left">Servico</th><th className="px-3 py-2 text-center">Status</th><th className="px-3 py-2 text-right">Valor</th></tr></thead>
                  <tbody className="divide-y">{results.map((r) => <tr key={r.os_id} onClick={() => setSelected((s) => { const n = new Set(s); n.has(r.os_id) ? n.delete(r.os_id) : n.add(r.os_id); return n; })} className={`cursor-pointer hover:bg-blue-50 ${selected.has(r.os_id) ? "bg-blue-50" : ""}`}><td className="px-3 py-2">{selected.has(r.os_id) ? <CheckSquare className="w-4 h-4 text-blue-600" /> : <Square className="w-4 h-4 text-gray-400" />}</td><td className="px-3 py-2">{r.clinica_nome || "-"}</td><td className="px-3 py-2 font-mono text-xs">{r.numero_os}</td><td className="px-3 py-2">{fmtDate(r.data_atendimento)}</td><td className="px-3 py-2">{r.paciente_nome || "-"}</td><td className="px-3 py-2">{r.tutor_nome || "-"}</td><td className="px-3 py-2">{r.servico_nome || "-"}</td><td className="px-3 py-2 text-center"><span className={`px-2 py-0.5 rounded text-xs ${r.status_os === "Pago" ? "bg-green-100 text-green-700" : r.status_os === "Cancelado" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>{r.status_os}</span></td><td className="px-3 py-2 text-right font-medium">{fmtMoney(r.valor_final)}</td></tr>)}</tbody>
                </table>
              </div>
            </section>

            <section className="fc-fiscal-export">
              <div className="fc-fiscal-section-heading"><div><span>Etapa 4</span><h2>Exportar relatório contábil</h2></div></div>
              <div className="fc-fiscal-format-tabs">{[{ id: "csv", label: "CSV", icon: File }, { id: "xlsx", label: "Excel", icon: FileSpreadsheet }, { id: "pdf", label: "PDF", icon: FileText }].map((f) => <button key={f.id} onClick={() => setFormat(f.id as ExportFormat)} className={`fc-fiscal-format-tab ${format === f.id ? "fc-fiscal-format-tab-active" : ""}`}><f.icon className="h-4 w-4" />{f.label}</button>)}</div>
              <div className="bg-blue-50 rounded-lg p-3 flex items-start gap-2 mb-4"><AlertCircle className="w-4 h-4 text-blue-600 mt-0.5" /><p className="text-sm text-blue-700">No modo multiclinica, o PDF e separado por clinica. Se houver cadastro incompleto, o sistema informa os campos faltantes antes da exportacao.</p></div>
              <button onClick={exportar} disabled={!selected.size || exporting} className="fc-fiscal-export-button">{exporting ? <><Loader2 className="h-5 w-5 animate-spin" />Exportando...</> : <><Download className="h-5 w-5" />Exportar relatório de {selected.size} OS em {format.toUpperCase()}</>}</button>
            </section>
          </>
        )}
        {!loadingResults && searchDone && results.length === 0 && (
          <div className="fc-fiscal-empty">
            Nenhuma ordem de serviço encontrada para os filtros selecionados.
          </div>
        )}

        <section className="mt-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Histórico de emissões fiscais">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Rastreabilidade fiscal</span>
              <h2 className="text-lg font-semibold text-slate-900">Histórico de relatórios emitidos</h2>
              <p className="text-sm text-slate-600">Cada download concluído fica registrado com o período, as clínicas e o valor exportado.</p>
            </div>
            <button type="button" onClick={() => void carregarHistorico()} disabled={loadingHistorico} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60">
              {loadingHistorico ? "Atualizando..." : "Atualizar histórico"}
            </button>
          </div>
          {loadingHistorico ? (
            <div className="flex items-center gap-2 py-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Carregando emissões...</div>
          ) : historico.length ? (
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-2 py-2">Emitido em</th><th className="px-2 py-2">Tipo</th><th className="px-2 py-2">Clínicas e serviços</th><th className="px-2 py-2">Formato</th><th className="px-2 py-2 text-right">Valor</th><th className="px-2 py-2">Responsável</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {historico.map((item) => {
                    const periodo = item.data_inicio && item.data_fim ? `${isoToBrDate(item.data_inicio)} a ${isoToBrDate(item.data_fim)}` : "Período não informado";
                    const clinicasHistorico = Array.isArray(item.clinicas) ? item.clinicas : [];
                    return <tr key={item.id} className="align-top"><td className="whitespace-nowrap px-2 py-3 text-slate-700">{fmtDateTime(item.emitido_em)}<span className="block text-xs text-slate-500">{periodo}</span></td><td className="px-2 py-3"><span className={`rounded-full px-2 py-1 text-xs font-medium ${item.tipo_emissao === "por_servico" ? "bg-violet-100 text-violet-800" : "bg-blue-100 text-blue-800"}`}>{item.tipo_emissao === "por_servico" ? "Conforme os serviços" : "Fechamento do período"}</span></td><td className="px-2 py-3 text-slate-700"><span className="block">{clinicasHistorico.map((clinica) => clinica.nome).join(", ") || "Clínica não informada"}</span><span className="text-xs text-slate-500">{item.quantidade_os} OS · {clinicasHistorico.length} clínica(s)</span></td><td className="px-2 py-3 uppercase text-slate-700">{item.formato}</td><td className="whitespace-nowrap px-2 py-3 text-right font-semibold text-slate-900">{fmtMoney(Number(item.valor_total || 0))}</td><td className="px-2 py-3 text-slate-700">{item.usuario_nome || "Usuário não identificado"}</td></tr>;
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-6 text-sm text-slate-500">Nenhum relatório fiscal foi emitido ainda.</p>
          )}
        </section>
      </div>
  );
  return embedded ? content : <DashboardLayout>{content}</DashboardLayout>;
}
