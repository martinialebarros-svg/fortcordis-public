"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";
import { normalizarCoordenadaOpcional } from "@/lib/coordinates";
import {
  createAgendaCatalogLoader,
  executarCargasAuxiliaresAgenda,
  extrairIdsAgendamentosVisiveis,
  normalizarOpcoesFiltroAgenda,
  type AgendaCatalogLoader,
} from "@/lib/agenda-loading";
import { montarToastAgendaRealtime } from "@/lib/agenda-realtime-toast";
import { useAgendaRealtime, type AgendaRealtimePayload } from "@/lib/useAgendaRealtime";
import {
  AgendaExcecaoConfig,
  AgendaFeriadoConfig,
  AgendaSemanalConfig,
  DEFAULT_AGENDA_SEMANAL,
  horarioParaMinutos,
  normalizarAgendaExcecoes,
  normalizarAgendaFeriados,
  normalizarAgendaSemanal,
  obterExcecaoData,
  obterJornadaDia,
  slotDentroDaJornada,
} from "@/lib/agenda-config";
import {
  getLaudoEditPath,
  TIPO_LAUDO_ECOCARDIOGRAMA,
  TIPO_LAUDO_ELETROCARDIOGRAMA,
  TIPO_LAUDO_PRESSAO_ARTERIAL,
  TIPO_LAUDO_ULTRASSOM_ABDOMINAL,
} from "@/lib/laudos";
import { baixarLaudoPdf as baixarLaudoPdfUtil, baixarLaudoPdfOriginal } from "@/lib/laudo-pdf";
import {
  AGENDA_STATUS_LIST,
  FORMA_PAGAMENTO_FALLBACK,
  FORMA_PAGAMENTO_PADRAO,
  descricaoFormaPagamentoConfig,
  normalizarCodigoFormaPagamento,
  obterOrigemAtendimentoMeta,
  obterTituloAgendamentoPorOrigem,
  type AgendaStatus,
  type FormaPagamentoConfig,
  obterAcoesStatusPorFluxo,
  obterProximosStatus,
  osEstaPaga,
} from "@/lib/agenda-shared-actions";
import {
  DEFAULT_AGENDA_ROTA_REGRAS,
  normalizarAgendaRotaRegras,
  type AgendaRotaRenderingPolicyConfig,
} from "@/lib/agenda-route-rules";
import {
  PRAZO_REABILITACAO_HORAS_MAX,
  PRAZO_REABILITACAO_HORAS_MIN,
  PRAZO_REABILITACAO_HORAS_PADRAO,
  calcularPrazoReabilitacao,
  normalizarPrazoReabilitacaoHoras,
  podeReabilitarReserva,
} from "@/lib/agenda-reabilitar-reserva";
import BaixaCredito from "@/components/financeiro/BaixaCredito";
import { ajustarPagamentoSugerido } from "@/lib/recebimento-desconto";
import { consultarSaldoCreditoCliente } from "@/lib/credito-cliente";
import {
  montarGoogleMapsDestinoLocal,
  montarWazeDestinoLocal,
  type WazeDestinoLocal,
} from "@/lib/waze";
import { 
  Calendar, Clock, User, Building, Plus, RefreshCw, X, Trash2,
  CheckCircle2, PlayCircle, CheckCircle, XCircle, AlertCircle,
  Search, ChevronDown, ChevronLeft, ChevronRight, Sun, Moon, FileText, Download, Stethoscope, Undo2, DollarSign, MapPin, Wallet, TimerReset
} from "lucide-react";
import NovoAgendamentoModal from "./NovoAgendamentoModal";
import type { PedidoAgenda } from "@/lib/whatsapp-pedido-agenda";
import ClienteInfoModal from "./ClienteInfoModal";
import { useFortinho } from "@/components/fortinho/FortinhoProvider";

interface Agendamento {
  id: number;
  paciente_id?: number | null;
  tutor_id?: number | null;
  clinica_id?: number | null;
  servico_id?: number | null;
  origem_atendimento?: "clinica_parceira" | "domiciliar" | string | null;
  paciente: string | null;
  tutor: string | null;
  clinica: string | null;
  servico: string | null;
  inicio: string;
  fim: string | null;
  status: string;
  reserva_expira_em?: string | null;
  observacoes: string | null;
  telefone: string | null;
  data: string;
  hora: string;
}

interface LaudoVinculado {
  id: number;
  status: string;
  titulo: string;
  tipo: string;
}

type LaudosVinculadosPorAgendamento = Record<number, Record<string, LaudoVinculado>>;

interface OrdemServicoResumo {
  id: number;
  agendamento_id: number;
  numero_os: string;
  status: string;
  valor_servico: number;
  desconto: number;
  valor_final: number;
}

interface ClinicaEndereco {
  id: number;
  nome?: string | null;
  endereco?: string | null;
  numero?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  estado?: string | null;
  cep?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  endereco_normalizado?: string | null;
}

type TutorEndereco = ClinicaEndereco;

interface FiltroOption {
  id: number;
  nome: string;
}

interface PagamentoRecebimentoItem {
  id: string;
  forma_codigo: string;
  valor: string;
}

interface ResumoFinanceiroAgenda {
  data_inicio: string;
  data_fim: string;
  qtd_realizados: number;
  qtd_agendados: number;
  valor_realizado: number;
  valor_agendado: number;
}

interface ToastRealtimeData {
  texto: string;
  classe: string;
  agendamentoId?: number;
}

interface CarregarAgendamentosOptions {
  includeRelated?: boolean;
  includeResumo?: boolean;
}

interface AgendaListaStatusDia {
  data: string;
  tipo: "fechada" | "janela-especial";
  inicio: string;
  fim: string;
  motivo: string;
}

type StatusType = AgendaStatus;
type ModoVisualizacao = "lista" | "panoramica-dia" | "panoramica-semana";

const toDateInput = (date: Date) => {
  const ano = date.getFullYear();
  const mes = String(date.getMonth() + 1).padStart(2, "0");
  const dia = String(date.getDate()).padStart(2, "0");
  return `${ano}-${mes}-${dia}`;
};

const parseDateInput = (value: string) => {
  const [ano, mes, dia] = value.split("-").map(Number);
  if (!ano || !mes || !dia) {
    return new Date();
  }
  return new Date(ano, mes - 1, dia);
};

const toTimeInput = (date: Date) => {
  const hora = String(date.getHours()).padStart(2, "0");
  const minuto = String(date.getMinutes()).padStart(2, "0");
  return `${hora}:${minuto}`;
};

const parseApiDateTime = (value?: string | null): Date | null => {
  if (!value) return null;

  const match = value
    .trim()
    .match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (match) {
    const [, ano, mes, dia, hora, minuto, segundo = "0"] = match;
    const dataLocal = new Date(
      Number(ano),
      Number(mes) - 1,
      Number(dia),
      Number(hora),
      Number(minuto),
      Number(segundo),
      0
    );
    if (!Number.isNaN(dataLocal.getTime())) {
      return dataLocal;
    }
  }

  const normalizado = value.includes("T") ? value : value.replace(" ", "T");
  const data = new Date(normalizado);
  return Number.isNaN(data.getTime()) ? null : data;
};

const parseAgendamentoInicioLocal = (ag: Agendamento): Date | null => {
  if (ag.data && ag.hora) {
    const [ano, mes, dia] = String(ag.data).split("-").map(Number);
    const [hora, minuto] = String(ag.hora).split(":").map(Number);
    if (
      Number.isFinite(ano) &&
      Number.isFinite(mes) &&
      Number.isFinite(dia) &&
      Number.isFinite(hora) &&
      Number.isFinite(minuto)
    ) {
      const data = new Date(ano, mes - 1, dia, hora, minuto, 0, 0);
      if (!Number.isNaN(data.getTime())) {
        return data;
      }
    }
  }

  return parseApiDateTime(ag.inicio);
};

const parseAgendamentoFimLocal = (ag: Agendamento, inicioLocal: Date): Date => {
  const rawInicio = parseApiDateTime(ag.inicio);
  const rawFim = parseApiDateTime(ag.fim);

  if (rawInicio && rawFim && rawFim > rawInicio) {
    const duracaoMs = rawFim.getTime() - rawInicio.getTime();
    return new Date(inicioLocal.getTime() + duracaoMs);
  }

  if (rawFim && rawFim > inicioLocal) {
    return rawFim;
  }

  return new Date(inicioLocal.getTime() + 30 * 60000);
};

const inicioDaSemana = (value: string) => {
  const data = parseDateInput(value);
  const diaSemana = data.getDay();
  const ajuste = diaSemana === 0 ? -6 : 1 - diaSemana;
  data.setDate(data.getDate() + ajuste);
  return data;
};

const gerarSlots = (inicioMinutos = 7 * 60, fimMinutos = 20 * 60, intervaloMinutos = 30) => {
  const slots: string[] = [];
  if (!Number.isFinite(inicioMinutos) || !Number.isFinite(fimMinutos) || fimMinutos <= inicioMinutos) {
    return slots;
  }
  for (let minutos = inicioMinutos; minutos < fimMinutos; minutos += intervaloMinutos) {
    const hora = Math.floor(minutos / 60);
    const minuto = minutos % 60;
    slots.push(`${String(hora).padStart(2, "0")}:${String(minuto).padStart(2, "0")}`);
  }
  return slots;
};

