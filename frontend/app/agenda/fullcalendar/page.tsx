"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import type {
  DateSelectArg,
  DatesSetArg,
  EventClickArg,
  EventContentArg,
  EventDropArg,
  EventInput,
} from "@fullcalendar/core";
import type { DateClickArg, EventResizeDoneArg } from "@fullcalendar/interaction";
import { CalendarDays, ChevronDown, Download, FileText, List, MapPin, RefreshCw, Stethoscope, TimerReset, Trash2, Wallet, X } from "lucide-react";

import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { useFortinho } from "@/components/fortinho/FortinhoProvider";
import AgendaDayOpportunities from "@/components/agenda/AgendaDayOpportunities";
import { normalizarCoordenadaOpcional } from "@/lib/coordinates";
import { agruparIdsAgendamentosVisiveis } from "@/lib/agenda-loading";
import { montarToastAgendaRealtime } from "@/lib/agenda-realtime-toast";
import { useAgendaRealtime, type AgendaRealtimePayload } from "@/lib/useAgendaRealtime";
import {
  AGENDA_STATUS_LIST,
  FORMA_PAGAMENTO_FALLBACK,
  FORMA_PAGAMENTO_PADRAO,
  descricaoFormaPagamentoConfig,
  normalizarCodigoFormaPagamento,
  obterOrigemAtendimentoMeta,
  obterTituloAgendamentoPorOrigem,
  type AgendaStatus,
  type AgendaStatusAction,
  type FormaPagamentoConfig,
  obterAcoesStatusPorFluxo,
  osEstaPaga,
} from "@/lib/agenda-shared-actions";
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
  getLaudoEditPath,
  TIPO_LAUDO_ECOCARDIOGRAMA,
  TIPO_LAUDO_ELETROCARDIOGRAMA,
  TIPO_LAUDO_PRESSAO_ARTERIAL,
  TIPO_LAUDO_ULTRASSOM_ABDOMINAL,
} from "@/lib/laudos";
import {
  AgendaExcecaoConfig,
  AgendaFeriadoConfig,
  AgendaSemanalConfig,
  DEFAULT_AGENDA_SEMANAL,
  horarioParaMinutos,
  normalizarAgendaExcecoes,
  normalizarAgendaFeriados,
  normalizarAgendaSemanal,
  obterJornadaDia,
  slotDentroDaJornada,
  validarHorarioAgendamento,
} from "@/lib/agenda-config";
import {
  DEFAULT_AGENDA_ROTA_REGRAS,
  normalizarAgendaRotaRegras,
  type AgendaRotaRenderingPolicyConfig,
} from "@/lib/agenda-route-rules";

const AgendaFullCalendarView = dynamic(() => import("./AgendaFullCalendarView"), {
  ssr: false,
  loading: () => (
    <div className="fc-calendar-loading">
      Carregando calendario...
    </div>
  ),
});

const NovoAgendamentoModal = dynamic(() => import("../NovoAgendamentoModal"));
const ClienteInfoModal = dynamic(() => import("../ClienteInfoModal"));

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
  observacoes: string | null;
  telefone: string | null;
  data: string;
  hora: string;
}

interface IntervaloConsulta {
  inicio: string;
  fim: string;
}

interface SlotSelecionado {
  data: string;
  hora: string;
}

type StatusAgenda = AgendaStatus;

interface StatusVisual {
  bg: string;
  border: string;
  text: string;
}

