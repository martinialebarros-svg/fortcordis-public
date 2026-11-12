"use client";

import { Fragment, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import GoogleMapsAdminPanel from "@/components/google-maps/GoogleMapsAdminPanel";
import { useRoutePerformanceReady } from "@/lib/use-route-performance-ready";
import { formatCalendarDate } from "@/lib/calendar-date";
import {
  PUBLICOS_CONHECIMENTO,
  formatarCusto,
  formatarInteiro,
  formatarLatencia,
  formatarTaxa,
  linhasDoChecklist,
  ordenarPorPendencia,
  resumirProntidao,
  validarConteudoBot,
} from "@/lib/whatsapp-bot-painel";
import { requestPushSync, syncPushNotificationsNow } from "@/lib/usePushNotifications";
import { parseHistorico } from "@/lib/whatsapp-bot-historico";
import {
  AgendaExcecaoConfig,
  AgendaFeriadoConfig,
  AgendaSemanalConfig,
  DEFAULT_AGENDA_SEMANAL,
  DIAS_SEMANA_LABELS,
  normalizarAgendaExcecoes,
  normalizarAgendaFeriados,
  normalizarAgendaSemanal,
} from "@/lib/agenda-config";
import {
  AgendaRotaClinicOverrideConfig,
  AgendaRotaRegrasConfig,
  DEFAULT_AGENDA_ROTA_REGRAS,
  formatarDiasAFrenteInput,
  normalizarAgendaRotaRegras,
  normalizarDiasAFrente,
} from "@/lib/agenda-route-rules";
import {
  Settings,
  Building2,
  UserCircle,
  Image as ImageIcon,
  Signature,
  Save,
  Upload,
  X,
  Trash2,
  Users,
  Shield,
  Activity,
  RefreshCw,
} from "lucide-react";

interface ConfiguracoesSistema {
  nome_empresa: string;
  endereco: string;
  telefone: string;
  email: string;
  cidade: string;
  estado: string;
  website: string;
  tem_logomarca: boolean;
  tem_assinatura: boolean;
  texto_rodape_laudo: string;
  mostrar_logomarca: boolean;
  mostrar_assinatura: boolean;
  fortinho_habilitado: boolean;
  whatsapp_lembrete_automatico_habilitado: boolean;
  whatsapp_bot_atendimento_habilitado: boolean;
  whatsapp_bot_modo: "off" | "suggest" | "auto";
  agenda_semanal: AgendaSemanalConfig;
  agenda_feriados: AgendaFeriadoConfig[];
  agenda_excecoes: AgendaExcecaoConfig[];
  agenda_rota_regras: AgendaRotaRegrasConfig;
  inscricao_municipal: string;
  inscricao_estadual: string;
  cnae: string;
  regime_tributario: number | null;
  codigo_municipio_servico: string;
}

interface ConfiguracoesUsuario {
  tema: string;
  idioma: string;
  notificacoes_email: boolean;
  notificacoes_push: boolean;
  notificacoes_push_tipos: string[];
  notificacoes_push_prioridade_alta_tipos: string[];
  notificacoes_push_agrupar: boolean;
  notificacoes_push_lembrete_pendencias: boolean;
  notificacoes_push_lembrete_horas: number;
  notificacoes_push_perfil: string;
  tem_assinatura: boolean;
  crmv: string;
  especialidade: string;
}

const TIPOS_PUSH_AGENDA_OPCOES: Array<{ valor: string; label: string; descricao: string }> = [
  { valor: "created", label: "Novo agendamento", descricao: "Quando um agendamento for criado." },
  { valor: "updated", label: "Agendamento atualizado", descricao: "Quando data, horario ou dados forem alterados." },
  { valor: "status_changed", label: "Mudanca de status", descricao: "Quando o status mudar (confirmado, realizado etc.)." },
  { valor: "cancelled", label: "Agendamento cancelado", descricao: "Quando o agendamento for marcado como cancelado." },
  { valor: "deleted", label: "Agendamento excluido", descricao: "Quando um agendamento for removido." },
  {
    valor: "whatsapp_reserva_resposta",
    label: "Resposta do WhatsApp",
    descricao: "Quando o paciente responder ao botao de confirmacao da reserva pelo WhatsApp.",
  },
];

const TIPOS_PUSH_FINANCEIRO_OPCOES: Array<{ valor: string; label: string; descricao: string }> = [
  { valor: "os_generated", label: "OS gerada", descricao: "Quando uma ordem de servico for gerada." },
  { valor: "payment_received", label: "Pagamento recebido", descricao: "Quando uma OS for marcada como paga." },
  { valor: "os_deleted", label: "OS excluida", descricao: "Quando uma ordem de servico for removida." },
  { valor: "payment_pending", label: "Lembrete de pendencia", descricao: "Quando a OS segue pendente apos X horas." },
];

const TIPOS_PUSH_WHATSAPP_OPCOES: Array<{ valor: string; label: string; descricao: string }> = [
  { valor: "mensagem_recebida", label: "Mensagem recebida", descricao: "Quando chegar uma nova mensagem de um contato no WhatsApp." },
];

const TIPOS_PUSH_OPCOES = [...TIPOS_PUSH_AGENDA_OPCOES, ...TIPOS_PUSH_FINANCEIRO_OPCOES, ...TIPOS_PUSH_WHATSAPP_OPCOES];
const TIPOS_PUSH_VALIDOS = new Set(TIPOS_PUSH_OPCOES.map((item) => item.valor));
const TIPOS_PUSH_PRIORIDADE_ALTA_PADRAO = ["os_deleted", "payment_pending"];

interface PerfilPushPreset {
  perfil: string;
  titulo: string;
  descricao: string;
  tipos: string[];
  alta_prioridade: string[];
  agrupar: boolean;
  lembrete_pendencias: boolean;
  lembrete_horas: number;
}

const PERFIS_PUSH_PRESETS: PerfilPushPreset[] = [
  {
    perfil: "recepcao",
    titulo: "Recepcao",
    descricao: "Foco em agenda e fluxo geral de atendimento.",
    tipos: ["created", "updated", "status_changed", "cancelled", "deleted", "os_generated", "mensagem_recebida"],
    alta_prioridade: ["status_changed", "cancelled", "deleted"],
    agrupar: true,
    lembrete_pendencias: false,
    lembrete_horas: 6,
  },
  {
    perfil: "financeiro",
    titulo: "Financeiro",
    descricao: "Foco em OS, recebimentos e pendencias de pagamento.",
    tipos: ["os_generated", "payment_received", "os_deleted", "payment_pending"],
    alta_prioridade: ["os_deleted", "payment_pending"],
    agrupar: true,
    lembrete_pendencias: true,
    lembrete_horas: 6,
  },
  {
    perfil: "medico",
    titulo: "Medico",
    descricao: "Foco em mudancas de agenda e eventos clinicos.",
    tipos: ["created", "updated", "status_changed", "cancelled", "deleted", "os_generated"],
    alta_prioridade: ["status_changed", "cancelled"],
    agrupar: false,
    lembrete_pendencias: false,
    lembrete_horas: 8,
  },
];

const normalizarTiposPushAgenda = (valor: unknown): string[] => {
  if (valor == null) {
    return TIPOS_PUSH_OPCOES.map((item) => item.valor);
  }

  const bruto = Array.isArray(valor)
    ? valor
    : String(valor)
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);

  const vistos = new Set<string>();
  const normalizado: string[] = [];
  for (const item of bruto) {
    const chave = String(item || "").trim().toLowerCase();
    if (!TIPOS_PUSH_VALIDOS.has(chave) || vistos.has(chave)) {
      continue;
    }
    vistos.add(chave);
    normalizado.push(chave);
  }
  return normalizado;
};

const normalizarTiposPrioridadeAltaPush = (valor: unknown): string[] => {
  if (valor == null) {
    return [...TIPOS_PUSH_PRIORIDADE_ALTA_PADRAO];
  }
  return normalizarTiposPushAgenda(valor);
};

interface PapelSistema {
  id: number;
  nome: string;
  descricao?: string | null;
}

interface UsuarioSistema {
  id: number;
  nome: string;
  email: string;
  ativo: number;
  papeis: string[];
  criado_em?: string | null;
  ultimo_acesso?: string | null;
}

interface UsuarioForm {
  id: number | null;
  nome: string;
  email: string;
  senha: string;
  ativo: boolean;
  papeis: string[];
}

interface ModuloPermissao {
  codigo: string;
  nome: string;
}

interface PermissaoPapel {
  modulo: string;
  visualizar: boolean;
  editar: boolean;
  excluir: boolean;
}

interface MatrizPermissaoPapel {
  id: number;
  nome: string;
  descricao?: string | null;
  permissoes: PermissaoPapel[];
}

interface AuditoriaEventoItem {
  id: number;
  created_at?: string | null;
  usuario_id?: number | null;
  usuario_nome?: string | null;
  usuario_email?: string | null;
  modulo: string;
  entidade: string;
  entidade_id?: string | null;
  acao: string;
  descricao?: string | null;
  detalhes?: Record<string, any>;
  ip_origem?: string | null;
  rota?: string | null;
  metodo?: string | null;
}

interface ClinicaProntidaoItem {
  clinica_id: number;
  clinica_nome: string;
  motivo: "sem_numero" | "numero_invalido" | null;
  valor_cadastrado?: string | null;
  agendamentos_60_dias: number;
}

interface ClinicaProntidaoWhatsapp {
  janela_dias: number;
  total_clinicas_ativas: number;
  total_prontas: number;
  total_com_problema: number;
  clinicas: ClinicaProntidaoItem[];
}

interface LatenciaRuntimeGrupo {
  endpoint: string;
  release_id: string;
  request_count: number;
  error_5xx_count: number;
  avg_ms: number | null;
  max_ms: number | null;
  slow_request_count: number;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  database_avg_ms: number | null;
  database_p95_ms: number | null;
  database_query_count_avg: number | null;
  database_query_count_p95: number | null;
  application_avg_ms: number | null;
  application_p95_ms: number | null;
  pool_wait_avg_ms: number | null;
  pool_wait_p95_ms: number | null;
  last_seen_at: string | null;
}

interface LatenciaRuntimeResumo {
  available: boolean;
  hours: number;
  retention_days: number;
  query_max_samples: number;
  slow_request_threshold_ms: number;
  truncated: boolean;
  groups: LatenciaRuntimeGrupo[];
}

interface DesempenhoFrontendGrupo {
  route_group: string;
  release_id: string;
  navigation_type: "initial" | "client";
  sample_count: number;
  shell_p50_ms: number | null;
  shell_p95_ms: number | null;
  shell_p99_ms: number | null;
  content_p50_ms: number | null;
  content_p95_ms: number | null;
  content_p99_ms: number | null;
  content_max_ms: number | null;
  slow_content_count: number;
  ready_count: number;
  partial_count: number;
  error_count: number;
  timeout_count: number;
  cancelled_count: number;
  last_seen_at: string | null;
}

interface DesempenhoFrontendResumo {
  available: boolean;
  hours: number;
  retention_days: number;
  query_max_samples: number;
  slow_content_threshold_ms: number;
  truncated: boolean;
  groups: DesempenhoFrontendGrupo[];
}