const gerarDatasNoPeriodo = (inicioIso: string, fimIso: string, limiteDias = 93): string[] => {
  if (!inicioIso || !fimIso) return [];
  const inicio = parseDateInput(inicioIso);
  const fim = parseDateInput(fimIso);
  if (Number.isNaN(inicio.getTime()) || Number.isNaN(fim.getTime())) return [];

  const cursor = inicio <= fim ? new Date(inicio) : new Date(fim);
  const limite = inicio <= fim ? fim : inicio;
  const datas: string[] = [];

  while (cursor <= limite && datas.length < limiteDias) {
    datas.push(toDateInput(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }

  return datas;
};

const hojeLocal = () => {
  return toDateInput(new Date());
};

const isDateInputValida = (value?: string | null): value is string => {
  if (!value) return false;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const data = parseDateInput(value);
  return !Number.isNaN(data.getTime());
};

const isModoVisualizacaoValido = (value?: string | null): value is ModoVisualizacao => {
  return value === "lista" || value === "panoramica-dia" || value === "panoramica-semana";
};

interface ReservaPrazoEstado {
  minutosRestantes: number;
  label: string;
  emAlerta: boolean;
  critico: boolean;
  vencido: boolean;
}

const obterEstadoPrazoReserva = (
  agendamento: Agendamento,
  agoraMs: number
): ReservaPrazoEstado | null => {
  if (agendamento.status !== "Reservado" || !agendamento.reserva_expira_em) {
    return null;
  }
  const prazoMs = new Date(agendamento.reserva_expira_em).getTime();
  if (!Number.isFinite(prazoMs)) return null;

  const minutosRestantes = Math.ceil((prazoMs - agoraMs) / 60_000);
  const vencido = minutosRestantes <= 0;
  const critico = minutosRestantes <= 15;
  const emAlerta = minutosRestantes <= 60;
  let label = "";
  if (vencido) {
    label = "prazo vencido agora";
  } else if (minutosRestantes >= 60) {
    const horas = Math.floor(minutosRestantes / 60);
    const minutos = minutosRestantes % 60;
    label = `expira em ${horas}h${minutos ? ` ${minutos}min` : ""}`;
  } else {
    label = `expira em ${minutosRestantes} min`;
  }
  return { minutosRestantes, label, emAlerta, critico, vencido };
};

const gerarPagamentoId = () => {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const toMoneyInput = (value: number): string => {
  if (!Number.isFinite(value)) return "0.00";
  return value.toFixed(2);
};

const parseMoneyValue = (value: string): number => {
  const normalizado = String(value || "").replace(",", ".").trim();
  const parsed = Number.parseFloat(normalizado);
  if (!Number.isFinite(parsed)) return 0;
  return parsed;
};

const criarIdempotencyKeyWhatsApp = (prefixo: string, osId: number) =>
  typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `${prefixo}-${osId}-${Date.now()}`;

const SLOT_INTERVALO_PADRAO_MIN = DEFAULT_AGENDA_ROTA_REGRAS.rendering_policy.slot_interval_min;

export default function AgendaPage() {
  const [agendamentos, setAgendamentos] = useState<Agendamento[]>([]);
  const [agoraReservas, setAgoraReservas] = useState(() => Date.now());
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState("");
  const [modoVisualizacao, setModoVisualizacao] = useState<ModoVisualizacao>("lista");
  const [filtroStatus, setFiltroStatus] = useState<string>("todos");
  const [filtroData, setFiltroData] = useState<string>(() => hojeLocal());
  const [filtroPeriodoInicio, setFiltroPeriodoInicio] = useState<string>(() => hojeLocal());
  const [filtroPeriodoFim, setFiltroPeriodoFim] = useState<string>(() => hojeLocal());
  const [filtroPacienteNome, setFiltroPacienteNome] = useState("");
  const [filtroTutorNome, setFiltroTutorNome] = useState("");
  const [filtroOrigemAtendimento, setFiltroOrigemAtendimento] = useState<string>("todos");
  const [filtroClinicaId, setFiltroClinicaId] = useState<string>("todos");
  const [filtroServicoId, setFiltroServicoId] = useState<string>("todos");
  const [busca, setBusca] = useState("");
  const [pedidoWhatsApp, setPedidoWhatsApp] = useState<PedidoAgenda | null>(null);
  const [modalAberto, setModalAberto] = useState(false);
  const [agendamentoEditando, setAgendamentoEditando] = useState<Agendamento | null>(null);
  const [slotSelecionado, setSlotSelecionado] = useState<{ data: string; hora: string } | null>(null);
  const [confirmando, setConfirmando] = useState<{ id: number; acao: string } | null>(null);
  const [clienteModalAlvo, setClienteModalAlvo] = useState<{ pacienteId?: number; tutorId?: number } | null>(null);
  const [atualizandoStatus, setAtualizandoStatus] = useState<number | null>(null);
  const [modalTipoHorario, setModalTipoHorario] = useState<{ id: number; status: StatusType } | null>(null);
  const [tipoHorario, setTipoHorario] = useState<"comercial" | "plantao">("comercial");
  const [modalReabilitarReserva, setModalReabilitarReserva] = useState<Agendamento | null>(null);
  const [prazoReabilitacaoHoras, setPrazoReabilitacaoHoras] = useState<string>(
    String(PRAZO_REABILITACAO_HORAS_PADRAO)
  );
  const [reabilitandoReservaId, setReabilitandoReservaId] = useState<number | null>(null);
  const [osGerada, setOsGerada] = useState<{ numero_os: string; valor_final: number } | null>(null);
  const [laudosVinculados, setLaudosVinculados] = useState<LaudosVinculadosPorAgendamento>({});
  const [ordensServicoPorAgendamento, setOrdensServicoPorAgendamento] = useState<Record<number, OrdemServicoResumo>>({});
  const [modalPagamentoAberto, setModalPagamentoAberto] = useState(false);
  const [formasPagamentoDisponiveis, setFormasPagamentoDisponiveis] = useState<FormaPagamentoConfig[]>(FORMA_PAGAMENTO_FALLBACK);
  const [carregandoFormasPagamento, setCarregandoFormasPagamento] = useState(false);
  const [pagamentosRecebimento, setPagamentosRecebimento] = useState<PagamentoRecebimentoItem[]>([]);
  const [dataRecebimentoPagamento, setDataRecebimentoPagamento] = useState<string>(() => hojeLocal());
  const [destinoCreditoExcedente, setDestinoCreditoExcedente] = useState<"cliente" | "clinica" | "nenhum">("cliente");
  const [agendamentoPagamentoId, setAgendamentoPagamentoId] = useState<number | null>(null);
  const [recebendoPagamentoId, setRecebendoPagamentoId] = useState<number | null>(null);
  const [saldoCreditoClientePagamento, setSaldoCreditoClientePagamento] = useState(0);
  const [carregandoSaldoCreditoPagamento, setCarregandoSaldoCreditoPagamento] = useState(false);
  const [erroSaldoCreditoPagamento, setErroSaldoCreditoPagamento] = useState("");
  const [usarCreditoClientePagamento, setUsarCreditoClientePagamento] = useState(false);
  const [baixandoCredito, setBaixandoCredito] = useState(false);
  const [valorCreditoUtilizadoPagamento, setValorCreditoUtilizadoPagamento] = useState("0.00");
  const [descontoPagamento, setDescontoPagamento] = useState("0.00");
  const [enviarReciboPdfWhatsAppAposRecebimento, setEnviarReciboPdfWhatsAppAposRecebimento] = useState(false);
  const [clinicasEndereco, setClinicasEndereco] = useState<Record<number, ClinicaEndereco>>({});
  const [tutoresEndereco, setTutoresEndereco] = useState<Record<number, TutorEndereco>>({});
  const [agendaSemanal, setAgendaSemanal] = useState<AgendaSemanalConfig>(() =>
    normalizarAgendaSemanal(DEFAULT_AGENDA_SEMANAL)
  );
  const [agendaFeriados, setAgendaFeriados] = useState<AgendaFeriadoConfig[]>([]);
  const [agendaExcecoes, setAgendaExcecoes] = useState<AgendaExcecaoConfig[]>([]);
  const [renderingPolicy, setRenderingPolicy] = useState<AgendaRotaRenderingPolicyConfig>(
    DEFAULT_AGENDA_ROTA_REGRAS.rendering_policy
  );
  const [isAdmin, setIsAdmin] = useState(false);
  const [resumoFinanceiro, setResumoFinanceiro] = useState<ResumoFinanceiroAgenda | null>(null);
  const [carregandoResumoFinanceiro, setCarregandoResumoFinanceiro] = useState(false);
  const [erroResumoFinanceiro, setErroResumoFinanceiro] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [mensagemRealtime, setMensagemRealtime] = useState("");
  const [toastRealtime, setToastRealtime] = useState<ToastRealtimeData | null>(null);
  const [opcoesClinicas, setOpcoesClinicas] = useState<FiltroOption[]>([]);
  const [opcoesServicos, setOpcoesServicos] = useState<FiltroOption[]>([]);
  const [carregandoClinicasFiltro, setCarregandoClinicasFiltro] = useState(false);
  const [carregandoServicosFiltro, setCarregandoServicosFiltro] = useState(false);
  const clinicasFiltroLoaderRef = useRef<AgendaCatalogLoader | null>(null);
  const servicosFiltroLoaderRef = useRef<AgendaCatalogLoader | null>(null);
  const realtimeRefreshTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastRealtimeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const agendaLoadSequenceRef = useRef(0);
  const relatedLoadSequenceRef = useRef(0);
  const financialSummaryLoadSequenceRef = useRef(0);
  const router = useRouter();
  const fortinho = useFortinho();
  const filtrosIniciaisAplicadosRef = useRef(false);

  useEffect(() => {
    if (!authChecked) return;
    const id = new URLSearchParams(window.location.search).get("pedido_whatsapp");
    if (!id || !/^[1-9][0-9]*$/.test(id)) return;
    let active = true;
    const controller = new AbortController();
    api.get<PedidoAgenda>(`/whatsapp/bot/solicitacoes/${id}/preparar-agendamento`, { signal: controller.signal })
      .then(({ data }) => {
        if (!active) return;
        setPedidoWhatsApp(data); setAgendamentoEditando(null); setSlotSelecionado(null); setModalAberto(true);
      }).catch((error) => {
        if (active) setErro(error?.response?.data?.detail || "Não foi possível preparar o pedido. Volte à fila e tente novamente.");
      });
    return () => { active = false; controller.abort(); };
  }, [authChecked]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setAgoraReservas(Date.now());
    }, 30_000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    if (filtrosIniciaisAplicadosRef.current) return;

    if (typeof window === "undefined") return;
    const urlParams = new URLSearchParams(window.location.search);
    const dataQuery = urlParams.get("data");
    const visaoQuery = urlParams.get("visao");
    const statusQuery = urlParams.get("status");
    const origemQuery = urlParams.get("origem_atendimento") || urlParams.get("origem");

    if (isDateInputValida(dataQuery)) {
      setFiltroData(dataQuery);
      setFiltroPeriodoInicio(dataQuery);
      setFiltroPeriodoFim(dataQuery);
    }

    if (isModoVisualizacaoValido(visaoQuery)) {
      setModoVisualizacao(visaoQuery);
    }

    if (statusQuery) {
      const statusNormalizado = statusQuery.trim();
      const statusEhValido = statusNormalizado === "todos" || AGENDA_STATUS_LIST.includes(statusNormalizado as AgendaStatus);
      if (statusEhValido) {
        setFiltroStatus(statusNormalizado);
      }
    }

    if (
      origemQuery === "todos" ||
      origemQuery === "clinica_parceira" ||
      origemQuery === "domiciliar"
    ) {
      setFiltroOrigemAtendimento(origemQuery);
    }

    filtrosIniciaisAplicadosRef.current = true;
  }, []);

  const carregarFormasPagamento = useCallback(async () => {
    try {
      setCarregandoFormasPagamento(true);
      const response = await api.get("/financeiro/formas-pagamento", {
        params: {
          apenas_ativas: true,
          limit: 200,
        },
      });
      const items = Array.isArray(response.data?.items) ? response.data.items : [];
      if (items.length > 0) {
        const normalizados: FormaPagamentoConfig[] = items.map((item: any) => ({
          id: Number(item.id),
          codigo: normalizarCodigoFormaPagamento(item.codigo),
          nome: String(item.nome || item.codigo || "Forma de pagamento"),
          tipo: item.tipo,
          adquirente: item.adquirente ?? null,
          bandeira_id: item.bandeira_id ?? null,
          bandeira_nome: item.bandeira_nome ?? null,
          taxa_percentual: Number(item.taxa_percentual || 0),
          taxa_fixa: Number(item.taxa_fixa || 0),
          ativo: Boolean(item.ativo ?? true),
        }));
        setFormasPagamentoDisponiveis(normalizados);
        return;
      }
      setFormasPagamentoDisponiveis(FORMA_PAGAMENTO_FALLBACK);
    } catch (error) {
      console.error("Erro ao carregar formas de pagamento:", error);
      setFormasPagamentoDisponiveis(FORMA_PAGAMENTO_FALLBACK);
    } finally {
      setCarregandoFormasPagamento(false);
    }
  }, []);

  useEffect(() => {
    void carregarFormasPagamento();
  }, [carregarFormasPagamento]);

  const osPagamentoAtual = agendamentoPagamentoId
    ? ordensServicoPorAgendamento[agendamentoPagamentoId]
    : undefined;
  const agendamentoPagamentoAtual = agendamentoPagamentoId
    ? agendamentos.find((item) => item.id === agendamentoPagamentoId) || null
    : null;

  useEffect(() => {
    if (!modalPagamentoAberto || !agendamentoPagamentoAtual) {
      setSaldoCreditoClientePagamento(0);
      setCarregandoSaldoCreditoPagamento(false);
      setErroSaldoCreditoPagamento("");
      return;
    }

    const pacienteId = Number(agendamentoPagamentoAtual.paciente_id || 0);
    if (!Number.isFinite(pacienteId) || pacienteId <= 0) {
      setSaldoCreditoClientePagamento(0);
      setCarregandoSaldoCreditoPagamento(false);
      setErroSaldoCreditoPagamento("");
      return;
    }

    let ativo = true;
    setCarregandoSaldoCreditoPagamento(true);
    setErroSaldoCreditoPagamento("");

    (async () => {
      try {
        const saldo = await consultarSaldoCreditoCliente({ pacienteId });
        if (!ativo) return;
        setSaldoCreditoClientePagamento(saldo > 0 ? saldo : 0);
      } catch (error) {
        console.error("Erro ao consultar credito do cliente no recebimento:", error);
        if (!ativo) return;
        setSaldoCreditoClientePagamento(0);
        setErroSaldoCreditoPagamento("Nao foi possivel consultar o credito do cliente.");
      } finally {
        if (!ativo) return;
        setCarregandoSaldoCreditoPagamento(false);
      }
    })();

    return () => {
      ativo = false;
    };
  }, [agendamentoPagamentoAtual, modalPagamentoAberto]);

  const abrirAgendaFullCalendar = useCallback(() => {
    const params = new URLSearchParams();
    const dataBase =
      modoVisualizacao === "lista"
        ? filtroPeriodoInicio || filtroData || hojeLocal()
        : filtroData || hojeLocal();

    params.set("data", dataBase);
    if (filtroStatus !== "todos") {
      params.set("status", filtroStatus);
    }
    if (filtroOrigemAtendimento !== "todos") {
      params.set("origem_atendimento", filtroOrigemAtendimento);
    }
    router.push(`/agenda/fullcalendar?${params.toString()}`);
  }, [filtroData, filtroOrigemAtendimento, filtroPeriodoInicio, filtroStatus, modoVisualizacao, router]);

  const periodoConsulta = useMemo(() => {
    const dataBase = filtroData || hojeLocal();

    if (modoVisualizacao === "panoramica-semana") {
      const inicioSemana = inicioDaSemana(dataBase);
      const inicio = toDateInput(inicioSemana);
      const fimSemana = new Date(inicioSemana);
      fimSemana.setDate(fimSemana.getDate() + 6);
      const fim = toDateInput(fimSemana);
      return { inicio, fim };
    }

    if (modoVisualizacao === "panoramica-dia") {
      return { inicio: dataBase, fim: dataBase };
    }

    if (modoVisualizacao === "lista") {
      const inicioPeriodo = filtroPeriodoInicio || dataBase;
      const fimPeriodo = filtroPeriodoFim || inicioPeriodo;
      if (inicioPeriodo <= fimPeriodo) {
        return { inicio: inicioPeriodo, fim: fimPeriodo };
      }
      return { inicio: fimPeriodo, fim: inicioPeriodo };
    }

    if (filtroData) {
      return { inicio: filtroData, fim: filtroData };
    }

    return { inicio: "", fim: "" };
  }, [filtroData, filtroPeriodoFim, filtroPeriodoInicio, modoVisualizacao]);

  const alertasAgendaLista = useMemo<AgendaListaStatusDia[]>(() => {
    if (modoVisualizacao !== "lista") return [];
    const diasPeriodo = gerarDatasNoPeriodo(periodoConsulta.inicio, periodoConsulta.fim);
    if (diasPeriodo.length === 0) return [];

    const alertas: AgendaListaStatusDia[] = [];

    for (const dataIso of diasPeriodo) {
      const jornada = obterJornadaDia(dataIso, agendaSemanal, agendaFeriados, agendaExcecoes);
      const excecao = obterExcecaoData(dataIso, agendaExcecoes);

      if (jornada.fechado) {
        alertas.push({
          data: dataIso,
          tipo: "fechada",
          inicio: jornada.inicio,
          fim: jornada.fim,
          motivo: jornada.motivo || "Agenda fechada",
        });
        continue;
      }

      if (excecao?.ativo) {
        alertas.push({
          data: dataIso,
          tipo: "janela-especial",
          inicio: jornada.inicio,
          fim: jornada.fim,
          motivo: excecao.motivo || "Janela especial de atendimento",
        });
      }
    }

    return alertas;
  }, [agendaExcecoes, agendaFeriados, agendaSemanal, modoVisualizacao, periodoConsulta.fim, periodoConsulta.inicio]);

  const usuarioEhAdmin = () => {
    if (typeof window === "undefined") return false;
    const userData = localStorage.getItem("user");
    const token = localStorage.getItem("token");

    try {
      if (userData) {
        const user = JSON.parse(userData);
        const papeisUser: unknown[] = Array.isArray(user?.papeis) ? user.papeis : [];
        if (papeisUser.some((papel: unknown) => String(papel || "").trim().toLowerCase() === "admin")) {
          return true;
        }
      }

      if (token) {
        const partes = token.split(".");
        if (partes.length >= 2) {
          const base64Url = partes[1];
          const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
          const normalizado = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
          const payloadStr = atob(normalizado);
          const payload = JSON.parse(payloadStr);
          const papeisToken: unknown[] = Array.isArray(payload?.papeis) ? payload.papeis : [];
          if (papeisToken.some((papel: unknown) => String(papel || "").trim().toLowerCase() === "admin")) {
            return true;
          }
        }
      }

      return false;
    } catch {
      return false;
    }
  };

  const carregarConfiguracaoAgenda = async () => {
    try {
      // Usa endpoint do modulo agenda para nao depender da permissao de "configuracoes".
      const response = await api.get("/agenda/configuracao");
      setAgendaSemanal(normalizarAgendaSemanal(response.data?.agenda_semanal));
      setAgendaFeriados(normalizarAgendaFeriados(response.data?.agenda_feriados));
      setAgendaExcecoes(normalizarAgendaExcecoes(response.data?.agenda_excecoes));
      const regrasRota = normalizarAgendaRotaRegras(response.data?.agenda_rota_regras);
      setRenderingPolicy(regrasRota.rendering_policy);
    } catch (error: any) {
      try {
        // Compatibilidade com backend legado sem /agenda/configuracao.
        if (error?.response?.status === 404) {
          const fallback = await api.get("/configuracoes");
          setAgendaSemanal(normalizarAgendaSemanal(fallback.data?.agenda_semanal));
          setAgendaFeriados(normalizarAgendaFeriados(fallback.data?.agenda_feriados));
          setAgendaExcecoes(normalizarAgendaExcecoes(fallback.data?.agenda_excecoes));
          const regrasRota = normalizarAgendaRotaRegras(fallback.data?.agenda_rota_regras);
          setRenderingPolicy(regrasRota.rendering_policy);
          return;
        }
      } catch (fallbackError) {
        console.error("Erro no fallback de configuracao da agenda:", fallbackError);
      }

      console.error("Erro ao carregar configuracao da agenda:", error);
      setAgendaSemanal(normalizarAgendaSemanal(DEFAULT_AGENDA_SEMANAL));
      setAgendaFeriados([]);
      setAgendaExcecoes([]);
      setRenderingPolicy(DEFAULT_AGENDA_ROTA_REGRAS.rendering_policy);
    }
  };

  const carregarOpcoesClinicasFiltro = () => {
    if (!clinicasFiltroLoaderRef.current) {
      clinicasFiltroLoaderRef.current = createAgendaCatalogLoader({
        request: async () => {
          const payload = await loadStableCatalog({
            catalog: "clinicas",
            variant: "limit=1000",
            load: () => api.get("/clinicas?limit=1000").then((response) => response.data),
          });
          return normalizarOpcoesFiltroAgenda(payload);
        },
        onSuccess: setOpcoesClinicas,
        onLoadingChange: setCarregandoClinicasFiltro,
        onError: (error) => console.error("Erro ao carregar clinicas do filtro da agenda:", error),
      });
    }
    return clinicasFiltroLoaderRef.current.load();
  };

  const carregarOpcoesServicosFiltro = () => {
    if (!servicosFiltroLoaderRef.current) {
      servicosFiltroLoaderRef.current = createAgendaCatalogLoader({
        request: async () => {
          const payload = await loadStableCatalog({
            catalog: "servicos",
            variant: "limit=1000",
            load: () => api.get("/servicos?limit=1000").then((response) => response.data),
          });
          return normalizarOpcoesFiltroAgenda(payload);
        },
        onSuccess: setOpcoesServicos,
        onLoadingChange: setCarregandoServicosFiltro,
        onError: (error) => console.error("Erro ao carregar servicos do filtro da agenda:", error),
      });
    }
    return servicosFiltroLoaderRef.current.load();
  };

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    setIsAdmin(usuarioEhAdmin());
    setAuthChecked(true);
    carregarAgendamentos({ includeResumo: false });
  }, [router, periodoConsulta.inicio, periodoConsulta.fim]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    carregarConfiguracaoAgenda();
  }, [router]);

  useEffect(() => {
    if (!authChecked) return;
    if (modoVisualizacao !== "lista") {
      financialSummaryLoadSequenceRef.current += 1;
      setResumoFinanceiro(null);
      setCarregandoResumoFinanceiro(false);
      setErroResumoFinanceiro(false);
      return;
    }
    carregarResumoFinanceiro();
  }, [
    isAdmin,
    modoVisualizacao,
    periodoConsulta.inicio,
    periodoConsulta.fim,
    filtroOrigemAtendimento,
    filtroClinicaId,
    filtroServicoId,
    filtroPacienteNome,
    filtroTutorNome,
    authChecked,
  ]);

  useEffect(() => {
    return () => {
      if (realtimeRefreshTimeoutRef.current) {
        clearTimeout(realtimeRefreshTimeoutRef.current);
        realtimeRefreshTimeoutRef.current = null;
      }
      if (toastRealtimeTimeoutRef.current) {
        clearTimeout(toastRealtimeTimeoutRef.current);
        toastRealtimeTimeoutRef.current = null;
      }
    };
  }, []);

  const carregarAgendamentos = async ({
    includeRelated = true,
    includeResumo = true,
  }: CarregarAgendamentosOptions = {}) => {
    const loadSequence = ++agendaLoadSequenceRef.current;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (periodoConsulta.inicio && periodoConsulta.fim) {
        params.append("data_inicio", periodoConsulta.inicio);
        params.append("data_fim", periodoConsulta.fim);
      }
      if (filtroClinicaId !== "todos") {
        params.append("clinica_id", filtroClinicaId);
      }
      if (filtroOrigemAtendimento !== "todos") {
        params.append("origem_atendimento", filtroOrigemAtendimento);
      }
      if (filtroServicoId !== "todos") {
        params.append("servico_id", filtroServicoId);
      }
      const pacienteNome = filtroPacienteNome.trim();
      if (pacienteNome) {
        params.append("paciente_nome", pacienteNome);
      }
      const tutorNome = filtroTutorNome.trim();
      if (tutorNome) {
        params.append("tutor_nome", tutorNome);
      }

      const response = await api.get(`/agenda?${params.toString()}`);
      if (loadSequence !== agendaLoadSequenceRef.current) return;
      const items = response.data.items || [];
      setAgendamentos(items);
      if (response.data?.agenda_semanal) {
        setAgendaSemanal(normalizarAgendaSemanal(response.data.agenda_semanal));
      }
      if (response.data?.agenda_feriados) {
        setAgendaFeriados(normalizarAgendaFeriados(response.data.agenda_feriados));
      }
      if (response.data?.agenda_excecoes) {
        setAgendaExcecoes(normalizarAgendaExcecoes(response.data.agenda_excecoes));
      }
      if (response.data?.agenda_rota_regras) {
        const regrasRota = normalizarAgendaRotaRegras(response.data.agenda_rota_regras);
        setRenderingPolicy(regrasRota.rendering_policy);
      }
      const auxiliaryLoads = [];
      if (includeRelated) {
        auxiliaryLoads.push(() => carregarRelacionadosVisiveis(items, loadSequence));
      }
      if (includeResumo) {
        auxiliaryLoads.push(() => carregarResumoFinanceiro());
      }
      if (auxiliaryLoads.length > 0) {
        void executarCargasAuxiliaresAgenda(auxiliaryLoads);
      }
      setErro("");
    } catch (error: any) {
      if (loadSequence !== agendaLoadSequenceRef.current) return;
      console.error("Erro ao carregar:", error);
      if (error.response?.status === 401) {
        setErro("Sessão expirada. Redirecionando...");
        localStorage.removeItem("token");
        setTimeout(() => router.push("/"), 2000);
      } else {
        setErro("Erro ao carregar agendamentos");
      }
    } finally {
      if (loadSequence === agendaLoadSequenceRef.current) {
        setLoading(false);
      }
    }
  };

  const agendarRefreshRealtime = useCallback(
    (payload?: { action?: string; agendamento_id?: number }) => {
      if (payload?.action) {
        const sufixoId =
          typeof payload.agendamento_id === "number" && Number.isFinite(payload.agendamento_id)
            ? ` #${payload.agendamento_id}`
            : "";
        setMensagemRealtime(`Atualizacao em tempo real: ${payload.action}${sufixoId}.`);
      }

      if (realtimeRefreshTimeoutRef.current) {
        return;
      }

      realtimeRefreshTimeoutRef.current = setTimeout(() => {
        realtimeRefreshTimeoutRef.current = null;
        void carregarAgendamentos({ includeRelated: false, includeResumo: false });
      }, 700);
    },
    [carregarAgendamentos]
  );

  const mostrarToastRealtime = useCallback((payload?: AgendaRealtimePayload) => {
    const toast = montarToastAgendaRealtime(payload);
    if (!toast) {
      return;
    }

    const agendamentoId =
      typeof payload?.agendamento_id === "number" && Number.isFinite(payload.agendamento_id)
        ? payload.agendamento_id
        : undefined;

    setToastRealtime({
      ...toast,
      agendamentoId,
    });
    if (toastRealtimeTimeoutRef.current) {
      clearTimeout(toastRealtimeTimeoutRef.current);
    }
    toastRealtimeTimeoutRef.current = setTimeout(() => {
      setToastRealtime(null);
      toastRealtimeTimeoutRef.current = null;
    }, 4000);
  }, []);

  const { conectado: realtimeConectado, ultimoEvento: realtimeUltimoEvento } = useAgendaRealtime(
    authChecked,
    (payload) => {
      agendarRefreshRealtime({
        action: payload.action,
        agendamento_id:
          typeof payload.agendamento_id === "number" ? payload.agendamento_id : undefined,
      });
      mostrarToastRealtime(payload);
    }
  );

  const abrirAgendamentoDoToast = useCallback(
    async (agendamentoId: number) => {
      try {
        let agendamento = agendamentos.find((item) => item.id === agendamentoId) || null;
        if (!agendamento) {
          const response = await api.get(`/agenda/${agendamentoId}`);
          agendamento = response.data as Agendamento;
        }

        setAgendamentoEditando(agendamento);
        setSlotSelecionado(null);
        setModalAberto(true);
        setToastRealtime(null);
      } catch (error) {
        console.error("Erro ao abrir agendamento pelo toast em tempo real:", error);
        setErro("Nao foi possivel abrir o agendamento do toast.");
      }
    },
    [agendamentos]
  );

  const carregarRelacionadosVisiveis = async (
    items: Agendamento[],
    agendaLoadSequence = agendaLoadSequenceRef.current
  ) => {
    const relatedLoadSequence = ++relatedLoadSequenceRef.current;
    const isCurrentLoad = () =>
      relatedLoadSequence === relatedLoadSequenceRef.current &&
      agendaLoadSequence === agendaLoadSequenceRef.current;
    const idsVisiveis = extrairIdsAgendamentosVisiveis(items);
    const limparRelacionados = () => {
      if (!isCurrentLoad()) return;
      setLaudosVinculados({});
      setOrdensServicoPorAgendamento({});
      setClinicasEndereco({});
      setTutoresEndereco({});
    };

    if (idsVisiveis.length === 0) {
      limparRelacionados();
      return;
    }

    const idsAgendamento = new Set(idsVisiveis);
    const pacientePorAgendamento = new Map(
      items.map((item) => [item.id, Number(item.paciente_id || 0)])
    );

    try {
      const response = await api.get("/agenda/relacionados", {
        params: { agendamento_ids: idsVisiveis.join(",") },
      });
      const listaLaudos = Array.isArray(response.data?.laudos) ? response.data.laudos : [];
      const listaOrdens = Array.isArray(response.data?.ordens_servico)
        ? response.data.ordens_servico
        : [];
      const listaClinicas = Array.isArray(response.data?.clinicas) ? response.data.clinicas : [];
      const listaTutores = Array.isArray(response.data?.tutores) ? response.data.tutores : [];

      if (!isCurrentLoad()) return;

      const mapaLaudos: LaudosVinculadosPorAgendamento = {};
      for (const laudo of listaLaudos) {
        const agendamentoId = Number(laudo?.agendamento_id);
        if (!Number.isInteger(agendamentoId) || !idsAgendamento.has(agendamentoId)) {
          continue;
        }

        const pacienteLaudoId = Number(laudo?.paciente_id);
        const pacienteAgendamentoId = Number(pacientePorAgendamento.get(agendamentoId) || 0);
        if (
          Number.isFinite(pacienteLaudoId) &&
          pacienteLaudoId > 0 &&
          Number.isFinite(pacienteAgendamentoId) &&
          pacienteAgendamentoId > 0 &&
          pacienteLaudoId !== pacienteAgendamentoId
        ) {
          continue;
        }

        const tipo = String(laudo?.tipo || "");
        const laudoId = Number(laudo?.id);
        if (!tipo || !Number.isInteger(laudoId)) {
          continue;
        }

        const laudosDoAgendamento = mapaLaudos[agendamentoId] || {};
        const anterior = laudosDoAgendamento[tipo];
        if (!anterior || laudoId > anterior.id) {
          mapaLaudos[agendamentoId] = {
            ...laudosDoAgendamento,
            [tipo]: {
              id: laudoId,
              status: String(laudo?.status || ""),
              titulo: String(laudo?.titulo || `Laudo ${laudoId}`),
              tipo,
            },
          };
        }
      }

      const mapaOrdens: Record<number, OrdemServicoResumo> = {};
      for (const os of listaOrdens) {
        const agendamentoId = Number(os?.agendamento_id);
        if (!Number.isInteger(agendamentoId) || !idsAgendamento.has(agendamentoId)) {
          continue;
        }

        const osId = Number(os?.id);
        if (!Number.isInteger(osId)) {
          continue;
        }

        const anterior = mapaOrdens[agendamentoId];
        if (!anterior || osId > anterior.id) {
          mapaOrdens[agendamentoId] = {
            id: osId,
            agendamento_id: agendamentoId,
            numero_os: String(os?.numero_os || ""),
            status: String(os?.status || ""),
            valor_servico: Number(os?.valor_servico || 0),
            desconto: Number(os?.desconto || 0),
            valor_final: Number(os?.valor_final || 0),
          };
        }
      }

      const mapaClinicas: Record<number, ClinicaEndereco> = {};
      for (const clinica of listaClinicas) {
        const clinicaId = Number(clinica?.id);
        if (!Number.isInteger(clinicaId) || clinicaId <= 0) continue;
        mapaClinicas[clinicaId] = {
          id: clinicaId,
          nome: clinica?.nome || null,
          endereco: clinica?.endereco || null,
          numero: clinica?.numero || null,
          bairro: clinica?.bairro || null,
          cidade: clinica?.cidade || null,
          estado: clinica?.estado || null,
          cep: clinica?.cep || null,
          latitude: normalizarCoordenadaOpcional(clinica?.latitude),
          longitude: normalizarCoordenadaOpcional(clinica?.longitude),
          endereco_normalizado: clinica?.endereco_normalizado || null,
        };
      }

      const mapaTutores: Record<number, TutorEndereco> = {};
      for (const tutor of listaTutores) {
        const tutorId = Number(tutor?.id);
        if (!Number.isInteger(tutorId) || tutorId <= 0) continue;
        mapaTutores[tutorId] = {
          id: tutorId,
          nome: tutor?.nome || null,
          endereco: tutor?.endereco || null,
          numero: tutor?.numero || null,
          bairro: tutor?.bairro || null,
          cidade: tutor?.cidade || null,
          estado: tutor?.estado || null,
          cep: tutor?.cep || null,
          latitude: normalizarCoordenadaOpcional(tutor?.latitude),
          longitude: normalizarCoordenadaOpcional(tutor?.longitude),
          endereco_normalizado: tutor?.endereco_normalizado || null,
        };
      }

      setLaudosVinculados(mapaLaudos);
      setOrdensServicoPorAgendamento(mapaOrdens);
      setClinicasEndereco(mapaClinicas);
      setTutoresEndereco(mapaTutores);
    } catch (error) {
      console.error("Erro ao carregar dados relacionados aos agendamentos visiveis:", error);
      limparRelacionados();
    }
  };

  const carregarResumoFinanceiro = async () => {
    const loadSequence = ++financialSummaryLoadSequenceRef.current;
    if (!isAdmin || modoVisualizacao !== "lista") {
      setResumoFinanceiro(null);
      setErroResumoFinanceiro(false);
      return;
    }

    const inicio = periodoConsulta.inicio || filtroData || hojeLocal();
    const fim = periodoConsulta.fim || inicio;
    setCarregandoResumoFinanceiro(true);
    setErroResumoFinanceiro(false);

    try {
      const params = new URLSearchParams();
      params.append("data_inicio", inicio);
      params.append("data_fim", fim);
      if (filtroClinicaId !== "todos") {
        params.append("clinica_id", filtroClinicaId);
      }
      if (filtroOrigemAtendimento !== "todos") {
        params.append("origem_atendimento", filtroOrigemAtendimento);
      }
      if (filtroServicoId !== "todos") {
        params.append("servico_id", filtroServicoId);
      }
      const pacienteNome = filtroPacienteNome.trim();
      if (pacienteNome) {
        params.append("paciente_nome", pacienteNome);
      }
      const tutorNome = filtroTutorNome.trim();
      if (tutorNome) {
        params.append("tutor_nome", tutorNome);
      }

      const respResumo = await api.get(`/agenda/resumo-financeiro?${params.toString()}`);
      if (loadSequence !== financialSummaryLoadSequenceRef.current) return;
      setResumoFinanceiro(respResumo.data || null);
      setErroResumoFinanceiro(false);
    } catch (error: any) {
      if (loadSequence !== financialSummaryLoadSequenceRef.current) return;
      if (error?.response?.status !== 403) {
        console.error("Erro ao carregar resumo financeiro da agenda:", error);
      }
      setResumoFinanceiro(null);
      setErroResumoFinanceiro(true);
    } finally {
      if (loadSequence === financialSummaryLoadSequenceRef.current) {
        setCarregandoResumoFinanceiro(false);
      }
    }
  };

  const abrirWazeParaDestino = (destinoLocal: WazeDestinoLocal | null | undefined, nomeDestino?: string | null) => {
    const destino = montarWazeDestinoLocal(destinoLocal);
    if (!destino) {
      alert(`Nao ha endereco ou coordenadas cadastradas para ${nomeDestino || "este destino"}.`);
      return;
    }

    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "");

    if (isMobile) {
      const startedAt = Date.now();
      window.location.href = destino.appUrl;

      window.setTimeout(() => {
        const elapsed = Date.now() - startedAt;
        const appProvavelmenteAberto = document.visibilityState === "hidden";
        if (!appProvavelmenteAberto && elapsed < 2200) {
          window.location.href = destino.webUrl;
        }
      }, 1200);
      return;
    }

    window.open(destino.webUrl, "_blank", "noopener,noreferrer");
  };

  const abrirGoogleMapsParaDestino = (
    destinoLocal: WazeDestinoLocal | null | undefined,
    nomeDestino?: string | null
  ) => {
    const destino = montarGoogleMapsDestinoLocal(destinoLocal);
    if (!destino) {
      alert(`Nao ha endereco ou coordenadas cadastradas para ${nomeDestino || "este destino"}.`);
      return;
    }

    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "");
    if (isMobile) {
      window.location.href = destino;
      return;
    }

    window.open(destino, "_blank", "noopener,noreferrer");
  };

  const resumoPagamentoModal = useMemo(() => {
    const linhas = pagamentosRecebimento.map((item) => {
      const codigo = normalizarCodigoFormaPagamento(item.forma_codigo);
      const forma = formasPagamentoDisponiveis.find(
        (opcao) => normalizarCodigoFormaPagamento(opcao.codigo) === codigo
      );
      const valor = parseMoneyValue(item.valor);
      const taxaPercentual = Number(forma?.taxa_percentual || 0);
      const taxaFixa = Number(forma?.taxa_fixa || 0);
      const taxa = Number((valor * (taxaPercentual / 100) + taxaFixa).toFixed(2));
      const liquido = Number((valor - taxa).toFixed(2));
      return {
        ...item,
        forma,
        valor,
        taxaPercentual,
        taxaFixa,
        taxa,
        liquido,
      };
    });
    const totalBruto = linhas.reduce((acc, item) => acc + item.valor, 0);
    const totalTaxa = linhas.reduce((acc, item) => acc + item.taxa, 0);
    const totalLiquido = linhas.reduce((acc, item) => acc + item.liquido, 0);
    const valorOsBrutoDireto = Number(osPagamentoAtual?.valor_servico || 0);
    const descontoBase = Number(osPagamentoAtual?.desconto || 0);
    const valorOsBruto = Number(
      (valorOsBrutoDireto > 0 ? valorOsBrutoDireto : Number(osPagamentoAtual?.valor_final || 0) + descontoBase).toFixed(
        2
      )
    );
    const descontoSolicitado = parseMoneyValue(descontoPagamento);
    const descontoAplicado = Math.max(0, Math.min(descontoSolicitado, Math.max(0, valorOsBruto)));
    const valorOs = Number((Math.max(0, valorOsBruto - descontoAplicado)).toFixed(2));
    const limiteCredito = Math.max(0, Number(saldoCreditoClientePagamento || 0));
    const creditoSolicitado = parseMoneyValue(valorCreditoUtilizadoPagamento);
    const creditoUtilizado = usarCreditoClientePagamento
      ? Math.max(0, Math.min(creditoSolicitado, limiteCredito))
      : 0;
    const totalCoberto = Number((totalBruto + creditoUtilizado).toFixed(2));
    const diferenca = Number((totalCoberto - valorOs).toFixed(2));
    return {
      linhas,
      totalBruto,
      totalTaxa,
      totalLiquido,
      totalCoberto,
      valorOsBruto,
      descontoAplicado,
      valorOs,
      limiteCredito,
      creditoSolicitado,
      creditoUtilizado,
      diferenca,
      excedente: diferenca > 0 ? diferenca : 0,
      faltante: diferenca < 0 ? Math.abs(diferenca) : 0,
    };
  }, [
    descontoPagamento,
    formasPagamentoDisponiveis,
    osPagamentoAtual?.desconto,
    osPagamentoAtual?.valor_servico,
    osPagamentoAtual?.valor_final,
    pagamentosRecebimento,
    saldoCreditoClientePagamento,
    usarCreditoClientePagamento,
    valorCreditoUtilizadoPagamento,
  ]);

  const atualizarLinhaPagamento = useCallback((id: string, campo: "forma_codigo" | "valor", valor: string) => {
    setPagamentosRecebimento((prev) =>
      prev.map((item) => (item.id === id ? { ...item, [campo]: valor } : item))
    );
  }, []);

  const removerLinhaPagamento = useCallback((id: string) => {
    setPagamentosRecebimento((prev) => {
      if (prev.length <= 1) return prev;
      return prev.filter((item) => item.id !== id);
    });
  }, []);

  const adicionarLinhaPagamento = useCallback(() => {
    const formaPadrao =
      formasPagamentoDisponiveis.find(
        (forma) => normalizarCodigoFormaPagamento(forma.codigo) === FORMA_PAGAMENTO_PADRAO
      ) || formasPagamentoDisponiveis[0];
    const codigo = normalizarCodigoFormaPagamento(formaPadrao?.codigo || FORMA_PAGAMENTO_PADRAO);
    setPagamentosRecebimento((prev) => [
      ...prev,
      {
        id: gerarPagamentoId(),
        forma_codigo: codigo,
        valor: "0.00",
      },
    ]);
  }, [formasPagamentoDisponiveis]);

  const abrirRecebimentoPagamentoModal = (agendamentoId: number) => {
    const osVinculada = ordensServicoPorAgendamento[agendamentoId];
    if (!osVinculada) {
      setErro("Este agendamento nao possui ordem de servico vinculada para recebimento.");
      return;
    }

    if (osEstaPaga(osVinculada.status)) {
      setErro("");
      return;
    }

    setErro("");
    const formaPadrao =
      formasPagamentoDisponiveis.find(
        (forma) => normalizarCodigoFormaPagamento(forma.codigo) === FORMA_PAGAMENTO_PADRAO
      ) || formasPagamentoDisponiveis[0];
    const formaCodigo = normalizarCodigoFormaPagamento(formaPadrao?.codigo || FORMA_PAGAMENTO_PADRAO);
    setPagamentosRecebimento([
      {
        id: gerarPagamentoId(),
        forma_codigo: formaCodigo,
        valor: toMoneyInput(Number(osVinculada.valor_final || 0)),
      },
    ]);
    setDescontoPagamento(toMoneyInput(Number(osVinculada.desconto || 0)));
    setDataRecebimentoPagamento(hojeLocal());
    setDestinoCreditoExcedente("cliente");
    setSaldoCreditoClientePagamento(0);
    setCarregandoSaldoCreditoPagamento(false);
    setErroSaldoCreditoPagamento("");
    setUsarCreditoClientePagamento(false);
    setValorCreditoUtilizadoPagamento("0.00");
    setEnviarReciboPdfWhatsAppAposRecebimento(false);
    setAgendamentoPagamentoId(agendamentoId);
    setModalPagamentoAberto(true);
    if (!formasPagamentoDisponiveis.length) {
      void carregarFormasPagamento();
    }
  };

  const confirmarRecebimentoPagamento = async () => {
    if (!agendamentoPagamentoId) return;
    const osVinculada = ordensServicoPorAgendamento[agendamentoPagamentoId];
    if (!osVinculada) {
      setErro("Este agendamento nao possui ordem de servico vinculada para recebimento.");
      setModalPagamentoAberto(false);
      setAgendamentoPagamentoId(null);
      return;
    }

    try {
      setRecebendoPagamentoId(agendamentoPagamentoId);
      setErro("");
      const pagamentosPayload = resumoPagamentoModal.linhas
        .filter((item) => item.valor > 0)
        .map((item) => ({
          forma_pagamento: normalizarCodigoFormaPagamento(item.forma_codigo),
          forma_pagamento_config_id: item.forma?.id ?? undefined,
          valor: Number(item.valor.toFixed(2)),
        }));
      const creditoUtilizado = Number(resumoPagamentoModal.creditoUtilizado || 0);

      if (pagamentosPayload.length === 0 && creditoUtilizado <= 0 && resumoPagamentoModal.valorOs > 0) {
        setErro("Informe ao menos um pagamento com valor maior que zero ou utilize credito disponivel.");
        return;
      }

      await api.patch(`/ordens-servico/${osVinculada.id}/receber`, {
        pagamentos: pagamentosPayload,
        data_recebimento: dataRecebimentoPagamento || null,
        desconto: Number(resumoPagamentoModal.descontoAplicado.toFixed(2)),
        valor_credito_utilizado: Number(creditoUtilizado.toFixed(2)),
        destino_credito_excedente: destinoCreditoExcedente,
      });

      let avisoRecibo = "";
      if (enviarReciboPdfWhatsAppAposRecebimento) {
        try {
          await api.post(`/ordens-servico/${osVinculada.id}/whatsapp/recibo-pdf`, {
            idempotency_key: criarIdempotencyKeyWhatsApp("agenda-recibo-pdf", osVinculada.id),
          });
        } catch (error: any) {
          avisoRecibo =
            error?.response?.data?.detail ||
            "O recebimento foi registrado, mas nao foi possivel enviar o recibo PDF para a clinica pelo WhatsApp.";
        }
      }

      setModalPagamentoAberto(false);
      setAgendamentoPagamentoId(null);
      setPagamentosRecebimento([]);
      setSaldoCreditoClientePagamento(0);
      setCarregandoSaldoCreditoPagamento(false);
      setErroSaldoCreditoPagamento("");
      setUsarCreditoClientePagamento(false);
      setValorCreditoUtilizadoPagamento("0.00");
      setDescontoPagamento("0.00");
      setEnviarReciboPdfWhatsAppAposRecebimento(false);
      await carregarAgendamentos();
      if (avisoRecibo) {
        window.alert(`Recebimento registrado com sucesso.\n\nAviso do WhatsApp: ${avisoRecibo}`);
      } else if (enviarReciboPdfWhatsAppAposRecebimento) {
        window.alert("Recebimento registrado e recibo PDF enviado para a clinica pelo WhatsApp!");
      }
    } catch (error: any) {
      console.error("Erro ao receber pagamento da OS na agenda:", error);
      const detail = error?.response?.data?.detail;
      const detailTexto = Array.isArray(detail)
        ? detail.map((item: any) => item?.msg || item?.message || JSON.stringify(item)).join("; ")
        : typeof detail === "string"
          ? detail
          : detail?.message || "";
      setErro(detailTexto || "Nao foi possivel registrar o recebimento desta OS.");
    } finally {
      setRecebendoPagamentoId(null);
    }
  };

  const atualizarStatus = async (id: number, novoStatus: StatusType, tipoHorarioParam?: "comercial" | "plantao") => {
    setErro("");
    // Se for Realizado, abre o modal de seleção de tipo de horário
    if (novoStatus === "Realizado" && !tipoHorarioParam) {
      setModalTipoHorario({ id, status: novoStatus });
      return;
    }

    const agendamentoAtual = agendamentos.find((item) => item.id === id);
    if (
      agendamentoAtual?.status === "Expirado" &&
      novoStatus === "Agendado" &&
      (!agendamentoAtual.paciente_id || !agendamentoAtual.tutor_id)
    ) {
      setErro(
        "Antes de confirmar tardiamente, abra a reserva e preencha os dados do tutor e do pet. Depois use 'Agendar após confirmação tardia'."
      );
      return;
    }

    setAtualizandoStatus(id);
    try {
      const enviarAtualizacaoStatus = (
        confirmarReservaExpirada = false,
        confirmarConflitoDeslocamento = false
      ) => {
        const params = new URLSearchParams();
        params.append("status", novoStatus);
        if (tipoHorarioParam) {
          params.append("tipo_horario", tipoHorarioParam);
        }
        if (confirmarReservaExpirada) {
          params.append("confirmar_slot_reserva_expirada", "true");
        }
        if (confirmarConflitoDeslocamento) {
          params.append("confirmar_conflito_deslocamento", "true");
        }
        return api.patch(`/agenda/${id}/status?${params.toString()}`);
      };

      let response;
      let confirmouReservaExpirada = false;
      let confirmouConflitoDeslocamento = false;
      // Uma reativação tardia pode bater em duas confirmações em sequência
      // (reserva expirada e conflito de rota), por isso o retry em laço.
      for (let tentativa = 0; tentativa < 3 && !response; tentativa += 1) {
        try {
          response = await enviarAtualizacaoStatus(
            confirmouReservaExpirada,
            confirmouConflitoDeslocamento
          );
        } catch (errorTentativa: any) {
          const detail = errorTentativa?.response?.data?.detail;
          const codigo =
            errorTentativa?.response?.status === 409 ? detail?.codigo : undefined;
          if (
            !confirmouReservaExpirada &&
            [
              "CONFIRMACAO_SLOT_RESERVA_EXPIRADA",
              "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA",
            ].includes(codigo)
          ) {
            const confirmou = await fortinho.confirm({
              title:
                codigo === "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA"
                  ? "Confirmação recebida após o prazo"
                  : "ATENÇÃO: este horário teve uma reserva expirada",
              message:
                codigo === "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA"
                  ? "Confirme somente se este mesmo cliente respondeu depois do vencimento. O sistema verificará se o horário ainda está livre antes de mudar o status para Agendado."
                  : "Antes de reativar este horário, volte às mensagens do WhatsApp e confira se a clínica enviou os dados do tutor ou do pet após o prazo. Só continue se não houver resposta.",
              mood: "alert",
              gesture: "open-arms",
              confirmLabel:
                codigo === "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA"
                  ? "Cliente confirmou; agendar"
                  : "Revisei as mensagens e quero continuar",
              cancelLabel:
                codigo === "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA"
                  ? "Cancelar"
                  : "Voltar e verificar WhatsApp",
            });
            if (!confirmou) return;
            confirmouReservaExpirada = true;
            continue;
          }
          if (codigo === "CONFLITO_DESLOCAMENTO" && !confirmouConflitoDeslocamento) {
            // Só admin pode abrir exceção de rota; para os demais o erro segue
            // o fluxo normal de exibição.
            if (!isAdmin) throw errorTentativa;
            const confirmou = await fortinho.confirm({
              title: "Conflito de deslocamento na rota",
              message: `${
                typeof detail?.mensagem === "string" ? detail.mensagem : ""
              } Como administrador, você pode abrir uma exceção para este agendamento. Ela fica registrada e vale enquanto horário, clínica e serviço não mudarem.`,
              mood: "alert",
              gesture: "open-arms",
              confirmLabel: "Abrir exceção e continuar",
              cancelLabel: "Voltar e ajustar o horário",
            });
            if (!confirmou) return;
            confirmouConflitoDeslocamento = true;
            continue;
          }
          throw errorTentativa;
        }
      }
      if (!response) return;
      await carregarAgendamentos();
      
      // Se gerou OS, mostra o modal
      if (response.data?.os_gerada) {
        setOsGerada(response.data.os_gerada);
      }
    } catch (error: any) {
      console.error("Erro ao atualizar status:", error);
      const detail = error?.response?.data?.detail;
      const detailTexto =
        typeof detail === "string"
          ? detail
          : (typeof detail?.mensagem === "string" ? detail.mensagem : error.message);
      const mensagemErro = String(detailTexto || "Falha inesperada.");
      const exigeFinalizacaoClinica =
        novoStatus === "Realizado" &&
        error?.response?.status === 409 &&
        mensagemErro.includes("Finalize pelo modulo Atendimento");
      if (exigeFinalizacaoClinica) {
        router.push(`/atendimento?agendamento_id=${id}`);
        return;
      }
      setErro("Erro ao atualizar status: " + mensagemErro);
    } finally {
      setAtualizandoStatus(null);
    }
  };

  const obterLaudoVinculado = (agendamentoId: number, tipo: string) =>
    laudosVinculados[agendamentoId]?.[tipo];

  const obterUltimoLaudoVinculado = (agendamentoId: number) => {
    const laudosDoAgendamento = Object.values(laudosVinculados[agendamentoId] || {});
    return laudosDoAgendamento.reduce<LaudoVinculado | undefined>(
      (maisRecente, atual) => (!maisRecente || atual.id > maisRecente.id ? atual : maisRecente),
      undefined
    );
  };

  const confirmarRealizado = async () => {
    if (!modalTipoHorario) return;
    await atualizarStatus(modalTipoHorario.id, modalTipoHorario.status, tipoHorario);
    setModalTipoHorario(null);
  };

  const abrirModalReabilitarReserva = (agendamento: Agendamento) => {
    setErro("");
    setPrazoReabilitacaoHoras(String(PRAZO_REABILITACAO_HORAS_PADRAO));
    setModalReabilitarReserva(agendamento);
  };

  const confirmarReabilitacaoReserva = async () => {
    const alvo = modalReabilitarReserva;
    if (!alvo) return;

    setErro("");
    const horas = normalizarPrazoReabilitacaoHoras(prazoReabilitacaoHoras);
    if (horas === null) {
      setErro(
        `Informe um prazo entre ${PRAZO_REABILITACAO_HORAS_MIN} e ${PRAZO_REABILITACAO_HORAS_MAX} horas.`
      );
      return;
    }

    setReabilitandoReservaId(alvo.id);
    try {
      const enviarReabilitacao = (
        confirmarSlotReservaExpirada = false,
        confirmarConflitoDeslocamento = false
      ) =>
        api.post(`/agenda/${alvo.id}/reabilitar-reserva`, {
          prazo_confirmacao_horas: horas,
          confirmar_slot_reserva_expirada: confirmarSlotReservaExpirada,
          confirmar_conflito_deslocamento: confirmarConflitoDeslocamento,
        });

      let response;
      let confirmouSlotReservaExpirada = false;
      let confirmouConflitoDeslocamento = false;
      for (let tentativa = 0; tentativa < 3 && !response; tentativa += 1) {
        try {
          response = await enviarReabilitacao(
            confirmouSlotReservaExpirada,
            confirmouConflitoDeslocamento
          );
        } catch (errorTentativa: any) {
          const detail = errorTentativa?.response?.data?.detail;
          const codigo =
            errorTentativa?.response?.status === 409 ? detail?.codigo : undefined;
          if (
            codigo === "CONFIRMACAO_SLOT_RESERVA_EXPIRADA" &&
            !confirmouSlotReservaExpirada
          ) {
            const confirmou = await fortinho.confirm({
              title: "ATENÇÃO: outra reserva expirada neste horário",
              message:
                "Outra clínica também teve uma reserva expirada neste slot. Confira as mensagens do WhatsApp antes de devolver o horário para esta clínica.",
              mood: "alert",
              gesture: "open-arms",
              confirmLabel: "Revisei as mensagens e quero continuar",
              cancelLabel: "Voltar e verificar WhatsApp",
            });
            if (!confirmou) return;
            confirmouSlotReservaExpirada = true;
            continue;
          }
          if (codigo === "CONFLITO_DESLOCAMENTO" && !confirmouConflitoDeslocamento) {
            if (!isAdmin) throw errorTentativa;
            const confirmou = await fortinho.confirm({
              title: "Conflito de deslocamento na rota",
              message: `${
                typeof detail?.mensagem === "string" ? detail.mensagem : ""
              } Como administrador, você pode abrir uma exceção para este agendamento. Ela fica registrada e vale enquanto horário, clínica e serviço não mudarem.`,
              mood: "alert",
              gesture: "open-arms",
              confirmLabel: "Abrir exceção e reabilitar",
              cancelLabel: "Voltar e ajustar o horário",
            });
            if (!confirmou) return;
            confirmouConflitoDeslocamento = true;
            continue;
          }
          throw errorTentativa;
        }
      }
      if (!response) return;

      setModalReabilitarReserva(null);
      setErro("");
      await carregarAgendamentos();
      fortinho.notify({
        title: "Reserva reabilitada",
        message:
          response.data?.mensagem ||
          "O horário voltou a ficar reservado até o novo prazo de confirmação.",
        mood: "happy",
        gesture: "wave",
      });
    } catch (error: any) {
      console.error("Erro ao reabilitar reserva expirada:", error);
      const detail = error?.response?.data?.detail;
      const detailTexto =
        typeof detail === "string"
          ? detail
          : typeof detail?.mensagem === "string"
            ? detail.mensagem
            : error?.message;
      setErro("Erro ao reabilitar reserva: " + String(detailTexto || "Falha inesperada."));
    } finally {
      setReabilitandoReservaId(null);
    }
  };

  const cancelarAgendamento = async (id: number) => {
    try {
      await api.patch(`/agenda/${id}/status?status=Cancelado`);
      setConfirmando(null);
      await carregarAgendamentos();
    } catch (error: any) {
      console.error("Erro ao cancelar:", error);
      setErro("Erro ao cancelar agendamento");
    }
  };

  const excluirAgendamento = async (id: number) => {
    try {
      await api.delete(`/agenda/${id}`);
      setConfirmando(null);
      await carregarAgendamentos();
    } catch (error: any) {
      console.error("Erro ao excluir:", error);
      if (error.response?.status === 403) {
        setErro("Apenas administradores e a equipe de recepção podem excluir agendamentos");
      } else {
        setErro("Erro ao excluir agendamento");
      }
    }
  };

  const getRotaNovoLaudo = (tipo: string, agendamentoId: number) => {
    if (tipo === TIPO_LAUDO_ELETROCARDIOGRAMA) {
      return `/laudos/eletrocardiograma/upload?agendamento_id=${agendamentoId}`;
    }
    if (tipo === TIPO_LAUDO_PRESSAO_ARTERIAL) {
      return `/laudos/novo?agendamento_id=${agendamentoId}&tipo=${TIPO_LAUDO_PRESSAO_ARTERIAL}`;
    }
    const basePath =
      tipo === TIPO_LAUDO_ULTRASSOM_ABDOMINAL ? "/ultrassonografia-abdominal/novo" : "/laudos/novo";
    return `${basePath}?agendamento_id=${agendamentoId}`;
  };

  const abrirFluxoLaudo = (ag: Agendamento, tipo: string) => {
    const laudoVinculado = obterLaudoVinculado(ag.id, tipo);
    if (laudoVinculado?.id) {
      router.push(getLaudoEditPath(laudoVinculado.id, tipo));
      return;
    }
    router.push(getRotaNovoLaudo(tipo, ag.id));
  };

  const abrirFluxoAtendimento = (ag: Agendamento) => {
    router.push(`/atendimento?agendamento_id=${ag.id}`);
  };

  const podeBaixarLaudo = (status?: string) => {
    const statusNormalizado = (status || "").trim().toLowerCase();
    return statusNormalizado === "finalizado" || statusNormalizado === "arquivado";
  };

  const baixarLaudoPdf = async (ag: Agendamento) => {
    const laudoVinculado = obterUltimoLaudoVinculado(ag.id);
    if (!laudoVinculado?.id) return;

    try {
      if (laudoVinculado.tipo === TIPO_LAUDO_ELETROCARDIOGRAMA) {
        await baixarLaudoPdfOriginal(laudoVinculado.id, `eletrocardiograma_agendamento_${ag.id}.pdf`);
        return;
      }
      await baixarLaudoPdfUtil(laudoVinculado.id, `laudo_agendamento_${ag.id}.pdf`);
    } catch (error) {
      console.error("Erro ao baixar PDF do laudo:", error);
      alert("Nao foi possivel baixar o laudo agora.");
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      'Agendado': 'bg-blue-100 text-blue-800 border-blue-200',
      'Reservado': 'bg-amber-100 text-amber-800 border-amber-200',
      'Confirmado': 'bg-green-100 text-green-800 border-green-200',
      'Em atendimento': 'bg-yellow-100 text-yellow-800 border-yellow-200',
      'Realizado': 'bg-emerald-100 text-emerald-800 border-emerald-200',
      'Cancelado': 'bg-red-100 text-red-800 border-red-200',
      'Faltou': 'bg-orange-100 text-orange-800 border-orange-200',
      'Expirado': 'bg-slate-100 text-slate-700 border-slate-300',
    };
    return colors[status] || 'bg-gray-100 text-gray-800 border-gray-200';
  };

  const getStatusIcon = (status: string) => {
    const icons: Record<string, any> = {
      'Agendado': Calendar,
      'Reservado': Clock,
      'Confirmado': CheckCircle2,
      'Em atendimento': PlayCircle,
      'Realizado': CheckCircle,
      'Cancelado': XCircle,
      'Faltou': AlertCircle,
      'Expirado': AlertCircle,
    };
    return icons[status] || Calendar;
  };

  const getOrdenacaoTimestamp = (ag: Agendamento) => {
    const inicioLocal = parseAgendamentoInicioLocal(ag);
    if (inicioLocal) return inicioLocal.getTime();
    return Number.MAX_SAFE_INTEGER;
  };

  const agendamentosFiltrados = [...agendamentos]
    .filter((a) => {
      const matchStatus = filtroStatus === "todos" || a.status === filtroStatus;
      const origemAtual = String(a.origem_atendimento || "clinica_parceira").trim() || "clinica_parceira";
      const matchOrigem =
        filtroOrigemAtendimento === "todos" || origemAtual === filtroOrigemAtendimento;
      const termo = busca.toLowerCase();
      const matchBusca = !busca ||
        (a.paciente?.toLowerCase().includes(termo)) ||
        (a.tutor?.toLowerCase().includes(termo)) ||
        (a.clinica?.toLowerCase().includes(termo)) ||
        (a.servico?.toLowerCase().includes(termo));
      return matchStatus && matchOrigem && matchBusca;
    })
    .sort((a, b) => {
      const diff = getOrdenacaoTimestamp(a) - getOrdenacaoTimestamp(b);
      if (diff !== 0) return diff;
      return a.id - b.id;
    });

  const diasPanoramica = useMemo(() => {
    const dataBase = filtroData || hojeLocal();

    if (modoVisualizacao === "panoramica-semana") {
      const inicioSemana = inicioDaSemana(dataBase);
      return Array.from({ length: 7 }, (_, idx) => {
        const data = new Date(inicioSemana);
        data.setDate(inicioSemana.getDate() + idx);
        return toDateInput(data);
      });
    }

    return [dataBase];
  }, [filtroData, modoVisualizacao]);

  const jornadaPanoramicaPorDia = useMemo(() => {
    const mapa = new Map<string, ReturnType<typeof obterJornadaDia>>();
    for (const dia of diasPanoramica) {
      mapa.set(dia, obterJornadaDia(dia, agendaSemanal, agendaFeriados, agendaExcecoes));
    }
    return mapa;
  }, [diasPanoramica, agendaSemanal, agendaFeriados, agendaExcecoes]);

  const intervaloSlotMinutos = useMemo(() => {
    const parsed = Number(renderingPolicy.slot_interval_min);
    if (!Number.isFinite(parsed)) return SLOT_INTERVALO_PADRAO_MIN;
    return Math.max(5, Math.min(120, Math.round(parsed)));
  }, [renderingPolicy.slot_interval_min]);

  const slotsPanoramica = useMemo(() => {
    const inicioConfigMin = horarioParaMinutos(renderingPolicy.window_start);
    const fimConfigMin = horarioParaMinutos(renderingPolicy.window_end);
    const janelaCustomValida =
      Boolean(renderingPolicy.use_custom_window) &&
      inicioConfigMin !== null &&
      fimConfigMin !== null &&
      fimConfigMin > inicioConfigMin;

    if (janelaCustomValida) {
      return gerarSlots(inicioConfigMin, fimConfigMin, intervaloSlotMinutos);
    }

    let inicioMin = Number.POSITIVE_INFINITY;
    let fimMin = 0;

    for (const dia of diasPanoramica) {
      const jornada = jornadaPanoramicaPorDia.get(dia);
      if (!jornada || jornada.fechado) continue;
      const minDiaInicio = horarioParaMinutos(jornada.inicio);
      const minDiaFim = horarioParaMinutos(jornada.fim);
      if (minDiaInicio === null || minDiaFim === null) continue;
      inicioMin = Math.min(inicioMin, minDiaInicio);
      fimMin = Math.max(fimMin, minDiaFim);
    }

    if (!Number.isFinite(inicioMin) || fimMin <= inicioMin) {
      const fallbackInicio = horarioParaMinutos(DEFAULT_AGENDA_SEMANAL["1"].inicio) ?? 8 * 60;
      const fallbackFim = horarioParaMinutos(DEFAULT_AGENDA_SEMANAL["1"].fim) ?? 14 * 60;
      return gerarSlots(fallbackInicio, fallbackFim, intervaloSlotMinutos);
    }

    return gerarSlots(inicioMin, fimMin, intervaloSlotMinutos);
  }, [diasPanoramica, intervaloSlotMinutos, jornadaPanoramicaPorDia, renderingPolicy]);

  const mapaOcupacao = useMemo(() => {
    const mapa = new Map<string, Agendamento[]>();

    for (const ag of agendamentosFiltrados) {
      // Cancelado ou expirado não deve ocupar slot na panorâmica.
      if (["cancelado", "expirado"].includes((ag.status || "").trim().toLowerCase())) continue;

      const inicio = parseAgendamentoInicioLocal(ag);
      if (!inicio) continue;

      const fim = parseAgendamentoFimLocal(ag, inicio);

      const cursor = new Date(inicio);
      cursor.setSeconds(0, 0);
      cursor.setMinutes(Math.floor(cursor.getMinutes() / intervaloSlotMinutos) * intervaloSlotMinutos);

      while (cursor < fim) {
        const chave = `${toDateInput(cursor)}|${toTimeInput(cursor)}`;
        const existentes = mapa.get(chave) || [];
        existentes.push(ag);
        mapa.set(chave, existentes);
        cursor.setMinutes(cursor.getMinutes() + intervaloSlotMinutos);
      }
    }

    return mapa;
  }, [agendamentosFiltrados, intervaloSlotMinutos]);

  const formatarDiaPanoramica = (data: string) => {
    const dt = parseDateInput(data);
    return dt.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" });
  };

  const abrirNovoNoHorario = (data: string, hora: string) => {
    const jornada = jornadaPanoramicaPorDia.get(data);
    if ((!jornada || !slotDentroDaJornada(hora, jornada)) && !isAdmin) {
      setErro(jornada?.motivo || "Agenda fechada para este horario.");
      return;
    }
    setErro("");
    setAgendamentoEditando(null);
    setSlotSelecionado({ data, hora });
    setModalAberto(true);
  };

  const stats = {
    total: agendamentos.length,
    agendado: agendamentos.filter(a => a.status === 'Agendado').length,
    reservado: agendamentos.filter(a => a.status === 'Reservado').length,
    confirmado: agendamentos.filter(a => a.status === 'Confirmado').length,
    emAtendimento: agendamentos.filter(a => a.status === 'Em atendimento').length,
    realizado: agendamentos.filter(a => a.status === 'Realizado').length,
    cancelado: agendamentos.filter(a => a.status === 'Cancelado').length,
  };

  const reservasEmAlerta = agendamentos
    .map((agendamento) => ({
      agendamento,
      prazo: obterEstadoPrazoReserva(agendamento, agoraReservas),
    }))
    .filter(
      (item): item is { agendamento: Agendamento; prazo: ReservaPrazoEstado } =>
        Boolean(item.prazo?.emAlerta)
    )
    .sort((a, b) => a.prazo.minutosRestantes - b.prazo.minutosRestantes);
  const existeReservaCritica = reservasEmAlerta.some((item) => item.prazo.critico);

  const formatarDataHora = (dataIso: string) => {
    if (!dataIso) return "-";
    const normalizado = dataIso.includes("T") ? dataIso : dataIso.replace(" ", "T");
    const data = new Date(normalizado);
    if (Number.isNaN(data.getTime())) {
      return dataIso;
    }
    return data.toLocaleString('pt-BR', { 
      day: '2-digit', 
      month: '2-digit', 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  };

  const formatarMoedaBRL = (valor: number) => {
    return Number(valor || 0).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
      minimumFractionDigits: 2,
    });
  };

  const navegarData = (dias: number) => {
    const data = parseDateInput(filtroData);
    data.setDate(data.getDate() + dias);
    setFiltroData(toDateInput(data));
  };

  const limparFiltrosAgenda = () => {
    const hoje = hojeLocal();
    setFiltroStatus("todos");
    setBusca("");
    setFiltroPacienteNome("");
    setFiltroTutorNome("");
    setFiltroOrigemAtendimento("todos");
    setFiltroClinicaId("todos");
    setFiltroServicoId("todos");
    setFiltroPeriodoInicio(hoje);
    setFiltroPeriodoFim(hoje);
    setFiltroData(hoje);
  };

  const formatarDataHoraAgendamento = (ag: Agendamento) => {
    if (ag.data && ag.hora) {
      const [ano, mes, dia] = String(ag.data).split("-");
      const hora = String(ag.hora).slice(0, 5);
      if (ano && mes && dia && hora) {
        return `${dia}/${mes}, ${hora}`;
      }
    }
    return formatarDataHora(ag.inicio);
  };

  const handleAgendamentoSuccess = async (agendamentoCriado?: { data?: string | null }) => {
    setSlotSelecionado(null);
    const dataCriada = agendamentoCriado?.data || "";
    if (dataCriada && modoVisualizacao === "lista") {
      setFiltroPeriodoInicio(dataCriada);
      setFiltroPeriodoFim(dataCriada);
      return;
    }
    if (dataCriada && dataCriada !== filtroData) {
      setFiltroData(dataCriada);
      return;
    }
    await carregarAgendamentos();
  };

  const dataResumoFinanceiro = filtroData || hojeLocal();
  const resumoPeriodoInicio = periodoConsulta.inicio || dataResumoFinanceiro;
  const resumoPeriodoFim = periodoConsulta.fim || resumoPeriodoInicio;
  const resumoInicioLabel = parseDateInput(resumoPeriodoInicio).toLocaleDateString("pt-BR");
  const resumoFimLabel = parseDateInput(resumoPeriodoFim).toLocaleDateString("pt-BR");
  const resumoPeriodoEhDia = resumoPeriodoInicio === resumoPeriodoFim;
  const dataResumoFinanceiroLabel = resumoPeriodoEhDia
    ? resumoInicioLabel
    : `${resumoInicioLabel} a ${resumoFimLabel}`;

  return (
    <DashboardLayout>
      <div className="fc-agenda-page">
        {(toastRealtime || erro) && (
          <div className="pointer-events-none fixed inset-x-4 top-[calc(env(safe-area-inset-top)+4.5rem)] z-[80] flex flex-col gap-2 sm:left-auto sm:w-[28rem] lg:top-16">
            {erro && (
              <div role="alert" className="pointer-events-auto flex max-h-[35dvh] items-start gap-3 overflow-y-auto rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 shadow-xl">
                <span className="min-w-0 flex-1 break-words">{erro}</span>
                <button
                  type="button"
                  onClick={() => setErro("")}
                  aria-label="Fechar aviso de erro"
                  className="shrink-0 rounded p-1 text-red-700 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            )}
            {toastRealtime && (
              <div className={`pointer-events-auto flex items-center gap-3 rounded-lg border px-3 py-2 text-xs shadow-lg ${toastRealtime.classe}`}>
                <span className="min-w-0 flex-1 font-medium">{toastRealtime.texto}</span>
                {typeof toastRealtime.agendamentoId === "number" && (
                  <button
                    type="button"
                    onClick={() => abrirAgendamentoDoToast(toastRealtime.agendamentoId as number)}
                    className="rounded-md border border-current/30 px-2 py-1 text-[11px] font-semibold hover:bg-white/40 transition-colors"
                  >
                    Abrir
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* Header */}
        <div className="fc-agenda-header">
          <div>
            <span className="fc-agenda-kicker">
              <Calendar className="h-4 w-4" />
              Central de agenda
            </span>
            <h1>Fluxo clínico</h1>
            <p>Organize horários, deslocamentos e etapas do atendimento em uma única visão.</p>
          </div>
          <div className="fc-agenda-header-actions">
            <button
              type="button"
              onClick={abrirAgendaFullCalendar}
              className="fc-agenda-button-secondary"
            >
              <Calendar className="h-4 w-4" />
              Calendário completo
            </button>
            <button
              onClick={() => {
                setAgendamentoEditando(null);
                setSlotSelecionado(null);
                setModalAberto(true);
              }}
              className="fc-agenda-button-primary"
            >
              <Plus className="w-4 h-4" />
              Novo Agendamento
            </button>
          </div>
        </div>

        <div
          className={`fc-agenda-livebar ${
            realtimeConectado
              ? "fc-agenda-livebar-online"
              : "fc-agenda-livebar-warning"
          }`}
        >
          <span className="fc-agenda-live-dot" />
          Tempo real: {realtimeConectado ? "conectado" : "reconectando..."}
          {realtimeUltimoEvento ? ` | Ultimo evento: ${realtimeUltimoEvento}` : ""}
          {mensagemRealtime ? ` | ${mensagemRealtime}` : ""}
        </div>

        {/* Stats Cards */}
        <div className="fc-agenda-stats">
          <div className="fc-agenda-stat fc-agenda-stat-ink">
            <div className="fc-agenda-stat-value">{stats.total}</div>
            <div className="fc-agenda-stat-label">Total</div>
          </div>
          <div className="fc-agenda-stat fc-agenda-stat-sky">
            <div className="fc-agenda-stat-value">{stats.agendado}</div>
            <div className="fc-agenda-stat-label">Agendados</div>
          </div>
          <div className="fc-agenda-stat fc-agenda-stat-amber">
            <div className="fc-agenda-stat-value">{stats.reservado}</div>
            <div className="fc-agenda-stat-label">Reservados</div>
          </div>
          <div className="fc-agenda-stat fc-agenda-stat-vital">
            <div className="fc-agenda-stat-value">{stats.confirmado}</div>
            <div className="fc-agenda-stat-label">Confirmados</div>
          </div>
          <div className="fc-agenda-stat fc-agenda-stat-gold">
            <div className="fc-agenda-stat-value">{stats.emAtendimento}</div>
            <div className="fc-agenda-stat-label">Em atendimento</div>
          </div>
          <div className="fc-agenda-stat fc-agenda-stat-emerald">
            <div className="fc-agenda-stat-value">{stats.realizado}</div>
            <div className="fc-agenda-stat-label">Realizados</div>
          </div>
          <div className="fc-agenda-stat fc-agenda-stat-cordis">
            <div className="fc-agenda-stat-value">{stats.cancelado}</div>
            <div className="fc-agenda-stat-label">Cancelados</div>
          </div>
        </div>

        {isAdmin && modoVisualizacao === "lista" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div className="fc-agenda-finance-card fc-agenda-finance-card-vital">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">
                    {resumoPeriodoEhDia ? "Realizado no dia" : "Realizado no período"}
                  </p>
                  <p className="text-2xl font-bold text-emerald-600">
                    {carregandoResumoFinanceiro
                      ? "Carregando..."
                      : erroResumoFinanceiro
                        ? "Indisponivel"
                      : formatarMoedaBRL(resumoFinanceiro?.valor_realizado || 0)}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {erroResumoFinanceiro
                      ? `Nao foi possivel carregar o resumo de ${dataResumoFinanceiroLabel}`
                      : `${resumoFinanceiro?.qtd_realizados || 0} atendimento(s) realizado(s) em ${dataResumoFinanceiroLabel}`}
                  </p>
                </div>
                <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
                  <DollarSign className="w-5 h-5" />
                </div>
              </div>
            </div>

            <div className="fc-agenda-finance-card fc-agenda-finance-card-sky">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">
                    {resumoPeriodoEhDia ? "Previsao do agendado" : "Previsao do agendado no período"}
                  </p>
                  <p className="text-2xl font-bold text-blue-600">
                    {carregandoResumoFinanceiro
                      ? "Carregando..."
                      : erroResumoFinanceiro
                        ? "Indisponivel"
                      : formatarMoedaBRL(resumoFinanceiro?.valor_agendado || 0)}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {erroResumoFinanceiro
                      ? `Nao foi possivel carregar o resumo de ${dataResumoFinanceiroLabel}`
                      : `${resumoFinanceiro?.qtd_agendados || 0} atendimento(s) agendado(s) em ${dataResumoFinanceiroLabel}`}
                  </p>
                </div>
                <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
                  <DollarSign className="w-5 h-5" />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Filtros */}
        {reservasEmAlerta.length > 0 && (
          <div
            className={`mb-5 rounded-2xl border-2 p-4 shadow-sm ${
              existeReservaCritica
                ? "border-red-500 bg-red-50 text-red-950"
                : "border-amber-400 bg-amber-50 text-amber-950"
            }`}
            role="alert"
            aria-live="assertive"
          >
            <div className="flex items-start gap-3">
              <AlertCircle
                className={`mt-0.5 h-7 w-7 shrink-0 ${
                  existeReservaCritica ? "text-red-600 animate-pulse" : "text-amber-600"
                }`}
              />
              <div className="min-w-0 flex-1">
                <h2 className="text-lg font-black uppercase tracking-wide">
                  Ação necessária: {reservasEmAlerta.length} reserva(s) perto de expirar
                </h2>
                <p className="mt-1 font-semibold">
                  Reforce agora com a clínica a necessidade de enviar os dados do tutor e do pet.
                  Se o prazo vencer, o horário voltará a ficar disponível.
                </p>
                <div className="mt-3 grid gap-2">
                  {reservasEmAlerta.slice(0, 5).map(({ agendamento, prazo }) => (
                    <div
                      key={agendamento.id}
                      className="flex flex-col gap-2 rounded-xl border border-current/20 bg-white/70 p-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div>
                        <div className="font-bold">
                          {agendamento.clinica || "Clínica não informada"} — {formatarDataHoraAgendamento(agendamento)}
                        </div>
                        <div className="text-sm">
                          Pet: {agendamento.paciente || "Pendente"} | Tutor: {agendamento.tutor || "Pendente"}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full px-3 py-1 text-sm font-black uppercase ${
                            prazo.critico ? "bg-red-600 text-white animate-pulse" : "bg-amber-500 text-white"
                          }`}
                        >
                          {prazo.label}
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            setAgendamentoEditando(agendamento);
                            setSlotSelecionado(null);
                            setModalAberto(true);
                          }}
                          className="rounded-lg border border-current px-3 py-1 text-sm font-bold hover:bg-white"
                        >
                          Abrir reserva
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="fc-agenda-filters">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 2xl:flex-row 2xl:items-center">
            <div className="fc-agenda-view-tabs">
              <button
                onClick={() => setModoVisualizacao("lista")}
                className={`fc-agenda-view-tab ${modoVisualizacao === "lista" ? "fc-agenda-view-tab-active" : ""}`}
              >
                Lista
              </button>
              <button
                onClick={() => setModoVisualizacao("panoramica-dia")}
                className={`fc-agenda-view-tab ${modoVisualizacao === "panoramica-dia" ? "fc-agenda-view-tab-active" : ""}`}
              >
                Panoramica Dia
              </button>
              <button
                onClick={() => setModoVisualizacao("panoramica-semana")}
                className={`fc-agenda-view-tab ${modoVisualizacao === "panoramica-semana" ? "fc-agenda-view-tab-active" : ""}`}
              >
                Panoramica Semana
              </button>
            </div>
              {modoVisualizacao === "lista" ? (
                <div className="flex flex-col sm:flex-row gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">De</span>
                    <input
                      type="date"
                      value={filtroPeriodoInicio}
                      onChange={(e) => {
                        const novaDataInicio = e.target.value || hojeLocal();
                        setFiltroPeriodoInicio(novaDataInicio);
                        setFiltroPeriodoFim(novaDataInicio);
                      }}
                      className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Ate</span>
                    <input
                      type="date"
                      value={filtroPeriodoFim}
                      min={filtroPeriodoInicio || undefined}
                      onChange={(e) => setFiltroPeriodoFim(e.target.value || filtroPeriodoInicio || hojeLocal())}
                      className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <button 
                    onClick={() => navegarData(modoVisualizacao === "panoramica-semana" ? -7 : -1)}
                    className="p-2 hover:bg-gray-100 rounded-lg"
                  >
                    <ChevronLeft className="w-5 h-5" />
                  </button>
                  <input
                    type="date"
                    value={filtroData}
                    onChange={(e) => setFiltroData(e.target.value || hojeLocal())}
                    className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                  <button 
                    onClick={() => navegarData(modoVisualizacao === "panoramica-semana" ? 7 : 1)}
                    className="p-2 hover:bg-gray-100 rounded-lg"
                  >
                    <ChevronRight className="w-5 h-5" />
                  </button>
                </div>
              )}

              {/* Busca local rápida */}
              <div className="flex-1 relative min-w-[220px]">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  placeholder="Busca local nos resultados..."
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Filtro status */}
              <select
                value={filtroStatus}
                onChange={(e) => setFiltroStatus(e.target.value)}
                className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="todos">Todos os status</option>
                {AGENDA_STATUS_LIST.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>

              <select
                value={filtroOrigemAtendimento}
                onChange={(e) => setFiltroOrigemAtendimento(e.target.value)}
                className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="todos">Todas as origens</option>
                <option value="clinica_parceira">Clinica parceira</option>
                <option value="domiciliar">Atendimento domiciliar</option>
              </select>

              <button
                onClick={() => carregarAgendamentos()}
                className="flex items-center justify-center gap-2 px-4 py-2 text-gray-600 hover:text-gray-900 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                Atualizar
              </button>
            </div>

            {modoVisualizacao === "lista" && (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                <input
                  type="text"
                  placeholder="Filtrar por animal"
                  value={filtroPacienteNome}
                  onChange={(e) => setFiltroPacienteNome(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                />
                <input
                  type="text"
                  placeholder="Filtrar por tutor"
                  value={filtroTutorNome}
                  onChange={(e) => setFiltroTutorNome(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                />
                <select
                  value={filtroClinicaId}
                  onChange={(e) => setFiltroClinicaId(e.target.value)}
                  onFocus={() => void carregarOpcoesClinicasFiltro()}
                  onPointerDown={() => void carregarOpcoesClinicasFiltro()}
                  aria-busy={carregandoClinicasFiltro}
                  className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="todos">
                    {carregandoClinicasFiltro ? "Carregando clinicas..." : "Todas as clinicas"}
                  </option>
                  {opcoesClinicas.map((clinica) => (
                    <option key={clinica.id} value={String(clinica.id)}>
                      {clinica.nome}
                    </option>
                  ))}
                </select>
                <select
                  value={filtroServicoId}
                  onChange={(e) => setFiltroServicoId(e.target.value)}
                  onFocus={() => void carregarOpcoesServicosFiltro()}
                  onPointerDown={() => void carregarOpcoesServicosFiltro()}
                  aria-busy={carregandoServicosFiltro}
                  className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="todos">
                    {carregandoServicosFiltro ? "Carregando servicos..." : "Todos os servicos"}
                  </option>
                  {opcoesServicos.map((servico) => (
                    <option key={servico.id} value={String(servico.id)}>
                      {servico.nome}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {modoVisualizacao === "lista" && (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => carregarAgendamentos()}
                  className="px-3 py-1.5 text-sm text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg"
                >
                  Aplicar filtros
                </button>
                <button
                  type="button"
                  onClick={limparFiltrosAgenda}
                  className="px-3 py-1.5 text-sm text-gray-700 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-lg"
                >
                  Limpar filtros
                </button>
                <span className="text-xs text-gray-500">
                  Periodo ativo: {periodoConsulta.inicio} ate {periodoConsulta.fim}
                </span>
              </div>
            )}

            {modoVisualizacao === "lista" && (
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-gray-600">
                    Estado da agenda no periodo
                  </span>
                  <span className="text-xs text-gray-500">
                    {periodoConsulta.inicio} ate {periodoConsulta.fim}
                  </span>
                </div>

                {alertasAgendaLista.length === 0 ? (
                  <p className="text-sm text-emerald-700">
                    Sem fechamentos ou janelas especiais no periodo selecionado.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {alertasAgendaLista.map((alerta) => {
                      const dataLabel = parseDateInput(alerta.data).toLocaleDateString("pt-BR", {
                        weekday: "short",
                        day: "2-digit",
                        month: "2-digit",
                      });
                      const fechado = alerta.tipo === "fechada";
                      return (
                        <div
                          key={`${alerta.data}-${alerta.tipo}`}
                          className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                            fechado
                              ? "border-red-200 bg-red-50 text-red-700"
                              : "border-amber-200 bg-amber-50 text-amber-700"
                          }`}
                          title={alerta.motivo}
                        >
                          <strong className="mr-1">{dataLabel}</strong>
                          {fechado ? "Agenda fechada" : "Janela especial"} ({alerta.inicio} as {alerta.fim})
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Chips de status */}
          <div className="fc-agenda-status-strip">
            {AGENDA_STATUS_LIST.map((status) => {
              const count = agendamentos.filter(a => a.status === status).length;
              return (
                <button
                  key={status}
                  onClick={() => setFiltroStatus(filtroStatus === status ? "todos" : status)}
                  className={`fc-agenda-status-chip ${
                    filtroStatus === status
                      ? getStatusColor(status)
                      : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  {status} {count > 0 && `(${count})`}
                </button>
              );
            })}
          </div>
        </div>

        {modoVisualizacao === "lista" ? (
        <div className="fc-agenda-list">
          {agendamentosFiltrados.length === 0 ? (
            <div className="fc-agenda-empty">
              <div className="fc-agenda-empty-icon">
                <Calendar className="h-6 w-6" />
              </div>
              <span>Agenda em repouso</span>
              <p>
                {busca ? "Nenhum agendamento encontrado para a busca" : "Nenhum agendamento para esta data"}
              </p>
              <button
                onClick={() => { setAgendamentoEditando(null); setSlotSelecionado(null); setModalAberto(true); }}
                className="fc-agenda-button-primary mt-5"
              >
                <Plus className="h-4 w-4" />
                Criar Agendamento
              </button>
            </div>
          ) : (
            <div className="divide-y divide-gray-200">
              {agendamentosFiltrados.map((ag) => {
                const StatusIcon = getStatusIcon(ag.status);
                const proximosStatus = obterProximosStatus(ag.status);
                const acoesStatus = obterAcoesStatusPorFluxo(ag.status);
                const laudoVinculado = obterUltimoLaudoVinculado(ag.id);
                const laudoPronto = podeBaixarLaudo(laudoVinculado?.status);
                const laudoEco = obterLaudoVinculado(ag.id, TIPO_LAUDO_ECOCARDIOGRAMA);
                const laudoEletro = obterLaudoVinculado(ag.id, TIPO_LAUDO_ELETROCARDIOGRAMA);
                const osVinculada = ordensServicoPorAgendamento[ag.id];
                const osPaga = osEstaPaga(osVinculada?.status);
                const origemMeta = obterOrigemAtendimentoMeta(ag.origem_atendimento);
                const tituloAgendamento = obterTituloAgendamentoPorOrigem(ag.origem_atendimento, ag.clinica);
                const atendimentoDomiciliar =
                  String(ag.origem_atendimento || "").trim().toLowerCase() === "domiciliar";
                const destinoNavegacao = atendimentoDomiciliar
                  ? (ag.tutor_id ? tutoresEndereco[ag.tutor_id] : undefined)
                  : (ag.clinica_id ? clinicasEndereco[ag.clinica_id] : undefined);
                const nomeDestinoNavegacao = atendimentoDomiciliar
                  ? (ag.tutor || "atendimento domiciliar")
                  : (ag.clinica || "clinica");
                const podeAbrirWaze = Boolean(montarWazeDestinoLocal(destinoNavegacao));
                const podeAbrirGoogleMaps = Boolean(montarGoogleMapsDestinoLocal(destinoNavegacao));
                const prazoReserva = obterEstadoPrazoReserva(ag, agoraReservas);
                const reservaEmAlerta = Boolean(prazoReserva?.emAlerta);
                const podeAbrirClienteModal = Boolean(ag.paciente_id || ag.tutor_id);
                const abrirClienteModal = () => {
                  if (ag.paciente_id) {
                    setClienteModalAlvo({ pacienteId: ag.paciente_id });
                  } else if (ag.tutor_id) {
                    setClienteModalAlvo({ tutorId: ag.tutor_id });
                  }
                };

                return (
                  <div
                    key={ag.id}
                    className={`fc-agenda-list-row ${
                      reservaEmAlerta
                        ? prazoReserva?.critico
                          ? "ring-2 ring-red-500 bg-red-50/70"
                          : "ring-2 ring-amber-400 bg-amber-50/70"
                        : ""
                    }`}
                  >
                    <div className="flex flex-col lg:flex-row lg:justify-between lg:items-start gap-4">
                      {/* Info Principal */}
                      <div className="flex-1">
                        <div className="flex items-center gap-3 mb-1 flex-wrap">
                          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                            <Building className="w-4 h-4 text-gray-400" />
                            {tituloAgendamento}
                          </h3>
                          <span className={origemMeta.badgeClassName}>{origemMeta.descricao}</span>
                          <span className={`inline-flex items-center gap-2 rounded-lg border-2 px-3 py-1.5 text-sm font-semibold ${getStatusColor(ag.status)}`}>
                            <StatusIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                            <span>Status atual: {ag.status}</span>
                          </span>
                          {osPaga && (
                            <span
                              className="px-3 py-1 rounded-full text-xs font-medium border flex items-center gap-1 bg-emerald-50 text-emerald-700 border-emerald-200"
                              title={osVinculada?.numero_os ? `OS ${osVinculada.numero_os} ja recebida no financeiro` : "OS recebida no financeiro"}
                            >
                              <CheckCircle2 className="w-3 h-3" />
                              Pago
                            </span>
                          )}
                        </div>

                        {reservaEmAlerta && prazoReserva && (
                          <div
                            className={`mb-3 flex items-start gap-2 rounded-xl border-2 p-3 font-bold ${
                              prazoReserva.critico
                                ? "border-red-500 bg-red-100 text-red-900"
                                : "border-amber-400 bg-amber-100 text-amber-900"
                            }`}
                            role="alert"
                          >
                            <AlertCircle
                              className={`mt-0.5 h-5 w-5 shrink-0 ${
                                prazoReserva.critico ? "animate-pulse" : ""
                              }`}
                            />
                            <div>
                              <div className="uppercase">
                                Atenção: esta reserva {prazoReserva.label}
                              </div>
                              <div className="text-sm font-semibold">
                                Reforce agora o envio dos dados do tutor e do pet para evitar a perda do horário.
                              </div>
                            </div>
                          </div>
                        )}

                        <div className="text-base font-semibold text-gray-900 mb-2">
                          {podeAbrirClienteModal ? (
                            <button
                              type="button"
                              onClick={abrirClienteModal}
                              className="text-left hover:text-blue-700 hover:underline"
                              title="Ver e editar dados do cliente"
                            >
                              {ag.paciente || "Animal nao informado"}
                            </button>
                          ) : (
                            ag.paciente || "Animal nao informado"
                          )}
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-sm text-gray-600">
                          <div className="flex items-center gap-2">
                            <User className="w-4 h-4 text-gray-400" />
                            {podeAbrirClienteModal ? (
                              <button
                                type="button"
                                onClick={abrirClienteModal}
                                className="hover:text-blue-700 hover:underline"
                                title="Ver e editar dados do cliente"
                              >
                                {ag.tutor || "Tutor nao informado"}
                              </button>
                            ) : (
                              <span>{ag.tutor || "Tutor nao informado"}</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <Clock className="w-4 h-4 text-gray-400" />
                            <span className="font-medium">{formatarDataHoraAgendamento(ag)}</span>
                          </div>
                          {ag.servico && (
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-gray-700">{ag.servico}</span>
                            </div>
                          )}
                        </div>

                        {ag.observacoes && (
                          <div className="mt-3 text-sm text-gray-500 bg-gray-50 p-2 rounded">
                            <span className="font-medium">Obs:</span> {ag.observacoes}
                          </div>
                        )}
                      </div>

                      {/* Ações */}
                      <div className="flex flex-wrap gap-2 lg:flex-[1.5_1_0%] lg:justify-end">
                        {(podeReabilitarReserva(ag.status) || proximosStatus.length > 0) && (
                          <div
                            role="group"
                            aria-label={`Alterar status do agendamento de ${ag.paciente || "animal não informado"}`}
                            className="w-full rounded-xl border border-slate-300 bg-slate-50 p-3"
                          >
                            <div className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-600">
                              Alterar status
                            </div>
                            <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
                              {/* Reserva expirada pode ser reabilitada sem preencher os dados do paciente agora. */}
                              {podeReabilitarReserva(ag.status) && (
                                <button
                                  type="button"
                                  onClick={() => abrirModalReabilitarReserva(ag)}
                                  disabled={reabilitandoReservaId === ag.id}
                                  title="Reservar este horário novamente por mais um período"
                                  className="col-span-2 inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 shadow-sm transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60 sm:col-span-1"
                                >
                                  {reabilitandoReservaId === ag.id ? (
                                    <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                                  ) : (
                                    <TimerReset className="h-4 w-4" aria-hidden="true" />
                                  )}
                                  Reabilitar reserva
                                </button>
                              )}

                              {proximosStatus.map((novoStatus) => {
                                const desfazerRealizado = ag.status === 'Realizado' && novoStatus === 'Em atendimento';
                                const Icon = desfazerRealizado ? Undo2 : getStatusIcon(novoStatus);
                                const actionLabel = desfazerRealizado
                                  ? "Desfazer realizado"
                                  : acoesStatus.find((acao) => acao.status === novoStatus)?.label || novoStatus;

                                return (
                                  <button
                                    key={novoStatus}
                                    type="button"
                                    onClick={() => atualizarStatus(ag.id, novoStatus)}
                                    disabled={atualizandoStatus === ag.id}
                                    className={`inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 shadow-sm transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60 ${proximosStatus.length === 1 ? "col-span-2 sm:col-span-1" : ""}`}
                                  >
                                    {atualizandoStatus === ag.id ? (
                                      <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                                    ) : (
                                      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                                    )}
                                    {actionLabel}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {osVinculada && (
                          <button
                            onClick={() => abrirRecebimentoPagamentoModal(ag.id)}
                            disabled={osPaga || recebendoPagamentoId === ag.id}
                            className={`px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center gap-1 ${
                              osPaga
                                ? "text-emerald-700 bg-emerald-50 border border-emerald-200 cursor-not-allowed"
                                : "text-orange-700 hover:text-orange-900 hover:bg-orange-50 border border-orange-200"
                            }`}
                            title={
                              osPaga
                                ? `OS ${osVinculada.numero_os || osVinculada.id} ja paga`
                                : `Receber OS ${osVinculada.numero_os || osVinculada.id}`
                            }
                          >
                            {recebendoPagamentoId === ag.id ? (
                              <RefreshCw className="w-4 h-4 animate-spin" />
                            ) : (
                              <Wallet className="w-4 h-4" />
                            )}
                            {osPaga ? "Pago" : "Receber"}
                          </button>
                        )}

                        {/* Editar */}
                        <button
                          onClick={() => { setAgendamentoEditando(ag); setSlotSelecionado(null); setModalAberto(true); }}
                          className="px-3 py-1.5 text-sm text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded-lg transition-colors"
                        >
                          Editar
                        </button>

                        <button
                          onClick={() => abrirFluxoAtendimento(ag)}
                          className="px-3 py-1.5 text-sm text-purple-700 hover:text-purple-900 hover:bg-purple-50 rounded-lg transition-colors flex items-center gap-1"
                          title="Abrir atendimento clinico para este agendamento"
                        >
                          <Stethoscope className="w-4 h-4" />
                          Atender
                        </button>

                        <button
                          onClick={() => abrirWazeParaDestino(destinoNavegacao, nomeDestinoNavegacao)}
                          disabled={!podeAbrirWaze}
                          className={`px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center gap-1 ${
                            podeAbrirWaze
                              ? "text-sky-700 hover:text-sky-900 hover:bg-sky-50"
                              : "text-gray-400 bg-gray-50 cursor-not-allowed"
                          }`}
                          title={
                            podeAbrirWaze
                              ? `Abrir Waze para ${nomeDestinoNavegacao || "destino"}`
                              : "Destino sem endereco cadastrado"
                          }
                        >
                          <img
                            src="/icons/waze.svg"
                            alt="Waze"
                            className="h-[19.4px] w-[19.4px] rounded-sm object-contain"
                            loading="lazy"
                          />
                          Waze
                        </button>

                        <button
                          onClick={() => abrirGoogleMapsParaDestino(destinoNavegacao, nomeDestinoNavegacao)}
                          disabled={!podeAbrirGoogleMaps}
                          className={`px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center gap-1 ${
                            podeAbrirGoogleMaps
                              ? "text-indigo-700 hover:text-indigo-900 hover:bg-indigo-50"
                              : "text-gray-400 bg-gray-50 cursor-not-allowed"
                          }`}
                          title={
                            podeAbrirGoogleMaps
                              ? `Abrir Google Maps para ${nomeDestinoNavegacao || "destino"}`
                              : "Destino sem endereco cadastrado"
                          }
                        >
                          <MapPin className="h-4 w-4" />
                          Maps
                        </button>

                        <details className="fc-agenda-row-menu">
                          <summary
                            className="list-none px-3 py-1.5 text-sm text-teal-700 hover:text-teal-900 hover:bg-teal-50 rounded-lg transition-colors flex items-center gap-1 cursor-pointer"
                            title="Escolher tipo de laudo"
                          >
                            <FileText className="w-4 h-4" />
                            Laudar
                            <ChevronDown className="w-4 h-4" />
                          </summary>
                          <div className="fc-agenda-row-menu-panel">
                            <button
                              type="button"
                              onClick={() => abrirFluxoLaudo(ag, TIPO_LAUDO_ECOCARDIOGRAMA)}
                              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50"
                            >
                              <span>Ecocardiograma</span>
                              <span className="text-xs text-gray-500">
                                {laudoEco ? "Editar existente" : "Novo laudo"}
                              </span>
                            </button>
                            <button
                              type="button"
                              onClick={() => abrirFluxoLaudo(ag, TIPO_LAUDO_ELETROCARDIOGRAMA)}
                              className="flex w-full items-center justify-between gap-3 border-t px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50"
                            >
                              <span>Eletrocardiograma</span>
                              <span className="text-xs text-gray-500">
                                {laudoEletro ? "Ver existente" : "Upload PDF"}
                              </span>
                            </button>
                            <button
                              type="button"
                              onClick={() => abrirFluxoLaudo(ag, TIPO_LAUDO_PRESSAO_ARTERIAL)}
                              className="flex w-full items-center justify-between gap-3 border-t px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50"
                            >
                              <span>Pressao arterial</span>
                              <span className="text-xs text-gray-500">
                                {obterLaudoVinculado(ag.id, TIPO_LAUDO_PRESSAO_ARTERIAL) ? "Editar existente" : "Novo laudo"}
                              </span>
                            </button>
                          </div>
                        </details>

                        {laudoVinculado && laudoPronto && (
                          <button
                            onClick={() => baixarLaudoPdf(ag)}
                            className="px-3 py-1.5 text-sm text-emerald-700 hover:text-emerald-900 hover:bg-emerald-50 rounded-lg transition-colors flex items-center gap-1"
                            title={`Baixar ${laudoVinculado.titulo}`}
                          >
                            <Download className="w-4 h-4" />
                            Baixar laudo
                          </button>
                        )}

                        {/* Excluir */}
                        <button
                          onClick={() => setConfirmando({ id: ag.id, acao: "excluir" })}
                          className="p-1.5 text-red-600 hover:text-red-800 hover:bg-red-50 rounded-lg transition-colors"
                          title="Excluir"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden border">
          <div className="px-4 py-3 border-b bg-gray-50 flex items-center justify-between">
            <div className="text-sm text-gray-700 font-medium">
              {modoVisualizacao === "panoramica-semana"
                ? `Semana de ${formatarDiaPanoramica(diasPanoramica[0])} até ${formatarDiaPanoramica(diasPanoramica[diasPanoramica.length - 1])}`
                : `Dia ${formatarDiaPanoramica(diasPanoramica[0])}`}
            </div>
            <div className="text-xs text-gray-500">
              Clique em um horário livre para agendar
            </div>
          </div>

          <div className="overflow-auto">
            <div
              className="grid min-w-[860px]"
              style={{ gridTemplateColumns: `80px repeat(${diasPanoramica.length}, minmax(180px, 1fr))` }}
            >
              <div className="sticky top-0 z-20 bg-gray-100 border-b border-r px-2 py-2 text-xs font-semibold text-gray-600">
                Hora
              </div>
              {diasPanoramica.map((dia) => (
                <div
                  key={`head-${dia}`}
                  className="sticky top-0 z-10 bg-gray-100 border-b border-r px-3 py-2 text-sm font-semibold text-gray-700"
                >
                  <div>{formatarDiaPanoramica(dia)}</div>
                  {jornadaPanoramicaPorDia.get(dia)?.fechado && (
                    <div className="mt-1 inline-flex items-center rounded-full bg-gray-200 px-2 py-0.5 text-[10px] font-medium text-gray-700">
                      Agenda fechada
                    </div>
                  )}
                </div>
              ))}

              {slotsPanoramica.map((slot) => (
                <Fragment key={`row-${slot}`}>
                  <div
                    key={`hora-${slot}`}
                    className="border-b border-r px-2 py-3 text-xs font-medium text-gray-500 bg-gray-50"
                  >
                    {slot}
                  </div>
                  {diasPanoramica.map((dia) => {
                    const chave = `${dia}|${slot}`;
                    const itens = mapaOcupacao.get(chave) || [];
                    const jornadaDia = jornadaPanoramicaPorDia.get(dia);
                    const slotDisponivel = jornadaDia ? slotDentroDaJornada(slot, jornadaDia) : false;

                    if (itens.length === 0 && !slotDisponivel) {
                      if (isAdmin) {
                        return (
                          <button
                            key={chave}
                            type="button"
                            onClick={() => abrirNovoNoHorario(dia, slot)}
                            className="border-b border-r px-2 py-2 text-left bg-amber-50 hover:bg-amber-100 text-amber-700 transition-colors"
                            title={jornadaDia?.motivo || "Agenda fechada"}
                          >
                            <div className="text-xs font-semibold">Agenda fechada</div>
                            <div className="text-[11px]">Agendar com confirmação</div>
                          </button>
                        );
                      }

                      return (
                        <div
                          key={chave}
                          className="border-b border-r px-2 py-2 text-left bg-gray-100 text-gray-400"
                          title={jornadaDia?.motivo || "Agenda fechada"}
                        >
                          <div className="text-xs font-semibold text-gray-600">Agenda fechada</div>
                        </div>
                      );
                    }

                    if (itens.length === 0) {
                      return (
                        <button
                          key={chave}
                          onClick={() => abrirNovoNoHorario(dia, slot)}
                          className="border-b border-r px-2 py-2 text-left bg-emerald-50 hover:bg-emerald-100 transition-colors"
                        >
                          <div className="text-xs font-semibold text-emerald-700">Livre</div>
                          <div className="text-[11px] text-emerald-600">Clique para agendar</div>
                        </button>
                      );
                    }

                    const primeiro = itens[0];
                    const statusPrimeiro = String(primeiro.status || "");
                    const origemPrimeiro = obterOrigemAtendimentoMeta(primeiro.origem_atendimento);
                    const tituloPrimeiro = obterTituloAgendamentoPorOrigem(primeiro.origem_atendimento, primeiro.clinica);
                    const slotReservado = statusPrimeiro === "Reservado";
                    const prazoReservaPrimeiro = obterEstadoPrazoReserva(primeiro, agoraReservas);
                    const reservaEmAlerta = Boolean(prazoReservaPrimeiro?.emAlerta);
                    const slotClasses = slotReservado && reservaEmAlerta
                      ? {
                          container: `border-b border-r px-2 py-2 text-left transition-colors ${
                            prazoReservaPrimeiro?.critico
                              ? "bg-red-100 hover:bg-red-200 ring-2 ring-inset ring-red-500"
                              : "bg-amber-100 hover:bg-amber-200 ring-2 ring-inset ring-amber-400"
                          }`,
                          titulo: prazoReservaPrimeiro?.critico
                            ? "text-xs font-black text-red-900 truncate"
                            : "text-xs font-black text-amber-900 truncate",
                          texto: prazoReservaPrimeiro?.critico
                            ? "text-[11px] text-red-800 truncate"
                            : "text-[11px] text-amber-800 truncate",
                          extra: prazoReservaPrimeiro?.critico
                            ? "text-[11px] text-red-700"
                            : "text-[11px] text-amber-700",
                          badge: prazoReservaPrimeiro?.critico
                            ? "inline-flex items-center rounded-full border border-red-600 bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white animate-pulse"
                            : "inline-flex items-center rounded-full border border-amber-500 bg-amber-500 px-2 py-0.5 text-[10px] font-bold text-white",
                        }
                      : slotReservado
                      ? {
                          container: "border-b border-r px-2 py-2 text-left bg-amber-50 hover:bg-amber-100 transition-colors",
                          titulo: "text-xs font-bold text-amber-800 truncate",
                          texto: "text-[11px] text-amber-700 truncate",
                          extra: "text-[11px] text-amber-600",
                          badge: "inline-flex items-center rounded-full border border-amber-200 bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800",
                        }
                      : {
                          container: "border-b border-r px-2 py-2 text-left bg-red-50 hover:bg-red-100 transition-colors",
                          titulo: "text-xs font-bold text-red-800 truncate",
                          texto: "text-[11px] text-red-600 truncate",
                          extra: "text-[11px] text-red-500",
                          badge: "inline-flex items-center rounded-full border border-red-200 bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-800",
                        };
                    return (
                      <button
                        key={chave}
                        onClick={() => { setAgendamentoEditando(primeiro); setSlotSelecionado(null); setModalAberto(true); }}
                        className={slotClasses.container}
                      >
                        <div className={slotClasses.titulo}>
                          {tituloPrimeiro}
                        </div>
                        <div className="mt-1 mb-1 flex flex-wrap gap-1">
                          <span className={origemPrimeiro.compactBadgeClassName}>{origemPrimeiro.label}</span>
                          <span className={slotClasses.badge}>{statusPrimeiro || "Agendado"}</span>
                        </div>
                        {reservaEmAlerta && prazoReservaPrimeiro && (
                          <div className={`${slotClasses.extra} mb-1 font-black uppercase`}>
                            Atenção: {prazoReservaPrimeiro.label}
                          </div>
                        )}
                        <div className={slotClasses.texto}>
                          {primeiro.paciente || "Animal nao informado"}
                        </div>
                        <div className={slotClasses.texto}>
                          Tutor: {primeiro.tutor || "Nao informado"}
                        </div>
                        {primeiro.servico && (
                          <div className={`${slotClasses.extra} truncate`}>
                            {primeiro.servico}
                          </div>
                        )}
                        {itens.length > 1 && (
                          <div className={`${slotClasses.extra} font-medium`}>
                            +{itens.length - 1} no mesmo slot
                          </div>
                        )}
                      </button>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          </div>
        </div>
        )}

        {/* Modal de Confirmação */}
        {confirmando && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
              <h3 className="text-lg font-bold text-gray-900 mb-2">
                {confirmando.acao === "excluir" ? "Excluir Agendamento" : "Confirmar Ação"}
              </h3>
              <p className="text-gray-600 mb-6">
                {confirmando.acao === "excluir"
                  ? "Tem certeza que deseja excluir este agendamento? Esta ação não pode ser desfeita."
                  : "Tem certeza que deseja realizar esta ação?"}
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setConfirmando(null)}
                  className="px-4 py-2 text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg"
                >
                  Cancelar
                </button>
                <button
                  onClick={() => {
                    if (confirmando.acao === "excluir") {
                      excluirAgendamento(confirmando.id);
                    }
                  }}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
                >
                  Excluir
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Modal de reabilitação de reserva expirada */}
        {modalReabilitarReserva && (() => {
          const horasInformadas = normalizarPrazoReabilitacaoHoras(prazoReabilitacaoHoras);
          const previsao =
            horasInformadas === null
              ? null
              : calcularPrazoReabilitacao(horasInformadas, modalReabilitarReserva.inicio);
          const salvando = reabilitandoReservaId === modalReabilitarReserva.id;

          return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
              <div className="mx-4 w-full max-w-md rounded-lg bg-white p-6">
                <h3 className="text-lg font-bold text-gray-900">Reabilitar reserva</h3>
                <p className="mt-1 text-sm text-gray-600">
                  A reserva de{" "}
                  <span className="font-semibold">
                    {obterTituloAgendamentoPorOrigem(
                      modalReabilitarReserva.origem_atendimento,
                      modalReabilitarReserva.clinica
                    )}
                  </span>{" "}
                  em {formatarDataHoraAgendamento(modalReabilitarReserva)} volta a segurar o
                  horário por mais um período, até a clínica enviar os dados do paciente.
                </p>

                <div className="mt-4">
                  <label
                    htmlFor="reabilitar-reserva-horas"
                    className="mb-1 block text-xs font-semibold uppercase tracking-wide text-amber-800"
                  >
                    Novo prazo para confirmação
                  </label>
                  <div className="flex max-w-xs overflow-hidden rounded-lg border border-amber-300 bg-white focus-within:border-amber-500 focus-within:ring-2 focus-within:ring-amber-200">
                    <input
                      id="reabilitar-reserva-horas"
                      type="number"
                      min={PRAZO_REABILITACAO_HORAS_MIN}
                      max={PRAZO_REABILITACAO_HORAS_MAX}
                      step="0.5"
                      inputMode="decimal"
                      value={prazoReabilitacaoHoras}
                      onChange={(event) => setPrazoReabilitacaoHoras(event.target.value)}
                      className="min-w-0 flex-1 border-0 px-3 py-2 text-gray-900 outline-none"
                    />
                    <span className="flex items-center border-l border-amber-200 bg-amber-50 px-3 font-medium text-amber-800">
                      horas
                    </span>
                  </div>
                  <div className="mt-2 text-sm">
                    {horasInformadas === null ? (
                      <span className="text-red-600">
                        Informe um prazo entre {PRAZO_REABILITACAO_HORAS_MIN} e{" "}
                        {PRAZO_REABILITACAO_HORAS_MAX} horas.
                      </span>
                    ) : previsao?.indisponivel ? (
                      <span className="text-red-600">
                        Este horário está próximo demais (ou já passou) para uma nova reserva.
                        Agende direto com os dados do paciente ou escolha outro horário.
                      </span>
                    ) : (
                      <span className="text-gray-700">
                        Confirmar até <span className="font-semibold">{previsao?.prazoLegivel}</span>
                        {previsao?.encurtado
                          ? " (encurtado para terminar antes do horário reservado)"
                          : ""}
                      </span>
                    )}
                  </div>
                </div>

                <p className="mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
                  O sistema confere se o horário continua livre e sem conflito com outros
                  agendamentos antes de reservar de novo. Avise a clínica do novo prazo pelo
                  WhatsApp.
                </p>

                <div className="mt-6 flex justify-end gap-3">
                  <button
                    onClick={() => setModalReabilitarReserva(null)}
                    disabled={salvando}
                    className="rounded-lg border border-gray-300 px-4 py-2 text-gray-600 hover:text-gray-900"
                  >
                    Cancelar
                  </button>
                  <button
                    onClick={confirmarReabilitacaoReserva}
                    disabled={salvando || horasInformadas === null || Boolean(previsao?.indisponivel)}
                    className="flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {salvando ? (
                      <RefreshCw className="h-4 w-4 animate-spin" />
                    ) : (
                      <TimerReset className="h-4 w-4" />
                    )}
                    Reabilitar reserva
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Modal de Seleção de Tipo de Horário */}
        {modalTipoHorario && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
              <h3 className="text-lg font-bold text-gray-900 mb-2">
                Selecionar Tipo de Horário
              </h3>
              <p className="text-gray-600 mb-6">
                Este atendimento foi realizado em qual tipo de horário? Isso afetará o valor calculado na Ordem de Serviço.
              </p>
              
              <div className="grid grid-cols-2 gap-3 mb-6">
                <button
                  onClick={() => setTipoHorario("comercial")}
                  className={`p-4 rounded-lg border-2 transition-all flex flex-col items-center gap-2 ${
                    tipoHorario === "comercial" 
                      ? "border-blue-500 bg-blue-50" 
                      : "border-gray-200 hover:border-blue-300"
                  }`}
                >
                  <Sun className="w-8 h-8 text-amber-500" />
                  <span className="font-medium text-gray-900">Comercial</span>
                  <span className="text-xs text-gray-500">Seg-Sex 8h-18h</span>
                </button>
                
                <button
                  onClick={() => setTipoHorario("plantao")}
                  className={`p-4 rounded-lg border-2 transition-all flex flex-col items-center gap-2 ${
                    tipoHorario === "plantao" 
                      ? "border-blue-500 bg-blue-50" 
                      : "border-gray-200 hover:border-blue-300"
                  }`}
                >
                  <Moon className="w-8 h-8 text-indigo-500" />
                  <span className="font-medium text-gray-900">Plantão</span>
                  <span className="text-xs text-gray-500">Fora do horário</span>
                </button>
              </div>
              
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setModalTipoHorario(null)}
                  className="px-4 py-2 text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg"
                >
                  Cancelar
                </button>
                <button
                  onClick={confirmarRealizado}
                  disabled={atualizandoStatus !== null}
                  className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 flex items-center gap-2"
                >
                  {atualizandoStatus === modalTipoHorario.id ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <CheckCircle className="w-4 h-4" />
                  )}
                  Confirmar Realizado
                </button>
              </div>
            </div>
          </div>
        )}

        {modalPagamentoAberto && agendamentoPagamentoId !== null && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="mx-4 max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto rounded-lg bg-white p-6">
              <h3 className="text-lg font-semibold text-gray-900">Receber pagamento</h3>
              <p className="mt-1 text-sm text-gray-600">
                Informe as formas de pagamento da OS vinculada ao agendamento.
              </p>

              {carregandoSaldoCreditoPagamento && (
                <div className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs text-cyan-800">
                  Consultando credito ativo do cliente...
                </div>
              )}
              {!carregandoSaldoCreditoPagamento && erroSaldoCreditoPagamento && (
                <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  {erroSaldoCreditoPagamento}
                </div>
              )}
              {!carregandoSaldoCreditoPagamento && saldoCreditoClientePagamento > 0 && (
                <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Cliente com credito ativo: <strong>{formatarMoedaBRL(saldoCreditoClientePagamento)}</strong>.
                  Avalie com o cliente se deseja usar esse saldo antes de confirmar o recebimento.
                </div>
              )}

              <div className="mt-4 space-y-3">
                {pagamentosRecebimento.map((pagamento, index) => (
                  <div key={pagamento.id} className="rounded-lg border border-gray-200 p-3">
                    <div className="mb-2 text-xs font-medium text-gray-500">Pagamento {index + 1}</div>
                    <label className="block text-xs font-medium text-gray-600">Forma de pagamento</label>
                    <select
                      value={pagamento.forma_codigo}
                      onChange={(event) => atualizarLinhaPagamento(pagamento.id, "forma_codigo", event.target.value)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    >
                      {formasPagamentoDisponiveis.map((forma) => {
                        const codigo = normalizarCodigoFormaPagamento(forma.codigo);
                        return (
                          <option key={`${codigo}-${forma.id ?? "fallback"}`} value={codigo}>
                            {descricaoFormaPagamentoConfig(forma)}
                          </option>
                        );
                      })}
                    </select>

                    <label className="mt-2 block text-xs font-medium text-gray-600">Valor</label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={pagamento.valor}
                      onChange={(event) => atualizarLinhaPagamento(pagamento.id, "valor", event.target.value)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    />
                    <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
                      <span>
                        Taxa estimada:{" "}
                        {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                          resumoPagamentoModal.linhas[index]?.taxa || 0
                        )}
                      </span>
                      {pagamentosRecebimento.length > 1 && (
                        <button
                          type="button"
                          onClick={() => removerLinhaPagamento(pagamento.id)}
                          className="text-red-600 hover:text-red-700"
                        >
                          Remover
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <button
                type="button"
                onClick={adicionarLinhaPagamento}
                className="mt-3 text-sm font-medium text-blue-600 hover:text-blue-700"
              >
                + Adicionar forma de pagamento
              </button>

              <label className="mt-4 block text-sm font-medium text-gray-700">Data do recebimento</label>
              <input
                type="date"
                value={dataRecebimentoPagamento}
                onChange={(event) => setDataRecebimentoPagamento(event.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />

              <label className="mt-4 block text-sm font-medium text-gray-700">Desconto aplicado na OS</label>
              <input
                type="number"
                min="0"
                step="0.01"
                max={Math.max(0, Number(resumoPagamentoModal.valorOsBruto || 0))}
                value={descontoPagamento}
                onChange={(event) => {
                  const desconto = Math.max(0, Math.min(parseMoneyValue(event.target.value), resumoPagamentoModal.valorOsBruto));
                  setPagamentosRecebimento((prev) => ajustarPagamentoSugerido(
                    prev, resumoPagamentoModal.valorOs, resumoPagamentoModal.valorOsBruto - desconto, resumoPagamentoModal.creditoUtilizado
                  ));
                  setDescontoPagamento(event.target.value);
                }}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
              <div className="mt-1 text-xs text-gray-500">
                Valor bruto da OS: {formatarMoedaBRL(Number(resumoPagamentoModal.valorOsBruto || 0))}. A sugestao de pagamento acompanha o desconto; confira o valor efetivamente recebido.
              </div>

              {!carregandoSaldoCreditoPagamento && saldoCreditoClientePagamento > 0 && (
                <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-amber-900">
                    <input
                      type="checkbox"
                      checked={usarCreditoClientePagamento}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setUsarCreditoClientePagamento(checked);
                        if (checked) {
                          const coberturaAtual = Math.max(
                            0,
                            Number(resumoPagamentoModal.valorOs || 0) - Number(resumoPagamentoModal.totalBruto || 0)
                          );
                          const sugestao = Math.min(
                            Number(saldoCreditoClientePagamento || 0),
                            coberturaAtual > 0 ? coberturaAtual : Number(resumoPagamentoModal.valorOs || 0)
                          );
                          setValorCreditoUtilizadoPagamento(toMoneyInput(sugestao));
                        }
                      }}
                    />
                    Usar credito do cliente neste recebimento
                  </label>
                  {usarCreditoClientePagamento && (
                    <div className="mt-2">
                      <label className="block text-xs font-medium text-amber-900">Valor do credito a usar</label>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        max={Number(saldoCreditoClientePagamento || 0)}
                        value={valorCreditoUtilizadoPagamento}
                        onChange={(event) => setValorCreditoUtilizadoPagamento(event.target.value)}
                        className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500/20"
                      />
                      <div className="mt-1 text-xs text-amber-800">
                        Saldo disponivel: {formatarMoedaBRL(saldoCreditoClientePagamento)}.
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-3">
                <label className="flex items-start gap-2 text-sm font-medium text-green-900">
                  <input
                    type="checkbox"
                    checked={enviarReciboPdfWhatsAppAposRecebimento}
                    onChange={(event) => setEnviarReciboPdfWhatsAppAposRecebimento(event.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Enviar o recibo em PDF para a clinica pelo WhatsApp oficial apos registrar
                    <span className="mt-1 block text-xs font-normal text-green-800">
                      O documento informa OS, data do atendimento, servico, tutor e pet.
                    </span>
                  </span>
                </label>
              </div>

              <BaixaCredito
                onBusy={setBaixandoCredito}
                key={agendamentoPagamentoAtual?.paciente_id}
                pacienteId={agendamentoPagamentoAtual?.paciente_id}
                clinicaId={agendamentoPagamentoAtual?.clinica_id}
                onSaldoCliente={(saldo) => {
                  setSaldoCreditoClientePagamento(Math.max(0, saldo));
                  setUsarCreditoClientePagamento(false);
                  setValorCreditoUtilizadoPagamento("0.00");
                }}
              />

              {resumoPagamentoModal.excedente > 0 && (
                <>
                  <label className="mt-4 block text-sm font-medium text-gray-700">
                    Excedente detectado. Destino do credito
                  </label>
                  <select
                    value={destinoCreditoExcedente}
                    onChange={(event) =>
                      setDestinoCreditoExcedente(event.target.value as "cliente" | "clinica" | "nenhum")
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  >
                    <option value="cliente">Cliente</option>
                    <option value="clinica">Clinica</option>
                    <option value="nenhum">Nao gerar credito</option>
                  </select>
                </>
              )}

              <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
                <div className="flex justify-between">
                  <span>Valor bruto da OS</span>
                  <strong>
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.valorOsBruto || 0
                    )}
                  </strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Desconto aplicado</span>
                  <strong>
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.descontoAplicado || 0
                    )}
                  </strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Valor liquido da OS</span>
                  <strong>
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.valorOs || 0
                    )}
                  </strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Total bruto informado</span>
                  <strong>
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.totalBruto || 0
                    )}
                  </strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Credito aplicado</span>
                  <strong>
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.creditoUtilizado || 0
                    )}
                  </strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Total coberto</span>
                  <strong>
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.totalCoberto || 0
                    )}
                  </strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Total de taxas estimadas</span>
                  <strong>
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.totalTaxa || 0
                    )}
                  </strong>
                </div>
                {resumoPagamentoModal.faltante > 0 && (
                  <div className="mt-1 text-red-700">
                    Falta cobrir{" "}
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.faltante
                    )}
                    .
                  </div>
                )}
                {resumoPagamentoModal.excedente > 0 && (
                  <div className="mt-1 text-emerald-700">
                    Excedente para credito:{" "}
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      resumoPagamentoModal.excedente
                    )}
                    .
                  </div>
                )}
              </div>

              <div className="mt-6 flex justify-end gap-2">
                <button
                  disabled={baixandoCredito}
                  type="button"
                  onClick={() => {
                    setModalPagamentoAberto(false);
                    setAgendamentoPagamentoId(null);
                    setSaldoCreditoClientePagamento(0);
                    setCarregandoSaldoCreditoPagamento(false);
                    setErroSaldoCreditoPagamento("");
                    setUsarCreditoClientePagamento(false);
                    setValorCreditoUtilizadoPagamento("0.00");
                    setDescontoPagamento("0.00");
                    setEnviarReciboPdfWhatsAppAposRecebimento(false);
                  }}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={confirmarRecebimentoPagamento}
                  disabled={
                    recebendoPagamentoId === agendamentoPagamentoId ||
                    baixandoCredito ||
                    carregandoFormasPagamento ||
                    resumoPagamentoModal.faltante > 0
                  }
                  className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-700 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {recebendoPagamentoId === agendamentoPagamentoId ? (
                    <RefreshCw className="h-4 w-4 animate-spin" />
                  ) : (
                    <Wallet className="h-4 w-4" />
                  )}
                  Confirmar recebimento
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Modal de Confirmação de OS Gerada */}
        {osGerada && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-12 h-12 bg-emerald-100 rounded-full flex items-center justify-center">
                  <FileText className="w-6 h-6 text-emerald-600" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-gray-900">
                    Ordem de Serviço Gerada!
                  </h3>
                  <p className="text-sm text-gray-500">Nº {osGerada.numero_os}</p>
                </div>
              </div>
              
              <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4 mb-6">
                <p className="text-sm text-emerald-800">
                  <span className="font-medium">Valor Final:</span>{" "}
                  {new Intl.NumberFormat('pt-BR', {
                    style: 'currency',
                    currency: 'BRL'
                  }).format(osGerada.valor_final)}
                </p>
                <p className="text-xs text-emerald-600 mt-1">
                  Baseado na tabela de preços da clínica e tipo de horário selecionado.
                </p>
              </div>
              
              <div className="flex justify-end">
                <button
                  onClick={() => setOsGerada(null)}
                  className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700"
                >
                  Entendido
                </button>
              </div>
            </div>
          </div>
        )}

        <NovoAgendamentoModal
          isOpen={modalAberto}
          agendamento={agendamentoEditando}
          pedidoWhatsApp={pedidoWhatsApp}
          onClose={() => {
            setModalAberto(false); setAgendamentoEditando(null); setSlotSelecionado(null); setPedidoWhatsApp(null);
            const url = new URL(window.location.href); url.searchParams.delete("pedido_whatsapp");
            window.history.replaceState(null, "", url.toString());
          }}
          onSuccess={handleAgendamentoSuccess}
          defaultDate={slotSelecionado?.data || filtroData || hojeLocal()}
          defaultTime={slotSelecionado?.hora}
          agendaSemanal={agendaSemanal}
          agendaFeriados={agendaFeriados}
          agendaExcecoes={agendaExcecoes}
          intervaloSlotMinutos={intervaloSlotMinutos}
          isAdmin={isAdmin}
        />

        {clienteModalAlvo && (
          <ClienteInfoModal
            pacienteId={clienteModalAlvo.pacienteId}
            tutorId={clienteModalAlvo.tutorId}
            onClose={() => setClienteModalAlvo(null)}
            onSaved={() => { void carregarAgendamentos(); }}
          />
        )}
      </div>
    </DashboardLayout>
  );
}