interface AtualizacaoHorarioArgs {
  id: number;
  inicio: Date;
  fim: Date;
  revert: () => void;
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

interface OrdemServicoResumo {
  id: number;
  agendamento_id: number;
  numero_os: string;
  status: string;
  valor_servico: number;
  desconto: number;
  valor_final: number;
}

interface LaudoVinculado {
  id: number;
  status: string;
  titulo: string;
  tipo: string;
}

type LaudosVinculadosPorAgendamento = Record<number, Record<string, LaudoVinculado>>;

interface ToastRealtimeData {
  texto: string;
  classe: string;
  agendamentoId?: number;
}

interface PagamentoRecebimentoItem {
  id: string;
  forma_codigo: string;
  valor: string;
}

interface CarregarAgendamentosOptions {
  includeRelated?: boolean;
}

type OpcaoRecorrencia = "apenas_este" | "cada_7_dias" | "seg_a_sex" | "todos_os_dias";

interface MovimentacaoPendente {
  origem: "movimentacao" | "edicao";
  id: number;
  inicioNovo: Date;
  fimNovo: Date;
  inicioOriginal: Date;
  fimOriginal: Date;
  revert: () => void;
}

interface ConflitoDeslocamentoDetail {
  codigo?: string;
  mensagem?: string;
  origem_clinica?: string;
  destino_clinica?: string;
  duracao_min?: number;
  folga_min?: number;
  confirmavel?: boolean;
}

const OPCOES_RECORRENCIA: Array<{ id: OpcaoRecorrencia; label: string; descricao: string }> = [
  { id: "apenas_este", label: "Apenas este", descricao: "Atualiza somente este agendamento." },
  { id: "cada_7_dias", label: "A cada 7 dias", descricao: "Replica semanalmente ate a data limite." },
  { id: "seg_a_sex", label: "Seg a sex", descricao: "Replica de segunda a sexta ate a data limite." },
  { id: "todos_os_dias", label: "Todos os dias", descricao: "Replica diariamente ate a data limite." },
];

const STATUS_CORES: Record<string, StatusVisual> = {
  Agendado: { bg: "#dbeafe", border: "#60a5fa", text: "#1e3a8a" },
  Reservado: { bg: "#fef3c7", border: "#f59e0b", text: "#92400e" },
  Confirmado: { bg: "#dcfce7", border: "#4ade80", text: "#14532d" },
  "Em atendimento": { bg: "#fef9c3", border: "#facc15", text: "#713f12" },
  Realizado: { bg: "#d1fae5", border: "#34d399", text: "#064e3b" },
  Cancelado: { bg: "#fee2e2", border: "#f87171", text: "#7f1d1d" },
  Faltou: { bg: "#ffedd5", border: "#fb923c", text: "#7c2d12" },
  Expirado: { bg: "#f1f5f9", border: "#94a3b8", text: "#334155" },
};

const STATUS_FILTRO = ["todos", ...AGENDA_STATUS_LIST];

const toDateInput = (date: Date) => {
  const ano = date.getFullYear();
  const mes = String(date.getMonth() + 1).padStart(2, "0");
  const dia = String(date.getDate()).padStart(2, "0");
  return `${ano}-${mes}-${dia}`;
};

const isDateInputValida = (value?: string | null): value is string => {
  if (!value) return false;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const data = new Date(`${value}T00:00:00`);
  return !Number.isNaN(data.getTime());
};

const toTimeInput = (date: Date) => {
  const hora = String(date.getHours()).padStart(2, "0");
  const minuto = String(date.getMinutes()).padStart(2, "0");
  return `${hora}:${minuto}`;
};

const toApiDateTime = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`;
};

const gerarPagamentoId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

const parseMoneyValue = (value: string): number => {
  const normalizado = String(value || "").replace(",", ".").trim();
  const parsed = Number.parseFloat(normalizado);
  if (!Number.isFinite(parsed)) return 0;
  return parsed;
};

const toMoneyInput = (value: number): string => {
  if (!Number.isFinite(value)) return "0.00";
  return value.toFixed(2);
};

const SLOT_INTERVALO_PADRAO_MIN = DEFAULT_AGENDA_ROTA_REGRAS.rendering_policy.slot_interval_min;

const minutosParaDuracao = (minutos: number): string => {
  const horas = Math.floor(minutos / 60);
  const mins = minutos % 60;
  return `${String(horas).padStart(2, "0")}:${String(mins).padStart(2, "0")}:00`;
};

const minutosParaHoraComSegundos = (minutos: number): string => {
  const normalizado = Math.max(0, Math.min(24 * 60, Math.round(minutos)));
  const horas = Math.floor(normalizado / 60);
  const mins = normalizado % 60;
  return `${String(horas).padStart(2, "0")}:${String(mins).padStart(2, "0")}:00`;
};

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

const adicionarDias = (data: Date, dias: number): Date => {
  const copia = new Date(data);
  copia.setDate(copia.getDate() + dias);
  return copia;
};

const combinarDataComHorario = (dataBase: Date, modeloHorario: Date): Date => {
  return new Date(
    dataBase.getFullYear(),
    dataBase.getMonth(),
    dataBase.getDate(),
    modeloHorario.getHours(),
    modeloHorario.getMinutes(),
    modeloHorario.getSeconds(),
    modeloHorario.getMilliseconds()
  );
};

const parseApiDateTime = (value?: string | null): Date | null => {
  if (!value) return null;

  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?/);
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

const parseInicioLocal = (ag: Agendamento): Date | null => {
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

const parseFimLocal = (ag: Agendamento, inicioLocal: Date): Date => {
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

const formatarDataHora = (ag: Agendamento) => {
  const inicio = parseInicioLocal(ag);
  if (!inicio) return "Horario invalido";
  const fim = parseFimLocal(ag, inicio);
  const data = inicio.toLocaleDateString("pt-BR");
  const horaInicio = inicio.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const horaFim = fim.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return `${data} ${horaInicio} - ${horaFim}`;
};

const formatarMoedaBRL = (valor: number) => {
  return Number(valor || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
};

const extrairMensagemErroApi = (detail: unknown, fallback: string): string => {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const payload = detail as Record<string, unknown>;
    const mensagem = payload.mensagem;
    if (typeof mensagem === "string" && mensagem.trim()) {
      return mensagem;
    }
    const message = payload.message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    const nestedDetail = payload.detail;
    if (typeof nestedDetail === "string" && nestedDetail.trim()) {
      return nestedDetail;
    }
  }
  return fallback;
};

const extrairConflitoDeslocamento = (error: any): ConflitoDeslocamentoDetail | null => {
  if (error?.response?.status !== 409) {
    return null;
  }

  const detail = error?.response?.data?.detail;
  if (detail && typeof detail === "object") {
    const payload = detail as Record<string, unknown>;
    if (payload.codigo === "CONFLITO_DESLOCAMENTO") {
      return payload as ConflitoDeslocamentoDetail;
    }
  }

  const texto = String(detail || "");
  if (texto.toLowerCase().includes("deslocamento")) {
    return { mensagem: texto, confirmavel: false };
  }

  return null;
};

export default function AgendaFullCalendarPage() {
  const fortinho = useFortinho();
  const [authChecked, setAuthChecked] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [identidadeAgenda, setIdentidadeAgenda] = useState("");
  const [transicaoRegionalAtiva, setTransicaoRegionalAtiva] = useState(false);
  const [intervalo, setIntervalo] = useState<IntervaloConsulta | null>(null);
  const [agendamentos, setAgendamentos] = useState<Agendamento[]>([]);
  const [clinicasEndereco, setClinicasEndereco] = useState<Record<number, ClinicaEndereco>>({});
  const [tutoresEndereco, setTutoresEndereco] = useState<Record<number, TutorEndereco>>({});
  const [ordensServicoPorAgendamento, setOrdensServicoPorAgendamento] = useState<Record<number, OrdemServicoResumo>>(
    {}
  );
  const [laudosVinculados, setLaudosVinculados] = useState<LaudosVinculadosPorAgendamento>({});
  const [loading, setLoading] = useState(false);
  const [atualizandoStatusId, setAtualizandoStatusId] = useState<number | null>(null);
  const [recebendoPagamentoId, setRecebendoPagamentoId] = useState<number | null>(null);
  const [modalPagamentoAberto, setModalPagamentoAberto] = useState(false);
  const [formasPagamentoDisponiveis, setFormasPagamentoDisponiveis] = useState<FormaPagamentoConfig[]>(FORMA_PAGAMENTO_FALLBACK);
  const [carregandoFormasPagamento, setCarregandoFormasPagamento] = useState(false);
  const [pagamentosRecebimento, setPagamentosRecebimento] = useState<PagamentoRecebimentoItem[]>([]);
  const [dataRecebimentoPagamento, setDataRecebimentoPagamento] = useState<string>(() => toDateInput(new Date()));
  const [destinoCreditoExcedente, setDestinoCreditoExcedente] = useState<"cliente" | "clinica" | "nenhum">("cliente");
  const [saldoCreditoClientePagamento, setSaldoCreditoClientePagamento] = useState(0);
  const [carregandoSaldoCreditoPagamento, setCarregandoSaldoCreditoPagamento] = useState(false);
  const [erroSaldoCreditoPagamento, setErroSaldoCreditoPagamento] = useState("");
  const [usarCreditoClientePagamento, setUsarCreditoClientePagamento] = useState(false);
  const [baixandoCredito, setBaixandoCredito] = useState(false);
  const [valorCreditoUtilizadoPagamento, setValorCreditoUtilizadoPagamento] = useState("0.00");
  const [descontoPagamento, setDescontoPagamento] = useState("0.00");
  const [excluindoAgendamentoId, setExcluindoAgendamentoId] = useState<number | null>(null);
  const [salvandoMovimentacao, setSalvandoMovimentacao] = useState(false);
  const [salvandoAgendaDia, setSalvandoAgendaDia] = useState(false);
  const [renderingPolicy, setRenderingPolicy] = useState<AgendaRotaRenderingPolicyConfig>(
    DEFAULT_AGENDA_ROTA_REGRAS.rendering_policy
  );
  const [erro, setErro] = useState("");
  const [filtroStatus, setFiltroStatus] = useState("todos");
  const [filtroOrigemAtendimento, setFiltroOrigemAtendimento] = useState("todos");
  const [mensagemStatus, setMensagemStatus] = useState("");
  const [dataControleAgenda, setDataControleAgenda] = useState(() => toDateInput(new Date()));
  const [modalRecorrenciaAberto, setModalRecorrenciaAberto] = useState(false);
  const [movimentacaoPendente, setMovimentacaoPendente] = useState<MovimentacaoPendente | null>(null);
  const [opcaoRecorrencia, setOpcaoRecorrencia] = useState<OpcaoRecorrencia>("apenas_este");
  const [dataLimiteRecorrencia, setDataLimiteRecorrencia] = useState(() => toDateInput(adicionarDias(new Date(), 30)));
  const [aplicandoRecorrencia, setAplicandoRecorrencia] = useState(false);
  const [menuStatusAberto, setMenuStatusAberto] = useState(false);
  const [selecionado, setSelecionado] = useState<Agendamento | null>(null);
  const [clienteModalAlvo, setClienteModalAlvo] = useState<{ pacienteId?: number; tutorId?: number } | null>(null);
  const [modalAberto, setModalAberto] = useState(false);
  const [modalTipoHorario, setModalTipoHorario] = useState<{ id: number; status: StatusAgenda } | null>(null);
  const [tipoHorario, setTipoHorario] = useState<"comercial" | "plantao">("comercial");
  const [modalReabilitarReservaAberto, setModalReabilitarReservaAberto] = useState(false);
  const [prazoReabilitacaoHoras, setPrazoReabilitacaoHoras] = useState<string>(
    String(PRAZO_REABILITACAO_HORAS_PADRAO)
  );
  const [reabilitandoReservaId, setReabilitandoReservaId] = useState<number | null>(null);
  const [agendamentoEditando, setAgendamentoEditando] = useState<Agendamento | null>(null);
  const [slotSelecionado, setSlotSelecionado] = useState<SlotSelecionado | null>(null);
  const [agendaSemanal, setAgendaSemanal] = useState<AgendaSemanalConfig>(() =>
    normalizarAgendaSemanal(DEFAULT_AGENDA_SEMANAL)
  );
  const [agendaFeriados, setAgendaFeriados] = useState<AgendaFeriadoConfig[]>([]);
  const [agendaExcecoes, setAgendaExcecoes] = useState<AgendaExcecaoConfig[]>([]);
  const [mensagemRealtime, setMensagemRealtime] = useState("");
  const [toastRealtime, setToastRealtime] = useState<ToastRealtimeData | null>(null);
  const statusMenuRef = useRef<HTMLDivElement | null>(null);
  const realtimeRefreshTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastRealtimeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const router = useRouter();
  const filtrosIniciaisAplicadosRef = useRef(false);

  const duracaoSlotMinutos = useMemo(() => {
    const parsed = Number(renderingPolicy.slot_interval_min);
    if (!Number.isFinite(parsed)) return SLOT_INTERVALO_PADRAO_MIN;
    return Math.max(5, Math.min(120, Math.round(parsed)));
  }, [renderingPolicy.slot_interval_min]);
  const duracaoSlot = useMemo(() => minutosParaDuracao(duracaoSlotMinutos), [duracaoSlotMinutos]);
  const osSelecionada = useMemo(() => {
    if (!selecionado) return null;
    return ordensServicoPorAgendamento[selecionado.id] || null;
  }, [ordensServicoPorAgendamento, selecionado]);
  const acoesStatusDisponiveis = useMemo<AgendaStatusAction[]>(
    () => obterAcoesStatusPorFluxo(selecionado?.status),
    [selecionado]
  );
  const origemSelecionadoMeta = useMemo(
    () => (selecionado ? obterOrigemAtendimentoMeta(selecionado.origem_atendimento) : null),
    [selecionado]
  );
  const resolverDestinoAgendamento = useCallback(
    (agendamento?: Agendamento | null): { destino: WazeDestinoLocal | null; nome: string } => {
      if (!agendamento) {
        return { destino: null, nome: "destino" };
      }

      const atendimentoDomiciliar =
        String(agendamento.origem_atendimento || "").trim().toLowerCase() === "domiciliar";
      if (atendimentoDomiciliar) {
        return {
          destino: agendamento.tutor_id ? tutoresEndereco[agendamento.tutor_id] || null : null,
          nome: String(agendamento.tutor || "atendimento domiciliar").trim() || "atendimento domiciliar",
        };
      }

      return {
        destino: agendamento.clinica_id ? clinicasEndereco[agendamento.clinica_id] || null : null,
        nome: String(agendamento.clinica || "clinica").trim() || "clinica",
      };
    },
    [clinicasEndereco, tutoresEndereco]
  );
  const laudoSelecionado = useMemo(() => {
    if (!selecionado) return null;
    const laudosDoAgendamento = Object.values(laudosVinculados[selecionado.id] || {});
    return laudosDoAgendamento.reduce<LaudoVinculado | null>(
      (maisRecente, atual) => (!maisRecente || atual.id > maisRecente.id ? atual : maisRecente),
      null
    );
  }, [laudosVinculados, selecionado]);
  const jornadaDataControle = useMemo(
    () => obterJornadaDia(dataControleAgenda, agendaSemanal, agendaFeriados, agendaExcecoes),
    [agendaExcecoes, agendaFeriados, agendaSemanal, dataControleAgenda]
  );
  const excecaoDataControle = useMemo(
    () => agendaExcecoes.find((item) => item.data === dataControleAgenda) || null,
    [agendaExcecoes, dataControleAgenda]
  );

  useEffect(() => {
    if (!modalPagamentoAberto || !selecionado) {
      setSaldoCreditoClientePagamento(0);
      setCarregandoSaldoCreditoPagamento(false);
      setErroSaldoCreditoPagamento("");
      return;
    }

    const pacienteId = Number(selecionado.paciente_id || 0);
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
        console.error("Erro ao consultar credito do cliente no FullCalendar:", error);
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
  }, [modalPagamentoAberto, selecionado]);
  useEffect(() => {
    if (filtrosIniciaisAplicadosRef.current) return;

    if (typeof window === "undefined") return;
    const urlParams = new URLSearchParams(window.location.search);
    const dataQuery = urlParams.get("data");
    const statusQuery = urlParams.get("status");
    const origemQuery = urlParams.get("origem_atendimento") || urlParams.get("origem");

    if (isDateInputValida(dataQuery)) {
      setDataControleAgenda(dataQuery);
    }

    if (statusQuery && STATUS_FILTRO.includes(statusQuery)) {
      setFiltroStatus(statusQuery);
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
        taxa,
        liquido,
      };
    });
    const totalBruto = linhas.reduce((acc, item) => acc + item.valor, 0);
    const totalTaxa = linhas.reduce((acc, item) => acc + item.taxa, 0);
    const totalLiquido = linhas.reduce((acc, item) => acc + item.liquido, 0);
    const valorOsBrutoDireto = Number(osSelecionada?.valor_servico || 0);
    const descontoBase = Number(osSelecionada?.desconto || 0);
    const valorOsBruto = Number(
      (valorOsBrutoDireto > 0 ? valorOsBrutoDireto : Number(osSelecionada?.valor_final || 0) + descontoBase).toFixed(2)
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
    osSelecionada?.desconto,
    osSelecionada?.valor_servico,
    osSelecionada?.valor_final,
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

  const slotMinTime = useMemo(() => {
    const inicioConfigMin = horarioParaMinutos(renderingPolicy.window_start);
    const fimConfigMin = horarioParaMinutos(renderingPolicy.window_end);
    const janelaCustomValida =
      Boolean(renderingPolicy.use_custom_window) &&
      inicioConfigMin !== null &&
      fimConfigMin !== null &&
      fimConfigMin > inicioConfigMin;
    if (janelaCustomValida) {
      return minutosParaHoraComSegundos(inicioConfigMin);
    }

    const inicios = Object.values(agendaSemanal)
      .filter((dia) => dia.ativo)
      .map((dia) => horarioParaMinutos(dia.inicio))
      .filter((valor): valor is number => valor !== null);
    const menor = inicios.length > 0 ? Math.min(...inicios) : 6 * 60;
    return minutosParaHoraComSegundos(menor);
  }, [agendaSemanal, renderingPolicy]);
  const slotMaxTime = useMemo(() => {
    const inicioConfigMin = horarioParaMinutos(renderingPolicy.window_start);
    const fimConfigMin = horarioParaMinutos(renderingPolicy.window_end);
    const janelaCustomValida =
      Boolean(renderingPolicy.use_custom_window) &&
      inicioConfigMin !== null &&
      fimConfigMin !== null &&
      fimConfigMin > inicioConfigMin;
    if (janelaCustomValida) {
      return minutosParaHoraComSegundos(fimConfigMin);
    }

    const fins = Object.values(agendaSemanal)
      .filter((dia) => dia.ativo)
      .map((dia) => horarioParaMinutos(dia.fim))
      .filter((valor): valor is number => valor !== null);
    const maior = fins.length > 0 ? Math.max(...fins) : 22 * 60;
    return minutosParaHoraComSegundos(maior);
  }, [agendaSemanal, renderingPolicy]);
  const businessHours = useMemo(() => {
    return (Object.entries(agendaSemanal) as Array<[string, { ativo: boolean; inicio: string; fim: string }]>)
      .filter(([, dia]) => dia.ativo)
      .map(([dia, configDia]) => ({
        daysOfWeek: [dia === "7" ? 0 : Number(dia)],
        startTime: `${configDia.inicio}:00`,
        endTime: `${configDia.fim}:00`,
      }));
  }, [agendaSemanal]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    setIsAdmin(usuarioEhAdmin());
    const atualizarIdentidade = () => {
      try {
        const usuario = JSON.parse(localStorage.getItem("user") || "{}");
        setIdentidadeAgenda(String(usuario?.id ?? ""));
      } catch {
        setIdentidadeAgenda("");
      }
    };
    atualizarIdentidade();
    const aoAtualizarSessao = (event: StorageEvent) => {
      if (event.key === "user" || event.key === null) atualizarIdentidade();
    };
    window.addEventListener("storage", aoAtualizarSessao);
    setAuthChecked(true);
    return () => window.removeEventListener("storage", aoAtualizarSessao);
  }, [router]);

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

  const montarWazeWebUrl = useCallback((destino: WazeDestinoLocal | null | undefined): string => {
    return montarWazeDestinoLocal(destino)?.webUrl || "";
  }, []);

  const montarGoogleMapsWebUrl = useCallback((destino: WazeDestinoLocal | null | undefined): string => {
    return montarGoogleMapsDestinoLocal(destino) || "";
  }, []);

  const wazeSelecionadoUrl = useMemo(() => {
    const { destino } = resolverDestinoAgendamento(selecionado);
    return montarWazeWebUrl(destino);
  }, [montarWazeWebUrl, resolverDestinoAgendamento, selecionado]);

  const googleMapsSelecionadoUrl = useMemo(() => {
    const { destino } = resolverDestinoAgendamento(selecionado);
    return montarGoogleMapsWebUrl(destino);
  }, [montarGoogleMapsWebUrl, resolverDestinoAgendamento, selecionado]);

  const carregarRelacionadosVisiveis = useCallback(async (items: Agendamento[]) => {
    const lotesIds = agruparIdsAgendamentosVisiveis(items);
    const limparRelacionados = () => {
      setClinicasEndereco({});
      setTutoresEndereco({});
      setOrdensServicoPorAgendamento({});
      setLaudosVinculados({});
    };

    if (lotesIds.length === 0) {
      limparRelacionados();
      return;
    }

    const idsAgendamento = new Set(lotesIds.flat());
    const pacientePorAgendamento = new Map(
      items.map((item) => [item.id, Number(item.paciente_id || 0)])
    );

    try {
      const responses = await Promise.all(
        lotesIds.map((ids) =>
          api.get("/agenda/relacionados", {
            params: { agendamento_ids: ids.join(",") },
          })
        )
      );
      const listaLaudos = responses.flatMap((response) =>
        Array.isArray(response.data?.laudos) ? response.data.laudos : []
      );
      const listaOrdens = responses.flatMap((response) =>
        Array.isArray(response.data?.ordens_servico) ? response.data.ordens_servico : []
      );
      const listaClinicas = responses.flatMap((response) =>
        Array.isArray(response.data?.clinicas) ? response.data.clinicas : []
      );
      const listaTutores = responses.flatMap((response) =>
        Array.isArray(response.data?.tutores) ? response.data.tutores : []
      );

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
        if (!Number.isInteger(agendamentoId) || !idsAgendamento.has(agendamentoId)) continue;
        const statusOs = String(os?.status || "").trim();
        if (statusOs === "Cancelado") continue;
        const osId = Number(os?.id);
        if (!Number.isInteger(osId)) continue;
        const anterior = mapaOrdens[agendamentoId];
        if (!anterior || osId > anterior.id) {
          mapaOrdens[agendamentoId] = {
            id: osId,
            agendamento_id: agendamentoId,
            numero_os: String(os?.numero_os || ""),
            status: statusOs || "Pendente",
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

      setClinicasEndereco(mapaClinicas);
      setTutoresEndereco(mapaTutores);
      setOrdensServicoPorAgendamento(mapaOrdens);
      setLaudosVinculados(mapaLaudos);
    } catch (error) {
      console.error("Erro ao carregar relacionados visiveis no FullCalendar:", error);
      limparRelacionados();
    }
  }, []);

  const obterLaudoVinculado = useCallback(
    (agendamentoId: number, tipo: string) => laudosVinculados[agendamentoId]?.[tipo],
    [laudosVinculados]
  );

  const carregarAgendamentos = useCallback(async (
    periodo: IntervaloConsulta,
    { includeRelated = true }: CarregarAgendamentosOptions = {}
  ) => {
    setLoading(true);
    try {
      const pageSize = 500;
      let skip = 0;
      let total = 0;
      const items: Agendamento[] = [];

      while (true) {
        const response = await api.get(
          `/agenda?data_inicio=${periodo.inicio}&data_fim=${periodo.fim}&skip=${skip}&limit=${pageSize}`
        );
        const pagina = Array.isArray(response.data?.items) ? (response.data.items as Agendamento[]) : [];
        const totalResposta = Number(response.data?.total);

        if (Number.isFinite(totalResposta) && totalResposta >= 0) {
          total = totalResposta;
        }

        items.push(...pagina);

        if (pagina.length === 0 || pagina.length < pageSize || (total > 0 && items.length >= total)) {
          break;
        }

        skip += pagina.length;
      }

      setAgendamentos(items);
      if (includeRelated) {
        await carregarRelacionadosVisiveis(items);
      }
      setErro("");
    } catch (error) {
      console.error("Erro ao carregar agenda FullCalendar:", error);
      setErro("Nao foi possivel carregar os agendamentos neste periodo.");
    } finally {
      setLoading(false);
    }
  }, [carregarRelacionadosVisiveis]);

  const carregarConfiguracaoAgenda = useCallback(async () => {
    try {
      const response = await api.get("/agenda/configuracao");
      setAgendaSemanal(normalizarAgendaSemanal(response.data?.agenda_semanal));
      setAgendaFeriados(normalizarAgendaFeriados(response.data?.agenda_feriados));
      setAgendaExcecoes(normalizarAgendaExcecoes(response.data?.agenda_excecoes));
      const regrasRota = normalizarAgendaRotaRegras(response.data?.agenda_rota_regras);
      setRenderingPolicy(regrasRota.rendering_policy);
      setTransicaoRegionalAtiva(regrasRota.route_policy.regional_transition_enabled);
    } catch (error: any) {
      try {
        if (error?.response?.status === 404) {
          const fallback = await api.get("/configuracoes");
          setAgendaSemanal(normalizarAgendaSemanal(fallback.data?.agenda_semanal));
          setAgendaFeriados(normalizarAgendaFeriados(fallback.data?.agenda_feriados));
          setAgendaExcecoes(normalizarAgendaExcecoes(fallback.data?.agenda_excecoes));
          const regrasRota = normalizarAgendaRotaRegras(fallback.data?.agenda_rota_regras);
          setRenderingPolicy(regrasRota.rendering_policy);
          setTransicaoRegionalAtiva(regrasRota.route_policy.regional_transition_enabled);
          return;
        }
      } catch (fallbackError) {
        console.error("Erro no fallback de configuracao da agenda (FullCalendar):", fallbackError);
      }

      console.error("Erro ao carregar configuracao da agenda (FullCalendar):", error);
      setAgendaSemanal(normalizarAgendaSemanal(DEFAULT_AGENDA_SEMANAL));
      setAgendaFeriados([]);
      setAgendaExcecoes([]);
      setRenderingPolicy(DEFAULT_AGENDA_ROTA_REGRAS.rendering_policy);
      setTransicaoRegionalAtiva(false);
    }
  }, []);

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
        if (intervalo) {
          void carregarAgendamentos(intervalo, { includeRelated: false });
        }
      }, 700);
    },
    [carregarAgendamentos, intervalo]
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

        setSelecionado(agendamento);
        setToastRealtime(null);
      } catch (error) {
        console.error("Erro ao abrir agendamento pelo toast em tempo real (FullCalendar):", error);
        setErro("Nao foi possivel abrir o agendamento do toast.");
      }
    },
    [agendamentos]
  );

  useEffect(() => {
    if (!authChecked || !intervalo) {
      return;
    }
    carregarAgendamentos(intervalo);
  }, [authChecked, intervalo, carregarAgendamentos]);

  useEffect(() => {
    if (!authChecked) {
      return;
    }
    carregarConfiguracaoAgenda();
  }, [authChecked, carregarConfiguracaoAgenda]);

  useEffect(() => {
    if (!selecionado) return;
    const agendamentoAtualizado = agendamentos.find((item) => item.id === selecionado.id);
    if (agendamentoAtualizado) {
      setSelecionado(agendamentoAtualizado);
    }
  }, [agendamentos, selecionado]);

  useEffect(() => {
    setMenuStatusAberto(false);
  }, [selecionado?.id]);

  useEffect(() => {
    setModalPagamentoAberto(false);
    setPagamentosRecebimento([]);
    setDataRecebimentoPagamento(toDateInput(new Date()));
    setDestinoCreditoExcedente("cliente");
    setSaldoCreditoClientePagamento(0);
    setCarregandoSaldoCreditoPagamento(false);
    setErroSaldoCreditoPagamento("");
    setUsarCreditoClientePagamento(false);
    setValorCreditoUtilizadoPagamento("0.00");
  }, [selecionado?.id]);

  useEffect(() => {
    if (!menuStatusAberto) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!statusMenuRef.current) return;
      if (!statusMenuRef.current.contains(event.target as Node)) {
        setMenuStatusAberto(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [menuStatusAberto]);

  const fecharModal = useCallback(() => {
    setModalAberto(false);
    setAgendamentoEditando(null);
    setSlotSelecionado(null);
  }, []);

  const handleAgendamentoSuccess = useCallback(async (
    agendamentoSalvo?: any,
    opcoes?: { manterModalAberto?: boolean }
  ) => {
    const edicaoAnterior = agendamentoEditando;
    if (intervalo) {
      await carregarAgendamentos(intervalo);
    }
    if (!opcoes?.manterModalAberto) {
      fecharModal();
    }

    if (!edicaoAnterior || !agendamentoSalvo) {
      return;
    }

    const inicioOriginal = parseInicioLocal(edicaoAnterior);
    if (!inicioOriginal) {
      return;
    }
    const fimOriginal = parseFimLocal(edicaoAnterior, inicioOriginal);

    const salvoNormalizado = agendamentoSalvo as Agendamento;
    const inicioNovo = parseInicioLocal(salvoNormalizado);
    if (!inicioNovo) {
      return;
    }
    const fimNovo = parseFimLocal(salvoNormalizado, inicioNovo);

    const mudouHorario =
      inicioOriginal.getTime() !== inicioNovo.getTime() || fimOriginal.getTime() !== fimNovo.getTime();
    if (!mudouHorario) {
      return;
    }

    setOpcaoRecorrencia("apenas_este");
    setDataLimiteRecorrencia(toDateInput(adicionarDias(inicioNovo, 30)));
    setMovimentacaoPendente({
      origem: "edicao",
      id: Number(edicaoAnterior.id),
      inicioNovo,
      fimNovo,
      inicioOriginal,
      fimOriginal,
      revert: () => undefined,
    });
    setModalRecorrenciaAberto(true);
  }, [agendamentoEditando, carregarAgendamentos, fecharModal, intervalo]);

  const abrirEdicaoSelecionado = useCallback(() => {
    if (!selecionado) return;
    setAgendamentoEditando(selecionado);
    setSlotSelecionado(null);
    setModalAberto(true);
  }, [selecionado]);

  const abrirAtendimentoSelecionado = useCallback(() => {
    if (!selecionado) return;
    router.push(`/atendimento?agendamento_id=${selecionado.id}`);
  }, [router, selecionado]);

  const getRotaNovoLaudo = useCallback((tipo: string, agendamentoId: number) => {
    if (tipo === TIPO_LAUDO_ELETROCARDIOGRAMA) {
      return `/laudos/eletrocardiograma/upload?agendamento_id=${agendamentoId}`;
    }
    if (tipo === TIPO_LAUDO_PRESSAO_ARTERIAL) {
      return `/laudos/novo?agendamento_id=${agendamentoId}&tipo=${TIPO_LAUDO_PRESSAO_ARTERIAL}`;
    }
    const basePath =
      tipo === TIPO_LAUDO_ULTRASSOM_ABDOMINAL ? "/ultrassonografia-abdominal/novo" : "/laudos/novo";
    return `${basePath}?agendamento_id=${agendamentoId}`;
  }, []);

  const laudarSelecionado = useCallback((tipo: string) => {
    if (!selecionado) return;
    const laudoVinculado = obterLaudoVinculado(selecionado.id, tipo);
    if (laudoVinculado?.id) {
      router.push(getLaudoEditPath(laudoVinculado.id, tipo));
      return;
    }
    router.push(getRotaNovoLaudo(tipo, selecionado.id));
  }, [getRotaNovoLaudo, obterLaudoVinculado, router, selecionado]);

  const podeBaixarLaudo = useCallback((status?: string) => {
    const statusNormalizado = (status || "").trim().toLowerCase();
    return statusNormalizado === "finalizado" || statusNormalizado === "arquivado";
  }, []);

  const baixarLaudoPdfSelecionado = useCallback(async () => {
    if (!selecionado || !laudoSelecionado?.id) {
      return;
    }

    try {
      const { baixarLaudoPdf, baixarLaudoPdfOriginal } = await import("@/lib/laudo-pdf");
      if (laudoSelecionado.tipo === TIPO_LAUDO_ELETROCARDIOGRAMA) {
        await baixarLaudoPdfOriginal(
          laudoSelecionado.id,
          `eletrocardiograma_agendamento_${selecionado.id}.pdf`,
        );
        return;
      }
      await baixarLaudoPdf(
        laudoSelecionado.id,
        `laudo_agendamento_${selecionado.id}.pdf`,
      );
    } catch (error) {
      console.error("Erro ao baixar PDF do laudo:", error);
      setErro("Nao foi possivel baixar o PDF do laudo agora.");
    }
  }, [laudoSelecionado?.id, laudoSelecionado?.tipo, selecionado]);

  const abrirModalCriacao = useCallback((data: Date, allDay = false) => {
    setDataControleAgenda(toDateInput(data));
    setAgendamentoEditando(null);
    setSelecionado(null);
    setSlotSelecionado({
      data: toDateInput(data),
      hora: allDay ? "08:00" : toTimeInput(data),
    });
    setModalAberto(true);
  }, []);

  const validarHorarioNaAgenda = useCallback(
    (inicio: Date, fim: Date): { valido: boolean; motivo: string } =>
      validarHorarioAgendamento(inicio, fim, agendaSemanal, agendaFeriados, agendaExcecoes),
    [agendaExcecoes, agendaFeriados, agendaSemanal]
  );

  const alternarAberturaAgendaDia = useCallback(async () => {
    const jornada = obterJornadaDia(dataControleAgenda, agendaSemanal, agendaFeriados, agendaExcecoes);
    const diaData = new Date(`${dataControleAgenda}T00:00:00`);
    const diaSemana = diaData.getDay();
    const diaKey = String(diaSemana === 0 ? 7 : diaSemana) as keyof AgendaSemanalConfig;
    const diaBase = agendaSemanal[diaKey] || DEFAULT_AGENDA_SEMANAL[diaKey];
    const excecaoExistente = agendaExcecoes.find((item) => item.data === dataControleAgenda);

    const inicioPadrao = jornada.inicio !== "00:00" ? jornada.inicio : diaBase.inicio;
    const fimPadrao = jornada.fim !== "00:00" ? jornada.fim : diaBase.fim;

    let novasExcecoes: AgendaExcecaoConfig[];
    if (jornada.fechado) {
      const abertura = {
        data: dataControleAgenda,
        ativo: true,
        inicio: excecaoExistente?.inicio || inicioPadrao,
        fim: excecaoExistente?.fim || fimPadrao,
        motivo: excecaoExistente?.motivo || "Abertura manual no FullCalendar",
      };
      novasExcecoes = [...agendaExcecoes.filter((item) => item.data !== dataControleAgenda), abertura];
    } else {
      const fechamento = {
        data: dataControleAgenda,
        ativo: false,
        inicio: excecaoExistente?.inicio || jornada.inicio || inicioPadrao,
        fim: excecaoExistente?.fim || jornada.fim || fimPadrao,
        motivo: excecaoExistente?.motivo || "Fechamento manual no FullCalendar",
      };
      novasExcecoes = [...agendaExcecoes.filter((item) => item.data !== dataControleAgenda), fechamento];
    }

    const payloadExcecoes = normalizarAgendaExcecoes(novasExcecoes);

    try {
      setSalvandoAgendaDia(true);
      setErro("");
      await api.put("/configuracoes", { agenda_excecoes: payloadExcecoes });
      setAgendaExcecoes(payloadExcecoes);
      setMensagemStatus(
        jornada.fechado
          ? `Agenda aberta em ${dataControleAgenda}.`
          : `Agenda fechada em ${dataControleAgenda}.`
      );
    } catch (error: any) {
      console.error("Erro ao atualizar abertura/fechamento da agenda:", error);
      if (error?.response?.status === 403) {
        setErro("Sem permissao para alterar abertura/fechamento da agenda.");
      } else {
        setErro(
          extrairMensagemErroApi(
            error?.response?.data?.detail,
            "Nao foi possivel atualizar a agenda desta data."
          )
        );
      }
    } finally {
      setSalvandoAgendaDia(false);
    }
  }, [agendaExcecoes, agendaFeriados, agendaSemanal, dataControleAgenda]);

  const atualizarStatusAgendamento = useCallback(
    async (agendamentoId: number, novoStatus: StatusAgenda, tipoHorarioParam?: "comercial" | "plantao") => {
      setErro("");
      setMensagemStatus("");
      setAtualizandoStatusId(agendamentoId);
      setMenuStatusAberto(false);

      try {
        const enviarAtualizacao = (
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
          return api.patch(`/agenda/${agendamentoId}/status?${params.toString()}`);
        };

        let response;
        let confirmouReservaExpirada = false;
        let confirmouConflitoDeslocamento = false;
        // Reativação tardia pode exigir duas confirmações em sequência
        // (reserva expirada e conflito de rota), daí o retry em laço.
        for (let tentativa = 0; tentativa < 3 && !response; tentativa += 1) {
          try {
            response = await enviarAtualizacao(
              confirmouReservaExpirada,
              confirmouConflitoDeslocamento
            );
          } catch (errorTentativa: any) {
            const detail = errorTentativa?.response?.data?.detail;
            const codigo =
              errorTentativa?.response?.status === 409 ? detail?.codigo : undefined;
            if (
              codigo === "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA" &&
              !confirmouReservaExpirada
            ) {
              const confirmou = await fortinho.confirm({
                title: "Confirmação recebida após o prazo",
                message:
                  "Confirme somente se este mesmo cliente respondeu depois do vencimento. O sistema verificará se o horário ainda está livre antes de mudar o status para Agendado.",
                mood: "alert",
                gesture: "open-arms",
                confirmLabel: "Cliente confirmou; agendar",
                cancelLabel: "Cancelar",
              });
              if (!confirmou) return;
              confirmouReservaExpirada = true;
              continue;
            }
            if (codigo === "CONFLITO_DESLOCAMENTO" && !confirmouConflitoDeslocamento) {
              // Exceção de rota é prerrogativa de admin.
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
        setErro("");
        setMensagemStatus(response.data?.mensagem || `Status atualizado para ${novoStatus}.`);

        if (intervalo) {
          await carregarAgendamentos(intervalo);
        }
      } catch (error: any) {
        console.error("Erro ao atualizar status via FullCalendar:", error);
        setErro(
          extrairMensagemErroApi(
            error?.response?.data?.detail,
            "Nao foi possivel atualizar o status deste agendamento."
          )
        );
      } finally {
        setAtualizandoStatusId(null);
      }
    },
    [carregarAgendamentos, fortinho, intervalo, isAdmin]
  );

  const executarAcaoStatus = useCallback(
    (acao: AgendaStatusAction) => {
      if (!selecionado) return;

      if (selecionado.status === acao.status) {
        setMensagemStatus(`Este agendamento ja esta com status ${acao.status}.`);
        setMenuStatusAberto(false);
        return;
      }

      if (
        selecionado.status === "Expirado" &&
        acao.status === "Agendado" &&
        (!selecionado.paciente_id || !selecionado.tutor_id)
      ) {
        setErro(
          "Antes de confirmar tardiamente, edite a reserva e preencha os dados do tutor e do pet. Depois use 'Agendar após confirmação tardia'."
        );
        setMenuStatusAberto(false);
        return;
      }

      if (acao.precisaTipoHorario) {
        setTipoHorario("comercial");
        setModalTipoHorario({ id: selecionado.id, status: acao.status });
        setMenuStatusAberto(false);
        return;
      }

      void atualizarStatusAgendamento(selecionado.id, acao.status);
    },
    [atualizarStatusAgendamento, selecionado]
  );

  const abrirModalReabilitarReserva = useCallback(() => {
    setErro("");
    setMensagemStatus("");
    setPrazoReabilitacaoHoras(String(PRAZO_REABILITACAO_HORAS_PADRAO));
    setMenuStatusAberto(false);
    setModalReabilitarReservaAberto(true);
  }, []);

  const confirmarReabilitacaoReserva = useCallback(async () => {
    if (!selecionado) return;

    setErro("");
    const horas = normalizarPrazoReabilitacaoHoras(prazoReabilitacaoHoras);
    if (horas === null) {
      setErro(
        `Informe um prazo entre ${PRAZO_REABILITACAO_HORAS_MIN} e ${PRAZO_REABILITACAO_HORAS_MAX} horas.`
      );
      return;
    }

    setReabilitandoReservaId(selecionado.id);
    try {
      const enviarReabilitacao = (
        confirmarSlotReservaExpirada = false,
        confirmarConflitoDeslocamento = false
      ) =>
        api.post(`/agenda/${selecionado.id}/reabilitar-reserva`, {
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

      setModalReabilitarReservaAberto(false);
      setErro("");
      setMensagemStatus(
        response.data?.mensagem ||
          "Reserva reabilitada: o horário voltou a ficar reservado até o novo prazo."
      );
      if (intervalo) {
        await carregarAgendamentos(intervalo);
      }
    } catch (error: any) {
      console.error("Erro ao reabilitar reserva expirada:", error);
      setErro(
        extrairMensagemErroApi(
          error?.response?.data?.detail,
          "Nao foi possivel reabilitar a reserva deste horario."
        )
      );
    } finally {
      setReabilitandoReservaId(null);
    }
  }, [carregarAgendamentos, fortinho, intervalo, isAdmin, prazoReabilitacaoHoras, selecionado]);

  const confirmarAtualizacaoRealizado = useCallback(async () => {
    if (!modalTipoHorario) return;
    await atualizarStatusAgendamento(modalTipoHorario.id, modalTipoHorario.status, tipoHorario);
    setModalTipoHorario(null);
  }, [atualizarStatusAgendamento, modalTipoHorario, tipoHorario]);

  const abrirRecebimentoPagamentoModal = useCallback(() => {
    if (!selecionado) return;

    const osVinculada = ordensServicoPorAgendamento[selecionado.id];
    if (!osVinculada) {
      setErro("Este agendamento nao possui ordem de servico vinculada para recebimento.");
      return;
    }
    if (osEstaPaga(osVinculada.status)) {
      setMensagemStatus(`A OS ${osVinculada.numero_os || osVinculada.id} ja esta paga.`);
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
    setDataRecebimentoPagamento(toDateInput(new Date()));
    setDestinoCreditoExcedente("cliente");
    setSaldoCreditoClientePagamento(0);
    setCarregandoSaldoCreditoPagamento(false);
    setErroSaldoCreditoPagamento("");
    setUsarCreditoClientePagamento(false);
    setValorCreditoUtilizadoPagamento("0.00");
    setModalPagamentoAberto(true);
    if (!formasPagamentoDisponiveis.length) {
      void carregarFormasPagamento();
    }
  }, [carregarFormasPagamento, formasPagamentoDisponiveis, ordensServicoPorAgendamento, selecionado]);

  const abrirAgendaLista = useCallback(() => {
    const params = new URLSearchParams();
    params.set("data", dataControleAgenda || toDateInput(new Date()));
    params.set("visao", "lista");
    if (filtroStatus !== "todos") {
      params.set("status", filtroStatus);
    }
    if (filtroOrigemAtendimento !== "todos") {
      params.set("origem_atendimento", filtroOrigemAtendimento);
    }
    router.push(`/agenda?${params.toString()}`);
  }, [dataControleAgenda, filtroOrigemAtendimento, filtroStatus, router]);

  const receberPagamentoSelecionado = useCallback(async () => {
    if (!selecionado) return;
    const osVinculada = ordensServicoPorAgendamento[selecionado.id];
    if (!osVinculada) {
      setErro("Este agendamento nao possui ordem de servico vinculada para recebimento.");
      setModalPagamentoAberto(false);
      return;
    }

    try {
      setRecebendoPagamentoId(selecionado.id);
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

      setMensagemStatus(
        `Pagamento recebido para a OS ${osVinculada.numero_os || osVinculada.id}.`
      );
      setModalPagamentoAberto(false);
      setPagamentosRecebimento([]);
      setSaldoCreditoClientePagamento(0);
      setCarregandoSaldoCreditoPagamento(false);
      setErroSaldoCreditoPagamento("");
      setUsarCreditoClientePagamento(false);
      setValorCreditoUtilizadoPagamento("0.00");
      setDescontoPagamento("0.00");
      if (intervalo) {
        await carregarAgendamentos(intervalo);
      }
    } catch (error: any) {
      console.error("Erro ao receber pagamento da OS:", error);
      setErro(
        extrairMensagemErroApi(
          error?.response?.data?.detail,
          "Nao foi possivel registrar o recebimento desta OS."
        )
      );
    } finally {
      setRecebendoPagamentoId(null);
    }
  }, [
    carregarAgendamentos,
    dataRecebimentoPagamento,
    destinoCreditoExcedente,
    intervalo,
    ordensServicoPorAgendamento,
    resumoPagamentoModal.valorOs,
    resumoPagamentoModal.descontoAplicado,
    resumoPagamentoModal.linhas,
    resumoPagamentoModal.creditoUtilizado,
    selecionado,
  ]);

  const excluirSelecionado = useCallback(async () => {
    if (!selecionado) return;
    const confirmar = await fortinho.confirm({
      title: "Excluir agendamento",
      message: "Deseja realmente excluir este agendamento?",
      confirmLabel: "Excluir",
      cancelLabel: "Cancelar",
      mood: "alert",
      gesture: "open-arms",
    });
    if (!confirmar) return;

    try {
      setExcluindoAgendamentoId(selecionado.id);
      setErro("");
      await api.delete(`/agenda/${selecionado.id}`);
      setMensagemStatus("Agendamento excluido com sucesso.");
      setSelecionado(null);
      if (intervalo) {
        await carregarAgendamentos(intervalo);
      }
    } catch (error: any) {
      console.error("Erro ao excluir agendamento no FullCalendar:", error);
      if (error?.response?.status === 403) {
        setErro("Apenas administradores e a equipe de recepção podem excluir agendamentos.");
      } else {
        setErro(
          extrairMensagemErroApi(error?.response?.data?.detail, "Nao foi possivel excluir este agendamento.")
        );
      }
    } finally {
      setExcluindoAgendamentoId(null);
    }
  }, [carregarAgendamentos, fortinho, intervalo, selecionado]);

  const existeConflitoSlot = useCallback(
    (inicio: Date, fim: Date, agendamentoIgnoradoId?: number) => {
      return agendamentos.some((agendamento) => {
        if (agendamentoIgnoradoId && agendamento.id === agendamentoIgnoradoId) {
          return false;
        }
        if (["Cancelado", "Expirado"].includes(String(agendamento.status || "").trim())) {
          return false;
        }

        const inicioExistente = parseInicioLocal(agendamento);
        if (!inicioExistente) {
          return false;
        }
        const fimExistente = parseFimLocal(agendamento, inicioExistente);
        return inicio < fimExistente && fim > inicioExistente;
      });
    },
    [agendamentos]
  );

  const handleDatesSet = useCallback((arg: DatesSetArg) => {
    const inicio = toDateInput(arg.start);
    const fimExclusivo = new Date(arg.end);
    fimExclusivo.setDate(fimExclusivo.getDate() - 1);
    const fim = toDateInput(fimExclusivo);

    setIntervalo((atual) => {
      if (atual?.inicio === inicio && atual?.fim === fim) {
        return atual;
      }
      return { inicio, fim };
    });
  }, []);

  const atualizarHorarioAgendamento = useCallback(
    async ({ id, inicio, fim, revert }: AtualizacaoHorarioArgs) => {
      const agendamento = agendamentos.find((item) => item.id === id);
      if (!agendamento) {
        revert();
        setErro("Nao foi possivel localizar o agendamento para atualizar.");
        return;
      }

      const validacaoHorario = validarHorarioNaAgenda(inicio, fim);
      if (!validacaoHorario.valido) {
        revert();
        setErro(validacaoHorario.motivo || "Horario fora do funcionamento da agenda.");
        return;
      }

      if (existeConflitoSlot(inicio, fim, id)) {
        revert();
        setErro("Slot ocupado: ja existe outro atendimento neste horario.");
        return;
      }

      try {
        setSalvandoMovimentacao(true);
        setErro("");

        const payloadBase = {
          paciente_id: agendamento.paciente_id ?? null,
          clinica_id: agendamento.clinica_id ?? null,
          servico_id: agendamento.servico_id ?? null,
          inicio: toApiDateTime(inicio),
          fim: toApiDateTime(fim),
          status: agendamento.status || "Agendado",
          observacoes: agendamento.observacoes || "",
        };

        const enviarAtualizacao = async () => {
          await api.put(`/agenda/${id}`, payloadBase);
        };

        try {
          await enviarAtualizacao();
        } catch (error: any) {
          const conflito = extrairConflitoDeslocamento(error);
          if (conflito) {
            throw new Error(
              extrairMensagemErroApi(
                conflito,
                "Conflito operacional de deslocamento. Ajuste o horario ou escolha outra clinica."
              )
            );
          }
          throw error;
        }

        if (intervalo) {
          await carregarAgendamentos(intervalo);
        }
        setDataControleAgenda(toDateInput(inicio));
      } catch (error: any) {
        console.error("Erro ao mover/redimensionar agendamento:", error);
        revert();
        setErro(
          extrairMensagemErroApi(
            error?.response?.data?.detail,
            "Nao foi possivel salvar a alteracao do horario. A mudanca foi desfeita."
          )
        );
      } finally {
        setSalvandoMovimentacao(false);
      }
    },
    [agendamentos, carregarAgendamentos, existeConflitoSlot, fortinho, intervalo, validarHorarioNaAgenda]
  );

  const abrirFluxoRecorrenciaMovimentacao = useCallback(
    ({ id, inicio, fim, revert }: AtualizacaoHorarioArgs) => {
      const agendamento = agendamentos.find((item) => item.id === id);
      if (!agendamento) {
        revert();
        setErro("Nao foi possivel identificar o agendamento para atualizar.");
        return;
      }

      const inicioOriginal = parseInicioLocal(agendamento);
      if (!inicioOriginal) {
        revert();
        setErro("Nao foi possivel identificar o horario original do agendamento.");
        return;
      }
      const fimOriginal = parseFimLocal(agendamento, inicioOriginal);

      setErro("");
      setMensagemStatus("");
      setOpcaoRecorrencia("apenas_este");
      setDataLimiteRecorrencia(toDateInput(adicionarDias(inicio, 30)));
      setMovimentacaoPendente({
        origem: "movimentacao",
        id,
        inicioNovo: inicio,
        fimNovo: fim,
        inicioOriginal,
        fimOriginal,
        revert,
      });
      setModalRecorrenciaAberto(true);
    },
    [agendamentos]
  );

  const cancelarRecorrenciaMovimentacao = useCallback(() => {
    if (movimentacaoPendente?.origem === "movimentacao") {
      movimentacaoPendente.revert();
    }
    setModalRecorrenciaAberto(false);
    setMovimentacaoPendente(null);
    setOpcaoRecorrencia("apenas_este");
  }, [movimentacaoPendente]);

  const gerarIniciosRecorrencia = useCallback(
    (inicioBase: Date, opcao: OpcaoRecorrencia, dataLimite: Date): Date[] => {
      const resultado: Date[] = [];
      const limite = new Date(dataLimite);
      limite.setHours(23, 59, 59, 999);

      if (opcao === "cada_7_dias") {
        let cursor = adicionarDias(inicioBase, 7);
        while (cursor <= limite) {
          resultado.push(new Date(cursor));
          cursor = adicionarDias(cursor, 7);
        }
        return resultado;
      }

      let cursor = adicionarDias(inicioBase, 1);
      while (cursor <= limite) {
        const diaSemana = cursor.getDay();
        if (opcao === "todos_os_dias") {
          resultado.push(new Date(cursor));
        } else if (opcao === "seg_a_sex" && diaSemana >= 1 && diaSemana <= 5) {
          resultado.push(new Date(cursor));
        }
        cursor = adicionarDias(cursor, 1);
      }

      return resultado;
    },
    []
  );

  const confirmarRecorrenciaMovimentacao = useCallback(async () => {
    if (!movimentacaoPendente) return;

    const { id, inicioNovo, fimNovo, revert, origem } = movimentacaoPendente;
    const agendamento = agendamentos.find((item) => item.id === id);
    if (!agendamento) {
      revert();
      setModalRecorrenciaAberto(false);
      setMovimentacaoPendente(null);
      setErro("Nao foi possivel localizar o agendamento para aplicar recorrencia.");
      return;
    }

    if (opcaoRecorrencia === "apenas_este") {
      setModalRecorrenciaAberto(false);
      setMovimentacaoPendente(null);
      if (origem === "movimentacao") {
        await atualizarHorarioAgendamento({ id, inicio: inicioNovo, fim: fimNovo, revert });
      } else {
        setMensagemStatus("Alteracao aplicada somente neste agendamento.");
      }
      return;
    }

    const limite = new Date(`${dataLimiteRecorrencia}T23:59:59`);
    if (Number.isNaN(limite.getTime()) || limite < inicioNovo) {
      setErro("Informe uma data limite valida para aplicar a recorrencia.");
      return;
    }

    try {
      setAplicandoRecorrencia(true);
      setSalvandoMovimentacao(true);
      setErro("");

      const validacaoHorario = validarHorarioNaAgenda(inicioNovo, fimNovo);
      if (!validacaoHorario.valido) {
        if (origem === "movimentacao") {
          revert();
        }
        setErro(validacaoHorario.motivo || "Horario fora do funcionamento da agenda.");
        setModalRecorrenciaAberto(false);
        setMovimentacaoPendente(null);
        return;
      }

      if (existeConflitoSlot(inicioNovo, fimNovo, id)) {
        if (origem === "movimentacao") {
          revert();
        }
        setErro("Slot ocupado: ja existe outro atendimento neste horario.");
        setModalRecorrenciaAberto(false);
        setMovimentacaoPendente(null);
        return;
      }

      if (origem === "movimentacao") {
        const payloadBase = {
          paciente_id: agendamento.paciente_id ?? null,
          clinica_id: agendamento.clinica_id ?? null,
          servico_id: agendamento.servico_id ?? null,
          inicio: toApiDateTime(inicioNovo),
          fim: toApiDateTime(fimNovo),
          status: agendamento.status || "Agendado",
          observacoes: agendamento.observacoes || "",
        };

        const enviarAtualizacaoMovimentacao = async () => {
          await api.put(`/agenda/${id}`, payloadBase);
        };

        try {
          await enviarAtualizacaoMovimentacao();
        } catch (error: any) {
          const conflito = extrairConflitoDeslocamento(error);
          if (conflito) {
            throw new Error(
              extrairMensagemErroApi(
                conflito,
                "Conflito operacional de deslocamento. Ajuste o horario ou escolha outra clinica."
              )
            );
          }
          throw error;
        }
      }

      const duracaoMs = Math.max(5 * 60000, fimNovo.getTime() - inicioNovo.getTime());
      const iniciosRecorrencia = gerarIniciosRecorrencia(inicioNovo, opcaoRecorrencia, limite);
      const ocupacoesLocais: Array<{ inicio: Date; fim: Date }> = [{ inicio: inicioNovo, fim: fimNovo }];
      let criados = 0;
      let pulados = 0;
      let falhas = 0;

      for (const inicioData of iniciosRecorrencia) {
        const inicioRecorrente = combinarDataComHorario(inicioData, inicioNovo);
        const fimRecorrente = new Date(inicioRecorrente.getTime() + duracaoMs);
        const validacaoRecorrente = validarHorarioNaAgenda(inicioRecorrente, fimRecorrente);
        if (!validacaoRecorrente.valido) {
          pulados += 1;
          continue;
        }

        const conflitaLocal = ocupacoesLocais.some(
          (slot) => inicioRecorrente < slot.fim && fimRecorrente > slot.inicio
        );
        if (conflitaLocal || existeConflitoSlot(inicioRecorrente, fimRecorrente)) {
          pulados += 1;
          continue;
        }

        try {
          await api.post("/agenda", {
            paciente_id: agendamento.paciente_id ?? null,
            tutor_id: agendamento.tutor_id ?? null,
            clinica_id: agendamento.clinica_id ?? null,
            servico_id: agendamento.servico_id ?? null,
            origem_atendimento: agendamento.origem_atendimento || "clinica_parceira",
            inicio: toApiDateTime(inicioRecorrente),
            fim: toApiDateTime(fimRecorrente),
            status: agendamento.status || "Agendado",
            observacoes: agendamento.observacoes || "",
          });
          ocupacoesLocais.push({ inicio: inicioRecorrente, fim: fimRecorrente });
          criados += 1;
        } catch (error: any) {
          if (error?.response?.status === 409 || error?.response?.status === 422) {
            pulados += 1;
          } else {
            falhas += 1;
          }
        }
      }

      if (intervalo) {
        await carregarAgendamentos(intervalo);
      }

      setMensagemStatus(
        `Alteracao aplicada. Recorrencias criadas: ${criados}. Puladas: ${pulados}. Falhas: ${falhas}.`
      );
      setDataControleAgenda(toDateInput(inicioNovo));
      setModalRecorrenciaAberto(false);
      setMovimentacaoPendente(null);
    } catch (error: any) {
      console.error("Erro ao aplicar recorrencia de horario:", error);
      if (origem === "movimentacao") {
        revert();
      }
      setErro(
        extrairMensagemErroApi(
          error?.response?.data?.detail,
          "Nao foi possivel aplicar a alteracao recorrente."
        )
      );
      setModalRecorrenciaAberto(false);
      setMovimentacaoPendente(null);
    } finally {
      setAplicandoRecorrencia(false);
      setSalvandoMovimentacao(false);
    }
  }, [
    agendamentos,
    carregarAgendamentos,
    dataLimiteRecorrencia,
    existeConflitoSlot,
    fortinho,
    gerarIniciosRecorrencia,
    intervalo,
    movimentacaoPendente,
    opcaoRecorrencia,
    atualizarHorarioAgendamento,
    validarHorarioNaAgenda,
  ]);

  const eventos = useMemo<EventInput[]>(() => {
    const lista: EventInput[] = [];

    for (const ag of agendamentos) {
      if (filtroStatus !== "todos" && ag.status !== filtroStatus) {
        continue;
      }
      const origemAtual = String(ag.origem_atendimento || "clinica_parceira").trim() || "clinica_parceira";
      if (filtroOrigemAtendimento !== "todos" && origemAtual !== filtroOrigemAtendimento) {
        continue;
      }

      const inicio = parseInicioLocal(ag);
      if (!inicio) {
        continue;
      }

      const fim = parseFimLocal(ag, inicio);
      const statusVisual = STATUS_CORES[ag.status] || {
        bg: "#e5e7eb",
        border: "#9ca3af",
        text: "#111827",
      };
      const { destino } = resolverDestinoAgendamento(ag);
      const wazeUrl = montarWazeWebUrl(destino);

      lista.push({
        id: String(ag.id),
        title: obterTituloAgendamentoPorOrigem(ag.origem_atendimento, ag.clinica),
        start: inicio,
        end: fim,
        backgroundColor: statusVisual.bg,
        borderColor: statusVisual.border,
        textColor: statusVisual.text,
        extendedProps: {
          agendamento: ag,
          wazeUrl,
        },
      });
    }

    return lista;
  }, [agendamentos, filtroOrigemAtendimento, filtroStatus, montarWazeWebUrl, resolverDestinoAgendamento]);

  const handleEventClick = useCallback((arg: EventClickArg) => {
    const agendamento = arg.event.extendedProps.agendamento as Agendamento | undefined;
    if (!agendamento) return;
    setSelecionado(agendamento);
    const inicio = parseInicioLocal(agendamento);
    if (inicio) {
      setDataControleAgenda(toDateInput(inicio));
    }
    setMensagemStatus("");
  }, []);

  const handleDateClick = useCallback(
    async (arg: DateClickArg) => {
      const inicio = new Date(arg.date);
      if (arg.allDay) {
        const jornada = obterJornadaDia(toDateInput(inicio), agendaSemanal, agendaFeriados, agendaExcecoes);
        const [horaJornada = "08", minutoJornada = "00"] = String(jornada.inicio || "08:00").split(":");
        inicio.setHours(Number(horaJornada), Number(minutoJornada), 0, 0);
      }
      const fim = new Date(inicio.getTime() + duracaoSlotMinutos * 60000);
      const validacaoHorario = validarHorarioNaAgenda(inicio, fim);
      if (!validacaoHorario.valido) {
        if (isAdmin) {
          setErro("");
          abrirModalCriacao(inicio, false);
          return;
        }
        setErro(validacaoHorario.motivo || "Agenda fechada para este horario.");
        return;
      }
      if (existeConflitoSlot(inicio, fim)) {
        setErro("Slot ocupado: selecione outro horario livre.");
        return;
      }
      setErro("");
      abrirModalCriacao(inicio, false);
    },
    [
      agendaExcecoes,
      agendaFeriados,
      agendaSemanal,
      abrirModalCriacao,
      duracaoSlotMinutos,
      existeConflitoSlot,
      isAdmin,
      validarHorarioNaAgenda,
    ]
  );

  const handleSelect = useCallback(
    async (arg: DateSelectArg) => {
      const inicio = new Date(arg.start);
      if (arg.allDay) {
        const jornada = obterJornadaDia(toDateInput(inicio), agendaSemanal, agendaFeriados, agendaExcecoes);
        const [horaJornada = "08", minutoJornada = "00"] = String(jornada.inicio || "08:00").split(":");
        inicio.setHours(Number(horaJornada), Number(minutoJornada), 0, 0);
      }
      const fim = arg.allDay
        ? new Date(inicio.getTime() + duracaoSlotMinutos * 60000)
        : arg.end
          ? new Date(arg.end)
          : new Date(inicio.getTime() + duracaoSlotMinutos * 60000);
      const validacaoHorario = validarHorarioNaAgenda(inicio, fim);
      if (!validacaoHorario.valido) {
        if (isAdmin) {
          setErro("");
          abrirModalCriacao(inicio, false);
          return;
        }
        setErro(validacaoHorario.motivo || "Agenda fechada para este horario.");
        return;
      }
      if (existeConflitoSlot(inicio, fim)) {
        setErro("Intervalo ocupado: nao e permitido mais de um atendimento no mesmo slot.");
        return;
      }
      setErro("");
      abrirModalCriacao(inicio, false);
    },
    [
      agendaExcecoes,
      agendaFeriados,
      agendaSemanal,
      abrirModalCriacao,
      duracaoSlotMinutos,
      existeConflitoSlot,
      isAdmin,
      validarHorarioNaAgenda,
    ]
  );

  const handleEventDrop = useCallback(
    (arg: EventDropArg) => {
      const id = Number(arg.event.id);
      const inicio = arg.event.start;

      if (!Number.isFinite(id) || !inicio) {
        arg.revert();
        setErro("Nao foi possivel identificar o agendamento para mover.");
        return;
      }

      const fim = arg.event.end ? new Date(arg.event.end) : new Date(inicio.getTime() + 30 * 60000);
      abrirFluxoRecorrenciaMovimentacao({ id, inicio: new Date(inicio), fim, revert: arg.revert });
    },
    [abrirFluxoRecorrenciaMovimentacao]
  );

  const handleEventResize = useCallback(
    (arg: EventResizeDoneArg) => {
      const id = Number(arg.event.id);
      const inicio = arg.event.start;

      if (!Number.isFinite(id) || !inicio) {
        arg.revert();
        setErro("Nao foi possivel identificar o agendamento para redimensionar.");
        return;
      }

      const fim = arg.event.end ? new Date(arg.event.end) : new Date(inicio.getTime() + 30 * 60000);
      abrirFluxoRecorrenciaMovimentacao({ id, inicio: new Date(inicio), fim, revert: arg.revert });
    },
    [abrirFluxoRecorrenciaMovimentacao]
  );

  const renderEventContent = useCallback((eventInfo: EventContentArg) => {
    const agendamento = eventInfo.event.extendedProps.agendamento as Agendamento | undefined;
    const origemMeta = obterOrigemAtendimentoMeta(agendamento?.origem_atendimento);
    const titulo = String(
      eventInfo.event.title || obterTituloAgendamentoPorOrigem(agendamento?.origem_atendimento, agendamento?.clinica)
    );

    return (
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className={origemMeta.compactBadgeClassName}>{origemMeta.label}</span>
        <span className="block truncate text-[11px] font-semibold leading-tight">{titulo}</span>
      </div>
    );
  }, []);

  const permiteInteracaoHorarioAgenda = useCallback(
    (inicio: Date, fim: Date) => validarHorarioNaAgenda(inicio, fim).valido,
    [validarHorarioNaAgenda]
  );

  const obterEstadoSlotAgenda = useCallback(
    (dataSlot?: Date) => {
      if (!dataSlot) {
        return {
          fechado: false,
          motivo: "",
        };
      }

      const dataIso = toDateInput(dataSlot);
      const jornada = obterJornadaDia(dataIso, agendaSemanal, agendaFeriados, agendaExcecoes);
      const horaSlot = toTimeInput(dataSlot);
      const fechado = !slotDentroDaJornada(horaSlot, jornada);

      return {
        fechado,
        motivo: jornada.motivo || "Agenda fechada",
      };
    },
    [agendaExcecoes, agendaFeriados, agendaSemanal]
  );

  const slotLaneClassNames = useCallback(
    (slotInfo: { date?: Date }) => {
      const estado = obterEstadoSlotAgenda(slotInfo.date);
      return estado.fechado ? ["bg-gray-100"] : [];
    },
    [obterEstadoSlotAgenda]
  );

  const slotLaneContent = useCallback(
    (slotInfo: { date?: Date }) => {
      const estado = obterEstadoSlotAgenda(slotInfo.date);
      if (!estado.fechado) return null;

      return (
        <div className="pointer-events-none flex h-full items-center justify-center px-1">
          <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600">
            Agenda fechada
          </span>
        </div>
      );
    },
    [obterEstadoSlotAgenda]
  );

  const slotLaneDidMount = useCallback(
    (slotInfo: { date?: Date; el: HTMLElement }) => {
      const estado = obterEstadoSlotAgenda(slotInfo.date);
      if (estado.fechado) {
        slotInfo.el.title = estado.motivo;
        return;
      }
      slotInfo.el.removeAttribute("title");
    },
    [obterEstadoSlotAgenda]
  );

  return (
    <DashboardLayout>
      <div className="fc-agenda-page fc-calendar-page">
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

        <div className="fc-agenda-header fc-calendar-header">
          <div>
            <span className="fc-agenda-kicker">
              <CalendarDays className="h-4 w-4" />
              Visão avançada
            </span>
            <h1>Calendário operacional</h1>
            <p>Clique em um horário vazio para criar e arraste eventos para reorganizar o fluxo.</p>
          </div>

          <div className="fc-calendar-controls">
            <button
              type="button"
              onClick={abrirAgendaLista}
              className="fc-agenda-button-secondary"
            >
              <List className="h-4 w-4" />
              Ver lista
            </button>
            <select
              value={filtroStatus}
              onChange={(event) => setFiltroStatus(event.target.value)}
              className="fc-agenda-control"
            >
              {STATUS_FILTRO.map((status) => (
                <option key={status} value={status}>
                  {status === "todos" ? "Todos os status" : status}
                </option>
              ))}
            </select>

            <select
              value={filtroOrigemAtendimento}
              onChange={(event) => setFiltroOrigemAtendimento(event.target.value)}
              className="fc-agenda-control"
            >
              <option value="todos">Todas as origens</option>
              <option value="clinica_parceira">Clinica parceira</option>
              <option value="domiciliar">Atendimento domiciliar</option>
            </select>

            <input
              type="date"
              value={dataControleAgenda}
              onChange={(event) => setDataControleAgenda(event.target.value || toDateInput(new Date()))}
              className="fc-agenda-control"
            />

            {isAdmin ? (
              <button
                onClick={alternarAberturaAgendaDia}
                disabled={salvandoAgendaDia}
                className={`fc-agenda-button-state ${
                  jornadaDataControle.fechado
                    ? "fc-agenda-button-state-open"
                    : "fc-agenda-button-state-close"
                }`}
              >
                {salvandoAgendaDia
                  ? "Salvando..."
                  : jornadaDataControle.fechado
                    ? "Abrir data"
                    : "Fechar data"}
              </button>
            ) : (
              <span className="fc-calendar-admin-note">
                Somente admin pode abrir/fechar agenda
              </span>
            )}

            <button
              onClick={() => intervalo && carregarAgendamentos(intervalo)}
              disabled={!intervalo || loading || salvandoMovimentacao}
              className="fc-agenda-button-primary"
            >
              <RefreshCw className={`h-4 w-4 ${loading || salvandoMovimentacao ? "animate-spin" : ""}`} />
              {salvandoMovimentacao ? "Salvando..." : "Atualizar"}
            </button>
          </div>
        </div>

        <div className="fc-calendar-day-state">
          Data {dataControleAgenda}:{" "}
          <strong>{jornadaDataControle.fechado ? "fechada" : "aberta"}</strong>
          {jornadaDataControle.motivo ? ` (${jornadaDataControle.motivo})` : ""}
          {excecaoDataControle ? " - com excecao cadastrada." : ""}
        </div>

        {transicaoRegionalAtiva && <AgendaDayOpportunities key={identidadeAgenda} data={dataControleAgenda} identityKey={identidadeAgenda} />}

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

        <div className="fc-calendar-surface">
          <AgendaFullCalendarView
            events={eventos}
            eventContent={renderEventContent}
            datesSet={handleDatesSet}
            eventClick={handleEventClick}
            dateClick={handleDateClick}
            select={handleSelect}
            eventDrop={handleEventDrop}
            eventResize={handleEventResize}
            businessHours={businessHours}
            selectAllow={(selectInfo) =>
              isAdmin || permiteInteracaoHorarioAgenda(selectInfo.start, selectInfo.end ?? selectInfo.start)
            }
            eventAllow={(dropInfo) => permiteInteracaoHorarioAgenda(dropInfo.start, dropInfo.end ?? dropInfo.start)}
            eventOverlap={(stillEvent, movingEvent) => {
              const statusStill = String(
                ((stillEvent.extendedProps?.agendamento as Agendamento | undefined)?.status || "").trim()
              );
              const statusMoving = String(
                ((movingEvent?.extendedProps?.agendamento as Agendamento | undefined)?.status || "").trim()
              );
              return ["Cancelado", "Expirado"].includes(statusStill) || ["Cancelado", "Expirado"].includes(statusMoving);
            }}
            selectOverlap={(event) => {
              const statusExistente = String(
                ((event.extendedProps?.agendamento as Agendamento | undefined)?.status || "").trim()
              );
              return ["Cancelado", "Expirado"].includes(statusExistente);
            }}
            slotMinTime={slotMinTime}
            slotMaxTime={slotMaxTime}
            duracaoSlot={duracaoSlot}
            slotLaneClassNames={slotLaneClassNames}
            slotLaneContent={slotLaneContent}
            slotLaneDidMount={slotLaneDidMount}
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <div className="fc-calendar-summary-card">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-700">
              <CalendarDays className="h-4 w-4" />
              Resumo do periodo carregado
            </div>
            <p className="text-sm text-gray-600">
              {intervalo
                ? `${intervalo.inicio} ate ${intervalo.fim}`
                : "Escolha uma visualizacao para iniciar o carregamento."}
            </p>
            <p className="mt-2 text-2xl font-bold text-gray-900">{eventos.length}</p>
            <p className="text-xs text-gray-500">eventos no filtro atual</p>
            <p className="mt-1 text-xs text-gray-500">
              Grade de slots: {duracaoSlotMinutos} min (configurada em Configuracoes &gt; Funcionamento da Agenda)
            </p>
          </div>

          <div className="fc-calendar-detail-card lg:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-gray-700">Detalhes do evento selecionado</h2>
            {!selecionado ? (
              <p className="text-sm text-gray-500">Clique em um evento para ver os detalhes e abrir as acoes.</p>
            ) : (
              <div className="space-y-3">
                {origemSelecionadoMeta && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-gray-500">Origem do atendimento</span>
                    <span className={origemSelecionadoMeta.badgeClassName}>{origemSelecionadoMeta.descricao}</span>
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={abrirEdicaoSelecionado}
                    className="inline-flex items-center rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                  >
                    Editar Agendamento
                  </button>

                  <button
                    onClick={abrirAtendimentoSelecionado}
                    className="inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-700 hover:bg-violet-100"
                  >
                    <Stethoscope className="h-3.5 w-3.5" />
                    Atender
                  </button>

                  <details className="fc-agenda-row-menu">
                    <summary className="list-none inline-flex cursor-pointer items-center gap-1 rounded-lg border border-teal-200 bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-700 hover:bg-teal-100">
                      <FileText className="h-3.5 w-3.5" />
                      Laudar
                      <ChevronDown className="h-3.5 w-3.5" />
                    </summary>
                    <div className="fc-agenda-row-menu-panel fc-agenda-row-menu-panel-start">
                      <button
                        type="button"
                        onClick={() => laudarSelecionado(TIPO_LAUDO_ECOCARDIOGRAMA)}
                        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50"
                      >
                        <span>Ecocardiograma</span>
                        <span className="text-xs text-gray-500">
                          {obterLaudoVinculado(selecionado.id, TIPO_LAUDO_ECOCARDIOGRAMA)
                            ? "Editar existente"
                            : "Novo laudo"}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => laudarSelecionado(TIPO_LAUDO_ELETROCARDIOGRAMA)}
                        className="flex w-full items-center justify-between gap-3 border-t px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50"
                      >
                        <span>Eletrocardiograma</span>
                        <span className="text-xs text-gray-500">
                          {obterLaudoVinculado(selecionado.id, TIPO_LAUDO_ELETROCARDIOGRAMA)
                            ? "Ver existente"
                            : "Upload PDF"}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => laudarSelecionado(TIPO_LAUDO_PRESSAO_ARTERIAL)}
                        className="flex w-full items-center justify-between gap-3 border-t px-4 py-3 text-left text-sm text-gray-700 hover:bg-gray-50"
                      >
                        <span>Pressao arterial</span>
                        <span className="text-xs text-gray-500">
                          {obterLaudoVinculado(selecionado.id, TIPO_LAUDO_PRESSAO_ARTERIAL)
                            ? "Editar existente"
                            : "Novo laudo"}
                        </span>
                      </button>
                    </div>
                  </details>

                  {laudoSelecionado && podeBaixarLaudo(laudoSelecionado.status) && (
                    <button
                      onClick={baixarLaudoPdfSelecionado}
                      className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Baixar laudo
                    </button>
                  )}

                  {wazeSelecionadoUrl && (
                    <a
                      href={wazeSelecionadoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-100"
                      title="Abrir rota no Waze"
                    >
                      <img
                        src="/icons/waze.svg"
                        alt="Waze"
                        className="h-[14px] w-[14px] rounded-sm object-contain"
                        loading="lazy"
                      />
                      Waze
                    </a>
                  )}

                  {googleMapsSelecionadoUrl && (
                    <a
                      href={googleMapsSelecionadoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
                      title="Abrir rota no Google Maps"
                    >
                      <MapPin className="h-3.5 w-3.5" />
                      Maps
                    </a>
                  )}

                  {podeReabilitarReserva(selecionado.status) && (
                    <button
                      onClick={abrirModalReabilitarReserva}
                      disabled={reabilitandoReservaId === selecionado.id}
                      title="Reservar este horario novamente por mais um periodo"
                      className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <TimerReset className="h-3.5 w-3.5" />
                      {reabilitandoReservaId === selecionado.id ? "Reabilitando..." : "Reabilitar reserva"}
                    </button>
                  )}

                  <div className="relative" ref={statusMenuRef}>
                    <button
                      onClick={() => setMenuStatusAberto((valor) => !valor)}
                      disabled={atualizandoStatusId === selecionado.id}
                      className="inline-flex items-center rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {atualizandoStatusId === selecionado.id ? "Atualizando status..." : "Alterar Status"}
                    </button>

                    {menuStatusAberto && (
                      <div className="absolute left-0 z-30 mt-2 w-56 rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
                        {acoesStatusDisponiveis.length === 0 ? (
                          <div className="px-2 py-2 text-xs text-gray-500">Sem transicoes disponiveis.</div>
                        ) : (
                          acoesStatusDisponiveis.map((acao) => (
                            <button
                              key={acao.status}
                              onClick={() => executarAcaoStatus(acao)}
                              className={`flex w-full items-center justify-between rounded-md px-2 py-2 text-left text-xs font-medium transition-colors ${
                                acao.danger ? "text-red-700 hover:bg-red-50" : "text-gray-700 hover:bg-gray-100"
                              }`}
                            >
                              <span>{acao.label}</span>
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>

                  <button
                    onClick={abrirRecebimentoPagamentoModal}
                    disabled={
                      recebendoPagamentoId === selecionado.id ||
                      !osSelecionada ||
                      osEstaPaga(osSelecionada.status)
                    }
                    className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Wallet className="h-3.5 w-3.5" />
                    {recebendoPagamentoId === selecionado.id ? "Recebendo..." : "Receber Pagamento"}
                  </button>

                  <button
                    onClick={excluirSelecionado}
                    disabled={excluindoAgendamentoId === selecionado.id}
                    className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {excluindoAgendamentoId === selecionado.id ? "Excluindo..." : "Excluir"}
                  </button>

                  <span className="rounded-full border border-gray-200 bg-gray-50 px-2 py-1 text-[11px] font-medium text-gray-700">
                    Status atual: {selecionado.status || "Nao informado"}
                  </span>
                </div>

                {mensagemStatus && (
                  <p className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-700">
                    {mensagemStatus}
                  </p>
                )}

                {osSelecionada ? (
                  <p className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-800">
                    OS: {osSelecionada.numero_os || osSelecionada.id} | Status: {osSelecionada.status} | Valor:{" "}
                    {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                      Number(osSelecionada.valor_final || 0)
                    )}
                  </p>
                ) : (
                  <p className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
                    Sem OS vinculada para este agendamento.
                  </p>
                )}

                <div className="grid gap-2 text-sm sm:grid-cols-2">
                  <p>
                    <span className="font-medium text-gray-700">Paciente:</span>{" "}
                    {selecionado.paciente_id || selecionado.tutor_id ? (
                      <button
                        type="button"
                        onClick={() =>
                          setClienteModalAlvo(
                            selecionado.paciente_id
                              ? { pacienteId: selecionado.paciente_id }
                              : { tutorId: selecionado.tutor_id! }
                          )
                        }
                        className="text-gray-900 hover:text-blue-700 hover:underline"
                        title="Ver e editar dados do cliente"
                      >
                        {selecionado.paciente || "Nao informado"}
                      </button>
                    ) : (
                      <span className="text-gray-900">{selecionado.paciente || "Nao informado"}</span>
                    )}
                  </p>
                  <p>
                    <span className="font-medium text-gray-700">Tutor:</span>{" "}
                    {selecionado.paciente_id || selecionado.tutor_id ? (
                      <button
                        type="button"
                        onClick={() =>
                          setClienteModalAlvo(
                            selecionado.paciente_id
                              ? { pacienteId: selecionado.paciente_id }
                              : { tutorId: selecionado.tutor_id! }
                          )
                        }
                        className="text-gray-900 hover:text-blue-700 hover:underline"
                        title="Ver e editar dados do cliente"
                      >
                        {selecionado.tutor || "Nao informado"}
                      </button>
                    ) : (
                      <span className="text-gray-900">{selecionado.tutor || "Nao informado"}</span>
                    )}
                  </p>
                  <p>
                    <span className="font-medium text-gray-700">
                      {origemSelecionadoMeta?.codigo === "domiciliar" ? "Local:" : "Clinica:"}
                    </span>{" "}
                    <span className="text-gray-900">
                      {obterTituloAgendamentoPorOrigem(selecionado.origem_atendimento, selecionado.clinica)}
                    </span>
                  </p>
                  <p>
                    <span className="font-medium text-gray-700">Servico:</span>{" "}
                    <span className="text-gray-900">{selecionado.servico || "Nao informado"}</span>
                  </p>
                  <p>
                    <span className="font-medium text-gray-700">Horario:</span>{" "}
                    <span className="text-gray-900">{formatarDataHora(selecionado)}</span>
                  </p>
                  <p className="sm:col-span-2">
                    <span className="font-medium text-gray-700">Observacoes:</span>{" "}
                    <span className="text-gray-900">{selecionado.observacoes || "Sem observacoes"}</span>
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {modalRecorrenciaAberto && movimentacaoPendente && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="w-full max-w-lg rounded-xl bg-white p-5 shadow-xl">
              <h3 className="text-lg font-semibold text-gray-900">Como aplicar esta alteracao?</h3>
              <p className="mt-1 text-sm text-gray-600">
                Voce alterou a data/horario do agendamento. Escolha se a mudanca vale somente para este item ou com
                recorrencia.
              </p>

              <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
                <p>
                  <strong>Antes:</strong>{" "}
                  {movimentacaoPendente.inicioOriginal.toLocaleDateString("pt-BR")}{" "}
                  {movimentacaoPendente.inicioOriginal.toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}{" "}
                  -{" "}
                  {movimentacaoPendente.fimOriginal.toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
                <p className="mt-1">
                  <strong>Depois:</strong>{" "}
                  {movimentacaoPendente.inicioNovo.toLocaleDateString("pt-BR")}{" "}
                  {movimentacaoPendente.inicioNovo.toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}{" "}
                  -{" "}
                  {movimentacaoPendente.fimNovo.toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>

              <div className="mt-4 space-y-2">
                {OPCOES_RECORRENCIA.map((opcao) => (
                  <label
                    key={opcao.id}
                    className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${
                      opcaoRecorrencia === opcao.id
                        ? "border-blue-500 bg-blue-50"
                        : "border-gray-200 bg-white hover:bg-gray-50"
                    }`}
                  >
                    <input
                      type="radio"
                      name="opcao_recorrencia"
                      value={opcao.id}
                      checked={opcaoRecorrencia === opcao.id}
                      onChange={() => setOpcaoRecorrencia(opcao.id)}
                      className="mt-0.5"
                    />
                    <span>
                      <strong>{opcao.label}</strong>
                      <span className="block text-xs text-gray-600">{opcao.descricao}</span>
                    </span>
                  </label>
                ))}
              </div>

              {opcaoRecorrencia !== "apenas_este" && (
                <div className="mt-4">
                  <label className="block text-sm font-medium text-gray-700">Repetir ate</label>
                  <input
                    type="date"
                    value={dataLimiteRecorrencia}
                    onChange={(event) => setDataLimiteRecorrencia(event.target.value)}
                    className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>
              )}

              <div className="mt-5 flex justify-end gap-2">
                <button
                  onClick={cancelarRecorrenciaMovimentacao}
                  disabled={aplicandoRecorrencia}
                  className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancelar
                </button>
                <button
                  onClick={confirmarRecorrenciaMovimentacao}
                  disabled={aplicandoRecorrencia}
                  className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {aplicandoRecorrencia ? "Aplicando..." : "Confirmar alteracao"}
                </button>
              </div>
            </div>
          </div>
        )}

        {modalPagamentoAberto && selecionado && osSelecionada && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
              <h3 className="text-lg font-semibold text-gray-900">Confirmar recebimento</h3>
              <p className="mt-1 text-sm text-gray-600">
                Informe as formas de pagamento da OS <strong>{osSelecionada.numero_os || osSelecionada.id}</strong>.
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

              <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                <p>
                  <strong>Valor liquido da OS:</strong>{" "}
                  {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                    Number(resumoPagamentoModal.valorOs || 0)
                  )}
                </p>
                <p className="mt-1">
                  <strong>Paciente:</strong> {selecionado.paciente || "Nao informado"}
                </p>
              </div>

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

              <BaixaCredito
                onBusy={setBaixandoCredito}
                key={selecionado?.paciente_id}
                pacienteId={selecionado?.paciente_id}
                clinicaId={selecionado?.clinica_id}
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
                <div className="flex justify-between">
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

              <div className="mt-5 flex justify-end gap-2">
                <button
                  disabled={baixandoCredito}
                  onClick={() => {
                    setModalPagamentoAberto(false);
                    setSaldoCreditoClientePagamento(0);
                    setCarregandoSaldoCreditoPagamento(false);
                    setErroSaldoCreditoPagamento("");
                    setUsarCreditoClientePagamento(false);
                    setValorCreditoUtilizadoPagamento("0.00");
                    setDescontoPagamento("0.00");
                  }}
                  className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancelar
                </button>
                <button
                  onClick={receberPagamentoSelecionado}
                  disabled={
                    recebendoPagamentoId === selecionado.id ||
                    baixandoCredito ||
                    carregandoFormasPagamento ||
                    resumoPagamentoModal.faltante > 0
                  }
                  className="inline-flex items-center rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {recebendoPagamentoId === selecionado.id ? "Recebendo..." : "Confirmar recebimento"}
                </button>
              </div>
            </div>
          </div>
        )}

        {modalReabilitarReservaAberto && selecionado && (() => {
          const horasInformadas = normalizarPrazoReabilitacaoHoras(prazoReabilitacaoHoras);
          const previsao =
            horasInformadas === null
              ? null
              : calcularPrazoReabilitacao(horasInformadas, selecionado.inicio);
          const salvando = reabilitandoReservaId === selecionado.id;

          return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
              <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
                <h3 className="text-lg font-semibold text-gray-900">Reabilitar reserva</h3>
                <p className="mt-1 text-sm text-gray-600">
                  A reserva de{" "}
                  <span className="font-semibold">
                    {obterTituloAgendamentoPorOrigem(selecionado.origem_atendimento, selecionado.clinica)}
                  </span>{" "}
                  volta a segurar o horario por mais um periodo, ate a clinica enviar os dados do
                  paciente.
                </p>

                <div className="mt-4">
                  <label
                    htmlFor="fc-reabilitar-reserva-horas"
                    className="mb-1 block text-xs font-semibold uppercase tracking-wide text-amber-800"
                  >
                    Novo prazo para confirmacao
                  </label>
                  <div className="flex max-w-xs overflow-hidden rounded-lg border border-amber-300 bg-white focus-within:border-amber-500 focus-within:ring-2 focus-within:ring-amber-200">
                    <input
                      id="fc-reabilitar-reserva-horas"
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
                        Este horario esta proximo demais (ou ja passou) para uma nova reserva.
                        Agende direto com os dados do paciente ou escolha outro horario.
                      </span>
                    ) : (
                      <span className="text-gray-700">
                        Confirmar ate <span className="font-semibold">{previsao?.prazoLegivel}</span>
                        {previsao?.encurtado
                          ? " (encurtado para terminar antes do horario reservado)"
                          : ""}
                      </span>
                    )}
                  </div>
                </div>

                <p className="mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
                  O sistema confere se o horario continua livre e sem conflito com outros
                  agendamentos antes de reservar de novo. Avise a clinica do novo prazo pelo
                  WhatsApp.
                </p>

                <div className="mt-5 flex justify-end gap-2">
                  <button
                    onClick={() => setModalReabilitarReservaAberto(false)}
                    disabled={salvando}
                    className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Cancelar
                  </button>
                  <button
                    onClick={confirmarReabilitacaoReserva}
                    disabled={salvando || horasInformadas === null || Boolean(previsao?.indisponivel)}
                    className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
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

        {modalTipoHorario && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
              <h3 className="text-lg font-semibold text-gray-900">Finalizar atendimento</h3>
              <p className="mt-1 text-sm text-gray-600">
                Escolha o tipo de horario para concluir como <strong>Realizado</strong>.
              </p>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <button
                  onClick={() => setTipoHorario("comercial")}
                  className={`rounded-lg border px-3 py-3 text-sm font-medium transition-colors ${
                    tipoHorario === "comercial"
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                  }`}
                >
                  Comercial
                </button>
                <button
                  onClick={() => setTipoHorario("plantao")}
                  className={`rounded-lg border px-3 py-3 text-sm font-medium transition-colors ${
                    tipoHorario === "plantao"
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                  }`}
                >
                  Plantao
                </button>
              </div>

              <div className="mt-5 flex justify-end gap-2">
                <button
                  onClick={() => setModalTipoHorario(null)}
                  className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancelar
                </button>
                <button
                  onClick={confirmarAtualizacaoRealizado}
                  disabled={atualizandoStatusId === modalTipoHorario.id}
                  className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {atualizandoStatusId === modalTipoHorario.id ? "Salvando..." : "Confirmar"}
                </button>
              </div>
            </div>
          </div>
        )}

        {modalAberto ? (
          <NovoAgendamentoModal
            isOpen={modalAberto}
            onClose={fecharModal}
            onSuccess={handleAgendamentoSuccess}
            agendamento={agendamentoEditando}
            defaultDate={slotSelecionado?.data}
            defaultTime={slotSelecionado?.hora}
            agendaSemanal={agendaSemanal}
            agendaFeriados={agendaFeriados}
            agendaExcecoes={agendaExcecoes}
            intervaloSlotMinutos={duracaoSlotMinutos}
            isAdmin={isAdmin}
          />
        ) : null}

        {clienteModalAlvo && (
          <ClienteInfoModal
            pacienteId={clienteModalAlvo.pacienteId}
            tutorId={clienteModalAlvo.tutorId}
            onClose={() => setClienteModalAlvo(null)}
            onSaved={() => { if (intervalo) void carregarAgendamentos(intervalo); }}
          />
        )}
      </div>
    </DashboardLayout>
  );
}