export default function ConfiguracoesPage() {
  const router = useRouter();
  const [aba, setAba] = useState<"empresa" | "usuario" | "usuarios" | "observabilidade" | "maps">("empresa");
  const [loading, setLoading] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [prontidaoClinicas, setProntidaoClinicas] = useState<ClinicaProntidaoWhatsapp | null>(null);
  const [prontidaoClinicasStatus, setProntidaoClinicasStatus] = useState<"idle" | "loading" | "error">("idle");

  // Configurações da empresa
  const [configEmpresa, setConfigEmpresa] = useState<ConfiguracoesSistema>({
    nome_empresa: "Fort Cordis Cardiologia Veterinária",
    endereco: "",
    telefone: "",
    email: "",
    cidade: "Fortaleza",
    estado: "CE",
    website: "",
    tem_logomarca: false,
    tem_assinatura: false,
    texto_rodape_laudo: "Fort Cordis Cardiologia Veterinária | Fortaleza-CE",
    mostrar_logomarca: true,
    mostrar_assinatura: true,
    fortinho_habilitado: false,
    whatsapp_lembrete_automatico_habilitado: false,
    whatsapp_bot_atendimento_habilitado: false,
    whatsapp_bot_modo: "suggest",
    agenda_semanal: normalizarAgendaSemanal(DEFAULT_AGENDA_SEMANAL),
    agenda_feriados: [],
    agenda_excecoes: [],
    agenda_rota_regras: normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS),
    inscricao_municipal: "",
    inscricao_estadual: "",
    cnae: "",
    regime_tributario: null,
    codigo_municipio_servico: "",
  });

  // Configurações do usuário
  const [configUsuario, setConfigUsuario] = useState<ConfiguracoesUsuario>({
    tema: "light",
    idioma: "pt-BR",
    notificacoes_email: true,
    notificacoes_push: true,
    notificacoes_push_tipos: TIPOS_PUSH_OPCOES.map((item) => item.valor),
    notificacoes_push_prioridade_alta_tipos: [...TIPOS_PUSH_PRIORIDADE_ALTA_PADRAO],
    notificacoes_push_agrupar: true,
    notificacoes_push_lembrete_pendencias: true,
    notificacoes_push_lembrete_horas: 6,
    notificacoes_push_perfil: "custom",
    tem_assinatura: false,
    crmv: "",
    especialidade: "",
  });

  // Preview de imagens
  const [previewLogo, setPreviewLogo] = useState<string | null>(null);
  const [previewAssinaturaSistema, setPreviewAssinaturaSistema] = useState<string | null>(null);
  const [previewAssinaturaUsuario, setPreviewAssinaturaUsuario] = useState<string | null>(null);
  const [usuariosSistema, setUsuariosSistema] = useState<UsuarioSistema[]>([]);
  const [papeisSistema, setPapeisSistema] = useState<PapelSistema[]>([]);
  const [carregandoUsuarios, setCarregandoUsuarios] = useState(false);
  const [salvandoUsuarioSistema, setSalvandoUsuarioSistema] = useState(false);
  const [erroUsuarios, setErroUsuarios] = useState("");
  const [erroPermissoes, setErroPermissoes] = useState("");
  const [carregandoPermissoes, setCarregandoPermissoes] = useState(false);
  const [salvandoPermissoes, setSalvandoPermissoes] = useState(false);
  const [somenteLeituraAgenda, setSomenteLeituraAgenda] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [latenciaRuntime, setLatenciaRuntime] = useState<LatenciaRuntimeResumo | null>(null);
  const [desempenhoFrontend, setDesempenhoFrontend] = useState<DesempenhoFrontendResumo | null>(null);
  const [statusLatenciaRuntime, setStatusLatenciaRuntime] = useState<"idle" | "loading" | "error">("idle");
  const [erroLatenciaRuntime, setErroLatenciaRuntime] = useState("");
  const [janelaLatenciaRuntime, setJanelaLatenciaRuntime] = useState<6 | 24 | 168>(24);
  const [modulosPermissoes, setModulosPermissoes] = useState<ModuloPermissao[]>([]);
  const [matrizPermissoes, setMatrizPermissoes] = useState<MatrizPermissaoPapel[]>([]);
  const [auditoriaItens, setAuditoriaItens] = useState<AuditoriaEventoItem[]>([]);
  const [auditoriaTotal, setAuditoriaTotal] = useState(0);
  const [auditoriaModulos, setAuditoriaModulos] = useState<string[]>([]);
  const [auditoriaAcoes, setAuditoriaAcoes] = useState<string[]>([]);
  const [carregandoAuditoria, setCarregandoAuditoria] = useState(false);
  const [erroAuditoria, setErroAuditoria] = useState("");
  const [filtroAuditoriaModulo, setFiltroAuditoriaModulo] = useState("todos");
  const [filtroAuditoriaAcao, setFiltroAuditoriaAcao] = useState("todos");
  const [filtroAuditoriaBusca, setFiltroAuditoriaBusca] = useState("");
  const [filtroAuditoriaDataInicio, setFiltroAuditoriaDataInicio] = useState("");
  const [filtroAuditoriaDataFim, setFiltroAuditoriaDataFim] = useState("");
  const [auditoriaExpandida, setAuditoriaExpandida] = useState<Record<number, boolean>>({});
  const [modoEdicaoUsuario, setModoEdicaoUsuario] = useState(false);
  const [novoFeriadoData, setNovoFeriadoData] = useState("");
  const [novoFeriadoTipo, setNovoFeriadoTipo] = useState<"local" | "nacional">("local");
  const [novoFeriadoDescricao, setNovoFeriadoDescricao] = useState("");
  const [novaExcecaoData, setNovaExcecaoData] = useState("");
  const [novaExcecaoAtiva, setNovaExcecaoAtiva] = useState(true);
  const [novaExcecaoInicio, setNovaExcecaoInicio] = useState("08:00");
  const [novaExcecaoFim, setNovaExcecaoFim] = useState("18:00");
  const [novaExcecaoMotivo, setNovaExcecaoMotivo] = useState("");
  // Painel do bot de atendimento (Fase 6)
  const [botProntidao, setBotProntidao] = useState<any>(null);
  const [botMetricas, setBotMetricas] = useState<any>(null);
  const [botConteudo, setBotConteudo] = useState<any>(null);
  const [botCarregando, setBotCarregando] = useState<string | null>(null);
  const [botErro, setBotErro] = useState<string | null>(null);
  const [botForm, setBotForm] = useState({ titulo: "", conteudo: "", fonte: "", publico: "ambos", indexar_semanticamente: false });
  const [botFormErros, setBotFormErros] = useState<string[]>([]);
  const [botSimulacao, setBotSimulacao] = useState<any>(null);
  const [botSimHistorico, setBotSimHistorico] = useState("");
  const [botSimPersona, setBotSimPersona] = useState("tutor");
  const [botSimMensagem, setBotSimMensagem] = useState("");
  const [botClinicas, setBotClinicas] = useState<any>(null);
  const [botClinicaBusca, setBotClinicaBusca] = useState("");
  const [usuarioForm, setUsuarioForm] = useState<UsuarioForm>({
    id: null,
    nome: "",
    email: "",
    senha: "",
    ativo: true,
    papeis: [],
  });

  const atualizarRegraRotaBase = (
    campo: keyof AgendaRotaRegrasConfig["base"],
    valor: string
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      let nextValue: string | number | null = valor;
      if (campo === "lat" || campo === "lng") {
        if (!valor.trim()) {
          nextValue = null;
        } else {
          const parsed = Number.parseFloat(valor.replace(",", "."));
          nextValue = Number.isFinite(parsed) ? parsed : null;
        }
      }
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          base: {
            ...regras.base,
            [campo]: nextValue,
          },
        },
      };
    });
  };

  const atualizarRegraRotaThreshold = (
    campo: keyof AgendaRotaRegrasConfig["thresholds"],
    valor: number
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          thresholds: {
            ...regras.thresholds,
            [campo]: Number.isFinite(valor) ? valor : 0,
          },
        },
      };
    });
  };

  const atualizarRegraRotaOfferDias = (
    campo:
      | "default_first_offer_days_ahead"
      | "distant_low_frequency_first_offer_days_ahead"
      | "emergency_first_offer_days_ahead",
    valor: string
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      const fallback = regras.offer_policy[campo];
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          offer_policy: {
            ...regras.offer_policy,
            [campo]: normalizarDiasAFrente(valor, fallback),
          },
        },
      };
    });
  };

  const atualizarRegraRotaOfferBool = (
    campo: "allow_d2_if_anchor_exists",
    valor: boolean
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          offer_policy: {
            ...regras.offer_policy,
            [campo]: valor,
          },
        },
      };
    });
  };

  const atualizarRegraRotaPolicy = (
    campo: keyof AgendaRotaRegrasConfig["route_policy"],
    valor: string | number | boolean
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          route_policy: {
            ...regras.route_policy,
            [campo]: valor,
          },
        },
      };
    });
  };

  const atualizarRegraPrimeiroAtendimentoCidade = (
    cidade: keyof AgendaRotaRegrasConfig["route_policy"]["first_appointment_city_floors"],
    horario: string
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          route_policy: {
            ...regras.route_policy,
            first_appointment_city_floors: {
              ...regras.route_policy.first_appointment_city_floors,
              [cidade]: horario,
            },
          },
        },
      };
    });
  };

  const atualizarRegraRotaFallback = (
    campo: keyof AgendaRotaRegrasConfig["fallback_policy"],
    valor: number | boolean
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          fallback_policy: {
            ...regras.fallback_policy,
            [campo]: valor,
          },
        },
      };
    });
  };

  const atualizarRegraRenderizacaoAgenda = (
    campo: keyof AgendaRotaRegrasConfig["rendering_policy"],
    valor: string | number | boolean
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          rendering_policy: {
            ...regras.rendering_policy,
            [campo]: valor,
          },
        },
      };
    });
  };

  const adicionarOverrideRota = () => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      const novo: AgendaRotaClinicOverrideConfig = {
        clinic_name: "",
        force_days_ahead: [...regras.offer_policy.distant_low_frequency_first_offer_days_ahead],
        prefer_only_when_anchor_exists: true,
        notes: "",
      };
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          clinic_overrides: [...(regras.clinic_overrides || []), novo],
        },
      };
    });
  };

  const removerOverrideRota = (index: number) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          clinic_overrides: (regras.clinic_overrides || []).filter((_, i) => i !== index),
        },
      };
    });
  };

  const atualizarOverrideRota = (
    index: number,
    campo: keyof AgendaRotaClinicOverrideConfig,
    valor: string | boolean
  ) => {
    setConfigEmpresa((prev) => {
      const regras = prev.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);
      const overrides = [...(regras.clinic_overrides || [])];
      if (!overrides[index]) return prev;
      if (campo === "force_days_ahead") {
        overrides[index] = {
          ...overrides[index],
          force_days_ahead: normalizarDiasAFrente(
            valor,
            regras.offer_policy.distant_low_frequency_first_offer_days_ahead
          ),
        };
      } else if (campo === "prefer_only_when_anchor_exists") {
        overrides[index] = {
          ...overrides[index],
          prefer_only_when_anchor_exists: Boolean(valor),
        };
      } else if (campo === "clinic_name") {
        overrides[index] = {
          ...overrides[index],
          clinic_name: String(valor ?? ""),
        };
      } else {
        overrides[index] = {
          ...overrides[index],
          notes: String(valor ?? ""),
        };
      }
      return {
        ...prev,
        agenda_rota_regras: {
          ...regras,
          clinic_overrides: overrides,
        },
      };
    });
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

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    setIsAdmin(usuarioEhAdmin());
    carregarConfiguracoes();
  }, [router]);

  useEffect(() => {
    if (aba === "usuarios") {
      carregarUsuariosPermissoes();
      carregarAuditoria();
    }
  }, [aba]);

  useEffect(() => {
    if (aba === "observabilidade" && isAdmin) {
      carregarLatenciaRuntime();
    }
  }, [aba, isAdmin, janelaLatenciaRuntime]);

  const carregarImagem = async (url: string): Promise<string | null> => {
    try {
      const response = await api.get(url, { responseType: 'blob' });
      return URL.createObjectURL(response.data);
    } catch (error) {
      console.error(`Erro ao carregar imagem ${url}:`, error);
      return null;
    }
  };

  const formatarDataHora = (valor?: string | null) => {
    if (!valor) return "-";
    const data = new Date(valor);
    if (Number.isNaN(data.getTime())) return "-";
    return data.toLocaleString("pt-BR");
  };

  const formatarMilissegundos = (valor?: number | null) => {
    if (typeof valor !== "number" || !Number.isFinite(valor)) return "-";
    return `${valor.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ms`;
  };

  const carregarLatenciaRuntime = async () => {
    try {
      setStatusLatenciaRuntime("loading");
      setErroLatenciaRuntime("");
      const [httpResult, frontendResult] = await Promise.allSettled([
        api.get("/admin/observability/http-latency", {
          params: { hours: janelaLatenciaRuntime },
        }),
        api.get("/admin/observability/frontend-performance", {
          params: { hours: janelaLatenciaRuntime },
        }),
      ]);
      const falhas: string[] = [];

      if (httpResult.status === "fulfilled") {
        const payload = httpResult.value?.data || {};
        setLatenciaRuntime({
          available: payload.available === true,
          hours: Number(payload.hours) || janelaLatenciaRuntime,
          retention_days: Number(payload.retention_days) || 14,
          query_max_samples: Number(payload.query_max_samples) || 0,
          slow_request_threshold_ms: Number(payload.slow_request_threshold_ms) || 1200,
          truncated: payload.truncated === true,
          groups: Array.isArray(payload.groups)
            ? payload.groups.map((group: Record<string, any>) => ({
                ...group,
                max_ms: Number.isFinite(Number(group.max_ms)) ? Number(group.max_ms) : null,
                slow_request_count: Number(group.slow_request_count) || 0,
              }))
            : [],
        });
      } else {
        setLatenciaRuntime(null);
        falhas.push("Não foi possível carregar a telemetria da API.");
      }

      if (frontendResult.status === "fulfilled") {
        const frontendPayload = frontendResult.value?.data || {};
        setDesempenhoFrontend({
          available: frontendPayload.available === true,
          hours: Number(frontendPayload.hours) || janelaLatenciaRuntime,
          retention_days: Number(frontendPayload.retention_days) || 14,
          query_max_samples: Number(frontendPayload.query_max_samples) || 0,
          slow_content_threshold_ms: Number(frontendPayload.slow_content_threshold_ms) || 3000,
          truncated: frontendPayload.truncated === true,
          groups: Array.isArray(frontendPayload.groups) ? frontendPayload.groups : [],
        });
      } else {
        setDesempenhoFrontend(null);
        falhas.push("Não foi possível carregar a telemetria do navegador.");
      }

      setErroLatenciaRuntime(falhas.join(" "));
      setStatusLatenciaRuntime(falhas.length > 0 ? "error" : "idle");
    } catch (error: any) {
      const detalhe = error?.response?.data?.detail;
      setErroLatenciaRuntime(
        typeof detalhe === "string" ? detalhe : "Não foi possível carregar a telemetria de desempenho."
      );
      setStatusLatenciaRuntime("error");
    }
  };

  const formatarValorAuditoria = (valor: unknown): string => {
    if (valor === null || valor === undefined || valor === "") return "(vazio)";
    if (typeof valor === "object") return JSON.stringify(valor);
    return String(valor);
  };

  // registrar_auditoria segue 2 formatos: {alteracoes: {campo: {antes, depois}}}
  // para updates, ou chave-valor simples para criacao/exclusao/estado pontual.
  const renderizarDetalhesAuditoria = (detalhes?: Record<string, any>) => {
    if (!detalhes || Object.keys(detalhes).length === 0) return null;
    const { alteracoes, ...outrosCampos } = detalhes;
    const temAlteracoes = alteracoes && typeof alteracoes === "object" && !Array.isArray(alteracoes);

    return (
      <div className="space-y-3">
        {temAlteracoes ? (
          <table className="min-w-full text-xs border border-gray-200 rounded-lg overflow-hidden">
            <thead className="bg-gray-100 text-gray-500">
              <tr>
                <th className="text-left px-2 py-1 font-medium">Campo</th>
                <th className="text-left px-2 py-1 font-medium">Antes</th>
                <th className="text-left px-2 py-1 font-medium">Depois</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(alteracoes as Record<string, any>).map(([campo, valores]) => (
                <tr key={campo} className="border-t border-gray-200">
                  <td className="px-2 py-1 font-medium text-gray-700">{campo}</td>
                  <td className="px-2 py-1 text-gray-500">{formatarValorAuditoria((valores as any)?.antes)}</td>
                  <td className="px-2 py-1 text-gray-700">{formatarValorAuditoria((valores as any)?.depois)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {Object.keys(outrosCampos).length > 0 ? (
          <div className="space-y-1 text-xs">
            {Object.entries(outrosCampos).map(([chave, valor]) => (
              <div key={chave} className="flex gap-2">
                <span className="font-medium text-gray-500">{chave}:</span>
                <span className="text-gray-700 break-all">{formatarValorAuditoria(valor)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    );
  };

  const limparFormularioUsuario = () => {
    setUsuarioForm({
      id: null,
      nome: "",
      email: "",
      senha: "",
      ativo: true,
      papeis: [],
    });
    setModoEdicaoUsuario(false);
  };

  const carregarUsuariosPermissoes = async () => {
    try {
      setCarregandoUsuarios(true);
      setCarregandoPermissoes(true);
      setErroUsuarios("");
      setErroPermissoes("");
      const [respPapeis, respUsuarios, respPermissoes] = await Promise.all([
        api.get("/admin/papeis"),
        api.get("/admin/usuarios"),
        api.get("/admin/permissoes"),
      ]);
      setPapeisSistema(Array.isArray(respPapeis.data) ? respPapeis.data : []);
      setUsuariosSistema(Array.isArray(respUsuarios.data) ? respUsuarios.data : []);
      const payloadPermissoes = respPermissoes?.data || {};
      setModulosPermissoes(Array.isArray(payloadPermissoes.modulos) ? payloadPermissoes.modulos : []);
      setMatrizPermissoes(Array.isArray(payloadPermissoes.papeis) ? payloadPermissoes.papeis : []);
    } catch (error: any) {
      const detalhe = error?.response?.data?.detail;
      const mensagem = typeof detalhe === "string" ? detalhe : "Erro ao carregar usuarios e permissoes.";
      setErroUsuarios(mensagem);
      setErroPermissoes(mensagem);
    } finally {
      setCarregandoUsuarios(false);
      setCarregandoPermissoes(false);
    }
  };

  const alternarPermissao = (
    papelId: number,
    modulo: string,
    campo: "visualizar" | "editar" | "excluir"
  ) => {
    setMatrizPermissoes((anterior) =>
      anterior.map((papel) => {
        if (papel.id !== papelId) return papel;
        const existe = papel.permissoes.some((perm) => perm.modulo === modulo);
        const permissoesAtualizadas = existe
          ? papel.permissoes.map((perm) =>
              perm.modulo === modulo ? { ...perm, [campo]: !perm[campo] } : perm
            )
          : [...papel.permissoes, { modulo, visualizar: false, editar: false, excluir: false, [campo]: true }];

        return {
          ...papel,
          permissoes: permissoesAtualizadas,
        };
      })
    );
  };

  const salvarPermissoes = async () => {
    const itens = matrizPermissoes.flatMap((papel) =>
      papel.permissoes.map((perm) => ({
        papel_id: papel.id,
        modulo: perm.modulo,
        visualizar: !!perm.visualizar,
        editar: !!perm.editar,
        excluir: !!perm.excluir,
      }))
    );

    if (itens.length === 0) {
      alert("Nao ha permissoes para salvar.");
      return;
    }

    try {
      setSalvandoPermissoes(true);
      await api.put("/admin/permissoes", { itens });
      alert("Permissoes salvas com sucesso.");
    } catch (error: any) {
      const detalhe = error?.response?.data?.detail;
      alert(typeof detalhe === "string" ? detalhe : "Erro ao salvar permissoes.");
    } finally {
      setSalvandoPermissoes(false);
    }
  };

  const alternarPapelFormulario = (nomePapel: string) => {
    setUsuarioForm((anterior) => {
      const jaSelecionado = anterior.papeis.includes(nomePapel);
      if (jaSelecionado) {
        return {
          ...anterior,
          papeis: anterior.papeis.filter((papel) => papel !== nomePapel),
        };
      }
      return { ...anterior, papeis: [...anterior.papeis, nomePapel] };
    });
  };

  const editarUsuario = (usuario: UsuarioSistema) => {
    setModoEdicaoUsuario(true);
    setUsuarioForm({
      id: usuario.id,
      nome: usuario.nome,
      email: usuario.email,
      senha: "",
      ativo: usuario.ativo === 1,
      papeis: usuario.papeis || [],
    });
  };

  const salvarUsuarioSistema = async () => {
    const nome = usuarioForm.nome.trim();
    const email = usuarioForm.email.trim().toLowerCase();
    const senha = usuarioForm.senha.trim();

    if (!nome || !email) {
      alert("Informe nome e email.");
      return;
    }

    if (!modoEdicaoUsuario && !senha) {
      alert("Informe a senha para criar o usuario.");
      return;
    }

    const payload: Record<string, any> = {
      nome,
      email,
      ativo: usuarioForm.ativo ? 1 : 0,
      papeis: usuarioForm.papeis,
    };

    if (senha) {
      payload.senha = senha;
    }

    try {
      setSalvandoUsuarioSistema(true);
      if (modoEdicaoUsuario && usuarioForm.id) {
        await api.put(`/admin/usuarios/${usuarioForm.id}`, payload);
        alert("Usuario atualizado com sucesso.");
      } else {
        await api.post("/admin/usuarios", payload);
        alert("Usuario criado com sucesso.");
      }
      limparFormularioUsuario();
      await Promise.all([carregarUsuariosPermissoes(), carregarAuditoria()]);
    } catch (error: any) {
      const detalhe = error?.response?.data?.detail;
      alert(typeof detalhe === "string" ? detalhe : "Erro ao salvar usuario.");
    } finally {
      setSalvandoUsuarioSistema(false);
    }
  };

  const desativarUsuario = async (usuario: UsuarioSistema) => {
    if (!confirm(`Deseja desativar o usuario ${usuario.nome}?`)) {
      return;
    }

    try {
      await api.delete(`/admin/usuarios/${usuario.id}`);
      if (usuarioForm.id === usuario.id) {
        limparFormularioUsuario();
      }
      await Promise.all([carregarUsuariosPermissoes(), carregarAuditoria()]);
      alert("Usuario desativado.");
    } catch (error: any) {
      const detalhe = error?.response?.data?.detail;
      alert(typeof detalhe === "string" ? detalhe : "Erro ao desativar usuario.");
    }
  };

  const carregarConfiguracoes = async () => {
    try {
      setLoading(true);

      try {
        // Carrega configuracoes completas da empresa (quando permitido).
        const respEmpresa = await api.get("/configuracoes");
        if (respEmpresa.data) {
          setConfigEmpresa((prev) => ({
            ...prev,
            ...respEmpresa.data,
            agenda_semanal: normalizarAgendaSemanal(respEmpresa.data?.agenda_semanal),
            agenda_feriados: normalizarAgendaFeriados(respEmpresa.data?.agenda_feriados),
            agenda_excecoes: normalizarAgendaExcecoes(respEmpresa.data?.agenda_excecoes),
            agenda_rota_regras: normalizarAgendaRotaRegras(respEmpresa.data?.agenda_rota_regras),
          }));

          // Carregar preview da logomarca se existir
          if (respEmpresa.data.tem_logomarca) {
            const logoUrl = await carregarImagem("/configuracoes/logomarca");
            if (logoUrl) setPreviewLogo(logoUrl);
          }

          // Carregar preview da assinatura do sistema se existir
          if (respEmpresa.data.tem_assinatura) {
            const assUrl = await carregarImagem("/configuracoes/assinatura");
            if (assUrl) setPreviewAssinaturaSistema(assUrl);
          }
        }
        setSomenteLeituraAgenda(false);
      } catch (errorEmpresa: any) {
        if (errorEmpresa?.response?.status === 403) {
          // Sem permissao de Configuracoes: exibe agenda em modo leitura.
          setSomenteLeituraAgenda(true);
        } else {
          console.error("Erro ao carregar configuracoes da empresa:", errorEmpresa);
        }
      }

      try {
        // Fonte unica do funcionamento da agenda (mesma regra da tela Agenda).
        const respAgenda = await api.get("/agenda/configuracao");
        setConfigEmpresa((prev) => ({
          ...prev,
          agenda_semanal: normalizarAgendaSemanal(respAgenda.data?.agenda_semanal),
          agenda_feriados: normalizarAgendaFeriados(respAgenda.data?.agenda_feriados),
          agenda_excecoes: normalizarAgendaExcecoes(respAgenda.data?.agenda_excecoes),
          agenda_rota_regras: normalizarAgendaRotaRegras(respAgenda.data?.agenda_rota_regras),
        }));
      } catch (errorAgenda) {
        console.error("Erro ao carregar funcionamento da agenda:", errorAgenda);
      }

      // Carregar configuracoes do usuario
      const respUsuario = await api.get("/configuracoes/usuario");
      if (respUsuario.data) {
        const lembreteHoras = Number(respUsuario.data?.notificacoes_push_lembrete_horas ?? 6);
        setConfigUsuario((prev) => ({
          ...prev,
          ...respUsuario.data,
          notificacoes_push_tipos: normalizarTiposPushAgenda(respUsuario.data?.notificacoes_push_tipos),
          notificacoes_push_prioridade_alta_tipos: normalizarTiposPrioridadeAltaPush(
            respUsuario.data?.notificacoes_push_prioridade_alta_tipos
          ),
          notificacoes_push_agrupar: respUsuario.data?.notificacoes_push_agrupar !== false,
          notificacoes_push_lembrete_pendencias:
            respUsuario.data?.notificacoes_push_lembrete_pendencias !== false,
          notificacoes_push_lembrete_horas: Number.isFinite(lembreteHoras)
            ? Math.min(168, Math.max(1, Math.round(lembreteHoras)))
            : 6,
          notificacoes_push_perfil: String(respUsuario.data?.notificacoes_push_perfil || "custom"),
        }));

        // Carregar preview da assinatura do usuario se existir
        if (respUsuario.data.tem_assinatura) {
          const assUrl = await carregarImagem("/configuracoes/usuario/assinatura");
          if (assUrl) setPreviewAssinaturaUsuario(assUrl);
        }
      }
    } catch (error) {
      console.error("Erro ao carregar configuracoes:", error);
    } finally {
      setLoading(false);
    }
  };

  const carregarAuditoria = async () => {
    try {
      setCarregandoAuditoria(true);
      setErroAuditoria("");
      const params: Record<string, any> = { limit: 200 };
      if (filtroAuditoriaModulo !== "todos") params.modulo = filtroAuditoriaModulo;
      if (filtroAuditoriaAcao !== "todos") params.acao = filtroAuditoriaAcao;
      if (filtroAuditoriaBusca.trim()) params.busca = filtroAuditoriaBusca.trim();
      if (filtroAuditoriaDataInicio) params.data_inicio = filtroAuditoriaDataInicio;
      if (filtroAuditoriaDataFim) params.data_fim = filtroAuditoriaDataFim;

      const resp = await api.get("/admin/auditoria", { params });
      const payload = resp?.data || {};
      setAuditoriaItens(Array.isArray(payload.items) ? payload.items : []);
      setAuditoriaTotal(Number(payload.total || 0));
      setAuditoriaModulos(Array.isArray(payload.modulos) ? payload.modulos : []);
      setAuditoriaAcoes(Array.isArray(payload.acoes) ? payload.acoes : []);
    } catch (error: any) {
      const detalhe = error?.response?.data?.detail;
      setErroAuditoria(typeof detalhe === "string" ? detalhe : "Erro ao carregar auditoria.");
    } finally {
      setCarregandoAuditoria(false);
    }
  };

  const verificarProntidaoClinicas = async () => {
    try {
      setProntidaoClinicasStatus("loading");
      const resp = await api.get("/agenda/whatsapp/lembrete-clinicas-prontidao");
      setProntidaoClinicas(resp?.data || null);
      setProntidaoClinicasStatus("idle");
    } catch {
      setProntidaoClinicas(null);
      setProntidaoClinicasStatus("error");
    }
  };

  const carregarBotProntidao = async () => {
    try {
      setBotCarregando("prontidao");
      setBotErro(null);
      const { data } = await api.get("/whatsapp/bot/prontidao");
      setBotProntidao(data);
    } catch {
      setBotErro("Não foi possível carregar a prontidão do bot.");
    } finally {
      setBotCarregando(null);
    }
  };

  const carregarBotClinicas = async () => {
    try {
      setBotCarregando("clinicas");
      setBotErro(null);
      const { data } = await api.get("/whatsapp/bot/clinicas");
      setBotClinicas(data);
    } catch {
      setBotErro("Não foi possível carregar a participação das clínicas.");
    } finally {
      setBotCarregando(null);
    }
  };

  const alterarModoDaClinica = async (clinicaId: number, modo: string) => {
    try {
      setBotCarregando(`clinica-${clinicaId}`);
      setBotErro(null);
      await api.put(`/whatsapp/bot/clinicas/${clinicaId}`, { modo });
      await carregarBotClinicas();
    } catch {
      setBotErro("Não foi possível alterar a participação desta clínica.");
    } finally {
      setBotCarregando(null);
    }
  };

  const removerMarcacaoDaClinica = async (clinicaId: number) => {
    try {
      setBotCarregando(`clinica-${clinicaId}`);
      setBotErro(null);
      await api.delete(`/whatsapp/bot/clinicas/${clinicaId}`);
      await carregarBotClinicas();
    } catch {
      setBotErro("Não foi possível remover a marcação desta clínica.");
    } finally {
      setBotCarregando(null);
    }
  };

  const alterarParticipacao = async (participacao: string) => {
    try {
      setBotCarregando("participacao");
      setBotErro(null);
      await api.put("/configuracoes", { whatsapp_bot_participacao: participacao });
      await carregarBotClinicas();
    } catch {
      setBotErro("Não foi possível alterar a postura de participação. Só admin pode.");
    } finally {
      setBotCarregando(null);
    }
  };

  const carregarBotMetricas = async () => {
    try {
      setBotCarregando("metricas");
      setBotErro(null);
      const { data } = await api.get("/whatsapp/bot/metricas", { params: { dias: 7 } });
      setBotMetricas(data);
    } catch {
      setBotErro("Não foi possível carregar as métricas do bot.");
    } finally {
      setBotCarregando(null);
    }
  };

  const carregarBotConteudo = async () => {
    try {
      setBotCarregando("conteudo");
      setBotErro(null);
      const { data } = await api.get("/whatsapp/bot/conhecimento");
      setBotConteudo(data);
    } catch {
      setBotErro("Não foi possível carregar o conteúdo do bot.");
    } finally {
      setBotCarregando(null);
    }
  };

  const salvarBotConteudo = async () => {
    const validacao = validarConteudoBot(botForm);
    setBotFormErros(validacao.erros);
    if (!validacao.valido) return;
    try {
      setBotCarregando("salvar-conteudo");
      setBotErro(null);
      await api.post("/whatsapp/bot/conhecimento", botForm);
      setBotForm({ titulo: "", conteudo: "", fonte: "", publico: "ambos", indexar_semanticamente: false });
      await carregarBotConteudo();
      await carregarBotProntidao();
    } catch {
      setBotErro("Não foi possível salvar o conteúdo. Conteúdo idêntico a outro já cadastrado é recusado.");
    } finally {
      setBotCarregando(null);
    }
  };

  const simularBot = async () => {
    if (botSimMensagem.trim().length < 3) return;
    try {
      setBotCarregando("simular");
      setBotErro(null);
      setBotSimulacao(null);
      const { data } = await api.post("/whatsapp/bot/simular", {
        mensagem: botSimMensagem,
        persona: botSimPersona,
        historico: parseHistorico(botSimHistorico),
      });
      setBotSimulacao(data);
    } catch {
      setBotErro("Não foi possível simular. A simulação faz chamada real de IA e pode ter falhado no provedor.");
    } finally {
      setBotCarregando(null);
    }
  };

  const salvarConfigEmpresa = async () => {
    try {
      setSalvando(true);
      const payload: Record<string, any> = {
        ...configEmpresa,
        agenda_semanal: normalizarAgendaSemanal(configEmpresa.agenda_semanal),
        agenda_feriados: normalizarAgendaFeriados(configEmpresa.agenda_feriados),
        agenda_excecoes: normalizarAgendaExcecoes(configEmpresa.agenda_excecoes),
        agenda_rota_regras: normalizarAgendaRotaRegras(configEmpresa.agenda_rota_regras),
      };
      if (!isAdmin) {
        delete payload.fortinho_habilitado;
        delete payload.whatsapp_lembrete_automatico_habilitado;
        delete payload.whatsapp_bot_atendimento_habilitado;
        delete payload.whatsapp_bot_modo;
      }
      await api.put("/configuracoes", payload);
      setConfigEmpresa((prev) => ({
        ...prev,
        agenda_semanal: payload.agenda_semanal,
        agenda_feriados: payload.agenda_feriados,
        agenda_excecoes: payload.agenda_excecoes,
        agenda_rota_regras: payload.agenda_rota_regras,
      }));
      alert("Configurações da empresa salvas com sucesso!");
    } catch (error) {
      alert("Erro ao salvar configurações da empresa.");
    } finally {
      setSalvando(false);
    }
  };

  const atualizarJornadaDia = (
    dia: keyof AgendaSemanalConfig,
    campo: "ativo" | "inicio" | "fim",
    valor: boolean | string
  ) => {
    setConfigEmpresa((prev) => {
      const agendaAtual = normalizarAgendaSemanal(prev.agenda_semanal);
      const diaAtual = agendaAtual[dia];
      return {
        ...prev,
        agenda_semanal: {
          ...agendaAtual,
          [dia]: {
            ...diaAtual,
            [campo]: valor,
          },
        },
      };
    });
  };

  const adicionarFeriado = () => {
    if (!novoFeriadoData) {
      alert("Selecione a data do feriado.");
      return;
    }

    const novoItem: AgendaFeriadoConfig = {
      data: novoFeriadoData,
      tipo: novoFeriadoTipo,
      descricao: novoFeriadoDescricao.trim(),
    };

    setConfigEmpresa((prev) => ({
      ...prev,
      agenda_feriados: normalizarAgendaFeriados([...prev.agenda_feriados, novoItem]),
    }));
    setNovoFeriadoData("");
    setNovoFeriadoDescricao("");
    setNovoFeriadoTipo("local");
  };

  const removerFeriado = (data: string) => {
    setConfigEmpresa((prev) => ({
      ...prev,
      agenda_feriados: prev.agenda_feriados.filter((item) => item.data !== data),
    }));
  };

  const adicionarExcecao = () => {
    if (!novaExcecaoData) {
      alert("Selecione a data da excecao.");
      return;
    }

    const novaExcecao: AgendaExcecaoConfig = {
      data: novaExcecaoData,
      ativo: novaExcecaoAtiva,
      inicio: novaExcecaoInicio,
      fim: novaExcecaoFim,
      motivo: novaExcecaoMotivo.trim(),
    };

    setConfigEmpresa((prev) => ({
      ...prev,
      agenda_excecoes: normalizarAgendaExcecoes([...prev.agenda_excecoes, novaExcecao]),
    }));
    setNovaExcecaoData("");
    setNovaExcecaoAtiva(true);
    setNovaExcecaoInicio("08:00");
    setNovaExcecaoFim("18:00");
    setNovaExcecaoMotivo("");
  };

  const removerExcecao = (data: string) => {
    setConfigEmpresa((prev) => ({
      ...prev,
      agenda_excecoes: prev.agenda_excecoes.filter((item) => item.data !== data),
    }));
  };

  const alternarTipoPushAgenda = (tipo: string) => {
    setConfigUsuario((prev) => {
      const atuais = normalizarTiposPushAgenda(prev.notificacoes_push_tipos);
      const existe = atuais.includes(tipo);
      const atualizados = existe
        ? atuais.filter((item) => item !== tipo)
        : [...atuais, tipo];

      const ordenados = TIPOS_PUSH_AGENDA_OPCOES
        .map((item) => item.valor)
        .filter((item) => atualizados.includes(item));

      const ordenadosFinanceiro = TIPOS_PUSH_FINANCEIRO_OPCOES
        .map((item) => item.valor)
        .filter((item) => atualizados.includes(item));

      const ordenadosWhatsApp = TIPOS_PUSH_WHATSAPP_OPCOES
        .map((item) => item.valor)
        .filter((item) => atualizados.includes(item));

      return {
        ...prev,
        notificacoes_push_tipos: [...ordenados, ...ordenadosFinanceiro, ...ordenadosWhatsApp],
        notificacoes_push_perfil: "custom",
      };
    });
  };

  const alternarTipoPrioridadeAltaPush = (tipo: string) => {
    setConfigUsuario((prev) => {
      const atuais = normalizarTiposPrioridadeAltaPush(prev.notificacoes_push_prioridade_alta_tipos);
      const existe = atuais.includes(tipo);
      const atualizados = existe
        ? atuais.filter((item) => item !== tipo)
        : [...atuais, tipo];
      const ordenados = TIPOS_PUSH_OPCOES.map((item) => item.valor).filter((item) => atualizados.includes(item));
      return {
        ...prev,
        notificacoes_push_prioridade_alta_tipos: ordenados,
        notificacoes_push_perfil: "custom",
      };
    });
  };

  const aplicarPerfilPush = (preset: PerfilPushPreset) => {
    setConfigUsuario((prev) => ({
      ...prev,
      notificacoes_push_tipos: normalizarTiposPushAgenda(preset.tipos),
      notificacoes_push_prioridade_alta_tipos: normalizarTiposPrioridadeAltaPush(preset.alta_prioridade),
      notificacoes_push_agrupar: preset.agrupar,
      notificacoes_push_lembrete_pendencias: preset.lembrete_pendencias,
      notificacoes_push_lembrete_horas: preset.lembrete_horas,
      notificacoes_push_perfil: preset.perfil,
    }));
  };

  const salvarConfigUsuario = async () => {
    try {
      setSalvando(true);
      const lembreteHoras = Number(configUsuario.notificacoes_push_lembrete_horas || 6);
      let proximaConfig = {
        ...configUsuario,
        notificacoes_push_tipos: normalizarTiposPushAgenda(configUsuario.notificacoes_push_tipos),
        notificacoes_push_prioridade_alta_tipos: normalizarTiposPrioridadeAltaPush(
          configUsuario.notificacoes_push_prioridade_alta_tipos
        ),
        notificacoes_push_lembrete_horas: Number.isFinite(lembreteHoras)
          ? Math.min(168, Math.max(1, Math.round(lembreteHoras)))
          : 6,
        notificacoes_push_perfil: String(configUsuario.notificacoes_push_perfil || "custom").toLowerCase(),
      };

      if (proximaConfig.notificacoes_push && proximaConfig.notificacoes_push_tipos.length === 0) {
        alert("Selecione pelo menos um tipo de evento para notificacao push.");
        return;
      }
      if (
        proximaConfig.notificacoes_push &&
        proximaConfig.notificacoes_push_lembrete_pendencias &&
        (proximaConfig.notificacoes_push_lembrete_horas < 1 ||
          proximaConfig.notificacoes_push_lembrete_horas > 168)
      ) {
        alert("Defina o lembrete de pendencia entre 1 e 168 horas.");
        return;
      }

      if (proximaConfig.notificacoes_push && typeof window !== "undefined") {
        const suportaPushWeb =
          window.isSecureContext &&
          "Notification" in window &&
          "serviceWorker" in navigator &&
          "PushManager" in window;

        if (!suportaPushWeb) {
          proximaConfig = { ...proximaConfig, notificacoes_push: false };
          setConfigUsuario(proximaConfig);
          alert("Este navegador/URL nao suporta push web. Use localhost ou HTTPS.");
        } else if (Notification.permission === "default") {
          const permissao = await Notification.requestPermission();
          if (permissao !== "granted") {
            proximaConfig = { ...proximaConfig, notificacoes_push: false };
            setConfigUsuario(proximaConfig);
            alert("Permissao de notificacoes nao concedida. Push foi desativado.");
          }
        } else if (Notification.permission === "denied") {
          proximaConfig = { ...proximaConfig, notificacoes_push: false };
          setConfigUsuario(proximaConfig);
          alert("Notificacoes bloqueadas no navegador para este site.");
        }
      }

      await api.put("/configuracoes/usuario", proximaConfig);
      await syncPushNotificationsNow(false);
      requestPushSync(proximaConfig.notificacoes_push);
      alert("Configurações pessoais salvas com sucesso!");
    } catch (error) {
      alert("Erro ao salvar configurações pessoais.");
    } finally {
      setSalvando(false);
    }
  };

  const handleUploadLogo = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      alert("Arquivo muito grande. Máximo: 5MB");
      return;
    }

    const formData = new FormData();
    formData.append("arquivo", file);

    try {
      await api.post("/configuracoes/logomarca", formData);
      
      // Criar preview local
      const reader = new FileReader();
      reader.onloadend = () => setPreviewLogo(reader.result as string);
      reader.readAsDataURL(file);
      
      setConfigEmpresa((prev) => ({ ...prev, tem_logomarca: true }));
      alert("Logomarca atualizada com sucesso!");
    } catch (error) {
      alert("Erro ao fazer upload da logomarca.");
    }
  };

  const handleUploadAssinaturaSistema = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      alert("Arquivo muito grande. Máximo: 5MB");
      return;
    }

    const formData = new FormData();
    formData.append("arquivo", file);

    try {
      await api.post("/configuracoes/assinatura", formData);
      
      const reader = new FileReader();
      reader.onloadend = () => setPreviewAssinaturaSistema(reader.result as string);
      reader.readAsDataURL(file);
      
      setConfigEmpresa((prev) => ({ ...prev, tem_assinatura: true }));
      alert("Assinatura do sistema atualizada com sucesso!");
    } catch (error) {
      alert("Erro ao fazer upload da assinatura.");
    }
  };

  const handleUploadAssinaturaUsuario = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      alert("Arquivo muito grande. Máximo: 5MB");
      return;
    }

    const formData = new FormData();
    formData.append("arquivo", file);

    try {
      await api.post("/configuracoes/usuario/assinatura", formData);
      
      const reader = new FileReader();
      reader.onloadend = () => setPreviewAssinaturaUsuario(reader.result as string);
      reader.readAsDataURL(file);
      
      setConfigUsuario((prev) => ({ ...prev, tem_assinatura: true }));
      alert("Assinatura pessoal atualizada com sucesso!");
    } catch (error) {
      alert("Erro ao fazer upload da assinatura pessoal.");
    }
  };

  const removerLogo = async () => {
    if (!confirm("Tem certeza que deseja remover a logomarca?")) return;
    
    try {
      await api.delete("/configuracoes/logomarca");
      setPreviewLogo(null);
      setConfigEmpresa((prev) => ({ ...prev, tem_logomarca: false }));
      alert("Logomarca removida com sucesso!");
    } catch (error) {
      alert("Erro ao remover logomarca.");
    }
  };

  const removerAssinaturaSistema = async () => {
    if (!confirm("Tem certeza que deseja remover a assinatura do sistema?")) return;
    
    try {
      await api.delete("/configuracoes/assinatura");
      setPreviewAssinaturaSistema(null);
      setConfigEmpresa((prev) => ({ ...prev, tem_assinatura: false }));
      alert("Assinatura removida com sucesso!");
    } catch (error) {
      alert("Erro ao remover assinatura.");
    }
  };

  const agendaSemanalAtual = normalizarAgendaSemanal(configEmpresa.agenda_semanal);
  const agendaRotaRegrasAtual =
    configEmpresa.agenda_rota_regras || normalizarAgendaRotaRegras(DEFAULT_AGENDA_ROTA_REGRAS);

  useRoutePerformanceReady(loading);

  if (loading) {
    return (
      <DashboardLayout>
        <div className="fc-settings-page">
          <div className="fc-settings-loading">
            <span aria-hidden="true" />
            Carregando configurações...
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="fc-settings-page">
        <div className="fc-settings-header">
          <div>
            <span className="fc-settings-kicker">
              <Settings className="h-4 w-4" />
              Governança do sistema
            </span>
            <h1>Configurações</h1>
            <p>Gerencie identidade, operação, preferências e acessos da Fort Cordis.</p>
          </div>
          <div className="fc-settings-context">
            <Shield className="h-5 w-5" />
            <span>Área atual</span>
            <strong>
              {aba === "empresa"
                ? "Empresa"
                : aba === "usuario"
                  ? "Minha conta"
                  : aba === "usuarios"
                    ? "Usuários"
                    : aba === "maps" ? "Google Maps" : "Desempenho"}
            </strong>
          </div>
        </div>

        <div className="fc-settings-tabs" role="tablist" aria-label="Áreas de configuração">
          <button
            type="button"
            role="tab"
            aria-selected={aba === "empresa"}
            onClick={() => setAba("empresa")}
            className={`fc-settings-tab ${aba === "empresa" ? "fc-settings-tab-active" : ""}`}
          >
            <Building2 className="w-4 h-4" />
            Empresa
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={aba === "usuario"}
            onClick={() => setAba("usuario")}
            className={`fc-settings-tab ${aba === "usuario" ? "fc-settings-tab-active" : ""}`}
          >
            <UserCircle className="w-4 h-4" />
            Minha Conta
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={aba === "usuarios"}
            onClick={() => setAba("usuarios")}
            className={`fc-settings-tab ${aba === "usuarios" ? "fc-settings-tab-active" : ""}`}
          >
            <Users className="w-4 h-4" />
            Usuários
          </button>
          {isAdmin ? (
            <button
              type="button"
              role="tab"
              aria-selected={aba === "observabilidade"}
              onClick={() => setAba("observabilidade")}
              className={`fc-settings-tab ${aba === "observabilidade" ? "fc-settings-tab-active" : ""}`}
            >
              <Activity className="w-4 h-4" />
              Desempenho
            </button>
          ) : null}
          {isAdmin && <button type="button" role="tab" aria-selected={aba === "maps"} onClick={() => setAba("maps")} className={`fc-settings-tab ${aba === "maps" ? "fc-settings-tab-active" : ""}`}><Shield className="w-4 h-4" />Custos Google Maps</button>}
        </div>

        {aba === "maps" && isAdmin && <GoogleMapsAdminPanel />}

        {aba === "empresa" && (
          <div className="fc-settings-content fc-settings-company">
            {/* Dados da Empresa */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Building2 className="w-5 h-5 text-teal-600" />
                Dados da Empresa
              </h2>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Nome da Empresa
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.nome_empresa ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, nome_empresa: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    E-mail
                  </label>
                  <input
                    type="email"
                    value={configEmpresa.email ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, email: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Telefone
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.telefone ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, telefone: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Website
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.website ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, website: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
                
                <div className="md:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Endereço
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.endereco ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, endereco: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Cidade
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.cidade ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, cidade: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Estado
                  </label>
                  <input
                    type="text"
                    maxLength={2}
                    value={configEmpresa.estado ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, estado: e.target.value.toUpperCase() })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
              </div>
              
              <div className="mt-4">
                <button
                  onClick={salvarConfigEmpresa}
                  disabled={salvando}
                  className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {salvando ? "Salvando..." : "Salvar Dados da Empresa"}
                </button>
              </div>
            </div>

            {/* Dados Fiscais (ISS / NFS-e) */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Building2 className="w-5 h-5 text-teal-600" />
                Dados Fiscais (Prestador de Servicos)
              </h2>
              <p className="text-sm text-gray-500 mb-4">
                Dados do prestador de servicos para emissao de NFS-e e calculo de ISS.
                Necessarios para exportar relatorios contabeis para o contador.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Inscricao Municipal (IM)
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.inscricao_municipal ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, inscricao_municipal: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                    placeholder="000000000"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Inscricao Estadual (IE) / CNPJ
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.inscricao_estadual ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, inscricao_estadual: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                    placeholder="00.000.000/0001-00"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    CNAE (Codigo Nacional de Atividade)
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.cnae ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, cnae: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                    placeholder="8622-1/01 (Clinica veterinaria)"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Regime Tributario
                  </label>
                  <select
                    value={configEmpresa.regime_tributario ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, regime_tributario: e.target.value ? Number(e.target.value) : null })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  >
                    <option value="">Selecione...</option>
                    <option value="1">1 - MEI (Microempreendedor Individual)</option>
                    <option value="2">2 - Simples Nacional</option>
                    <option value="3">3 - Lucro Presumido</option>
                    <option value="4">4 - Lucro Real</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Codigo do Municipio (IBGE)
                  </label>
                  <input
                    type="text"
                    value={configEmpresa.codigo_municipio_servico ?? ""}
                    onChange={(e) => setConfigEmpresa({ ...configEmpresa, codigo_municipio_servico: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                    placeholder="230440 (Fortaleza)"
                  />
                  <p className="text-xs text-gray-400 mt-1">Codigo IBGE do municipio onde o servico e prestado.</p>
                </div>
              </div>

              <div className="mt-4">
                <button
                  onClick={salvarConfigEmpresa}
                  disabled={salvando}
                  className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {salvando ? "Salvando..." : "Salvar Dados Fiscais"}
                </button>
              </div>
            </div>

            {/* Jornada da Agenda */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-2">Funcionamento da Agenda</h2>
              {somenteLeituraAgenda && (
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-3">
                  Visualizacao em modo leitura para este perfil. Edicao disponivel apenas com permissao em Configuracoes.
                </p>
              )}
              <p className="text-sm text-gray-500 mb-4">
                Defina abertura/fechamento por dia da semana e os feriados (local ou nacional) em que a agenda fica fechada.
              </p>

              <div className="overflow-x-auto mb-6">
                <table className="min-w-full text-sm border border-gray-200 rounded-lg">
                  <thead className="bg-gray-50 text-gray-600">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium">Dia</th>
                      <th className="text-left px-3 py-2 font-medium">Aberta</th>
                      <th className="text-left px-3 py-2 font-medium">Abre</th>
                      <th className="text-left px-3 py-2 font-medium">Fecha</th>
                    </tr>
                  </thead>
                  <tbody>
                    {DIAS_SEMANA_LABELS.map((dia) => {
                      const cfg = agendaSemanalAtual[dia.id];
                      return (
                        <tr key={dia.id} className="border-t border-gray-100">
                          <td className="px-3 py-2 text-gray-800">{dia.nome}</td>
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              checked={cfg.ativo}
                              disabled={somenteLeituraAgenda}
                              onChange={(e) => atualizarJornadaDia(dia.id, "ativo", e.target.checked)}
                              className="w-4 h-4 text-teal-600"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="time"
                              value={cfg.inicio}
                              disabled={somenteLeituraAgenda || !cfg.ativo}
                              onChange={(e) => atualizarJornadaDia(dia.id, "inicio", e.target.value)}
                              className="px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100 disabled:text-gray-400"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="time"
                              value={cfg.fim}
                              disabled={somenteLeituraAgenda || !cfg.ativo}
                              onChange={(e) => atualizarJornadaDia(dia.id, "fim", e.target.value)}
                              className="px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100 disabled:text-gray-400"
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="border border-gray-200 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-gray-800 mb-3">Feriados com agenda fechada</h3>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
                  <input
                    type="date"
                    value={novoFeriadoData}
                    disabled={somenteLeituraAgenda}
                    onChange={(e) => setNovoFeriadoData(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg"
                  />
                  <select
                    value={novoFeriadoTipo}
                    disabled={somenteLeituraAgenda}
                    onChange={(e) => setNovoFeriadoTipo((e.target.value === "nacional" ? "nacional" : "local"))}
                    className="px-3 py-2 border border-gray-300 rounded-lg"
                  >
                    <option value="local">Local</option>
                    <option value="nacional">Nacional</option>
                  </select>
                  <input
                    type="text"
                    value={novoFeriadoDescricao}
                    disabled={somenteLeituraAgenda}
                    onChange={(e) => setNovoFeriadoDescricao(e.target.value)}
                    placeholder="Descricao (opcional)"
                    className="px-3 py-2 border border-gray-300 rounded-lg md:col-span-2"
                  />
                </div>

                <button
                  type="button"
                  onClick={adicionarFeriado}
                  disabled={somenteLeituraAgenda}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  Adicionar feriado
                </button>

                <div className="mt-4 space-y-2">
                  {configEmpresa.agenda_feriados.length === 0 ? (
                    <p className="text-sm text-gray-500">Nenhum feriado cadastrado.</p>
                  ) : (
                    configEmpresa.agenda_feriados.map((feriado) => (
                      <div
                        key={feriado.data}
                        className="flex items-center justify-between gap-3 px-3 py-2 border border-gray-200 rounded-lg"
                      >
                        <div className="text-sm text-gray-700">
                          <span className="font-medium">{formatCalendarDate(feriado.data)}</span>
                          <span className="mx-2 text-gray-400">|</span>
                          <span className="uppercase text-xs font-semibold text-orange-700">
                            {feriado.tipo || "local"}
                          </span>
                          {(feriado.descricao || "").trim() ? (
                            <span className="ml-2 text-gray-600">- {feriado.descricao}</span>
                          ) : null}
                        </div>
                        <button
                          type="button"
                          disabled={somenteLeituraAgenda}
                          onClick={() => removerFeriado(feriado.data)}
                          className="px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded"
                        >
                          Remover
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="border border-gray-200 rounded-lg p-4 mt-4">
                <h3 className="text-sm font-semibold text-gray-800 mb-3">Excecoes por data (horario especial)</h3>
                <p className="text-xs text-gray-500 mb-3">
                  Use para ampliar ou reduzir horario em um dia especifico. Exemplo: amanha das 08:00 as 18:00.
                </p>

                <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-3">
                  <input
                    type="date"
                    value={novaExcecaoData}
                    disabled={somenteLeituraAgenda}
                    onChange={(e) => setNovaExcecaoData(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg"
                  />
                  <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={novaExcecaoAtiva}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => setNovaExcecaoAtiva(e.target.checked)}
                      className="w-4 h-4 text-teal-600"
                    />
                    Agenda aberta
                  </label>
                  <input
                    type="time"
                    value={novaExcecaoInicio}
                    disabled={somenteLeituraAgenda || !novaExcecaoAtiva}
                    onChange={(e) => setNovaExcecaoInicio(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100 disabled:text-gray-400"
                  />
                  <input
                    type="time"
                    value={novaExcecaoFim}
                    disabled={somenteLeituraAgenda || !novaExcecaoAtiva}
                    onChange={(e) => setNovaExcecaoFim(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100 disabled:text-gray-400"
                  />
                  <button
                    type="button"
                    onClick={adicionarExcecao}
                    disabled={somenteLeituraAgenda}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                  >
                    Adicionar excecao
                  </button>
                </div>

                <input
                  type="text"
                  value={novaExcecaoMotivo}
                  disabled={somenteLeituraAgenda}
                  onChange={(e) => setNovaExcecaoMotivo(e.target.value)}
                  placeholder="Motivo (opcional)"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-4"
                />

                <div className="space-y-2">
                  {configEmpresa.agenda_excecoes.length === 0 ? (
                    <p className="text-sm text-gray-500">Nenhuma excecao cadastrada.</p>
                  ) : (
                    configEmpresa.agenda_excecoes.map((excecao) => (
                      <div
                        key={excecao.data}
                        className="flex items-center justify-between gap-3 px-3 py-2 border border-gray-200 rounded-lg"
                      >
                        <div className="text-sm text-gray-700">
                          <span className="font-medium">{formatCalendarDate(excecao.data)}</span>
                          <span className="mx-2 text-gray-400">|</span>
                          {excecao.ativo ? (
                            <span className="text-emerald-700 font-medium">
                              Aberta {excecao.inicio} as {excecao.fim}
                            </span>
                          ) : (
                            <span className="text-red-700 font-medium">Fechada</span>
                          )}
                          {(excecao.motivo || "").trim() ? (
                            <span className="ml-2 text-gray-600">- {excecao.motivo}</span>
                          ) : null}
                        </div>
                        <button
                          type="button"
                          disabled={somenteLeituraAgenda}
                          onClick={() => removerExcecao(excecao.data)}
                          className="px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded"
                        >
                          Remover
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="border border-gray-200 rounded-lg p-4 mt-4 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-gray-800">Regras de rota e oferta</h3>
                  <p className="text-xs text-gray-500 mt-1">
                    Ajuste as regras de sugestao de horario para reduzir deslocamento e melhorar encaixe por regiao.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Nome da base</label>
                    <input
                      type="text"
                      value={agendaRotaRegrasAtual.base.label || ""}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaBase("label", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Endereco da base</label>
                    <input
                      type="text"
                      value={agendaRotaRegrasAtual.base.address || ""}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaBase("address", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">CEP da base</label>
                    <input
                      type="text"
                      value={agendaRotaRegrasAtual.base.zip_code || ""}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaBase("zip_code", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Latitude (opcional)</label>
                      <input
                        type="number"
                        step="0.000001"
                        value={agendaRotaRegrasAtual.base.lat ?? ""}
                        disabled={somenteLeituraAgenda}
                        onChange={(e) => atualizarRegraRotaBase("lat", e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Longitude (opcional)</label>
                      <input
                        type="number"
                        step="0.000001"
                        value={agendaRotaRegrasAtual.base.lng ?? ""}
                        disabled={somenteLeituraAgenda}
                        onChange={(e) => atualizarRegraRotaBase("lng", e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                      />
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-teal-200 bg-teal-50 p-3 space-y-3">
                  <div>
                    <h4 className="text-sm font-semibold text-teal-950">Primeiro atendimento do dia</h4>
                    <p className="mt-1 text-xs text-teal-900">
                      O primeiro horario parte da abertura da agenda somada ao trajeto desde a base e a margem segura. Hoje, considera tambem a hora atual. As cidades abaixo exigem seus horarios minimos quando forem posteriores a esse calculo.
                    </p>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {([
                      ["caucaia", "Caucaia"],
                      ["maracanau", "Maracanaú"],
                      ["eusebio", "Eusébio"],
                      ["itaitinga", "Itaitinga"],
                    ] as const).map(([cidade, nome]) => (
                      <div key={cidade}>
                        <label className="block text-xs font-medium text-teal-950 mb-1" htmlFor={`agenda-primeiro-${cidade}`}>
                          {nome} a partir de
                        </label>
                        <input
                          id={`agenda-primeiro-${cidade}`}
                          type="time"
                          value={agendaRotaRegrasAtual.route_policy.first_appointment_city_floors[cidade]}
                          disabled={somenteLeituraAgenda}
                          onChange={(e) => atualizarRegraPrimeiroAtendimentoCidade(cidade, e.target.value)}
                          className="w-full px-3 py-2 border border-teal-300 rounded-lg"
                        />
                      </div>
                    ))}
                  </div>
                </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    <div className="md:col-span-2 lg:col-span-3 border border-gray-200 rounded-lg p-3 bg-gray-50">
                      <h4 className="text-sm font-semibold text-gray-800">Renderizacao das grades da agenda</h4>
                      <p className="text-xs text-gray-500 mt-1 mb-3">
                        Define o periodo exibido nas visoes de grade e o tamanho de cada slot (Agenda panoramica e FullCalendar).
                      </p>
                      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                        <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 md:col-span-2">
                          <input
                            type="checkbox"
                            checked={agendaRotaRegrasAtual.rendering_policy.use_custom_window}
                            disabled={somenteLeituraAgenda}
                            onChange={(e) =>
                              atualizarRegraRenderizacaoAgenda("use_custom_window", e.target.checked)
                            }
                            className="w-4 h-4 text-teal-600"
                          />
                          Usar periodo fixo de renderizacao
                        </label>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1">Inicio da grade</label>
                          <input
                            type="time"
                            value={agendaRotaRegrasAtual.rendering_policy.window_start}
                            disabled={
                              somenteLeituraAgenda || !agendaRotaRegrasAtual.rendering_policy.use_custom_window
                            }
                            onChange={(e) =>
                              atualizarRegraRenderizacaoAgenda("window_start", e.target.value)
                            }
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100 disabled:text-gray-400"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1">Fim da grade</label>
                          <input
                            type="time"
                            value={agendaRotaRegrasAtual.rendering_policy.window_end}
                            disabled={
                              somenteLeituraAgenda || !agendaRotaRegrasAtual.rendering_policy.use_custom_window
                            }
                            onChange={(e) =>
                              atualizarRegraRenderizacaoAgenda("window_end", e.target.value)
                            }
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100 disabled:text-gray-400"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1">
                            Tamanho do slot (min)
                          </label>
                          <input
                            type="number"
                            min={5}
                            max={120}
                            step={5}
                            value={agendaRotaRegrasAtual.rendering_policy.slot_interval_min}
                            disabled={somenteLeituraAgenda}
                            onChange={(e) =>
                              atualizarRegraRenderizacaoAgenda(
                                "slot_interval_min",
                                Number(e.target.value || 0)
                              )
                            }
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                          />
                        </div>
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Ancora proxima (min)</label>
                    <input
                      type="number"
                      min={1}
                      max={240}
                      value={agendaRotaRegrasAtual.thresholds.nearby_anchor_max_travel_min}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaThreshold(
                          "nearby_anchor_max_travel_min",
                          Number(e.target.value || 0)
                        )
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Clinica distante da base (min)</label>
                    <input
                      type="number"
                      min={1}
                      max={360}
                      value={agendaRotaRegrasAtual.thresholds.distant_clinic_min_travel_from_base_min}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaThreshold(
                          "distant_clinic_min_travel_from_base_min",
                          Number(e.target.value || 0)
                        )
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Baixa frequencia (agend. 30d)</label>
                    <input
                      type="number"
                      min={0}
                      max={60}
                      value={agendaRotaRegrasAtual.thresholds.low_frequency_max_bookings_30d}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaThreshold(
                          "low_frequency_max_bookings_30d",
                          Number(e.target.value || 0)
                        )
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Desvio maximo insercao (min)</label>
                    <input
                      type="number"
                      min={0}
                      max={360}
                      value={agendaRotaRegrasAtual.thresholds.max_insertion_detour_min}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaThreshold(
                          "max_insertion_detour_min",
                          Number(e.target.value || 0)
                        )
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Deslocamento maximo entre atendimentos (min)
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={360}
                      value={agendaRotaRegrasAtual.thresholds.max_neighbor_travel_min}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaThreshold(
                          "max_neighbor_travel_min",
                          Number(e.target.value || 0)
                        )
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Margem segura deslocamento (min)</label>
                    <input
                      type="number"
                      min={0}
                      max={120}
                      value={agendaRotaRegrasAtual.thresholds.safe_margin_min}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaThreshold("safe_margin_min", Number(e.target.value || 0))
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Intervalo entre pacientes na mesma clínica (min)</label>
                    <input
                      type="number"
                      min={0}
                      max={120}
                      value={agendaRotaRegrasAtual.thresholds.same_location_transition_min}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaThreshold("same_location_transition_min", Number(e.target.value || 0))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                    <p className="mt-1 text-xs text-gray-500">Tempo entre atendimentos no mesmo local. Não altera a duração do serviço nem a margem de deslocamento.</p>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Inicio da janela fim de rota</label>
                    <input
                      type="time"
                      value={agendaRotaRegrasAtual.route_policy.end_of_route_window_start}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaPolicy("end_of_route_window_start", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                </div>

                <div className="rounded-lg border border-teal-200 bg-teal-50 p-3">
                  <label className="inline-flex items-center gap-2 text-sm font-semibold text-gray-800">
                    <input
                      type="checkbox"
                      checked={agendaRotaRegrasAtual.route_policy.regional_transition_enabled}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaPolicy("regional_transition_enabled", e.target.checked)}
                      className="h-4 w-4 text-teal-600"
                    />
                    Permitir uma transição regional por dia
                  </label>
                  <p className="mt-1 text-xs text-gray-600">
                    Permite um único deslocamento acima do limite normal de {agendaRotaRegrasAtual.thresholds.max_neighbor_travel_min} min,
                    com tempo de viagem e margem reservados. Os demais trechos seguem o limite normal.
                  </p>
                  <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div>
                      <label htmlFor="transicao-regional-deslocamento" className="mb-1 block text-xs font-medium text-gray-600">
                        Viagem máxima da transição (min)
                      </label>
                      <input
                        id="transicao-regional-deslocamento"
                        type="number"
                        min={1}
                        max={50}
                        value={agendaRotaRegrasAtual.route_policy.regional_transition_max_travel_min}
                        disabled={somenteLeituraAgenda || !agendaRotaRegrasAtual.route_policy.regional_transition_enabled}
                        onChange={(e) => atualizarRegraRotaPolicy("regional_transition_max_travel_min", Number(e.target.value || 0))}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 disabled:bg-gray-100 disabled:text-gray-400"
                      />
                    </div>
                    <div>
                      <label htmlFor="transicao-regional-margem" className="mb-1 block text-xs font-medium text-gray-600">
                        Margem total além da viagem (min)
                      </label>
                      <input
                        id="transicao-regional-margem"
                        type="number"
                        min={15}
                        max={120}
                        value={agendaRotaRegrasAtual.route_policy.regional_transition_margin_min}
                        disabled={somenteLeituraAgenda || !agendaRotaRegrasAtual.route_policy.regional_transition_enabled}
                        onChange={(e) => atualizarRegraRotaPolicy("regional_transition_margin_min", Number(e.target.value || 0))}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 disabled:bg-gray-100 disabled:text-gray-400"
                      />
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-gray-600">
                    Limite fixo de uma transição por dia, com viagem de até 50 min e margem mínima de 15 min.
                    A recorrência considera os últimos 60 dias para priorizar clínicas, sem excluir as demais.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Oferta padrao (dias a frente)
                    </label>
                    <input
                      type="text"
                      value={formatarDiasAFrenteInput(
                        agendaRotaRegrasAtual.offer_policy.default_first_offer_days_ahead
                      )}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaOfferDias("default_first_offer_days_ahead", e.target.value)
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                      placeholder="Ex.: 2"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Oferta distantes/baixa freq. (dias)
                    </label>
                    <input
                      type="text"
                      value={formatarDiasAFrenteInput(
                        agendaRotaRegrasAtual.offer_policy.distant_low_frequency_first_offer_days_ahead
                      )}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaOfferDias(
                          "distant_low_frequency_first_offer_days_ahead",
                          e.target.value
                        )
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                      placeholder="Ex.: 3, 4"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Emergencia (dias a frente)
                    </label>
                    <input
                      type="text"
                      value={formatarDiasAFrenteInput(
                        agendaRotaRegrasAtual.offer_policy.emergency_first_offer_days_ahead
                      )}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaOfferDias("emergency_first_offer_days_ahead", e.target.value)
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                      placeholder="Ex.: 1, 2"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={agendaRotaRegrasAtual.offer_policy.allow_d2_if_anchor_exists}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaOfferBool("allow_d2_if_anchor_exists", e.target.checked)}
                      className="w-4 h-4 text-teal-600"
                    />
                    Permitir D+2 quando houver ancora
                  </label>
                  <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={agendaRotaRegrasAtual.route_policy.prefer_near_base_at_end_of_route}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaPolicy("prefer_near_base_at_end_of_route", e.target.checked)}
                      className="w-4 h-4 text-teal-600"
                    />
                    Priorizar proximas da base no fim da rota
                  </label>
                  <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={agendaRotaRegrasAtual.route_policy.reject_clear_inefficiency}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) => atualizarRegraRotaPolicy("reject_clear_inefficiency", e.target.checked)}
                      className="w-4 h-4 text-teal-600"
                    />
                    Bloquear encaixe ineficiente
                  </label>
                  <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={agendaRotaRegrasAtual.fallback_policy.suggest_alternative_slots_when_blocked}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaFallback(
                          "suggest_alternative_slots_when_blocked",
                          e.target.checked
                        )
                      }
                      className="w-4 h-4 text-teal-600"
                    />
                    Sugerir alternativas quando bloquear
                  </label>
                  <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={agendaRotaRegrasAtual.fallback_policy.allow_extra_slot_start_or_end_route_for_emergency}
                      disabled={somenteLeituraAgenda}
                      onChange={(e) =>
                        atualizarRegraRotaFallback(
                          "allow_extra_slot_start_or_end_route_for_emergency",
                          e.target.checked
                        )
                      }
                      className="w-4 h-4 text-teal-600"
                    />
                    Permitir extra para emergencia
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Bonus perto da base</label>
                      <input
                        type="number"
                        min={0}
                        max={999}
                        value={agendaRotaRegrasAtual.route_policy.bonus_near_base_score}
                        disabled={somenteLeituraAgenda}
                        onChange={(e) =>
                          atualizarRegraRotaPolicy("bonus_near_base_score", Number(e.target.value || 0))
                        }
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Penalty longe da base</label>
                      <input
                        type="number"
                        min={0}
                        max={999}
                        value={agendaRotaRegrasAtual.route_policy.penalty_far_base_score}
                        disabled={somenteLeituraAgenda}
                        onChange={(e) =>
                          atualizarRegraRotaPolicy("penalty_far_base_score", Number(e.target.value || 0))
                        }
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold text-gray-800">Overrides por clinica</h4>
                    <button
                      type="button"
                      onClick={adicionarOverrideRota}
                      disabled={somenteLeituraAgenda}
                      className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                    >
                      Adicionar override
                    </button>
                  </div>

                  {agendaRotaRegrasAtual.clinic_overrides.length === 0 ? (
                    <p className="text-sm text-gray-500">Nenhuma clinica com regra especifica.</p>
                  ) : (
                    <div className="space-y-3">
                      {agendaRotaRegrasAtual.clinic_overrides.map((item, index) => (
                        <div key={`override-${index}`} className="border border-gray-200 rounded-lg p-3">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">Clinica</label>
                              <input
                                type="text"
                                value={item.clinic_name}
                                disabled={somenteLeituraAgenda}
                                onChange={(e) => atualizarOverrideRota(index, "clinic_name", e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">
                                Dias a frente (csv)
                              </label>
                              <input
                                type="text"
                                value={formatarDiasAFrenteInput(item.force_days_ahead)}
                                disabled={somenteLeituraAgenda}
                                onChange={(e) => atualizarOverrideRota(index, "force_days_ahead", e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                                placeholder="Ex.: 3, 4"
                              />
                            </div>
                            <div className="flex items-end justify-between gap-3">
                              <label className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-700">
                                <input
                                  type="checkbox"
                                  checked={item.prefer_only_when_anchor_exists}
                                  disabled={somenteLeituraAgenda}
                                  onChange={(e) =>
                                    atualizarOverrideRota(
                                      index,
                                      "prefer_only_when_anchor_exists",
                                      e.target.checked
                                    )
                                  }
                                  className="w-4 h-4 text-teal-600"
                                />
                                Exigir ancora proxima
                              </label>
                              <button
                                type="button"
                                disabled={somenteLeituraAgenda}
                                onClick={() => removerOverrideRota(index)}
                                className="px-3 py-2 text-xs text-red-600 border border-red-200 rounded-lg hover:bg-red-50"
                              >
                                Remover
                              </button>
                            </div>
                          </div>
                          <div className="mt-3">
                            <label className="block text-xs font-medium text-gray-600 mb-1">Observacao</label>
                            <input
                              type="text"
                              value={item.notes || ""}
                              disabled={somenteLeituraAgenda}
                              onChange={(e) => atualizarOverrideRota(index, "notes", e.target.value)}
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-4">
                <button
                  onClick={salvarConfigEmpresa}
                  disabled={salvando || somenteLeituraAgenda}
                  className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {salvando ? "Salvando..." : "Salvar funcionamento da agenda"}
                </button>
              </div>
            </div>

            {/* Logomarca */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-teal-600" />
                Logomarca
              </h2>
              
              <div className="flex items-center gap-6">
                <div className="w-40 h-32 bg-gray-100 rounded-lg flex items-center justify-center border-2 border-dashed border-gray-300 overflow-hidden">
                  {previewLogo ? (
                    <img src={previewLogo} alt="Logomarca" className="w-full h-full object-contain" />
                  ) : (
                    <span className="text-gray-400 text-sm">Sem logomarca</span>
                  )}
                </div>
                
                <div className="space-y-3">
                  <label className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer">
                    <Upload className="w-4 h-4" />
                    Upload Logomarca
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleUploadLogo}
                      className="hidden"
                    />
                  </label>
                  
                  {previewLogo && (
                    <button
                      onClick={removerLogo}
                      className="flex items-center gap-2 px-4 py-2 bg-red-100 text-red-600 rounded-lg hover:bg-red-200"
                    >
                      <Trash2 className="w-4 h-4" />
                      Remover
                    </button>
                  )}
                </div>
              </div>
              
              <div className="mt-4 flex items-center gap-2">
                <input
                  type="checkbox"
                  id="mostrar_logomarca"
                  checked={configEmpresa.mostrar_logomarca}
                  onChange={(e) => setConfigEmpresa({ ...configEmpresa, mostrar_logomarca: e.target.checked })}
                  className="w-4 h-4 text-teal-600"
                />
                <label htmlFor="mostrar_logomarca" className="text-sm text-gray-700">
                  Mostrar logomarca nos laudos
                </label>
              </div>
            </div>

            {/* Assinatura do Sistema */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Signature className="w-5 h-5 text-teal-600" />
                Assinatura Padrão do Sistema
              </h2>
              
              <div className="flex items-center gap-6">
                <div className="w-40 h-24 bg-gray-100 rounded-lg flex items-center justify-center border-2 border-dashed border-gray-300 overflow-hidden">
                  {previewAssinaturaSistema ? (
                    <img src={previewAssinaturaSistema} alt="Assinatura" className="w-full h-full object-contain" />
                  ) : (
                    <span className="text-gray-400 text-sm">Sem assinatura</span>
                  )}
                </div>
                
                <div className="space-y-3">
                  <label className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer">
                    <Upload className="w-4 h-4" />
                    Upload Assinatura
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleUploadAssinaturaSistema}
                      className="hidden"
                    />
                  </label>
                  
                  {previewAssinaturaSistema && (
                    <button
                      onClick={removerAssinaturaSistema}
                      className="flex items-center gap-2 px-4 py-2 bg-red-100 text-red-600 rounded-lg hover:bg-red-200"
                    >
                      <Trash2 className="w-4 h-4" />
                      Remover
                    </button>
                  )}
                </div>
              </div>
              
              <p className="mt-3 text-sm text-gray-500">
                Esta assinatura será usada como padrão quando o usuário não tiver assinatura própria.
              </p>
              
              <div className="mt-4 flex items-center gap-2">
                <input
                  type="checkbox"
                  id="mostrar_assinatura"
                  checked={configEmpresa.mostrar_assinatura}
                  onChange={(e) => setConfigEmpresa({ ...configEmpresa, mostrar_assinatura: e.target.checked })}
                  className="w-4 h-4 text-teal-600"
                />
                <label htmlFor="mostrar_assinatura" className="text-sm text-gray-700">
                  Mostrar assinatura nos laudos
                </label>
              </div>
            </div>

            {/* Fortinho */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-2">Fortinho</h2>
              <p className="text-sm text-gray-500 mb-4">
                Controle global do assistente Fortinho para todo o sistema.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="fortinho_habilitado"
                  checked={configEmpresa.fortinho_habilitado}
                  disabled={!isAdmin}
                  onChange={(e) => setConfigEmpresa({ ...configEmpresa, fortinho_habilitado: e.target.checked })}
                  className="w-4 h-4 text-teal-600 disabled:opacity-50"
                />
                <label htmlFor="fortinho_habilitado" className="text-sm text-gray-700">
                  Ativar Fortinho no sistema
                </label>
              </div>
              {!isAdmin && (
                <p className="mt-3 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                  Somente administradores podem ativar ou desativar o Fortinho.
                </p>
              )}
            </div>

            {/* Lembrete automatico WhatsApp */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-2">Lembrete automático de consulta (WhatsApp)</h2>
              <p className="text-sm text-gray-500 mb-4">
                Quando ativo, envia automaticamente o lembrete de consulta para a clínica
                parceira, 24h antes do horário agendado — sem precisar clicar manualmente
                na Agenda.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="whatsapp_lembrete_automatico_habilitado"
                  checked={configEmpresa.whatsapp_lembrete_automatico_habilitado}
                  disabled={!isAdmin}
                  onChange={(e) => setConfigEmpresa({ ...configEmpresa, whatsapp_lembrete_automatico_habilitado: e.target.checked })}
                  className="w-4 h-4 text-teal-600 disabled:opacity-50"
                />
                <label htmlFor="whatsapp_lembrete_automatico_habilitado" className="text-sm text-gray-700">
                  Ativar lembrete automático de consulta
                </label>
              </div>
              {!isAdmin && (
                <p className="mt-3 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                  Somente administradores podem ativar ou desativar o lembrete automático.
                </p>
              )}

              <div className="mt-4 pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={() => void verificarProntidaoClinicas()}
                  disabled={prontidaoClinicasStatus === "loading"}
                  className="text-sm text-teal-700 hover:text-teal-800 underline disabled:opacity-50"
                >
                  {prontidaoClinicasStatus === "loading"
                    ? "Verificando clínicas..."
                    : "Verificar números de WhatsApp das clínicas antes de habilitar"}
                </button>

                {prontidaoClinicasStatus === "error" && (
                  <p className="mt-2 text-xs text-red-700">Erro ao verificar. Tentar de novo.</p>
                )}

                {prontidaoClinicas && (
                  <div className="mt-3">
                    <p className="text-sm text-gray-700">
                      {prontidaoClinicas.total_prontas} de {prontidaoClinicas.total_clinicas_ativas} clínicas ativas
                      prontas para o lembrete automático. Ordenadas por quantidade de agendamentos solicitados nos
                      últimos {prontidaoClinicas.janela_dias} dias, da maior para a menor — priorize a revisão pelo topo.
                    </p>
                    {prontidaoClinicas.clinicas.length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {prontidaoClinicas.clinicas.map((clinica) => (
                          <li
                            key={clinica.clinica_id}
                            className={`text-xs rounded px-3 py-2 flex items-center justify-between gap-2 border ${
                              clinica.motivo ? "text-amber-800 bg-amber-50 border-amber-200" : "text-emerald-800 bg-emerald-50 border-emerald-200"
                            }`}
                          >
                            <span>
                              <strong>{clinica.agendamentos_60_dias}</strong> agendamento(s) —{" "}
                              <strong>{clinica.clinica_nome}</strong>
                              {" — "}
                              {clinica.motivo === "sem_numero"
                                ? "sem WhatsApp cadastrado"
                                : clinica.motivo === "numero_invalido"
                                  ? `número inválido (${clinica.valor_cadastrado})`
                                  : "pronta"}
                            </span>
                            {clinica.motivo && (
                              <a href={`/clinicas/${clinica.clinica_id}`} className="text-teal-700 underline whitespace-nowrap">
                                Corrigir
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Atendimento automatico WhatsApp */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-2">Atendimento automático (WhatsApp)</h2>
              <p className="text-sm text-gray-500 mb-4">
                Controla o copiloto da Central de WhatsApp. Em modo sugerir, as respostas ficam
                como rascunho e só chegam ao contato depois da revisão de um atendente.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="whatsapp_bot_atendimento_habilitado"
                  checked={configEmpresa.whatsapp_bot_atendimento_habilitado}
                  disabled={!isAdmin}
                  onChange={(e) => setConfigEmpresa({ ...configEmpresa, whatsapp_bot_atendimento_habilitado: e.target.checked })}
                  className="w-4 h-4 text-teal-600 disabled:opacity-50"
                />
                <label htmlFor="whatsapp_bot_atendimento_habilitado" className="text-sm text-gray-700">
                  Ativar copiloto de atendimento
                </label>
              </div>
              <label className="mt-4 block text-sm text-gray-700">
                <span className="mb-1 block font-medium">Modo padrão</span>
                <select
                  value={configEmpresa.whatsapp_bot_modo}
                  disabled={!isAdmin}
                  onChange={(e) => setConfigEmpresa({ ...configEmpresa, whatsapp_bot_modo: e.target.value as "off" | "suggest" | "auto" })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white disabled:opacity-50"
                >
                  <option value="off">Desligado</option>
                  <option value="suggest">Sugerir rascunho para revisão</option>
                  <option value="auto" disabled>Automático (aguarda rollout)</option>
                </select>
              </label>
              <p className="mt-3 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                O modo automático permanece bloqueado até a fase de observação em stage. Use “Sugerir” durante a validação.
              </p>
              {!isAdmin ? (
                <p className="mt-3 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                  Somente administradores podem alterar o controle institucional.
                </p>
              ) : (
                <button type="button" onClick={salvarConfigEmpresa} disabled={salvando}
                  className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50">
                  <Save className="w-4 h-4" /> {salvando ? "Salvando..." : "Salvar atendimento automático"}
                </button>
              )}
            </div>

            {/* Painel do bot de atendimento (Fase 6) */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-1">Painel do atendimento automático</h2>
              <p className="text-xs text-gray-500 mb-4">
                Prontidão, conteúdo, observação e teste. Tudo aqui é leitura ou cadastro:
                nada envia mensagem a cliente.
              </p>

              {botErro ? (
                <p className="mb-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{botErro}</p>
              ) : null}

              {/* Participação por clínica (piloto) */}
              <div className="mb-6">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-gray-800">Quem o bot atende</h3>
                  <button type="button" onClick={carregarBotClinicas} disabled={botCarregando === "clinicas"}
                    className="text-xs px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
                    {botCarregando === "clinicas" ? "Carregando..." : "Listar clínicas"}
                  </button>
                </div>

                {!botClinicas ? (
                  <p className="text-xs text-gray-400">
                    Clique em Listar para liberar o bot clínica por clínica.
                  </p>
                ) : (
                  <>
                    <div className="mb-3 flex flex-wrap items-center gap-2">
                      <span className="text-xs text-gray-600">Postura:</span>
                      {["todos", "piloto"].map((opcao) => (
                        <button key={opcao} type="button"
                          onClick={() => void alterarParticipacao(opcao)}
                          disabled={botCarregando === "participacao" || botClinicas.participacao === opcao}
                          className={`text-xs px-3 py-1.5 rounded-lg border ${botClinicas.participacao === opcao ? "border-vital-400 bg-vital-50 font-semibold text-vital-800" : "border-gray-300 hover:bg-gray-50"} disabled:opacity-60`}>
                          {opcao === "todos" ? "Todos" : "Só o piloto"}
                        </button>
                      ))}
                    </div>
                    <p className="mb-3 text-[11px] text-gray-500">
                      {botClinicas.participacao === "piloto"
                        ? "No piloto, só quem foi habilitado aqui é atendido — inclusive tutor, que entra apenas por conversa. Alterar a postura exige admin."
                        : "Em Todos, quem não tem marcação segue o modo padrão. Marcar uma clínica como Desligado vale mesmo aqui."}
                    </p>

                    <input type="text" value={botClinicaBusca}
                      onChange={(e) => setBotClinicaBusca(e.target.value)}
                      placeholder="Filtrar por nome da clínica"
                      className="mb-2 w-full text-xs border border-gray-300 rounded-lg px-3 py-2" />

                    <div className="max-h-64 overflow-y-auto divide-y divide-gray-100 border border-gray-200 rounded-lg">
                      {(botClinicas.clinicas || [])
                        .filter((c: any) => !botClinicaBusca.trim() || String(c.nome || "").toLowerCase().includes(botClinicaBusca.trim().toLowerCase()))
                        .map((c: any) => (
                        <div key={c.clinica_id} className="flex items-center justify-between gap-3 px-3 py-2">
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-gray-800 truncate">{c.nome}</p>
                            <p className="text-[10px] text-gray-500">
                              {c.participa ? "atendida pelo bot" : "fora do atendimento"}
                              {c.modo ? ` · marcada como ${c.modo}` : " · sem marcação"}
                            </p>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            {["off", "suggest"].map((m) => (
                              <button key={m} type="button"
                                onClick={() => void alterarModoDaClinica(c.clinica_id, m)}
                                disabled={botCarregando === `clinica-${c.clinica_id}` || c.modo === m}
                                className={`text-[11px] px-2 py-1 rounded border ${c.modo === m ? "border-vital-400 bg-vital-50 font-semibold text-vital-800" : "border-gray-300 hover:bg-gray-50"} disabled:opacity-60`}>
                                {m === "off" ? "Desligado" : "Sugerir"}
                              </button>
                            ))}
                            {/* So aparece quando ha o que desfazer. "Sem marcacao"
                                nao e um terceiro modo: e a ausencia dos dois, e em
                                `todos` ela INCLUI a clinica, ao contrario de Desligado. */}
                            {c.modo ? (
                              <button type="button"
                                onClick={() => void removerMarcacaoDaClinica(c.clinica_id)}
                                disabled={botCarregando === `clinica-${c.clinica_id}`}
                                title="Volta ao padrão: em Todos a clínica é atendida; no piloto, fica de fora"
                                className="text-[11px] px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-60">
                                Sem marcação
                              </button>
                            ) : null}
                          </div>
                        </div>
                      ))}
                      {(botClinicas.clinicas || []).length === 0 ? (
                        <p className="px-3 py-3 text-xs text-gray-400">Nenhuma clínica ativa cadastrada.</p>
                      ) : null}
                    </div>
                    <p className="mt-2 text-[10px] text-gray-400">
                      &quot;Automático&quot; não aparece aqui de propósito: o envio automático ainda não existe.
                    </p>
                  </>
                )}
              </div>

              {/* Prontidão */}
              <div className="mb-6">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-gray-800">O bot consegue responder?</h3>
                  <button type="button" onClick={carregarBotProntidao} disabled={botCarregando === "prontidao"}
                    className="text-xs px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
                    {botCarregando === "prontidao" ? "Verificando..." : "Verificar"}
                  </button>
                </div>
                {!botProntidao ? (
                  <p className="text-xs text-gray-400">Clique em Verificar. A checagem não usa IA e não custa nada.</p>
                ) : (
                  <>
                    {(() => {
                      const r = resumirProntidao(botProntidao.personas);
                      return (
                        <p className="text-xs text-gray-600 mb-3">
                          {r.prontos} de {r.total} prontos
                          {r.acionaveis > 0 ? ` · ${r.acionaveis} dependem de configuração sua` : " · nada pendente de configuração"}
                        </p>
                      );
                    })()}
                    <div className="grid gap-4 md:grid-cols-2">
                      {(["tutor", "clinica"] as const).map((persona) => (
                        <div key={persona}>
                          <p className="text-xs font-semibold text-gray-700 mb-1 capitalize">
                            {persona === "tutor" ? "Tutor" : "Clínica parceira"}
                          </p>
                          <ul className="space-y-1">
                            {ordenarPorPendencia(botProntidao.personas?.[persona]?.itens ?? []).map((item) => (
                              <li key={item.intent} className="text-xs">
                                <span className={item.pronto ? "text-emerald-700" : item.depende_da_conversa ? "text-gray-500" : "text-amber-700"}>
                                  {item.pronto ? "✓" : item.depende_da_conversa ? "•" : "!"} {item.rotulo}
                                </span>
                                {item.diagnostico ? (
                                  <span className="block text-gray-500 pl-4">{item.diagnostico}</span>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                    <p className="mt-3 text-[11px] text-gray-400">{botProntidao.resumo?.observacao}</p>
                  </>
                )}
              </div>

              {/* Conteúdo */}
              <div className="mb-6 border-t border-gray-100 pt-4">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-gray-800">Conteúdo que o bot usa</h3>
                  <button type="button" onClick={carregarBotConteudo} disabled={botCarregando === "conteudo"}
                    className="text-xs px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
                    {botCarregando === "conteudo" ? "Carregando..." : "Listar"}
                  </button>
                </div>
                {botConteudo ? (
                  <p className="text-xs text-gray-600 mb-3">
                    {botConteudo.total_visiveis} visível(is) para o bot
                    {botConteudo.total_ignorados > 0
                      ? ` · ${botConteudo.total_ignorados} na base que o bot ignora (categoria fora da audiência dele)`
                      : ""}
                  </p>
                ) : null}
                {isAdmin ? (
                  <div className="space-y-2">
                    <input value={botForm.titulo} onChange={(e) => setBotForm({ ...botForm, titulo: e.target.value })}
                      placeholder="Título (ex.: Como agendar na FortCordis)"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" />
                    <div className="grid gap-2 sm:grid-cols-2">
                      <select value={botForm.publico} onChange={(e) => setBotForm({ ...botForm, publico: e.target.value })}
                        className="px-3 py-2 border border-gray-300 rounded-lg text-sm">
                        {PUBLICOS_CONHECIMENTO.map((p) => (
                          <option key={p.valor} value={p.valor}>{p.rotulo}</option>
                        ))}
                      </select>
                      <input value={botForm.fonte} onChange={(e) => setBotForm({ ...botForm, fonte: e.target.value })}
                        placeholder="Fonte (obrigatória)"
                        className="px-3 py-2 border border-gray-300 rounded-lg text-sm" />
                    </div>
                    <textarea value={botForm.conteudo} onChange={(e) => setBotForm({ ...botForm, conteudo: e.target.value })}
                      rows={5} placeholder="O que o bot deve saber. Escreva como você responderia ao cliente."
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" />
                    <label className="flex items-start gap-2 text-xs text-gray-600">
                      <input type="checkbox" checked={botForm.indexar_semanticamente}
                        onChange={(e) => setBotForm({ ...botForm, indexar_semanticamente: e.target.checked })}
                        className="mt-0.5" />
                      <span>Ativar busca semântica (o texto vai à OpenAI só para gerar vetores)</span>
                    </label>
                    {botFormErros.length > 0 ? (
                      <ul className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                        {botFormErros.map((erro) => <li key={erro}>• {erro}</li>)}
                      </ul>
                    ) : null}
                    <button type="button" onClick={salvarBotConteudo} disabled={botCarregando === "salvar-conteudo"}
                      className="inline-flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 text-sm">
                      <Save className="w-4 h-4" /> {botCarregando === "salvar-conteudo" ? "Salvando..." : "Adicionar conteúdo"}
                    </button>
                    <p className="text-[11px] text-gray-400">
                      A categoria é definida pelo público escolhido, e a fonte é obrigatória — as duas coisas
                      que antes tornavam um documento invisível para o bot sem avisar.
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                    Somente administradores podem cadastrar conteúdo do bot.
                  </p>
                )}
              </div>

              {/* Observação */}
              <div className="mb-6 border-t border-gray-100 pt-4">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-gray-800">Observação (últimos 7 dias)</h3>
                  <button type="button" onClick={carregarBotMetricas} disabled={botCarregando === "metricas"}
                    className="text-xs px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
                    {botCarregando === "metricas" ? "Carregando..." : "Carregar"}
                  </button>
                </div>
                {!botMetricas ? (
                  <p className="text-xs text-gray-400">Sem dados carregados.</p>
                ) : (
                  <>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-gray-500 text-left">
                            <th className="py-1 pr-3">Recorte</th>
                            <th className="py-1 pr-3">Aceite</th>
                            <th className="py-1 pr-3">Sem edição</th>
                            <th className="py-1 pr-3">Descarte</th>
                            <th className="py-1 pr-3">Bloqueio</th>
                            <th className="py-1 pr-3">p95</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[
                            ["Geral", botMetricas.geral],
                            ...Object.entries(botMetricas.por_persona ?? {}),
                            ...Object.entries(botMetricas.por_faixa_horario ?? {}),
                          ].map(([rotulo, b]: any) => (
                            <tr key={rotulo} className="border-t border-gray-100">
                              <td className="py-1 pr-3 capitalize">{String(rotulo).replace(/_/g, " ")}</td>
                              <td className="py-1 pr-3">{formatarTaxa(b?.taxa_aceite)}</td>
                              <td className="py-1 pr-3">{formatarTaxa(b?.taxa_aceite_sem_edicao)}</td>
                              <td className="py-1 pr-3">{formatarTaxa(b?.taxa_descarte)}</td>
                              <td className="py-1 pr-3">{formatarTaxa(b?.taxa_bloqueio)}</td>
                              <td className="py-1 pr-3">{formatarLatencia(b?.latencia_p95_ms)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="mt-2 text-xs text-gray-600">
                      Custo: {formatarCusto(botMetricas.geral?.custo_total, botMetricas.geral?.custo_configurado)}
                      {" · "}rascunhos decididos: {formatarInteiro(botMetricas.geral?.decididos)}
                    </p>
                    {Object.keys(botMetricas.geral?.bloqueios_por_motivo ?? {}).length > 0 ? (
                      <p className="mt-1 text-xs text-gray-600">
                        Bloqueios: {Object.entries(botMetricas.geral.bloqueios_por_motivo)
                          .map(([m, n]) => `${m} ${n}`).join(" · ")}
                      </p>
                    ) : null}
                    <div className="mt-3 rounded border border-gray-200 bg-gray-50 p-3">
                      <p className="text-xs font-semibold text-gray-700 mb-1">Amostra para decidir o modo automático</p>
                      <ul className="space-y-0.5">
                        {linhasDoChecklist(botMetricas.pronto_para_decidir_auto).map((linha) => (
                          <li key={linha.rotulo} className="text-xs text-gray-600">
                            {linha.atendido ? "✓" : "○"} {linha.rotulo}
                            {linha.detalhe ? <span className="text-gray-400"> — {linha.detalhe}</span> : null}
                          </li>
                        ))}
                      </ul>
                      <p className="mt-2 text-[11px] text-gray-500">
                        {botMetricas.pronto_para_decidir_auto?.observacao}
                      </p>
                    </div>
                  </>
                )}
              </div>

              {/* Teste */}
              <div className="border-t border-gray-100 pt-4">
                <h3 className="text-sm font-semibold text-gray-800 mb-2">Testar sem enviar</h3>
                <div className="grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)]">
                  <select value={botSimPersona} onChange={(e) => setBotSimPersona(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg text-sm">
                    <option value="tutor">Como tutor</option>
                    <option value="clinica">Como clínica</option>
                  </select>
                  <input value={botSimMensagem} onChange={(e) => setBotSimMensagem(e.target.value)}
                    placeholder="Digite a pergunta de um cliente"
                    className="px-3 py-2 border border-gray-300 rounded-lg text-sm" />
                </div>
                <textarea value={botSimHistorico} onChange={(e) => setBotSimHistorico(e.target.value)}
                  rows={3}
                  placeholder={"Conversa anterior (opcional), uma mensagem por linha:\ncliente: quanto custa o eco?\nnos: Ecocardiograma custa R$ 180,00."}
                  className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono" />
                <p className="mt-1 text-[11px] text-gray-400">
                  Sem prefixo, a linha conta como mensagem do cliente. Serve para testar se o bot
                  entende &quot;e domiciliar?&quot; ou &quot;quanto fica entao?&quot; sem repetir o assunto.
                </p>
                <button type="button" onClick={simularBot}
                  disabled={botCarregando === "simular" || botSimMensagem.trim().length < 3}
                  className="mt-2 text-xs px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
                  {botCarregando === "simular" ? "Simulando..." : "Ver o que o bot responderia"}
                </button>
                <p className="mt-1 text-[11px] text-gray-400">
                  Faz chamada real de IA, então consome tokens. Nada é enviado ao cliente e nada entra nas métricas.
                </p>
                {botSimulacao ? (
                  <div className="mt-3 rounded border border-gray-200 p-3 text-xs space-y-1">
                    <p><span className="text-gray-500">decisão:</span> {botSimulacao.decisao} · <span className="text-gray-500">motivo:</span> {botSimulacao.motivo || "—"}</p>
                    {botSimulacao.texto_gerado ? (
                      <p className="whitespace-pre-wrap text-gray-800 bg-gray-50 rounded p-2">{botSimulacao.texto_gerado}</p>
                    ) : (
                      <p className="text-gray-500">Nenhum texto gerado — veja o motivo acima.</p>
                    )}
                    <p className="text-gray-400">
                      {formatarInteiro(botSimulacao.input_tokens)} tokens entrada · {formatarInteiro(botSimulacao.output_tokens)} saída · {formatarLatencia(botSimulacao.latencia_ms)}
                    </p>
                  </div>
                ) : null}
              </div>
            </div>

            {/* Texto do Rodapé */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4">Texto do Rodapé do Laudo</h2>
              <textarea
                value={configEmpresa.texto_rodape_laudo ?? ""}
                onChange={(e) => setConfigEmpresa({ ...configEmpresa, texto_rodape_laudo: e.target.value })}
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>
        )}

        {aba === "usuario" && (
          <div className="fc-settings-content fc-settings-account">
            {/* Dados Profissionais */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Shield className="w-5 h-5 text-teal-600" />
                Dados Profissionais
              </h2>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    CRMV
                  </label>
                  <input
                    type="text"
                    value={configUsuario.crmv ?? ""}
                    onChange={(e) => setConfigUsuario({ ...configUsuario, crmv: e.target.value })}
                    placeholder="Ex: CE-1234"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                  <p className="mt-1 text-xs text-gray-500">
                    Será exibido nos laudos emitidos por você
                  </p>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Especialidade
                  </label>
                  <input
                    type="text"
                    value={configUsuario.especialidade ?? ""}
                    onChange={(e) => setConfigUsuario({ ...configUsuario, especialidade: e.target.value })}
                    placeholder="Ex: Cardiologia Veterinária"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>
              </div>
            </div>

            {/* Assinatura Pessoal */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Signature className="w-5 h-5 text-teal-600" />
                Minha Assinatura
              </h2>
              
              <div className="flex items-center gap-6">
                <div className="w-40 h-24 bg-gray-100 rounded-lg flex items-center justify-center border-2 border-dashed border-gray-300 overflow-hidden">
                  {previewAssinaturaUsuario ? (
                    <img src={previewAssinaturaUsuario} alt="Assinatura" className="w-full h-full object-contain" />
                  ) : (
                    <span className="text-gray-400 text-sm">Sem assinatura</span>
                  )}
                </div>
                
                <div className="space-y-3">
                  <label className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer">
                    <Upload className="w-4 h-4" />
                    Upload Assinatura
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleUploadAssinaturaUsuario}
                      className="hidden"
                    />
                  </label>
                </div>
              </div>
              
              <p className="mt-3 text-sm text-gray-500">
                Esta assinatura será usada nos laudos emitidos por você. Se não houver assinatura pessoal, será usada a assinatura padrão do sistema.
              </p>
            </div>

            {/* Preferências */}
            <div className="fc-settings-card">
              <h2 className="text-lg font-semibold mb-4">Preferências</h2>
              
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="notif_email"
                    checked={configUsuario.notificacoes_email}
                    onChange={(e) => setConfigUsuario({ ...configUsuario, notificacoes_email: e.target.checked })}
                    className="w-4 h-4 text-teal-600"
                  />
                  <label htmlFor="notif_email" className="text-sm text-gray-700">
                    Receber notificações por e-mail
                  </label>
                </div>
                
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="notif_push"
                    checked={configUsuario.notificacoes_push}
                    onChange={(e) => setConfigUsuario({ ...configUsuario, notificacoes_push: e.target.checked })}
                    className="w-4 h-4 text-teal-600"
                  />
                  <label htmlFor="notif_push" className="text-sm text-gray-700">
                    Receber notificações push
                  </label>
                </div>

                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-gray-600">
                    Perfil rapido de notificacao
                  </p>
                  <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
                    {PERFIS_PUSH_PRESETS.map((preset) => {
                      const selecionado =
                        String(configUsuario.notificacoes_push_perfil || "custom").toLowerCase() === preset.perfil;
                      return (
                        <button
                          key={preset.perfil}
                          type="button"
                          onClick={() => aplicarPerfilPush(preset)}
                          disabled={!configUsuario.notificacoes_push}
                          className={`rounded-lg border px-3 py-2 text-left transition ${
                            !configUsuario.notificacoes_push
                              ? "cursor-not-allowed opacity-60"
                              : selecionado
                                ? "border-teal-600 bg-teal-50"
                                : "border-gray-200 bg-white hover:border-teal-300"
                          }`}
                        >
                          <p className="text-sm font-semibold text-gray-800">{preset.titulo}</p>
                          <p className="text-xs text-gray-500">{preset.descricao}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-gray-600">
                    Eventos da agenda para push
                  </p>
                  <div className="mt-2 space-y-2">
                    {TIPOS_PUSH_AGENDA_OPCOES.map((opcao) => (
                      <label
                        key={opcao.valor}
                        className={`flex items-start gap-2 rounded-md px-2 py-1 ${
                          configUsuario.notificacoes_push ? "cursor-pointer" : "cursor-not-allowed opacity-60"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={normalizarTiposPushAgenda(configUsuario.notificacoes_push_tipos).includes(opcao.valor)}
                          disabled={!configUsuario.notificacoes_push}
                          onChange={() => alternarTipoPushAgenda(opcao.valor)}
                          className="mt-0.5 h-4 w-4 text-teal-600"
                        />
                        <span>
                          <span className="block text-sm text-gray-800">{opcao.label}</span>
                          <span className="block text-xs text-gray-500">{opcao.descricao}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-gray-600">
                    Eventos do financeiro para push
                  </p>
                  <div className="mt-2 space-y-2">
                    {TIPOS_PUSH_FINANCEIRO_OPCOES.map((opcao) => (
                      <label
                        key={opcao.valor}
                        className={`flex items-start gap-2 rounded-md px-2 py-1 ${
                          configUsuario.notificacoes_push ? "cursor-pointer" : "cursor-not-allowed opacity-60"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={normalizarTiposPushAgenda(configUsuario.notificacoes_push_tipos).includes(opcao.valor)}
                          disabled={!configUsuario.notificacoes_push}
                          onChange={() => alternarTipoPushAgenda(opcao.valor)}
                          className="mt-0.5 h-4 w-4 text-teal-600"
                        />
                        <span>
                          <span className="block text-sm text-gray-800">{opcao.label}</span>
                          <span className="block text-xs text-gray-500">{opcao.descricao}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-gray-600">
                    Eventos do WhatsApp para push
                  </p>
                  <div className="mt-2 space-y-2">
                    {TIPOS_PUSH_WHATSAPP_OPCOES.map((opcao) => (
                      <label
                        key={opcao.valor}
                        className={`flex items-start gap-2 rounded-md px-2 py-1 ${
                          configUsuario.notificacoes_push ? "cursor-pointer" : "cursor-not-allowed opacity-60"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={normalizarTiposPushAgenda(configUsuario.notificacoes_push_tipos).includes(opcao.valor)}
                          disabled={!configUsuario.notificacoes_push}
                          onChange={() => alternarTipoPushAgenda(opcao.valor)}
                          className="mt-0.5 h-4 w-4 text-teal-600"
                        />
                        <span>
                          <span className="block text-sm text-gray-800">{opcao.label}</span>
                          <span className="block text-xs text-gray-500">{opcao.descricao}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-gray-600">
                    Prioridade alta (item 1)
                  </p>
                  <p className="mt-1 text-xs text-gray-500">
                    Eventos marcados como alta prioridade usam destaque visual e alerta reforcado.
                  </p>
                  <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
                    {TIPOS_PUSH_OPCOES.map((opcao) => (
                      <label
                        key={`prioridade-${opcao.valor}`}
                        className={`flex items-start gap-2 rounded-md px-2 py-1 ${
                          configUsuario.notificacoes_push ? "cursor-pointer" : "cursor-not-allowed opacity-60"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={normalizarTiposPrioridadeAltaPush(
                            configUsuario.notificacoes_push_prioridade_alta_tipos
                          ).includes(opcao.valor)}
                          disabled={!configUsuario.notificacoes_push}
                          onChange={() => alternarTipoPrioridadeAltaPush(opcao.valor)}
                          className="mt-0.5 h-4 w-4 text-amber-600"
                        />
                        <span className="text-sm text-gray-800">{opcao.label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-gray-600">
                    Automacoes (itens 3, 4 e 6)
                  </p>
                  <div className="mt-3 space-y-3">
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={configUsuario.notificacoes_push_agrupar}
                        disabled={!configUsuario.notificacoes_push}
                        onChange={(e) =>
                          setConfigUsuario((prev) => ({
                            ...prev,
                            notificacoes_push_agrupar: e.target.checked,
                            notificacoes_push_perfil: "custom",
                          }))
                        }
                        className="h-4 w-4 text-teal-600"
                      />
                      Agrupar notificacoes semelhantes em sequencia (reduz spam)
                    </label>

                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={configUsuario.notificacoes_push_lembrete_pendencias}
                        disabled={!configUsuario.notificacoes_push}
                        onChange={(e) =>
                          setConfigUsuario((prev) => ({
                            ...prev,
                            notificacoes_push_lembrete_pendencias: e.target.checked,
                            notificacoes_push_perfil: "custom",
                          }))
                        }
                        className="h-4 w-4 text-teal-600"
                      />
                      Enviar lembrete automatico de OS pendente de pagamento
                    </label>

                    <div className="flex items-center gap-2">
                      <label className="text-sm text-gray-700">Lembrar apos</label>
                      <input
                        type="number"
                        min={1}
                        max={168}
                        disabled={!configUsuario.notificacoes_push || !configUsuario.notificacoes_push_lembrete_pendencias}
                        value={configUsuario.notificacoes_push_lembrete_horas}
                        onChange={(e) =>
                          setConfigUsuario((prev) => ({
                            ...prev,
                            notificacoes_push_lembrete_horas: Number(e.target.value || 6),
                            notificacoes_push_perfil: "custom",
                          }))
                        }
                        className="w-24 rounded-md border border-gray-300 px-2 py-1 text-sm"
                      />
                      <span className="text-sm text-gray-600">hora(s)</span>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="mt-4">
                <button
                  onClick={salvarConfigUsuario}
                  disabled={salvando}
                  className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {salvando ? "Salvando..." : "Salvar Configurações"}
                </button>
              </div>
            </div>
          </div>
        )}

        {aba === "observabilidade" && isAdmin && (
          <div className="fc-settings-content space-y-6">
            <div className="fc-settings-card">
              <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                    <Activity className="w-5 h-5 text-teal-600" />
                    Latência por endpoint e release
                  </h2>
                  <p className="text-sm text-gray-500 mt-1">
                    Histórico agregado das rotas prioritárias. Não inclui URL, paciente, usuário ou conteúdo clínico.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    aria-label="Janela de telemetria"
                    value={janelaLatenciaRuntime}
                    onChange={(event) => setJanelaLatenciaRuntime(Number(event.target.value) as 6 | 24 | 168)}
                    className="px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white"
                  >
                    <option value={6}>Últimas 6 horas</option>
                    <option value={24}>Últimas 24 horas</option>
                    <option value={168}>Últimos 7 dias</option>
                  </select>
                  <button
                    type="button"
                    onClick={carregarLatenciaRuntime}
                    disabled={statusLatenciaRuntime === "loading"}
                    className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                  >
                    <RefreshCw className="w-4 h-4" />
                    {statusLatenciaRuntime === "loading" ? "Atualizando..." : "Atualizar"}
                  </button>
                </div>
              </div>

              {erroLatenciaRuntime ? (
                <div className="p-3 rounded-lg bg-red-50 text-red-700 text-sm">{erroLatenciaRuntime}</div>
              ) : null}

              {statusLatenciaRuntime === "loading" && !latenciaRuntime ? (
                <div className="py-8 text-center text-gray-500">Carregando telemetria...</div>
              ) : !latenciaRuntime?.available ? (
                <div className="p-4 rounded-lg bg-amber-50 text-amber-800 text-sm">
                  A telemetria persistida ainda não está disponível. Confirme a migração deste release antes de avaliar os números.
                </div>
              ) : latenciaRuntime.groups.length === 0 ? (
                <div className="py-8 text-center text-gray-500">
                  Nenhuma amostra nas últimas {latenciaRuntime.hours} horas. Navegue por uma rota prioritária e atualize este painel.
                </div>
              ) : (
                <>
                  <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                    <span>Retenção: {latenciaRuntime.retention_days} dias</span>
                    {latenciaRuntime.truncated ? (
                      <span className="text-amber-700">A consulta atingiu o limite de amostras; amplie a filtragem antes de concluir.</span>
                    ) : null}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="bg-gray-50 text-gray-600">
                        <tr>
                          <th className="text-left px-3 py-2 font-medium">Endpoint</th>
                          <th className="text-left px-3 py-2 font-medium">Release</th>
                          <th className="text-right px-3 py-2 font-medium">Amostras</th>
                          <th className="text-right px-3 py-2 font-medium">p50</th>
                          <th className="text-right px-3 py-2 font-medium">p95</th>
                          <th className="text-right px-3 py-2 font-medium">p99</th>
                          <th className="text-right px-3 py-2 font-medium">Máximo</th>
                          <th className="text-right px-3 py-2 font-medium">
                            &gt; {formatarMilissegundos(latenciaRuntime.slow_request_threshold_ms)}
                          </th>
                          <th className="text-right px-3 py-2 font-medium">Banco p95</th>
                          <th className="text-right px-3 py-2 font-medium">App p95</th>
                          <th className="text-right px-3 py-2 font-medium">Consultas p95</th>
                          <th className="text-right px-3 py-2 font-medium">Pool p95</th>
                          <th className="text-right px-3 py-2 font-medium">5xx</th>
                          <th className="text-left px-3 py-2 font-medium">Última amostra</th>
                        </tr>
                      </thead>
                      <tbody>
                        {latenciaRuntime.groups.map((grupo) => (
                          <tr key={`${grupo.endpoint}-${grupo.release_id}`} className="border-t border-gray-100">
                            <td className="px-3 py-2 font-mono text-xs text-gray-800">{grupo.endpoint}</td>
                            <td className="px-3 py-2 font-mono text-xs text-gray-700">{grupo.release_id}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{grupo.request_count}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.p50_ms)}</td>
                            <td className="px-3 py-2 text-right font-medium text-gray-900">{formatarMilissegundos(grupo.p95_ms)}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.p99_ms)}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.max_ms)}</td>
                            <td className="px-3 py-2 text-right">
                              <span className={grupo.slow_request_count > 0 ? "text-amber-700 font-medium" : "text-gray-700"}>
                                {grupo.slow_request_count}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.database_p95_ms)}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.application_p95_ms)}</td>
                            <td className="px-3 py-2 text-right text-gray-700">
                              {grupo.database_query_count_p95 === null ? "—" : Math.round(grupo.database_query_count_p95)}
                            </td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.pool_wait_p95_ms)}</td>
                            <td className="px-3 py-2 text-right">
                              <span className={grupo.error_5xx_count > 0 ? "text-red-700 font-medium" : "text-gray-700"}>
                                {grupo.error_5xx_count}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-xs text-gray-500">{formatarDataHora(grupo.last_seen_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>

            <div className="fc-settings-card">
              <div className="mb-5">
                <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <Activity className="w-5 h-5 text-teal-600" />
                  Tempo percebido no navegador
                </h2>
                <p className="text-sm text-gray-500 mt-1">
                  Navegações reais agregadas por página e release. Não inclui URL completa, usuário, paciente ou conteúdo clínico.
                </p>
              </div>

              {!desempenhoFrontend?.available ? (
                <div className="p-4 rounded-lg bg-amber-50 text-amber-800 text-sm">
                  A telemetria do navegador ainda não está disponível neste release.
                </div>
              ) : desempenhoFrontend.groups.length === 0 ? (
                <div className="py-8 text-center text-gray-500">
                  Nenhuma navegação monitorada nas últimas {desempenhoFrontend.hours} horas.
                </div>
              ) : (
                <>
                  <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                    <span>Retenção: {desempenhoFrontend.retention_days} dias</span>
                    <span>
                      Lento: conteúdo acima de {formatarMilissegundos(desempenhoFrontend.slow_content_threshold_ms)}
                    </span>
                    {desempenhoFrontend.truncated ? (
                      <span className="text-amber-700">A consulta atingiu o limite de amostras.</span>
                    ) : null}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="bg-gray-50 text-gray-600">
                        <tr>
                          <th className="text-left px-3 py-2 font-medium">Página</th>
                          <th className="text-left px-3 py-2 font-medium">Navegação</th>
                          <th className="text-left px-3 py-2 font-medium">Release</th>
                          <th className="text-right px-3 py-2 font-medium">Amostras</th>
                          <th className="text-right px-3 py-2 font-medium">Estrutura p95</th>
                          <th className="text-right px-3 py-2 font-medium">Conteúdo p50</th>
                          <th className="text-right px-3 py-2 font-medium">Conteúdo p95</th>
                          <th className="text-right px-3 py-2 font-medium">Conteúdo p99</th>
                          <th className="text-right px-3 py-2 font-medium">Máximo</th>
                          <th className="text-right px-3 py-2 font-medium">Lentas</th>
                          <th className="text-right px-3 py-2 font-medium">Parciais</th>
                          <th className="text-right px-3 py-2 font-medium">Timeouts</th>
                          <th className="text-right px-3 py-2 font-medium">Canceladas</th>
                          <th className="text-right px-3 py-2 font-medium">Erros</th>
                          <th className="text-left px-3 py-2 font-medium">Última amostra</th>
                        </tr>
                      </thead>
                      <tbody>
                        {desempenhoFrontend.groups.map((grupo) => (
                          <tr
                            key={`${grupo.route_group}-${grupo.release_id}-${grupo.navigation_type}`}
                            className="border-t border-gray-100"
                          >
                            <td className="px-3 py-2 font-mono text-xs text-gray-800">{grupo.route_group}</td>
                            <td className="px-3 py-2 text-gray-700">
                              {grupo.navigation_type === "initial" ? "Entrada" : "Interna"}
                            </td>
                            <td className="px-3 py-2 font-mono text-xs text-gray-700">{grupo.release_id}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{grupo.sample_count}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.shell_p95_ms)}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.content_p50_ms)}</td>
                            <td className="px-3 py-2 text-right font-medium text-gray-900">{formatarMilissegundos(grupo.content_p95_ms)}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.content_p99_ms)}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{formatarMilissegundos(grupo.content_max_ms)}</td>
                            <td className="px-3 py-2 text-right text-amber-700">{grupo.slow_content_count}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{grupo.partial_count}</td>
                            <td className="px-3 py-2 text-right text-red-700">{grupo.timeout_count}</td>
                            <td className="px-3 py-2 text-right text-gray-700">{grupo.cancelled_count}</td>
                            <td className="px-3 py-2 text-right text-red-700">{grupo.error_count}</td>
                            <td className="px-3 py-2 text-xs text-gray-500">{formatarDataHora(grupo.last_seen_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {aba === "usuarios" && (
          <div className="fc-settings-content fc-settings-users grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="fc-settings-card xl:col-span-1">
              <h3 className="text-lg font-semibold text-gray-900 mb-1">
                {modoEdicaoUsuario ? "Editar usuario" : "Novo usuario"}
              </h3>
              <p className="text-sm text-gray-500 mb-4">
                Defina os dados de acesso e os papeis do usuario no sistema.
              </p>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Nome
                  </label>
                  <input
                    type="text"
                    value={usuarioForm.nome}
                    onChange={(e) => setUsuarioForm((prev) => ({ ...prev, nome: e.target.value }))}
                    placeholder="Nome completo"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    E-mail
                  </label>
                  <input
                    type="email"
                    value={usuarioForm.email}
                    onChange={(e) => setUsuarioForm((prev) => ({ ...prev, email: e.target.value }))}
                    placeholder="usuario@email.com"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Senha {modoEdicaoUsuario && <span className="text-gray-400">(opcional)</span>}
                  </label>
                  <input
                    type="password"
                    value={usuarioForm.senha}
                    onChange={(e) => setUsuarioForm((prev) => ({ ...prev, senha: e.target.value }))}
                    placeholder={modoEdicaoUsuario ? "Preencha para trocar a senha" : "Senha inicial"}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                  />
                </div>

                <div className="flex items-center gap-2">
                  <input
                    id="usuario_ativo"
                    type="checkbox"
                    checked={usuarioForm.ativo}
                    onChange={(e) => setUsuarioForm((prev) => ({ ...prev, ativo: e.target.checked }))}
                    className="w-4 h-4 text-teal-600"
                  />
                  <label htmlFor="usuario_ativo" className="text-sm text-gray-700">
                    Usuario ativo
                  </label>
                </div>

                <div>
                  <p className="block text-sm font-medium text-gray-700 mb-2">Papeis</p>
                  <div className="space-y-2 max-h-36 overflow-auto pr-1">
                    {papeisSistema.length === 0 && (
                      <p className="text-sm text-gray-400">Nenhum papel disponivel.</p>
                    )}
                    {papeisSistema.map((papel) => (
                      <label key={papel.id} className="flex items-start gap-2 text-sm text-gray-700">
                        <input
                          type="checkbox"
                          checked={usuarioForm.papeis.includes(papel.nome)}
                          onChange={() => alternarPapelFormulario(papel.nome)}
                          className="mt-0.5 w-4 h-4 text-teal-600"
                        />
                        <span>
                          <span className="font-medium">{papel.nome}</span>
                          {papel.descricao ? (
                            <span className="block text-xs text-gray-500">{papel.descricao}</span>
                          ) : null}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <div className="mt-6 flex flex-wrap gap-2">
                <button
                  onClick={salvarUsuarioSistema}
                  disabled={salvandoUsuarioSistema}
                  className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {salvandoUsuarioSistema
                    ? "Salvando..."
                    : modoEdicaoUsuario
                      ? "Atualizar usuario"
                      : "Criar usuario"}
                </button>

                <button
                  onClick={limparFormularioUsuario}
                  type="button"
                  className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                >
                  <X className="w-4 h-4" />
                  Limpar
                </button>
              </div>
            </div>

            <div className="fc-settings-card xl:col-span-2">
              <div className="flex items-center justify-between gap-3 mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Usuarios cadastrados</h3>
                <button
                  onClick={carregarUsuariosPermissoes}
                  type="button"
                  disabled={carregandoUsuarios}
                  className="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                >
                  {carregandoUsuarios ? "Atualizando..." : "Atualizar"}
                </button>
              </div>

              {erroUsuarios ? (
                <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-700 text-sm">
                  {erroUsuarios}
                </div>
              ) : null}

              {carregandoUsuarios ? (
                <div className="py-8 text-center text-gray-500">Carregando usuarios...</div>
              ) : usuariosSistema.length === 0 ? (
                <div className="py-8 text-center text-gray-500">
                  Nenhum usuario encontrado.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 text-gray-600">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium">Nome</th>
                        <th className="text-left px-3 py-2 font-medium">E-mail</th>
                        <th className="text-left px-3 py-2 font-medium">Papeis</th>
                        <th className="text-left px-3 py-2 font-medium">Status</th>
                        <th className="text-left px-3 py-2 font-medium">Ultimo acesso</th>
                        <th className="text-right px-3 py-2 font-medium">Acoes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usuariosSistema.map((usuario) => (
                        <tr key={usuario.id} className="border-t border-gray-100">
                          <td className="px-3 py-2 text-gray-900">{usuario.nome}</td>
                          <td className="px-3 py-2 text-gray-700">{usuario.email}</td>
                          <td className="px-3 py-2 text-gray-700">
                            {usuario.papeis?.length ? usuario.papeis.join(", ") : "-"}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                                usuario.ativo === 1
                                  ? "bg-green-100 text-green-700"
                                  : "bg-gray-100 text-gray-600"
                              }`}
                            >
                              {usuario.ativo === 1 ? "Ativo" : "Inativo"}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-gray-700">
                            {formatarDataHora(usuario.ultimo_acesso)}
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex justify-end gap-2">
                              <button
                                onClick={() => editarUsuario(usuario)}
                                className="px-3 py-1.5 text-xs bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
                              >
                                Editar
                              </button>
                              {usuario.ativo === 1 ? (
                                <button
                                  onClick={() => desativarUsuario(usuario)}
                                  className="px-3 py-1.5 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200"
                                >
                                  Desativar
                                </button>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="fc-settings-card xl:col-span-3">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">Permissoes por papel</h3>
                  <p className="text-sm text-gray-500">
                    Marque o que cada papel pode visualizar, editar ou excluir.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={carregarUsuariosPermissoes}
                    type="button"
                    disabled={carregandoPermissoes}
                    className="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                  >
                    {carregandoPermissoes ? "Atualizando..." : "Atualizar"}
                  </button>
                  <button
                    onClick={salvarPermissoes}
                    type="button"
                    disabled={salvandoPermissoes || carregandoPermissoes}
                    className="flex items-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {salvandoPermissoes ? "Salvando..." : "Salvar permissoes"}
                  </button>
                </div>
              </div>

              {erroPermissoes ? (
                <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-700 text-sm">
                  {erroPermissoes}
                </div>
              ) : null}

              {carregandoPermissoes ? (
                <div className="py-8 text-center text-gray-500">Carregando matriz de permissoes...</div>
              ) : matrizPermissoes.length === 0 ? (
                <div className="py-8 text-center text-gray-500">Nenhum papel encontrado para configurar.</div>
              ) : (
                <div className="space-y-4">
                  {matrizPermissoes.map((papel) => (
                    <div key={papel.id} className="border border-gray-200 rounded-lg p-4">
                      <div className="mb-3">
                        <p className="text-sm font-semibold text-gray-900">{papel.nome}</p>
                        {papel.descricao ? (
                          <p className="text-xs text-gray-500">{papel.descricao}</p>
                        ) : null}
                      </div>

                      <div className="overflow-x-auto">
                        <table className="min-w-full text-sm">
                          <thead className="bg-gray-50 text-gray-600">
                            <tr>
                              <th className="text-left px-3 py-2 font-medium">Modulo</th>
                              <th className="text-center px-3 py-2 font-medium">Visualizar</th>
                              <th className="text-center px-3 py-2 font-medium">Editar</th>
                              <th className="text-center px-3 py-2 font-medium">Excluir</th>
                            </tr>
                          </thead>
                          <tbody>
                            {modulosPermissoes.map((modulo) => {
                              const permissao = papel.permissoes.find((perm) => perm.modulo === modulo.codigo);
                              return (
                                <tr key={`${papel.id}-${modulo.codigo}`} className="border-t border-gray-100">
                                  <td className="px-3 py-2 text-gray-800">{modulo.nome}</td>
                                  <td className="px-3 py-2 text-center">
                                    <input
                                      type="checkbox"
                                      checked={!!permissao?.visualizar}
                                      onChange={() => alternarPermissao(papel.id, modulo.codigo, "visualizar")}
                                      className="w-4 h-4 text-teal-600"
                                    />
                                  </td>
                                  <td className="px-3 py-2 text-center">
                                    <input
                                      type="checkbox"
                                      checked={!!permissao?.editar}
                                      onChange={() => alternarPermissao(papel.id, modulo.codigo, "editar")}
                                      className="w-4 h-4 text-teal-600"
                                    />
                                  </td>
                                  <td className="px-3 py-2 text-center">
                                    <input
                                      type="checkbox"
                                      checked={!!permissao?.excluir}
                                      onChange={() => alternarPermissao(papel.id, modulo.codigo, "excluir")}
                                      className="w-4 h-4 text-teal-600"
                                    />
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="fc-settings-card xl:col-span-3">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">Auditoria de acoes</h3>
                  <p className="text-sm text-gray-500">
                    Registros de quem cadastrou, alterou status, recebeu, cancelou ou excluiu.
                  </p>
                </div>
                <button
                  onClick={carregarAuditoria}
                  type="button"
                  disabled={carregandoAuditoria}
                  className="px-3 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                >
                  {carregandoAuditoria ? "Atualizando..." : "Atualizar log"}
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-4">
                <select
                  value={filtroAuditoriaModulo}
                  onChange={(e) => setFiltroAuditoriaModulo(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg"
                >
                  <option value="todos">Todos modulos</option>
                  {auditoriaModulos.map((modulo) => (
                    <option key={modulo} value={modulo}>
                      {modulo}
                    </option>
                  ))}
                </select>

                <select
                  value={filtroAuditoriaAcao}
                  onChange={(e) => setFiltroAuditoriaAcao(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg"
                >
                  <option value="todos">Todas acoes</option>
                  {auditoriaAcoes.map((acao) => (
                    <option key={acao} value={acao}>
                      {acao}
                    </option>
                  ))}
                </select>

                <input
                  type="date"
                  value={filtroAuditoriaDataInicio}
                  onChange={(e) => setFiltroAuditoriaDataInicio(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg"
                />

                <input
                  type="date"
                  value={filtroAuditoriaDataFim}
                  onChange={(e) => setFiltroAuditoriaDataFim(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg"
                />

                <input
                  type="text"
                  value={filtroAuditoriaBusca}
                  onChange={(e) => setFiltroAuditoriaBusca(e.target.value)}
                  placeholder="Buscar usuario, email ou descricao"
                  className="px-3 py-2 border border-gray-300 rounded-lg"
                />
              </div>

              <div className="mb-4 flex gap-2">
                <button
                  onClick={carregarAuditoria}
                  type="button"
                  disabled={carregandoAuditoria}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  Filtrar
                </button>
                <button
                  onClick={() => {
                    setFiltroAuditoriaModulo("todos");
                    setFiltroAuditoriaAcao("todos");
                    setFiltroAuditoriaDataInicio("");
                    setFiltroAuditoriaDataFim("");
                    setFiltroAuditoriaBusca("");
                  }}
                  type="button"
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                >
                  Limpar filtros
                </button>
                <div className="ml-auto text-sm text-gray-500 self-center">
                  {auditoriaTotal} registro(s)
                </div>
              </div>

              {erroAuditoria ? (
                <div className="mb-4 p-3 rounded-lg bg-red-50 text-red-700 text-sm">
                  {erroAuditoria}
                </div>
              ) : null}

              {carregandoAuditoria ? (
                <div className="py-8 text-center text-gray-500">Carregando auditoria...</div>
              ) : auditoriaItens.length === 0 ? (
                <div className="py-8 text-center text-gray-500">Nenhum registro encontrado.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 text-gray-600">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium">Data/Hora</th>
                        <th className="text-left px-3 py-2 font-medium">Usuario</th>
                        <th className="text-left px-3 py-2 font-medium">Acao</th>
                        <th className="text-left px-3 py-2 font-medium">Modulo</th>
                        <th className="text-left px-3 py-2 font-medium">Descricao</th>
                        <th className="text-left px-3 py-2 font-medium">Detalhes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditoriaItens.map((item) => {
                        const temDetalhes = !!item.detalhes && Object.keys(item.detalhes).length > 0;
                        const expandido = !!auditoriaExpandida[item.id];
                        return (
                          <Fragment key={item.id}>
                            <tr className="border-t border-gray-100">
                              <td className="px-3 py-2 text-gray-700">{formatarDataHora(item.created_at)}</td>
                              <td className="px-3 py-2 text-gray-700">
                                <div className="font-medium text-gray-900">{item.usuario_nome || "-"}</div>
                                <div className="text-xs text-gray-500">{item.usuario_email || "-"}</div>
                              </td>
                              <td className="px-3 py-2">
                                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700">
                                  {item.acao}
                                </span>
                              </td>
                              <td className="px-3 py-2 text-gray-700">
                                <div>{item.modulo}</div>
                                <div className="text-xs text-gray-500">
                                  {item.entidade}
                                  {item.entidade_id ? ` #${item.entidade_id}` : ""}
                                </div>
                              </td>
                              <td className="px-3 py-2 text-gray-700">
                                <div>{item.descricao || "-"}</div>
                                {item.rota ? (
                                  <div className="text-xs text-gray-500">
                                    {item.metodo || "-"} {item.rota}
                                  </div>
                                ) : null}
                              </td>
                              <td className="px-3 py-2">
                                {temDetalhes ? (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setAuditoriaExpandida((atual) => ({ ...atual, [item.id]: !atual[item.id] }))
                                    }
                                    className="text-xs font-medium text-blue-600 hover:underline"
                                  >
                                    {expandido ? "Ocultar" : "Ver detalhes"}
                                  </button>
                                ) : (
                                  <span className="text-xs text-gray-400">-</span>
                                )}
                              </td>
                            </tr>
                            {temDetalhes && expandido ? (
                              <tr className="border-t border-gray-100 bg-gray-50">
                                <td colSpan={6} className="py-3">
                                  <div className="sticky left-0 w-fit max-w-[90vw] px-3">
                                    {renderizarDetalhesAuditoria(item.detalhes)}
                                  </div>
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
