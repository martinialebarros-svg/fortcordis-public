"use client";

import { PatientAgeFields } from "@/components/pacientes/PatientAgeFields";
import { patientAgeForm, patientAgePayload, type PatientAgeValue } from "@/lib/paciente-idade";
import { useEffect, useRef, useState } from "react";
import { X, User, Building, Calendar, Clock, Sparkles, Search, ChevronDown, Check, Copy, MessageCircle, Pencil, Plus, Trash2, Send, Loader2 } from "lucide-react";
import api from "@/lib/axios";
import { divergenciasPedido, camposPedidoAgenda, type PedidoAgenda } from "@/lib/whatsapp-pedido-agenda";
import AgendaPreferenciasCampos from "@/components/agenda/AgendaPreferenciasCampos";
import {
  dataFortaleza, filtrosDePreferencia, resolverPreferenciaAgenda,
  type FiltrosPreferenciaAgenda,
} from "@/lib/agenda-preferencias";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";
import { useFortinho } from "@/components/fortinho/FortinhoProvider";
import {
  formatarCepVisual,
  formatarCpfVisual,
  formatarTelefoneVisual,
  normalizarCep,
} from "@/lib/atendimento-cadastro";
import { consultarSaldoCreditoCliente } from "@/lib/credito-cliente";
import {
  deveResetarAssistentePorTrocaDeData,
  excecaoManualEstaLiberada,
} from "@/lib/agenda-assistente-excecao";
import { coordenadasSaoConfiaveis, normalizarCoordenadaOpcional } from "@/lib/coordinates";
import {
  AgendaExcecaoConfig,
  AgendaFeriadoConfig,
  AgendaSemanalConfig,
  validarHorarioAgendamento,
} from "@/lib/agenda-config";
import {
  criarPrazoPadraoReserva,
  criarPrazoReservaPorHoras,
  formatarPrazoReserva,
  montarLinkWhatsAppReserva,
  type ReservaManualDestinatario,
} from "@/lib/agenda-reserva-manual";
import {
  formatarWhatsAppVisual,
  normalizarWhatsappsParaApi,
  obterWhatsappsClinica,
  prepararWhatsappsFormulario,
} from "@/lib/clinica-whatsapp";
import {
  addRacaCustomPorEspecie,
  editarRacaCatalogo,
  excluirRacaCatalogo,
  getRacaOptions,
  getRacasCatalogo,
  loadAjustesRacasPorEspecie,
  loadRacasCustomPorEspecie,
  saveAjustesRacasPorEspecie,
  saveRacasCustomPorEspecie,
  type AjustesRacasPorEspecie,
  type RacasCustomPorEspecie,
} from "@/lib/racas";
import {
  AGENDA_WHATSAPP_TEMPLATES,
  isValidAgendaWhatsAppServiceName,
  normalizeAgendaWhatsAppServiceName,
  renderAgendaWhatsAppTemplate,
  type AgendaWhatsAppTemplateKey,
} from "@/lib/agenda-whatsapp-templates";

import TutorIdentificacaoFields from "@/components/TutorIdentificacaoFields";
import { chaveOperacaoTutor, concluirOperacaoTutor } from "@/lib/tutor-mesclagem";

const LIMITE_MINUTOS_PROXIMIDADE = 25;
const LIMITE_ESTENDIDO_EXTRA_MIN = 15;
const COOLDOWN_POPUP_PROXIMIDADE_MS = 60_000;

interface NovoAgendamentoModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (
    agendamentoCriado?: { data?: string | null },
    opcoes?: { manterModalAberto?: boolean }
  ) => void | Promise<void>;
  agendamento?: any;
  pedidoWhatsApp?: PedidoAgenda | null;
  defaultDate?: string;
  defaultTime?: string;
  agendaSemanal: AgendaSemanalConfig;
  agendaFeriados: AgendaFeriadoConfig[];
  agendaExcecoes: AgendaExcecaoConfig[];
  intervaloSlotMinutos?: number;
  isAdmin?: boolean;
}

interface SugestaoHorarioVizinho {
  agendamento_id: number;
  clinica_id?: number | null;
  tutor_id?: number | null;
  tipo?: OrigemAtendimento;
  clinica: string;
  inicio?: string;
  fim?: string;
  duracao_deslocamento_min: number;
  folga_min: number | null;
  margem_min: number | null;
  fonte: string;
}

interface SugestaoHorarioItem {
  inicio: string;
  fim: string;
  score: number;
  risco: number;
  tempo_deslocamento_total_min: number;
  tempo_deslocamento_base_min?: number | null;
  fonte_deslocamento_base?: string | null;
  inicio_minimo_primeira_saida?: string | null;
  origem_primeira_saida?: "base_operacional" | null;
  ociosidade_min: number;
  destino_operacional?: string;
  destino_operacional_tipo?: OrigemAtendimento;
  anterior: SugestaoHorarioVizinho | null;
  proximo: SugestaoHorarioVizinho | null;
}

interface SugestoesHorarioResponse {
  ok: boolean;
  data: string;
  clinica_id?: number | null;
  tutor_id?: number | null;
  origem_atendimento?: OrigemAtendimento;
  destino_operacional?: string;
  duracao_minutos: number;
  perfil_deslocamento: string;
  intervalo_minutos?: number;
  motivo?: string;
  itens_ignorados_janela?: number;
  total_encontrados: number;
  items: SugestaoHorarioItem[];
}

interface ValidacaoOfertaResponse {
  ok: boolean;
  valido: boolean;
  codigo?: string;
  mensagem?: string;
  inicio_minimo_primeira_saida?: string | null;
}

type AssistenteDecisao = "pendente" | "aceito" | "sem_opcao";

type EtapaWizardNovo = {
  id: "preparo" | "ofertas" | "desfecho";
  titulo: string;
  descricao: string;
};

const ETAPAS_WIZARD_NOVO: EtapaWizardNovo[] = [
  {
    id: "preparo",
    titulo: "Preparar dados",
    descricao: "Selecionar destino operacional, servico e data.",
  },
  {
    id: "ofertas",
    titulo: "Panorama de ofertas",
    descricao: "Visualizar todas as opcoes sugeridas pelo assistente.",
  },
  {
    id: "desfecho",
    titulo: "Desfecho",
    descricao: "Registrar aceite ou recusa com justificativa para fluxo de excecao.",
  },
];

const resolverIndiceEtapaWizardNovo = (
  prontoParaSugerir: boolean,
  decisao: AssistenteDecisao
): number => {
  if (decisao === "aceito" || decisao === "sem_opcao") {
    return 2;
  }
  if (!prontoParaSugerir) {
    return 0;
  }
  return 1;
};

interface ConflitoDeslocamentoDetail {
  codigo?: string;
  mensagem?: string;
  duracao_min?: number;
  folga_min?: number;
  confirmavel?: boolean;
  desvio_insercao_min?: number;
  limite_desvio_min?: number;
}

interface ReservaExpiradaDetail {
  codigo?: string;
  mensagem?: string;
  confirmavel?: boolean;
  reservas_expiradas?: Array<{
    id: number;
    clinica?: string | null;
    paciente?: string | null;
    tutor?: string | null;
    inicio?: string | null;
    fim?: string | null;
    reserva_expira_em?: string | null;
  }>;
}

interface SugestaoProximidadeResponse {
  ok: boolean;
  sugerir: boolean;
  mensagem: string;
  clinica_id?: number | null;
  tutor_id?: number | null;
  origem_atendimento?: OrigemAtendimento;
  destino_operacional?: string;
  limite_minutos?: number;
  acima_do_limite?: boolean;
  politica_oferta?: {
    data_contato?: string;
    datas_preferenciais?: string[];
    distante_base?: boolean;
    baixa_frequencia?: boolean;
    ancora_d2?: boolean;
  };
  item?: {
    agendamento_id: number;
    clinica_id?: number | null;
    tutor_id?: number | null;
    clinica: string;
    clinica_destino?: string;
    destino_operacional?: string;
    destino_operacional_tipo?: OrigemAtendimento;
    clinica_anterior?: string | null;
    clinica_posterior?: string | null;
    ha_agendamento_anterior?: boolean;
    ha_agendamento_posterior?: boolean;
    data?: string | null;
    inicio?: string | null;
    fim?: string | null;
    duracao_deslocamento_min: number;
    tempo_deslocamento_total_min?: number;
    duracao_deslocamento_anterior_min?: number;
    duracao_deslocamento_proximo_min?: number;
    fonte_deslocamento?: string;
    status?: string;
    data_preferencial?: boolean;
  } | null;
}

interface AssistenteOfertaResponse {
  ok: boolean;
  clinica_id?: number | null;
  tutor_id?: number | null;
  origem_atendimento?: OrigemAtendimento;
  data_referencia: string;
  data_contato?: string;
  data_base: string;
  origem_data_automatica: "manual" | "proximidade" | "politica" | "progressao_dias";
  politica_oferta?: SugestaoProximidadeResponse["politica_oferta"];
  sugestao_proximidade?: SugestaoProximidadeResponse | null;
  panorama_ofertas?: SugestoesHorarioResponse | null;
  mensagem_panorama?: string;
}

interface TutorOption {
  identificacao_pendente?: boolean;
  origem_cadastro?: string | null;
  id: number;
  nome: string;
  telefone?: string | null;
  whatsapp?: string | null;
  email?: string | null;
  cidade?: string | null;
  endereco_resumo?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  georreferenciado?: boolean;
  pets?: Array<{ id: number; nome: string }>;
  total_pets?: number;
}

interface PacienteOption {
  id: number;
  nome: string;
  tutor_id?: number | null;
  tutor?: string;
  especie?: string;
  raca?: string;
}

interface ClinicaOption {
  id: number;
  nome: string;
  telefone?: string | null;
  whatsapps?: string[] | null;
  endereco?: string | null;
  numero?: string | null;
  complemento?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  estado?: string | null;
  cep?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

interface SearchableSelectOption {
  value: string;
  label: string;
  description?: string;
  searchText?: string;
}

interface SearchableSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SearchableSelectOption[];
  placeholder: string;
  searchPlaceholder: string;
  emptyText: string;
  selectionHint?: string;
  clearLabel?: string;
  disabled?: boolean;
  showSelectedDescription?: boolean;
  onSearchChange?: (value: string) => void;
  isSearching?: boolean;
  searchingText?: string;
  searchError?: string;
}

type OrigemAtendimento = "clinica_parceira" | "domiciliar";

interface FormDataAgenda {
  origem_atendimento: OrigemAtendimento;
  tutor_id: string;
  paciente_id: string;
  clinica_id: string;
  clinica_nova_nome: string;
  clinica_nova_razao_social: string;
  clinica_nova_tabela_preco_id: string;
  servico_id: string;
  data: string;
  hora: string;
  marcar_como_reserva: boolean;
  reserva_destinatario_manual: ReservaManualDestinatario;
  reserva_prazo_horas: string;
  reserva_prazo_confirmacao: string;
  observacoes: string;
}

interface MensagemAgendaPosCriacao {
  agendamentoId: number | null;
  tipo: "reserva" | "agendamento";
  destinatarioTipo: ReservaManualDestinatario;
  destinatarioId: string;
  destinatarioNome: string;
  telefones: string[];
  telefoneSugerido: string;
  prazoLabel?: string;
  pacienteNome: string;
  servicoNome: string;
  dataLabel: string;
  horaLabel: string;
  modeloSugerido: AgendaWhatsAppTemplateKey;
}

const ULTIMO_WHATSAPP_STORAGE_PREFIX = "fortcordis:agenda:ultimo-whatsapp:v1";

function obterUltimoWhatsappStorageKey(tipo: ReservaManualDestinatario, id: string): string | null {
  if (!id) return null;
  return `${ULTIMO_WHATSAPP_STORAGE_PREFIX}:${tipo}:${id}`;
}

function lerUltimoWhatsappSelecionado(tipo: ReservaManualDestinatario, id: string): string {
  if (typeof window === "undefined") return "";
  const key = obterUltimoWhatsappStorageKey(tipo, id);
  if (!key) return "";
  try {
    return window.localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function salvarUltimoWhatsappSelecionado(tipo: ReservaManualDestinatario, id: string, telefone: string): void {
  if (typeof window === "undefined" || !telefone) return;
  const key = obterUltimoWhatsappStorageKey(tipo, id);
  if (!key) return;
  try {
    window.localStorage.setItem(key, telefone);
  } catch {
    // localStorage indisponivel (modo privado, quota, etc.) - segue sem lembrar.
  }
}

interface NovoTutorForm {
  identificacao_pendente: boolean;
  origem_cadastro: string;
  identificacao_observacoes: string;
  id?: string;
  nome: string;
  telefone: string;
  whatsapp: string;
  email: string;
  cpf: string;
  cep: string;
  endereco: string;
  numero: string;
  complemento: string;
  bairro: string;
  cidade: string;
  estado: string;
  latitude: number | null;
  longitude: number | null;
  place_id: string;
  endereco_normalizado: string;
}

interface NovoAnimalForm extends PatientAgeValue {
  tutor_id: string;
  nome: string;
  especie: string;
  raca: string;
  sexo: string;
  peso_kg: string;
  data_nascimento: string;
  microchip: string;
  observacoes: string;
}

interface TutorPanoramaPet {
  id: number;
  nome: string;
  especie?: string | null;
  raca?: string | null;
  sexo?: string | null;
  ativo?: string | number | boolean | null;
}

interface TutorPanoramaData {
  tutor: {
    identificacao_pendente?: boolean;
    origem_cadastro?: string | null;
    identificacao_observacoes?: string | null;
    id: number;
    nome: string;
    telefone?: string | null;
    whatsapp?: string | null;
    email?: string | null;
    cpf?: string | null;
    cep?: string | null;
    endereco?: string | null;
    numero?: string | null;
    complemento?: string | null;
    bairro?: string | null;
    cidade?: string | null;
    estado?: string | null;
    latitude?: number | null;
    longitude?: number | null;
    place_id?: string | null;
    endereco_normalizado?: string | null;
    georreferenciado?: boolean;
  };
  pets: TutorPanoramaPet[];
  resumo?: {
    total_pets?: number;
    pets_ativos?: number;
    endereco_preenchido?: boolean;
    georreferenciado?: boolean;
  };
}

const buildInitialFormData = (defaultDate?: string, defaultTime?: string): FormDataAgenda => ({
  origem_atendimento: "clinica_parceira",
  tutor_id: "",
  paciente_id: "",
  clinica_id: "",
  clinica_nova_nome: "",
  clinica_nova_razao_social: "",
  clinica_nova_tabela_preco_id: "1",
  servico_id: "",
  data: defaultDate || "",
  hora: defaultTime || "",
  marcar_como_reserva: false,
  reserva_destinatario_manual: "clinica",
  reserva_prazo_horas: "3",
  reserva_prazo_confirmacao: criarPrazoPadraoReserva(),
  observacoes: "",
});

const buildInitialTutorForm = (): NovoTutorForm => ({
  identificacao_pendente: true,
  origem_cadastro: "",
  identificacao_observacoes: "",
  id: "",
  nome: "",
  telefone: "",
  whatsapp: "",
  email: "",
  cpf: "",
  cep: "",
  endereco: "",
  numero: "",
  complemento: "",
  bairro: "",
  cidade: "",
  estado: "CE",
  latitude: null,
  longitude: null,
  place_id: "",
  endereco_normalizado: "",
});

const buildInitialAnimalForm = (tutorId = ""): NovoAnimalForm => ({
  tutor_id: tutorId,
  nome: "",
  especie: "",
  raca: "",
  sexo: "",
  peso_kg: "",
  ...patientAgeForm(),
  microchip: "",
  observacoes: "",
});

const normalizeSearchText = (value?: string | null): string =>
  String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();

const matchesSearch = (value: string, query: string): boolean => {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) return true;

  const normalizedValue = normalizeSearchText(value);
  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);
  const flexibleValue = normalizedValue.replace(/(.)\1+/g, "$1");
  return tokens.every((token) => {
    const flexibleToken = token.replace(/(.)\1+/g, "$1");
    return (
      normalizedValue.includes(token) ||
      flexibleValue.includes(flexibleToken)
    );
  });
};

const formatarEnderecoClinica = (clinica?: ClinicaOption | null): string => {
  if (!clinica) return "";

  const enderecoLinha = [
    clinica.endereco,
    clinica.numero,
    clinica.complemento,
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .join(", ");

  const regiaoLinha = [
    clinica.bairro,
    [clinica.cidade, clinica.estado].map((item) => String(item || "").trim()).filter(Boolean).join("/"),
    clinica.cep,
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .join(" - ");

  return [enderecoLinha, regiaoLinha].filter(Boolean).join(" - ");
};

const formatarResumoPaciente = (paciente: PacienteOption): string => {
  const detalhes = [
    paciente.tutor ? `Tutor: ${paciente.tutor}` : "",
    paciente.especie || "",
    paciente.raca || "",
  ].filter(Boolean);

  return detalhes.join(" - ");
};

const tutorTemGeorreferenciamento = (tutor?: {
  latitude?: number | null;
  longitude?: number | null;
  georreferenciado?: boolean;
} | null): boolean => {
  if (!tutor) return false;
  return coordenadasSaoConfiaveis(tutor.latitude, tutor.longitude);
};

const clinicaTemGeorreferenciamento = (clinica?: ClinicaOption | null): boolean =>
  coordenadasSaoConfiaveis(clinica?.latitude, clinica?.longitude);

const resumoEnderecoTutor = (tutor?: {
  endereco?: string | null;
  numero?: string | null;
  complemento?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  estado?: string | null;
  cep?: string | null;
} | null): string => {
  if (!tutor) return "";

  const linha1 = [tutor.endereco, tutor.numero, tutor.complemento]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .join(", ");
  const linha2 = [
    tutor.bairro,
    [tutor.cidade, tutor.estado].map((item) => String(item || "").trim()).filter(Boolean).join("/"),
    tutor.cep,
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .join(" - ");

  return [linha1, linha2].filter(Boolean).join(" - ");
};

const formatarMoedaBRL = (valor: number): string => {
  return Number(valor || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
};

const rotularFonteDeslocamento = (fonte?: string | null): string => {
  const valor = String(fonte || "").trim().toLowerCase();
  if (!valor) return "Fonte nao informada";
  if (valor.startsWith("google_")) return "Google Maps";
  if (valor.startsWith("heuristica")) return "Heuristica local";
  if (valor === "mesma_clinica") return "Mesma clinica";
  if (valor === "clinica_indefinida") return "Clinica indefinida";
  if (valor === "sem_matriz") return "Sem matriz";
  return valor.replaceAll("_", " ");
};

const nomeClinicaLegivel = (nome?: string | null): string => {
  const valor = String(nome || "").trim();
  return valor || "destino nao informado";
};

const fraseDeslocamentoEntreClinicas = (origem?: string | null, destino?: string | null, duracaoMin = 0): string => {
  const origemNome = nomeClinicaLegivel(origem);
  const destinoNome = nomeClinicaLegivel(destino);
  if (origemNome.toLocaleLowerCase("pt-BR") === destinoNome.toLocaleLowerCase("pt-BR")) {
    return `Deslocamento local em ${origemNome}: ${duracaoMin} min.`;
  }
  return `Deslocamento entre ${origemNome} e ${destinoNome} de ${duracaoMin} min.`;
};

const detalharComposicaoDeslocamento = (
  totalMinutos?: number | null,
  anteriorMinutos?: number | null,
  proximoMinutos?: number | null,
  clinicaDestino?: string | null,
  clinicaAnterior?: string | null,
  clinicaProximo?: string | null,
  haAgendamentoAnterior = false,
  haAgendamentoProximo = false
): string => {
  const total = Number.isFinite(Number(totalMinutos)) ? Math.max(0, Number(totalMinutos)) : 0;
  const anterior = Number.isFinite(Number(anteriorMinutos)) ? Math.max(0, Number(anteriorMinutos)) : 0;
  const proximo = Number.isFinite(Number(proximoMinutos)) ? Math.max(0, Number(proximoMinutos)) : 0;
  const destino = String(clinicaDestino || "").trim() || "destino selecionado";
  const partes: string[] = [];

  if (haAgendamentoAnterior) {
    partes.push(fraseDeslocamentoEntreClinicas(clinicaAnterior, destino, anterior));
  } else {
    partes.push("Nao ha agendamentos anteriores ainda.");
  }

  if (haAgendamentoProximo) {
    partes.push(fraseDeslocamentoEntreClinicas(destino, clinicaProximo, proximo));
  } else {
    partes.push("Nao ha agendamentos posteriores ainda.");
  }

  partes.push(`Total estimado entre atendimentos: ${total} min.`);
  return partes.join(" ");
};

const resumirDeslocamentoSugestao = (item: SugestaoHorarioItem): string => {
  const fontes = [item.anterior?.fonte, item.proximo?.fonte].filter(Boolean) as string[];
  const detalheComposicao = detalharComposicaoDeslocamento(
    item.tempo_deslocamento_total_min,
    item.anterior?.duracao_deslocamento_min,
    item.proximo?.duracao_deslocamento_min,
    undefined,
    item.anterior?.clinica,
    item.proximo?.clinica,
    Boolean(item.anterior),
    Boolean(item.proximo)
  );
  if (fontes.length === 0) {
    return `Composicao do deslocamento: ${detalheComposicao}.`;
  }

  const fontesUnicas = Array.from(new Set(fontes.map((fonte) => rotularFonteDeslocamento(fonte))));
  return `Composicao do deslocamento: ${detalheComposicao}. Fonte do deslocamento: ${fontesUnicas.join(" + ")}.`;
};

const resumirPrimeiraSaidaSugestao = (item: SugestaoHorarioItem): string | null => {
  if (item.anterior || item.origem_primeira_saida !== "base_operacional") return null;
  const tempoBase = item.tempo_deslocamento_base_min;
  const viagem = typeof tempoBase === "number" && Number.isFinite(tempoBase)
    ? `Trajeto estimado casa → primeiro atendimento: ${tempoBase} min`
    : "Casa → primeiro atendimento: tempo de viagem indisponivel";
  const fonte = item.fonte_deslocamento_base
    ? ` (${rotularFonteDeslocamento(item.fonte_deslocamento_base)})`
    : "";
  const [dataMinima, horaMinima] = String(item.inicio_minimo_primeira_saida || "").split(" ");
  const horarioMinimo = /^\d{4}-\d{2}-\d{2}$/.test(dataMinima) && /^\d{2}:\d{2}$/.test(horaMinima)
    ? ` Primeiro inicio estimado com saida da base: ${dataMinima.split("-").reverse().join("/")} as ${horaMinima}.`
    : "";
  return `${viagem}${fonte}.${horarioMinimo}`;
};

function SearchableSelect({
  value,
  onChange,
  options,
  placeholder,
  searchPlaceholder,
  emptyText,
  selectionHint,
  clearLabel = "Selecione...",
  disabled = false,
  showSelectedDescription = false,
  onSearchChange,
  isSearching = false,
  searchingText = "Buscando...",
  searchError,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const selectedOption = options.find((option) => option.value === value) || null;
  const filteredOptions = options.filter((option) =>
    matchesSearch(
      [option.label, option.description || "", option.searchText || ""].filter(Boolean).join(" "),
      search
    )
  );

  useEffect(() => {
    if (!open) {
      setSearch("");
      onSearchChange?.("");
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (wrapperRef.current?.contains(target)) return;
      setOpen(false);
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [open, onSearchChange]);

  useEffect(() => {
    if (!open) return;

    const timer = window.setTimeout(() => {
      inputRef.current?.focus();
    }, 0);

    return () => {
      window.clearTimeout(timer);
    };
  }, [open]);

  const selecionar = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
    setSearch("");
  };

  return (
    <div ref={wrapperRef} className="fc-appointment-select relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((prev) => !prev)}
        className={`fc-appointment-select-trigger flex w-full items-center justify-between gap-3 rounded-lg border border-gray-300 bg-white px-3 py-2 text-left transition focus:outline-none ${
          disabled ? "cursor-not-allowed bg-gray-100 text-gray-400" : "hover:border-gray-400"
        }`}
        aria-expanded={open}
      >
        <span className="min-w-0 flex-1">
          <span className={`block truncate ${selectedOption ? "text-gray-900" : "text-gray-500"}`}>
            {selectedOption?.label || placeholder}
          </span>
          {showSelectedDescription && selectedOption?.description ? (
            <span className="mt-0.5 block truncate text-xs text-gray-500">
              {selectedOption.description}
            </span>
          ) : null}
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-gray-500 transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="fc-appointment-select-menu absolute left-0 right-0 z-30 mt-1 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl">
          <div className="border-b border-gray-100 p-2">
            <div className="fc-appointment-select-search flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
              <Search className="h-4 w-4 shrink-0 text-gray-400" />
              <input
                ref={inputRef}
                type="text"
                value={search}
                autoComplete="off"
                onChange={(event) => {
                  const nextSearch = event.target.value;
                  setSearch(nextSearch);
                  onSearchChange?.(nextSearch);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setOpen(false);
                    return;
                  }

                  if (event.key === "Enter") {
                    event.preventDefault();
                    if (filteredOptions.length === 1) {
                      selecionar(filteredOptions[0].value);
                    }
                  }
                }}
                placeholder={searchPlaceholder}
                className="w-full bg-transparent text-sm text-gray-900 outline-none placeholder:text-gray-400"
              />
            </div>
            {selectionHint ? (
              <p className="mt-1.5 px-1 text-xs text-amber-800">
                {selectionHint}
              </p>
            ) : null}
            {searchError ? (
              <p className="mt-1.5 px-1 text-xs text-red-700" role="alert">
                {searchError}
              </p>
            ) : null}
          </div>

          <div className="max-h-72 overflow-y-auto py-1">
            {isSearching && filteredOptions.length > 0 ? (
              <div className="px-3 py-2 text-xs text-gray-500" role="status">{searchingText}</div>
            ) : null}
            <button
              type="button"
              onClick={() => selecionar("")}
              className={`fc-appointment-select-option flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition ${
                !value ? "bg-blue-50 text-blue-700" : "text-gray-700"
              }`}
            >
              <span className="truncate">{clearLabel}</span>
              {!value ? <Check className="h-4 w-4 shrink-0" /> : null}
            </button>

            {filteredOptions.length === 0 ? (
              <div className="px-3 py-4 text-sm text-gray-500">
                {isSearching ? searchingText : emptyText}
              </div>
            ) : (
              filteredOptions.map((option) => {
                const isSelected = option.value === value;

                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => selecionar(option.value)}
                    className={`fc-appointment-select-option flex w-full items-start justify-between gap-3 px-3 py-2 text-left transition ${
                      isSelected ? "bg-blue-50 text-blue-700" : "text-gray-900"
                    }`}
                    title={option.description || option.label}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{option.label}</span>
                      {option.description ? (
                        <span className={`mt-0.5 block text-xs leading-4 ${isSelected ? "text-blue-600" : "text-gray-500"}`}>
                          {option.description}
                        </span>
                      ) : null}
                    </span>
                    {isSelected ? <Check className="mt-0.5 h-4 w-4 shrink-0" /> : null}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function NovoAgendamentoModal({ 
  isOpen, 
  onClose, 
  onSuccess,
  agendamento,
  pedidoWhatsApp,
  defaultDate,
  defaultTime,
  agendaSemanal,
  agendaFeriados,
  agendaExcecoes,
  isAdmin = false,
}: NovoAgendamentoModalProps) {
  const fortinho = useFortinho();
  const [loading, setLoading] = useState(false);
  const [pacientes, setPacientes] = useState<PacienteOption[]>([]);
  const [pacientesRemotos, setPacientesRemotos] = useState<PacienteOption[]>([]);
  const [pacientesDoTutor, setPacientesDoTutor] = useState<PacienteOption[]>([]);
  const [pacienteDetalhe, setPacienteDetalhe] = useState<PacienteOption | null>(null);
  const [buscaPacienteRemota, setBuscaPacienteRemota] = useState("");
  const [buscandoPacientes, setBuscandoPacientes] = useState(false);
  const [carregandoPacientesDoTutor, setCarregandoPacientesDoTutor] = useState(false);
  const [erroBuscaPaciente, setErroBuscaPaciente] = useState("");
  const [tutores, setTutores] = useState<TutorOption[]>([]);
  const [clinicas, setClinicas] = useState<ClinicaOption[]>([]);
  const [servicos, setServicos] = useState<any[]>([]);
  const [tutorSelecionado, setTutorSelecionado] = useState<string>("");
  const [tutorPanorama, setTutorPanorama] = useState<TutorPanoramaData | null>(null);
  const [carregandoTutorPanorama, setCarregandoTutorPanorama] = useState(false);
  const [buscaTutorRemota, setBuscaTutorRemota] = useState("");
  const [buscandoTutores, setBuscandoTutores] = useState(false);
  const [erroCarregamento, setErroCarregamento] = useState<string>("");
  const [carregandoSugestoes, setCarregandoSugestoes] = useState(false);
  const [sugestoesHorario, setSugestoesHorario] = useState<SugestaoHorarioItem[]>([]);
  const [ofertasPanoramicasConsultadas, setOfertasPanoramicasConsultadas] = useState(false);
  const [erroSugestoes, setErroSugestoes] = useState<string>("");
  const [erroSalvamento, setErroSalvamento] = useState<string>("");
  const [indiceOfertaEmValidacao, setIndiceOfertaEmValidacao] = useState<number | null>(null);
  const [mensagemSugestoes, setMensagemSugestoes] = useState<string>("");
  const [indiceSugestaoAtual, setIndiceSugestaoAtual] = useState(0);
  const [decisaoAssistente, setDecisaoAssistente] = useState<AssistenteDecisao>("pendente");
  const [motivoSemOpcao, setMotivoSemOpcao] = useState("");
  const [excecaoConcedida, setExcecaoConcedida] = useState(false);
  const [registrandoEncerramento, setRegistrandoEncerramento] = useState(false);
  const [itensIgnoradosJanela, setItensIgnoradosJanela] = useState(0);
  const [mensagemProximidade, setMensagemProximidade] = useState<string>("");
  const [sugestaoProximidade, setSugestaoProximidade] = useState<SugestaoProximidadeResponse | null>(null);
  const [dataContatoAssistente, setDataContatoAssistente] = useState<string>("");
  const [referenciaPreferencia, setReferenciaPreferencia] = useState(() => dataFortaleza());
  const [filtrosPreferencia, setFiltrosPreferencia] = useState<FiltrosPreferenciaAgenda>(() => filtrosDePreferencia());
  const [interacaoProximidade, setInteracaoProximidade] = useState({
    clinica: false,
    servico: false,
    data: false,
  });
  const popupProximidadeHistoricoRef = useRef<Record<string, number>>({});
  const sequenciaConsultaProximidadeRef = useRef(0);
  const sequenciaConsultaOfertasRef = useRef(0);
  const sequenciaValidacaoOfertaRef = useRef(0);
  const sequenciaBuscaTutorRef = useRef(0);
  const sequenciaPanoramaTutorRef = useRef(0);
  const [modalTutorAberto, setModalTutorAberto] = useState(false);
  const [modalAnimalAberto, setModalAnimalAberto] = useState(false);
  const [salvandoTutor, setSalvandoTutor] = useState(false);
  const [salvandoAnimal, setSalvandoAnimal] = useState(false);
  const [novoTutor, setNovoTutor] = useState<NovoTutorForm>(buildInitialTutorForm());
  const [novoAnimal, setNovoAnimal] = useState<NovoAnimalForm>(buildInitialAnimalForm());
  const [novaRaca, setNovaRaca] = useState("");
  const [racasCustomPorEspecie, setRacasCustomPorEspecie] = useState<RacasCustomPorEspecie>({});
  const [ajustesRacasPorEspecie, setAjustesRacasPorEspecie] = useState<AjustesRacasPorEspecie>({});
  const [racasLoaded, setRacasLoaded] = useState(false);
  const [gestaoRacasAberta, setGestaoRacasAberta] = useState(false);
  const [racaEmEdicaoId, setRacaEmEdicaoId] = useState("");
  const [nomeRacaEmEdicao, setNomeRacaEmEdicao] = useState("");
  const [consultandoCepTutor, setConsultandoCepTutor] = useState(false);
  const [geocodificandoTutor, setGeocodificandoTutor] = useState(false);
  const [statusEnderecoTutor, setStatusEnderecoTutor] = useState("");
  const ultimoCepConsultadoTutorRef = useRef("");
  const consultaCepTutorSequenciaRef = useRef(0);
  const [saldoCreditoCliente, setSaldoCreditoCliente] = useState(0);
  const [carregandoCreditoCliente, setCarregandoCreditoCliente] = useState(false);
  const [erroCreditoCliente, setErroCreditoCliente] = useState("");
  const [mensagemAgendaCriada, setMensagemAgendaCriada] = useState<MensagemAgendaPosCriacao | null>(null);
  const [feedbackMensagemAgenda, setFeedbackMensagemAgenda] = useState("");
  const [whatsappMensagemSelecionado, setWhatsappMensagemSelecionado] = useState("");
  const [envioAutomaticoStatus, setEnvioAutomaticoStatus] = useState<"idle" | "sending" | "sent">("idle");
  const [modeloAgendaSelecionado, setModeloAgendaSelecionado] = useState<AgendaWhatsAppTemplateKey>("reservation");
  const envioAutomaticoIdempotencyRef = useRef("");
  const [editandoWhatsappDestinatario, setEditandoWhatsappDestinatario] = useState(false);
  const [whatsappsDestinatarioEdicao, setWhatsappsDestinatarioEdicao] = useState<string[]>([""]);
  const [salvandoWhatsappDestinatario, setSalvandoWhatsappDestinatario] = useState(false);
  // A resolução operacional independe do tamanho visual das linhas da agenda.
  const intervaloSugestaoMinutos = 15;
  const preferenciaResolvida = resolverPreferenciaAgenda(filtrosPreferencia, referenciaPreferencia);

  const [formData, setFormData] = useState<FormDataAgenda>(
    buildInitialFormData(defaultDate, defaultTime)
  );

  const racasCatalogo = getRacasCatalogo(
    novoAnimal.especie,
    racasCustomPorEspecie[novoAnimal.especie] || [],
    ajustesRacasPorEspecie,
  );
  const opcoesRacaAnimal = getRacaOptions(
    novoAnimal.especie,
    novoAnimal.raca,
    racasCustomPorEspecie[novoAnimal.especie] || [],
    ajustesRacasPorEspecie,
  );
  const racaSelecionadaNoCatalogo = racasCatalogo.find(
    (raca) => raca.nome === novoAnimal.raca,
  );

  const isEditando = !!agendamento;
  const statusFormulario = isEditando
    ? (agendamento?.status || "Agendado")
    : (formData.marcar_como_reserva ? "Reservado" : "Agendado");
  const permiteSemPacienteTutor = statusFormulario === "Reservado";
  const editandoReservaExpirada = isEditando && statusFormulario === "Expirado";
  const atendimentoDomiciliar = formData.origem_atendimento === "domiciliar";
  const estadoExcecaoManual = {
    isEditando,
    isAdmin,
    decisaoAssistente,
    excecaoConcedida,
  };
  const excecaoManualAtiva = excecaoManualEstaLiberada(estadoExcecaoManual);

  const parseApiDateTime = (value?: string): Date | null => {
    if (!value) return null;

    const match = value
      .trim()
      .match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?/);
    if (match) {
      const [, ano, mes, dia, hora, minuto, segundo = "0"] = match;
      const local = new Date(
        Number(ano),
        Number(mes) - 1,
        Number(dia),
        Number(hora),
        Number(minuto),
        Number(segundo),
        0
      );
      if (!Number.isNaN(local.getTime())) {
        return local;
      }
    }

    const normalized = value.includes("T") ? value : value.replace(" ", "T");
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  };

  const parseAgendamentoInicio = (ag: any): Date | null => {
    if (ag?.data && ag?.hora) {
      const [ano, mes, dia] = String(ag.data).split("-").map(Number);
      const [hora, minuto] = String(ag.hora).split(":").map(Number);
      if (
        Number.isFinite(ano) &&
        Number.isFinite(mes) &&
        Number.isFinite(dia) &&
        Number.isFinite(hora) &&
        Number.isFinite(minuto)
      ) {
        const local = new Date(ano, mes - 1, dia, hora, minuto, 0, 0);
        if (!Number.isNaN(local.getTime())) {
          return local;
        }
      }
    }

    return parseApiDateTime(ag?.inicio);
  };

  const toInputDate = (date: Date): string => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };

  const hojeLocalIso = (): string => {
    const agora = new Date();
    return toInputDate(agora);
  };

  const agoraFortalezaIso = (): string => {
    const partes = new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Fortaleza",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date());
    const valor = Object.fromEntries(partes.map((parte) => [parte.type, parte.value]));
    return `${valor.year}-${valor.month}-${valor.day}T${valor.hour}:${valor.minute}:${valor.second}`;
  };

  const toBrDate = (isoDate?: string): string => {
    const match = String(isoDate || "")
      .trim()
      .match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return String(isoDate || "").trim();
    const [, year, month, day] = match;
    return `${day}/${month}/${year}`;
  };

  const isDataPassada = (isoDate?: string): boolean => {
    const match = String(isoDate || "")
      .trim()
      .match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return false;
    const [, year, month, day] = match;
    const dataSelecionada = new Date(Number(year), Number(month) - 1, Number(day), 0, 0, 0, 0);
    if (Number.isNaN(dataSelecionada.getTime())) return false;
    const agora = new Date();
    const hoje = new Date(agora.getFullYear(), agora.getMonth(), agora.getDate(), 0, 0, 0, 0);
    return dataSelecionada.getTime() < hoje.getTime();
  };

  const getDiaRelativo = (isoDate?: string): string => {
    const match = String(isoDate || "")
      .trim()
      .match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return "";

    const [, year, month, day] = match;
    const dataReferencia = new Date(Number(year), Number(month) - 1, Number(day), 0, 0, 0, 0);
    if (Number.isNaN(dataReferencia.getTime())) return "";

    const agora = new Date();
    const hoje = new Date(agora.getFullYear(), agora.getMonth(), agora.getDate(), 0, 0, 0, 0);
    const diffDias = Math.round((dataReferencia.getTime() - hoje.getTime()) / (24 * 60 * 60 * 1000));

    if (diffDias === 0) return "hoje";
    if (diffDias === 1) return "amanhã";
    if (diffDias === 2) return "depois de amanhã";
    return "";
  };

  const toInputTime = (date: Date): string => {
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${hours}:${minutes}`;
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

  useEffect(() => {
    setRacasCustomPorEspecie(loadRacasCustomPorEspecie());
    setAjustesRacasPorEspecie(loadAjustesRacasPorEspecie());
    setRacasLoaded(true);
  }, []);

  useEffect(() => {
    if (!racasLoaded) return;
    saveRacasCustomPorEspecie(racasCustomPorEspecie);
  }, [racasCustomPorEspecie, racasLoaded]);

  useEffect(() => {
    if (!racasLoaded) return;
    saveAjustesRacasPorEspecie(ajustesRacasPorEspecie);
  }, [ajustesRacasPorEspecie, racasLoaded]);

  // Inicializa formulario ao abrir no modo "novo" sem resetar quando pacientes/tutores atualizam.
  useEffect(() => {
    if (!isOpen || isEditando) return;
    setDivergenciaAceita("");
    setFormData({ ...buildInitialFormData(defaultDate, defaultTime), ...(pedidoWhatsApp ? camposPedidoAgenda(pedidoWhatsApp) : {}) });
    setDataContatoAssistente((atual) => atual || dataFortaleza());
    setReferenciaPreferencia(dataFortaleza());
    setFiltrosPreferencia(filtrosDePreferencia(pedidoWhatsApp?.dados_coletados?.preferencia_agenda));
    setTutorSelecionado(pedidoWhatsApp?.tutor?.nome || "");
    setSugestoesHorario([]);
    setIndiceOfertaEmValidacao(null);
    setOfertasPanoramicasConsultadas(false);
    setIndiceSugestaoAtual(0);
    setDecisaoAssistente("pendente");
    setMotivoSemOpcao("");
    setExcecaoConcedida(false);
    setRegistrandoEncerramento(false);
    setItensIgnoradosJanela(0);
    setErroSugestoes("");
    setErroSalvamento("");
    setMensagemSugestoes("");
    setMensagemProximidade("");
    setSugestaoProximidade(null);
    setInteracaoProximidade({ clinica: false, servico: false, data: false });
    popupProximidadeHistoricoRef.current = {};
    sequenciaConsultaProximidadeRef.current += 1;
    sequenciaConsultaOfertasRef.current += 1;
    setCarregandoSugestoes(false);
  }, [defaultDate, defaultTime, isEditando, isOpen, pedidoWhatsApp]);

  useEffect(() => {
    if (!isOpen || !isEditando) return;
    setReferenciaPreferencia(dataFortaleza());
    setFiltrosPreferencia(filtrosDePreferencia());
  }, [isOpen, isEditando, agendamento?.id]);

  // Preenche formulario ao abrir/atualizar no modo de edicao.
  useEffect(() => {
    if (!isOpen || !isEditando || !agendamento) return;
    setDataContatoAssistente("");

    const inicio = parseAgendamentoInicio(agendamento);
    const data = inicio ? toInputDate(inicio) : "";
    const hora = inicio ? toInputTime(inicio) : "";
    const pacienteSelecionado =
      agendamento.paciente_id && agendamento.paciente_id > 0
        ? pacientes.find((p) => p.id === agendamento.paciente_id)
        : null;
    const tutorIdInicial = agendamento?.tutor_id
      ? String(agendamento.tutor_id)
      : pacienteSelecionado?.tutor_id !== null &&
          pacienteSelecionado?.tutor_id !== undefined
        ? pacienteSelecionado.tutor_id.toString()
        : "";
    const origemAtendimento: OrigemAtendimento =
      agendamento?.origem_atendimento === "domiciliar" ? "domiciliar" : "clinica_parceira";

    setFormData({
      origem_atendimento: origemAtendimento,
      tutor_id: tutorIdInicial,
      paciente_id:
        agendamento.paciente_id && agendamento.paciente_id > 0
          ? agendamento.paciente_id.toString()
          : "",
      clinica_id: agendamento.clinica_id?.toString() || "",
      clinica_nova_nome: "",
      clinica_nova_razao_social: "",
      clinica_nova_tabela_preco_id: "1",
      servico_id: agendamento.servico_id?.toString() || "",
      data,
      hora,
      marcar_como_reserva: agendamento.status === "Reservado",
      reserva_destinatario_manual: origemAtendimento === "domiciliar" ? "tutor" : "clinica",
      reserva_prazo_horas: "3",
      reserva_prazo_confirmacao: criarPrazoPadraoReserva(),
      observacoes: agendamento.observacoes || "",
    });

    setTutorSelecionado(
      tutorIdInicial ? (pacienteSelecionado?.tutor || agendamento?.tutor || "") : ""
    );
    setSugestoesHorario([]);
    setIndiceOfertaEmValidacao(null);
    setOfertasPanoramicasConsultadas(false);
    setIndiceSugestaoAtual(0);
    setDecisaoAssistente("pendente");
    setMotivoSemOpcao("");
    setExcecaoConcedida(false);
    setRegistrandoEncerramento(false);
    setItensIgnoradosJanela(0);
    setErroSugestoes("");
    setErroSalvamento("");
    setMensagemSugestoes("");
    setInteracaoProximidade({ clinica: false, servico: false, data: false });
    popupProximidadeHistoricoRef.current = {};
    sequenciaConsultaProximidadeRef.current += 1;
    sequenciaConsultaOfertasRef.current += 1;
    setCarregandoSugestoes(false);
  }, [agendamento, isEditando, isOpen, pacientes]);

  // Carregar dados dos selects
  useEffect(() => {
    if (isOpen) {
      carregarDados();
      return;
    }

    setModalTutorAberto(false);
    setModalAnimalAberto(false);
    setSalvandoTutor(false);
    setSalvandoAnimal(false);
    setNovoTutor(buildInitialTutorForm());
    setNovoAnimal(buildInitialAnimalForm());
    setPacientesRemotos([]);
    setPacientesDoTutor([]);
    setPacienteDetalhe(null);
    setBuscaPacienteRemota("");
    setBuscandoPacientes(false);
    setCarregandoPacientesDoTutor(false);
    setErroBuscaPaciente("");
    setNovaRaca("");
    setGestaoRacasAberta(false);
    setRacaEmEdicaoId("");
    setNomeRacaEmEdicao("");
    setTutorPanorama(null);
    setCarregandoTutorPanorama(false);
    setGeocodificandoTutor(false);
    setStatusEnderecoTutor("");
    setFormData(buildInitialFormData(defaultDate, defaultTime));
    setTutorSelecionado("");
    setSugestoesHorario([]);
    setIndiceOfertaEmValidacao(null);
    setOfertasPanoramicasConsultadas(false);
    setIndiceSugestaoAtual(0);
    setDecisaoAssistente("pendente");
    setMotivoSemOpcao("");
    setExcecaoConcedida(false);
    setRegistrandoEncerramento(false);
    setItensIgnoradosJanela(0);
    setErroSugestoes("");
    setErroSalvamento("");
    setMensagemSugestoes("");
    setMensagemProximidade("");
    setSugestaoProximidade(null);
    setDataContatoAssistente("");
    setSaldoCreditoCliente(0);
    setCarregandoCreditoCliente(false);
    setErroCreditoCliente("");
    setMensagemAgendaCriada(null);
    setFeedbackMensagemAgenda("");
    setWhatsappMensagemSelecionado("");
    setModeloAgendaSelecionado("reservation");
    setEditandoWhatsappDestinatario(false);
    setWhatsappsDestinatarioEdicao([""]);
    setSalvandoWhatsappDestinatario(false);
    setInteracaoProximidade({ clinica: false, servico: false, data: false });
    popupProximidadeHistoricoRef.current = {};
    sequenciaConsultaProximidadeRef.current += 1;
    sequenciaConsultaOfertasRef.current += 1;
    setCarregandoSugestoes(false);
  }, [defaultDate, defaultTime, isOpen]);

  useEffect(() => {
    if (!isOpen || isEditando) {
      setSaldoCreditoCliente(0);
      setCarregandoCreditoCliente(false);
      setErroCreditoCliente("");
      return;
    }

    const tutorId = Number.parseInt(formData.tutor_id || "", 10);
    const pacienteId = Number.parseInt(formData.paciente_id || "", 10);
    const tutorValido = Number.isFinite(tutorId) && tutorId > 0;
    const pacienteValido = Number.isFinite(pacienteId) && pacienteId > 0;

    if (!tutorValido && !pacienteValido) {
      setSaldoCreditoCliente(0);
      setCarregandoCreditoCliente(false);
      setErroCreditoCliente("");
      return;
    }

    let ativo = true;
    setCarregandoCreditoCliente(true);
    setErroCreditoCliente("");

    (async () => {
      try {
        const saldo = await consultarSaldoCreditoCliente({
          tutorId: tutorValido ? tutorId : null,
          pacienteId: pacienteValido ? pacienteId : null,
        });
        if (!ativo) return;
        setSaldoCreditoCliente(saldo > 0 ? saldo : 0);
      } catch (error) {
        console.error("Erro ao consultar saldo de credito do cliente:", error);
        if (!ativo) return;
        setSaldoCreditoCliente(0);
        setErroCreditoCliente("Nao foi possivel consultar o credito do cliente no momento.");
      } finally {
        if (!ativo) return;
        setCarregandoCreditoCliente(false);
      }
    })();

    return () => {
      ativo = false;
    };
  }, [formData.paciente_id, formData.tutor_id, isEditando, isOpen]);

  useEffect(() => {
    setEditandoWhatsappDestinatario(false);
    setWhatsappsDestinatarioEdicao([""]);
  }, [
    formData.clinica_id,
    formData.reserva_destinatario_manual,
    formData.tutor_id,
  ]);

  const carregarDados = async () => {
    const extrairItems = (payload: any): any[] => {
      if (Array.isArray(payload?.items)) return payload.items;
      if (Array.isArray(payload?.data)) return payload.data;
      if (Array.isArray(payload)) return payload;
      return [];
    };

    const resultados = await Promise.allSettled([
      api.get("/pacientes?limit=1000"),
      api.get("/tutores?limit=1000"),
      loadStableCatalog({
        catalog: "clinicas",
        variant: "limit=1000",
        load: () => api.get("/clinicas?limit=1000").then((response) => response.data),
      }),
      loadStableCatalog({
        catalog: "servicos",
        variant: "limit=1000",
        load: () => api.get("/servicos?limit=1000").then((response) => response.data),
      }),
    ]);

    const falhas: string[] = [];

    const pacientesResp = resultados[0];
    if (pacientesResp.status === "fulfilled") {
      const items = extrairItems(pacientesResp.value?.data) as PacienteOption[];
      setPacientes(pedidoWhatsApp?.paciente && !items.some(p => p.id === pedidoWhatsApp.paciente?.id) ? [...items, pedidoWhatsApp.paciente] : items);
    } else {
      setPacientes([]);
      falhas.push("pacientes");
    }

    const tutoresResp = resultados[1];
    if (tutoresResp.status === "fulfilled") {
      const items = extrairItems(tutoresResp.value?.data) as TutorOption[];
      setTutores(pedidoWhatsApp?.tutor && !items.some(t => t.id === pedidoWhatsApp.tutor?.id) ? [...items, pedidoWhatsApp.tutor] : items);
    } else {
      setTutores([]);
      falhas.push("tutores");
    }

    const clinicasResp = resultados[2];
    if (clinicasResp.status === "fulfilled") {
      setClinicas(extrairItems(clinicasResp.value));
    } else {
      setClinicas([]);
      falhas.push("clinicas");
    }

    const servicosResp = resultados[3];
    if (servicosResp.status === "fulfilled") {
      setServicos(extrairItems(servicosResp.value));
    } else {
      setServicos([]);
      falhas.push("servicos");
    }

    if (falhas.length > 0) {
      setErroCarregamento(
        `Falha ao carregar ${falhas.join(", ")}. Atualize a pagina e tente novamente.`
      );
    } else {
      setErroCarregamento("");
    }
  };

  useEffect(() => {
    const termo = buscaTutorRemota.trim();
    if (!isOpen || termo.length < 2) {
      sequenciaBuscaTutorRef.current += 1;
      setBuscandoTutores(false);
      return;
    }

    const sequencia = sequenciaBuscaTutorRef.current + 1;
    sequenciaBuscaTutorRef.current = sequencia;
    setBuscandoTutores(true);

    const timer = window.setTimeout(async () => {
      try {
        const response = await api.get("/tutores", {
          params: { busca: termo, limit: 50 },
        });
        if (sequencia !== sequenciaBuscaTutorRef.current) return;

        const encontrados = Array.isArray(response?.data?.items)
          ? (response.data.items as TutorOption[])
          : [];
        setTutores((atuais) => {
          const porId = new Map(atuais.map((tutor) => [tutor.id, tutor]));
          encontrados.forEach((tutor) => porId.set(tutor.id, tutor));
          return Array.from(porId.values()).sort((a, b) =>
            a.nome.localeCompare(b.nome, "pt-BR")
          );
        });
      } catch (error) {
        console.error("Erro ao buscar tutores:", error);
      } finally {
        if (sequencia === sequenciaBuscaTutorRef.current) {
          setBuscandoTutores(false);
        }
      }
    }, 250);

    return () => {
      window.clearTimeout(timer);
    };
  }, [buscaTutorRemota, isOpen]);

  useEffect(() => {
    const tutorId = Number.parseInt(formData.tutor_id, 10);
    if (!isOpen || !Number.isFinite(tutorId) || tutorId <= 0) {
      setPacientesDoTutor([]);
      setCarregandoPacientesDoTutor(false);
      return;
    }

    let ativo = true;
    setPacientesDoTutor([]);
    setCarregandoPacientesDoTutor(true);
    (async () => {
      try {
        const encontrados: PacienteOption[] = [];
        let skip = 0;
        while (ativo) {
          const response = await api.get("/pacientes", {
            params: { tutor_id: tutorId, skip, limit: 100 },
          });
          if (!ativo) return;
          const pagina = Array.isArray(response?.data?.items)
            ? (response.data.items as PacienteOption[])
            : [];
          encontrados.push(...pagina);
          skip += pagina.length;
          const total = Number(response?.data?.total);
          if (pagina.length === 0 || !Number.isFinite(total) || skip >= total) break;
        }
        setPacientesDoTutor(encontrados);
        setErroBuscaPaciente("");
      } catch (error) {
        console.error("Erro ao carregar animais do tutor:", error);
        if (ativo) setErroBuscaPaciente("Nao foi possivel carregar todos os animais deste tutor. Busque pelo nome ou ID.");
      } finally {
        if (ativo) setCarregandoPacientesDoTutor(false);
      }
    })();

    return () => {
      ativo = false;
    };
  }, [formData.tutor_id, isOpen]);

  useEffect(() => {
    const termo = buscaPacienteRemota.trim();
    if (!isOpen || termo.length < 2) {
      setBuscandoPacientes(false);
      setErroBuscaPaciente("");
      return;
    }

    let ativo = true;
    setBuscandoPacientes(true);
    setErroBuscaPaciente("");
    const timer = window.setTimeout(async () => {
      try {
        const tutorId = Number.parseInt(formData.tutor_id, 10);
        const response = await api.get("/pacientes", {
          params: {
            search: termo,
            limit: 50,
            ...(Number.isFinite(tutorId) && tutorId > 0 ? { tutor_id: tutorId } : {}),
          },
        });
        if (!ativo) return;
        const encontrados = Array.isArray(response?.data?.items)
          ? (response.data.items as PacienteOption[])
          : [];
        setPacientesRemotos((atuais) => {
          const porId = new Map(atuais.map((paciente) => [paciente.id, paciente]));
          encontrados.forEach((paciente) => porId.set(paciente.id, paciente));
          return Array.from(porId.values());
        });
      } catch (error) {
        console.error("Erro ao buscar animais:", error);
        if (ativo) setErroBuscaPaciente("Falha ao buscar animais. Tente novamente.");
      } finally {
        if (ativo) setBuscandoPacientes(false);
      }
    }, 250);

    return () => {
      ativo = false;
      window.clearTimeout(timer);
    };
  }, [buscaPacienteRemota, formData.tutor_id, isOpen]);

  useEffect(() => {
    const pacienteId = Number(agendamento?.paciente_id);
    if (!isOpen || !isEditando || !Number.isFinite(pacienteId) || pacienteId <= 0) {
      setPacienteDetalhe(null);
      return;
    }

    let ativo = true;
    api.get(`/pacientes/${pacienteId}`)
      .then((response) => {
        if (ativo && Number(response?.data?.id) === pacienteId) {
          setPacienteDetalhe(response.data as PacienteOption);
        }
      })
      .catch((error) => {
        console.error("Erro ao carregar animal do agendamento:", error);
      });
    return () => {
      ativo = false;
    };
  }, [agendamento?.paciente_id, isEditando, isOpen]);

  useEffect(() => {
    if (!isOpen || !isEditando || !pacienteDetalhe) return;
    if (formData.paciente_id !== String(pacienteDetalhe.id) || formData.tutor_id) return;
    if (!pacienteDetalhe.tutor_id) return;
    setFormData((atual) => ({ ...atual, tutor_id: String(pacienteDetalhe.tutor_id) }));
    setTutorSelecionado((atual) => atual || pacienteDetalhe.tutor || "");
  }, [formData.paciente_id, formData.tutor_id, isEditando, isOpen, pacienteDetalhe]);

  const preencherModalTutor = (tutor?: TutorPanoramaData["tutor"] | null) => {
    if (!tutor) {
      setNovoTutor(buildInitialTutorForm());
      setStatusEnderecoTutor("");
      ultimoCepConsultadoTutorRef.current = "";
      return;
    }

    setNovoTutor({
      id: String(tutor.id || ""),
      identificacao_pendente: tutor.identificacao_pendente ?? true,
      origem_cadastro: tutor.origem_cadastro || "",
      identificacao_observacoes: tutor.identificacao_observacoes || "",
      nome: String(tutor.nome || ""),
      telefone: formatarTelefoneVisual(String(tutor.telefone || "")),
      whatsapp: formatarTelefoneVisual(String(tutor.whatsapp || "")),
      email: String(tutor.email || ""),
      cpf: formatarCpfVisual(String(tutor.cpf || "")),
      cep: formatarCepVisual(String(tutor.cep || "")),
      endereco: String(tutor.endereco || ""),
      numero: String(tutor.numero || ""),
      complemento: String(tutor.complemento || ""),
      bairro: String(tutor.bairro || ""),
      cidade: String(tutor.cidade || ""),
      estado: String(tutor.estado || "CE"),
      latitude: normalizarCoordenadaOpcional(tutor.latitude),
      longitude: normalizarCoordenadaOpcional(tutor.longitude),
      place_id: String(tutor.place_id || ""),
      endereco_normalizado: String(tutor.endereco_normalizado || ""),
    });
    ultimoCepConsultadoTutorRef.current = normalizarCep(tutor.cep || "");
    setStatusEnderecoTutor(
      tutorTemGeorreferenciamento(tutor)
        ? "Endereco do tutor georreferenciado com sucesso."
        : "Complete o endereco e execute o georreferenciamento antes de usar o tutor no fluxo domiciliar."
    );
  };

  const carregarPanoramaTutor = async (tutorId: string) => {
    const sequencia = sequenciaPanoramaTutorRef.current + 1;
    sequenciaPanoramaTutorRef.current = sequencia;
    const idNumerico = Number.parseInt(tutorId || "", 10);
    if (!Number.isFinite(idNumerico) || idNumerico <= 0) {
      setTutorPanorama(null);
      return;
    }

    try {
      setCarregandoTutorPanorama(true);
      const response = await api.get(`/tutores/${idNumerico}/panorama`);
      if (sequencia !== sequenciaPanoramaTutorRef.current) return;
      const panorama = response?.data as TutorPanoramaData;
      setTutorPanorama(panorama);
      if (panorama?.tutor) {
        setTutores((atuais) => {
          const tutorAtualizado = panorama.tutor as TutorOption;
          const restantes = atuais.filter((item) => item.id !== tutorAtualizado.id);
          return [...restantes, tutorAtualizado].sort((a, b) =>
            a.nome.localeCompare(b.nome, "pt-BR")
          );
        });
      }
      preencherModalTutor(panorama?.tutor);
    } catch (error) {
      if (sequencia !== sequenciaPanoramaTutorRef.current) return;
      console.error("Erro ao carregar panorama do tutor:", error);
      setTutorPanorama(null);
    } finally {
      if (sequencia === sequenciaPanoramaTutorRef.current) {
        setCarregandoTutorPanorama(false);
      }
    }
  };

  useEffect(() => {
    if (!isOpen) {
      sequenciaPanoramaTutorRef.current += 1;
      return;
    }
    if (!formData.tutor_id) {
      sequenciaPanoramaTutorRef.current += 1;
      setTutorPanorama(null);
      setCarregandoTutorPanorama(false);
      return;
    }
    void carregarPanoramaTutor(formData.tutor_id);
  }, [formData.tutor_id, isOpen]);

  const consultarCepTutor = async (cepFonte = novoTutor.cep) => {
    const cep = normalizarCep(cepFonte || "");
    if (cep.length !== 8) return;
    if (ultimoCepConsultadoTutorRef.current === cep) return;

    const sequencia = consultaCepTutorSequenciaRef.current + 1;
    consultaCepTutorSequenciaRef.current = sequencia;

    try {
      setConsultandoCepTutor(true);
      setStatusEnderecoTutor("Consultando CEP...");
      const response = await api.get(`/clinicas/cep/${cep}`);
      const item = response?.data?.item || {};

      if (sequencia !== consultaCepTutorSequenciaRef.current) {
        return;
      }

      setNovoTutor((prev) => ({
        ...prev,
        cep: formatarCepVisual(item.cep || cep),
        endereco: item.logradouro || prev.endereco,
        complemento: prev.complemento || item.complemento || "",
        bairro: item.bairro || prev.bairro,
        cidade: item.cidade || prev.cidade,
        estado: item.estado || prev.estado,
        latitude: null,
        longitude: null,
        place_id: "",
        endereco_normalizado: "",
      }));
      ultimoCepConsultadoTutorRef.current = normalizarCep(item.cep || cep);
      setStatusEnderecoTutor(
        item?.bairro_origem === "aprendizado"
          ? "CEP preenchido com bairro aprendido. Informe o numero e georreferencie o endereco."
          : "CEP preenchido pelo ViaCEP. Informe o numero e georreferencie o endereco."
      );
    } catch (error: any) {
      if (sequencia !== consultaCepTutorSequenciaRef.current) {
        return;
      }
      ultimoCepConsultadoTutorRef.current = "";
      const detail = error?.response?.data?.detail || error?.message || "Falha ao consultar CEP.";
      setStatusEnderecoTutor(String(detail));
    } finally {
      if (sequencia === consultaCepTutorSequenciaRef.current) {
        setConsultandoCepTutor(false);
      }
    }
  };

  const geocodificarTutorEndereco = async () => {
    if (!novoTutor.endereco.trim() || !novoTutor.numero.trim() || !novoTutor.cidade.trim() || !novoTutor.estado.trim()) {
      setStatusEnderecoTutor("Preencha endereco, numero, cidade e UF para georreferenciar o tutor.");
      return;
    }

    try {
      setGeocodificandoTutor(true);
      setStatusEnderecoTutor("");
      const response = await api.post("/agenda/geocode-endereco-tutor", {
        endereco: novoTutor.endereco,
        numero: novoTutor.numero,
        complemento: novoTutor.complemento,
        bairro: novoTutor.bairro,
        cidade: novoTutor.cidade,
        estado: novoTutor.estado,
        cep: novoTutor.cep,
      });
      const item = response?.data?.item || {};
      setNovoTutor((prev) => ({
        ...prev,
        bairro: item.bairro || prev.bairro,
        cidade: item.cidade || prev.cidade,
        estado: item.estado || prev.estado,
        cep: item.cep || prev.cep,
        latitude: normalizarCoordenadaOpcional(item.latitude) ?? prev.latitude,
        longitude: normalizarCoordenadaOpcional(item.longitude) ?? prev.longitude,
        place_id: item.place_id || prev.place_id,
        endereco_normalizado: item.endereco_normalizado || prev.endereco_normalizado,
      }));
      setStatusEnderecoTutor("Endereco do tutor georreferenciado com sucesso.");
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || "Falha ao georreferenciar o tutor.";
      setStatusEnderecoTutor(String(detail));
    } finally {
      setGeocodificandoTutor(false);
    }
  };

  const resetFluxoAssistente = (preservarMensagemProximidade = true) => {
    sequenciaConsultaProximidadeRef.current += 1;
    sequenciaConsultaOfertasRef.current += 1;
    setCarregandoSugestoes(false);
    setSugestoesHorario([]);
    setIndiceOfertaEmValidacao(null);
    setOfertasPanoramicasConsultadas(false);
    setIndiceSugestaoAtual(0);
    setDecisaoAssistente("pendente");
    setMotivoSemOpcao("");
    setExcecaoConcedida(false);
    setItensIgnoradosJanela(0);
    setErroSugestoes("");
    setErroSalvamento("");
    setMensagemSugestoes("");
    if (!preservarMensagemProximidade) {
      setMensagemProximidade("");
      setSugestaoProximidade(null);
    }
  };

  const alterarPreferencia = (filtros: FiltrosPreferenciaAgenda) => {
    resetFluxoAssistente(false);
    setFiltrosPreferencia(filtros);
    popupProximidadeHistoricoRef.current = {};
    if (!isEditando) setFormData((prev) => ({ ...prev, hora: "" }));
  };

  const handleOrigemAtendimentoChange = (origem: OrigemAtendimento) => {
    if (!isEditando) {
      resetFluxoAssistente(false);
    }
    setFormData((prev) => ({
      ...prev,
      origem_atendimento: origem,
      clinica_id: origem === "domiciliar" ? "" : prev.clinica_id,
      reserva_destinatario_manual: origem === "domiciliar" ? "tutor" : "clinica",
    }));
    if (origem === "domiciliar") {
      setMensagemProximidade("");
      setSugestaoProximidade(null);
    }
  };

  const handleTutorChange = (tutorId: string) => {
    const tutor = tutores.find((t) => t.id.toString() === tutorId);
    if (!isEditando && atendimentoDomiciliar) {
      resetFluxoAssistente(false);
    }
    setInteracaoProximidade((prev) => ({ ...prev, clinica: true }));
    setBuscaPacienteRemota("");
    setErroBuscaPaciente("");
    setTutorSelecionado(tutor?.nome || "");
    setFormData((prev) => ({
      ...prev,
      tutor_id: tutorId,
      paciente_id: "",
    }));
  };

  const handlePacienteChange = (pacienteId: string, pacienteInformado?: PacienteOption) => {
    const paciente = pacienteInformado || pacientesDisponiveis.find((p) => p.id.toString() === pacienteId);
    if (pacienteInformado) {
      setPacientesRemotos((atuais) => {
        const porId = new Map(atuais.map((item) => [item.id, item]));
        porId.set(pacienteInformado.id, pacienteInformado);
        return Array.from(porId.values());
      });
    }
    if (paciente?.tutor_id && paciente.tutor) {
      const tutorId = paciente.tutor_id;
      const tutorNome = paciente.tutor;
      setTutores((atuais) => atuais.some((tutor) => tutor.id === tutorId)
        ? atuais
        : [...atuais, { id: tutorId, nome: tutorNome }]
          .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR")));
    }
    setTutorSelecionado(paciente?.tutor || "");
    setFormData((prev) => ({
      ...prev,
      paciente_id: pacienteId,
      tutor_id:
        paciente?.tutor_id !== null && paciente?.tutor_id !== undefined
          ? paciente.tutor_id.toString()
          : prev.tutor_id,
    }));
  };

  const buscarSugestaoProximidade = async (clinicaId: string, dataISO: string) => {
    if (preferenciaResolvida.erro) return;
    const clinicaIdNum = Number.parseInt(clinicaId, 10);
    const tutorIdNum = Number.parseInt(formData.tutor_id || "", 10);
    if (!Number.isFinite(clinicaIdNum)) {
      if (!atendimentoDomiciliar) {
        setMensagemProximidade("");
        setSugestaoProximidade(null);
        return;
      }
    }
    if (!dataISO) {
      setMensagemProximidade("Selecione a data para ativar o assistente inteligente de proximidade.");
      setSugestaoProximidade(null);
      return;
    }
    if (atendimentoDomiciliar) {
      if (!Number.isFinite(tutorIdNum)) {
        setMensagemProximidade("Selecione um tutor georreferenciado para ativar a sugestao de proximidade.");
        setSugestaoProximidade(null);
        return;
      }
      if (!tutorSelecionadoGeorreferenciado) {
        setMensagemProximidade(
          "Georreferencie o endereco do tutor antes de consultar sugestoes de proximidade para o atendimento domiciliar."
        );
        setSugestaoProximidade(null);
        return;
      }
    } else {
      const clinicaAtual = clinicas.find((item) => item.id === clinicaIdNum) || null;
      if (!clinicaTemGeorreferenciamento(clinicaAtual)) {
        setMensagemProximidade(
          "Georreferencie o endereco da clinica na tela de Clinicas antes de consultar sugestoes de proximidade."
        );
        setSugestaoProximidade(null);
        return;
      }
    }
    const consultaId = ++sequenciaConsultaProximidadeRef.current;

    try {
      const dataContato = !isEditando ? (dataContatoAssistente || hojeLocalIso()) : undefined;
      const response = await api.post<SugestaoProximidadeResponse>("/agenda/sugestao-proximidade", {
        origem_atendimento: formData.origem_atendimento,
        clinica_id: atendimentoDomiciliar ? null : clinicaIdNum,
        tutor_id: atendimentoDomiciliar ? tutorIdNum : null,
        data: dataISO,
        data_contato: dataContato,
        servico_id: formData.servico_id ? Number.parseInt(formData.servico_id, 10) : null,
        duracao_minutos: obterDuracaoServicoSelecionado(),
        intervalo_minutos: intervaloSugestaoMinutos,
        preferencia: preferenciaResolvida.preferencia,
        limite_sugestoes_operacionais: 8,
        perfil_deslocamento: "comercial",
        limite_minutos: LIMITE_MINUTOS_PROXIMIDADE,
        ignorar_agendamento_id: isEditando ? agendamento?.id : null,
      });
      if (consultaId !== sequenciaConsultaProximidadeRef.current) {
        return;
      }

      const data = response?.data || null;
      setSugestaoProximidade(data);
      const mensagem = String(data?.mensagem || "").trim();

      const item = data?.item;
      if (!data?.sugerir || !item) {
        setMensagemProximidade(mensagem || "Assistente inteligente sem sugestao para os dados atuais.");
        return;
      }

      const limiteBase = Number(data?.limite_minutos || LIMITE_MINUTOS_PROXIMIDADE);
      const duracao = Number(item?.duracao_deslocamento_min || 0);
      const duracaoAnterior = Number(item?.duracao_deslocamento_anterior_min || 0);
      const duracaoProximo = Number(item?.duracao_deslocamento_proximo_min || 0);
      const detalheComposicao = detalharComposicaoDeslocamento(
        duracao,
        duracaoAnterior,
        duracaoProximo,
        item?.clinica_destino || undefined,
        item?.clinica_anterior || undefined,
        item?.clinica_posterior || undefined,
        Boolean(item?.ha_agendamento_anterior),
        Boolean(item?.ha_agendamento_posterior)
      );

      const dataSugerida = String(item?.data || dataISO || "").trim();
      const horaSugerida = String(item?.inicio || "").trim();
      const clinicaSugerida = String(item?.clinica || "").trim();
      const nomeTutorAtual = String(tutorPanorama?.tutor?.nome || tutorSelecionadoOption?.nome || tutorSelecionado || "").trim();
      const clinicaDestino = String(
        atendimentoDomiciliar
          ? data?.destino_operacional || item?.destino_operacional || item?.clinica_destino || (nomeTutorAtual ? `Domicilio de ${nomeTutorAtual}` : "Atendimento domiciliar")
          : clinicas.find((c) => String(c?.id || "") === String(clinicaIdNum))?.nome ||
              data?.destino_operacional ||
              item?.destino_operacional ||
              item?.clinica_destino ||
              ""
      ).trim();
      const mesmoDestino = !!clinicaDestino && clinicaDestino === clinicaSugerida;
      const detalheHora = horaSugerida ? ` às ${horaSugerida}` : "";
      const dataSugeridaBr = toBrDate(dataSugerida) || dataSugerida;
      const diaRelativo = getDiaRelativo(dataSugerida);
      const dataSugeridaContexto = diaRelativo ? `${dataSugeridaBr} (${diaRelativo})` : dataSugeridaBr;
      const resumoHorario = `${dataSugeridaContexto}${detalheHora}`.trim() || "a data e o horário sugeridos";
      const acimaDoLimite = duracao > limiteBase || Boolean(data?.acima_do_limite);
      const politicaDistanteBaixa =
        Boolean(data?.politica_oferta?.distante_base) &&
        Boolean(data?.politica_oferta?.baixa_frequencia);
      const dataPreferencial = Boolean(item?.data_preferencial);
      const textoDeslocamento =
        clinicaDestino && !mesmoDestino
          ? `e a composicao do deslocamento para ${clinicaDestino} é de ${detalheComposicao}`
          : `com composicao estimada de deslocamento em ${detalheComposicao}`;
      const textoBase = `Encontramos uma opção melhor de horário para reduzir deslocamento. Temos um atendimento ${
        clinicaSugerida ? `de referencia em ${clinicaSugerida}` : "proximo"
      } no dia ${resumoHorario} ${textoDeslocamento}.`;
      const mensagemAssistente = acimaDoLimite
        ? `${textoBase} (limite configurado: ${limiteBase} min).`
        : `${textoBase} Esse deslocamento está dentro do limite configurado de ${limiteBase} min.`;
      const mensagemFinal = mensagem || mensagemAssistente;
      setMensagemProximidade(mensagemFinal);

      // Com a excecao concedida o admin ja decidiu por data/hora manual: manter
      // o texto informativo, mas sem interromper com o popup de aplicar horario.
      if (excecaoManualAtiva) {
        return;
      }

      if (politicaDistanteBaixa && !dataPreferencial) {
        return;
      }

      const limiteEstendido = limiteBase + LIMITE_ESTENDIDO_EXTRA_MIN;
      if (!Number.isFinite(duracao) || duracao <= 0 || duracao > limiteEstendido) {
        return;
      }

      const chavePopup = [
        formData.origem_atendimento,
        String(atendimentoDomiciliar ? tutorIdNum : clinicaIdNum),
        String(clinicaIdNum),
        String(formData.servico_id || ""),
        String(item?.agendamento_id || ""),
        String(item?.data || ""),
        String(item?.inicio || ""),
      ].join("|");
      const agora = Date.now();
      const ultimo = popupProximidadeHistoricoRef.current[chavePopup] || 0;
      if (agora - ultimo < COOLDOWN_POPUP_PROXIMIDADE_MS) {
        return;
      }
      popupProximidadeHistoricoRef.current[chavePopup] = agora;

      const mensagemPopup = acimaDoLimite
        ? [
            "Sugestão de proximidade acima do limite:",
            "",
            mensagemFinal,
            "",
            "Posso aplicar esse horário?",
          ].join("\n")
        : [
            "Sugestão inteligente de proximidade:",
            "",
            mensagemFinal,
            "",
            "Posso aplicar esse horário?",
          ].join("\n");
      const confirmou = await fortinho.confirm({
        title: acimaDoLimite
          ? "Sugestao de proximidade acima do limite"
          : "Sugestao inteligente de proximidade",
        message: mensagemPopup,
        confirmLabel: "Aplicar horario",
        cancelLabel: "Manter como esta",
        mood: acimaDoLimite ? "alert" : "thinking",
        gesture: "point-right",
      });
      if (consultaId !== sequenciaConsultaProximidadeRef.current) return;

      if (confirmou && dataSugerida) {
        try {
          const { items, itensIgnorados } = await buscarSugestoesOperacionais(dataSugerida);
          if (consultaId !== sequenciaConsultaProximidadeRef.current) return;
          setItensIgnoradosJanela(itensIgnorados);
          setSugestoesHorario(items);
          setOfertasPanoramicasConsultadas(true);
          setIndiceSugestaoAtual(0);
          setMotivoSemOpcao("");
          setExcecaoConcedida(false);
          if (items.length === 0) {
            setDecisaoAssistente("pendente");
            setMensagemSugestoes(
              "Sem ofertas aderentes para a data sugerida por proximidade. Ajuste os filtros e gere novas ofertas antes de registrar recusa."
            );
            return;
          }
          setDecisaoAssistente("pendente");

          const candidatosRelacionados = items.filter(
            (cand) => Number(cand?.anterior?.agendamento_id || 0) === Number(item?.agendamento_id || 0)
          );

          const origemBusca = (candidatosRelacionados.length > 0 ? candidatosRelacionados : items).slice();

          const itemAlternativo = origemBusca.find((cand) => {
            const [dataCand, horaCand] = String(cand?.inicio || "").split(" ");
            if (!dataCand || !horaCand) return false;
            return dataCand !== dataSugerida || horaCand !== horaSugerida;
          });

          if (itemAlternativo?.inicio) {
            const [dataAplicacao, horaAplicacao] = String(itemAlternativo.inicio || "").split(" ");
            if (dataAplicacao && horaAplicacao) {
              setFormData((prev) => ({
                ...prev,
                data: dataAplicacao,
                hora: horaAplicacao,
              }));
              setErroSugestoes("");
              setMensagemSugestoes(
                `Horario operacional aplicado automaticamente: ${horaAplicacao}. Revise o panorama de ofertas antes de registrar aceite ou recusa.`
              );
              return;
            }
          }

          setFormData((prev) => ({
            ...prev,
            data: dataSugerida,
            hora: "",
          }));
          setErroSugestoes("");
          setMensagemSugestoes(
            items.length > 0
              ? "Data de proximidade aplicada. Revise o panorama completo de ofertas e registre aceite ou recusa."
              : "Data de proximidade aplicada. Clique em Sugerir horarios para encontrar um horario operacional."
          );
        } catch {
          if (consultaId !== sequenciaConsultaProximidadeRef.current) return;
          setFormData((prev) => ({
            ...prev,
            data: dataSugerida,
            hora: "",
          }));
          setErroSugestoes("");
          setMensagemSugestoes(
            "Data de proximidade aplicada. Nao foi possivel aplicar horario automaticamente agora."
          );
        }
      }
    } catch {
      if (consultaId !== sequenciaConsultaProximidadeRef.current) {
        return;
      }
      setMensagemProximidade("Nao foi possivel consultar sugestoes de proximidade agora.");
      setSugestaoProximidade(null);
    }
  };

  const handleClinicaChange = (clinicaId: string) => {
    setInteracaoProximidade((prev) => ({ ...prev, clinica: true }));
    if (!isEditando) {
      resetFluxoAssistente(false);
    }
    setFormData((prev) => ({
      ...prev,
      clinica_id: clinicaId,
      clinica_nova_nome: clinicaId ? "" : prev.clinica_nova_nome,
      clinica_nova_razao_social: clinicaId ? "" : prev.clinica_nova_razao_social,
    }));
  };

  const handleServicoChange = (servicoId: string) => {
    setInteracaoProximidade((prev) => ({ ...prev, servico: true }));
    if (!isEditando) {
      resetFluxoAssistente();
    }
    setFormData((prev) => ({
      ...prev,
      servico_id: servicoId,
    }));
  };

  // Sob excecao concedida a data manual e o objetivo do fluxo: manter desfecho,
  // motivo e excecao, descartando apenas o panorama que era daquela outra data.
  const invalidarPanoramaMantendoExcecao = () => {
    setSugestoesHorario([]);
    setOfertasPanoramicasConsultadas(false);
    setIndiceSugestaoAtual(0);
    setItensIgnoradosJanela(0);
    setErroSugestoes("");
    setMensagemSugestoes(
      "Data ajustada sob excecao concedida. Motivo e excecao seguem registrados; ajuste a hora e salve, ou gere nova oferta para recomecar o assistente."
    );
  };

  const handleDataChange = (data: string) => {
    setInteracaoProximidade((prev) => ({ ...prev, data: true }));
    if (deveResetarAssistentePorTrocaDeData(estadoExcecaoManual)) {
      resetFluxoAssistente();
    } else if (!isEditando) {
      invalidarPanoramaMantendoExcecao();
    }
    setFormData((prev) => ({
      ...prev,
      data,
    }));
  };

  const tutorSelecionadoGeorreferenciadoAtual = tutorPanorama?.tutor
    ? tutorTemGeorreferenciamento(tutorPanorama.tutor)
    : tutorTemGeorreferenciamento(tutores.find((tutor) => tutor.id.toString() === formData.tutor_id) || null);

  useEffect(() => {
    // No modo novo, primeiro a recepção informa as preferências e então solicita ofertas.
    if (!isOpen || !isEditando) return;
    if (!formData.servico_id) {
      setMensagemProximidade("Selecione o servico para ativar o assistente inteligente de proximidade.");
      setSugestaoProximidade(null);
      return;
    }
    if (atendimentoDomiciliar) {
      if (!formData.tutor_id) {
        setMensagemProximidade("Selecione um tutor georreferenciado para ativar o assistente inteligente.");
        setSugestaoProximidade(null);
        return;
      }
      if (!tutorSelecionadoGeorreferenciadoAtual) {
        setMensagemProximidade("O tutor selecionado ainda nao possui georreferenciamento confirmado.");
        setSugestaoProximidade(null);
        return;
      }
    } else {
      if (!formData.clinica_id) {
        setMensagemProximidade("");
        setSugestaoProximidade(null);
        return;
      }
      const clinicaAtual = clinicas.find((clinica) => clinica.id.toString() === formData.clinica_id) || null;
      if (!clinicaTemGeorreferenciamento(clinicaAtual)) {
        setMensagemProximidade("A clinica selecionada ainda nao possui georreferenciamento confirmado.");
        setSugestaoProximidade(null);
        return;
      }
    }
    if (!interacaoProximidade.clinica || !interacaoProximidade.servico) {
      return;
    }
    void buscarSugestaoProximidade(formData.clinica_id, formData.data);
  }, [
    isOpen,
    formData.clinica_id,
    formData.servico_id,
    formData.data,
    interacaoProximidade.clinica,
    interacaoProximidade.servico,
    clinicas,
    atendimentoDomiciliar,
    formData.tutor_id,
    tutorSelecionadoGeorreferenciadoAtual,
    isEditando,
    filtrosPreferencia,
  ]);

  const pacientesDisponiveis = Array.from(
    new Map(
      [
        ...pacientes,
        ...pacientesDoTutor,
        ...pacientesRemotos,
        ...(pacienteDetalhe ? [pacienteDetalhe] : []),
      ].map((paciente) => [paciente.id, paciente])
    ).values()
  );
  const pacientesFiltradosPorTutor = formData.tutor_id
    ? pacientesDisponiveis.filter((paciente) => String(paciente.tutor_id || "") === formData.tutor_id)
    : pacientesDisponiveis;
  const petsAtivosDoTutor = tutorPanorama?.pets?.filter(
    (pet) => !["0", "false"].includes(String(pet.ativo ?? 1).toLowerCase())
  ) || [];

  const tutorOptions: SearchableSelectOption[] = tutores.map((tutor) => ({
    value: tutor.id.toString(),
    label: tutor.nome,
    description: [
      `Tutor #${tutor.id}`,
      tutor.identificacao_pendente ? "Identificacao pendente" : "Identificacao confirmada",
      tutor.origem_cadastro ? `Origem: ${tutor.origem_cadastro}` : "",
      tutor.whatsapp || tutor.telefone ? `WhatsApp: ${tutor.whatsapp || tutor.telefone}` : "",
      tutor.endereco_resumo ||
        (tutor.georreferenciado ? "Endereco georreferenciado" : "Endereco pendente"),
      tutor.pets?.length
        ? `Pets: ${tutor.pets.map((pet) => pet.nome).filter(Boolean).join(", ")}`
        : tutor.total_pets === 0
          ? "Sem pets vinculados"
          : "",
    ]
      .filter(Boolean)
      .join(" - "),
    searchText: [
      tutor.nome,
      tutor.whatsapp || "",
      tutor.telefone || "",
      tutor.email || "",
      tutor.cidade || "",
      ...(tutor.pets || []).map((pet) => pet.nome),
    ]
      .filter(Boolean)
      .join(" "),
  }));

  const pacienteOptions: SearchableSelectOption[] = pacientesFiltradosPorTutor.map((paciente) => ({
    value: paciente.id.toString(),
    label: paciente.nome,
    description: formatarResumoPaciente(paciente) || undefined,
    searchText: [paciente.nome, String(paciente.id), paciente.tutor || "", String(paciente.tutor_id || ""), paciente.especie || "", paciente.raca || ""]
      .filter(Boolean)
      .join(" "),
  }));

  const clinicaOptions: SearchableSelectOption[] = clinicas.map((clinica) => {
    const endereco = formatarEnderecoClinica(clinica) || "Endereco nao cadastrado";

    return {
      value: clinica.id.toString(),
      label: clinica.nome,
      description: `${endereco} - ${clinicaTemGeorreferenciamento(clinica) ? "georreferenciada" : "pendente de georreferenciamento"}`,
      searchText: [clinica.nome, endereco].filter(Boolean).join(" "),
    };
  });

  const clinicaSelecionada = clinicas.find((clinica) => clinica.id.toString() === formData.clinica_id) || null;
  const clinicaSelecionadaGeorreferenciada = clinicaTemGeorreferenciamento(clinicaSelecionada);
  const tutorSelecionadoOption = tutores.find((tutor) => tutor.id.toString() === formData.tutor_id) || null;
  const tutorPanoramaSelecionado = String(tutorPanorama?.tutor?.id || "") === formData.tutor_id
    ? tutorPanorama?.tutor
    : null;
  const nomeTutorReservaManual = String(
    tutorSelecionadoOption?.nome || tutorPanoramaSelecionado?.nome || tutorSelecionado || ""
  ).trim();
  const telefoneTutorReservaManual = String(
    tutorSelecionadoOption?.whatsapp ||
      tutorPanoramaSelecionado?.whatsapp ||
      tutorSelecionadoOption?.telefone ||
      tutorPanoramaSelecionado?.telefone ||
      ""
  ).trim();
  const nomeClinicaReservaManual = String(clinicaSelecionada?.nome || "").trim();
  const telefonesClinicaMensagem = obterWhatsappsClinica(
    clinicaSelecionada?.whatsapps,
    clinicaSelecionada?.telefone,
  );
  const pacienteSelecionadoMensagem = pacientesDisponiveis.find(
    (paciente) => paciente.id.toString() === formData.paciente_id
  ) || null;
  const tutorSelecionadoGeorreferenciado = tutorPanorama?.tutor
    ? tutorTemGeorreferenciamento(tutorPanorama.tutor)
    : tutorTemGeorreferenciamento(tutorSelecionadoOption);
  const destinoOperacionalAtualLabel = atendimentoDomiciliar
    ? (() => {
        const nomeTutor = String(
          tutorPanorama?.tutor?.nome || tutorSelecionadoOption?.nome || tutorSelecionado || ""
        ).trim();
        return nomeTutor ? `Domicilio de ${nomeTutor}` : "Atendimento domiciliar";
      })()
    : String(clinicaSelecionada?.nome || "").trim() || "Clinica selecionada";

  const obterDuracaoServicoSelecionado = (): number => {
    const servicoSelecionado = servicos.find((s) => s.id?.toString() === formData.servico_id);
    const duracaoMinutos = Number.parseInt(
      `${servicoSelecionado?.duracao_minutos ?? ""}`,
      10
    );
    return Number.isFinite(duracaoMinutos) && duracaoMinutos > 0 ? duracaoMinutos : 30;
  };

  const buscarSugestoesOperacionais = async (
    dataBaseBusca: string
  ): Promise<{ items: SugestaoHorarioItem[]; motivo: string; itensIgnorados: number }> => {
    const clinicaId = Number.parseInt(formData.clinica_id || "", 10);
    const tutorId = Number.parseInt(formData.tutor_id || "", 10);
    const payload = {
      data: dataBaseBusca,
      origem_atendimento: formData.origem_atendimento,
      clinica_id: atendimentoDomiciliar ? null : (Number.isFinite(clinicaId) ? clinicaId : null),
      tutor_id: atendimentoDomiciliar && Number.isFinite(tutorId) ? tutorId : null,
      servico_id: formData.servico_id ? parseInt(formData.servico_id, 10) : null,
      duracao_minutos: obterDuracaoServicoSelecionado(),
      intervalo_minutos: intervaloSugestaoMinutos,
      preferencia: preferenciaResolvida.preferencia,
      limite: 8,
      perfil_deslocamento: "comercial",
      ignorar_agendamento_id: isEditando ? agendamento?.id : null,
    };

    const response = await api.post<SugestoesHorarioResponse>("/agenda/sugestoes-horario", payload);
    const items = Array.isArray(response?.data?.items) ? response.data.items : [];
    const motivo = String(response?.data?.motivo || "").trim();
    const itensIgnorados = Number(response?.data?.itens_ignorados_janela || 0);
    return { items, motivo, itensIgnorados };
  };

  const aplicarSugestaoHorario = (item: SugestaoHorarioItem): boolean => {
    const [data, hora] = String(item.inicio || "").split(" ");
    if (!data || !hora) {
      setErroSugestoes("Nao foi possivel aplicar o horario sugerido.");
      return false;
    }

    setFormData((prev) => ({ ...prev, data, hora }));
    setMensagemSugestoes(`Horario sugerido aplicado: ${hora}.`);
    setErroSugestoes("");
    return true;
  };

  const confirmarAceiteSugestao = async (item: SugestaoHorarioItem, indice: number) => {
    if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(item.inicio)) {
      setErroSalvamento("Esta oferta tem um horario invalido. Gere novas ofertas antes de continuar.");
      return;
    }
    const consultaId = sequenciaConsultaOfertasRef.current;
    const validacaoId = ++sequenciaValidacaoOfertaRef.current;
    const clinicaId = Number.parseInt(formData.clinica_id || "", 10);
    const tutorId = Number.parseInt(formData.tutor_id || "", 10);
    setIndiceOfertaEmValidacao(indice);
    setDecisaoAssistente("pendente");
    setFormData((prev) => ({ ...prev, hora: "" }));
    setErroSalvamento("");
    setErroSugestoes("");

    try {
      const response = await api.post<ValidacaoOfertaResponse>("/agenda/assistente/validar-oferta", {
        inicio: item.inicio,
        origem_atendimento: formData.origem_atendimento,
        clinica_id: atendimentoDomiciliar ? null : (Number.isFinite(clinicaId) ? clinicaId : null),
        tutor_id: atendimentoDomiciliar && Number.isFinite(tutorId) ? tutorId : null,
        servico_id: formData.servico_id ? Number.parseInt(formData.servico_id, 10) : null,
        duracao_minutos: obterDuracaoServicoSelecionado(),
        perfil_deslocamento: "comercial",
      });
      if (consultaId !== sequenciaConsultaOfertasRef.current || validacaoId !== sequenciaValidacaoOfertaRef.current) return;

      if (response.data?.valido !== true) {
        const mensagem = String(response.data?.mensagem || "Esta oferta nao esta mais disponivel.").trim();
        resetFluxoAssistente();
        setFormData((prev) => ({ ...prev, hora: "" }));
        setErroSalvamento(`${mensagem} Gere novas ofertas antes de registrar o aceite.`);
        return;
      }

      if (!aplicarSugestaoHorario(item)) return;
      setIndiceSugestaoAtual(indice);
      setDecisaoAssistente("aceito");
      setMotivoSemOpcao("");
      setExcecaoConcedida(false);
      setErroSugestoes("");
      setMensagemSugestoes("Oferta revalidada. Cliente aceitou o horario sugerido pelo assistente.");
    } catch (error: any) {
      if (consultaId !== sequenciaConsultaOfertasRef.current || validacaoId !== sequenciaValidacaoOfertaRef.current) return;
      const detail = error?.response?.data?.detail ?? error?.message;
      setErroSalvamento(
        `${extrairMensagemErro(detail, "Nao foi possivel revalidar esta oferta agora.")} Tente novamente antes de registrar o aceite.`
      );
    } finally {
      if (consultaId === sequenciaConsultaOfertasRef.current && validacaoId === sequenciaValidacaoOfertaRef.current) {
        setIndiceOfertaEmValidacao(null);
      }
    }
  };

  const liberarFluxoManual = () => {
    if (!ofertasPanoramicasConsultadas) {
      setErroSugestoes("Gere e visualize as ofertas do assistente antes de registrar recusa.");
      return;
    }
    if (totalSugestoes < 1) {
      setErroSugestoes("Nao e possivel registrar recusa sem ao menos 1 oferta exibida no panorama.");
      return;
    }
    setDecisaoAssistente("sem_opcao");
    setExcecaoConcedida(false);
    setErroSugestoes("");
    setMensagemSugestoes(
      isAdmin
        ? "Nenhuma oferta panoramica atendeu. Registre o motivo e conceda excecao para liberar data/hora manual."
        : "Nenhuma oferta panoramica atendeu. Registre o motivo e solicite excecao ao administrador."
    );
  };

  const liberarFluxoRetroativoAdmin = () => {
    if (!isAdmin) {
      setErroSugestoes("Apenas administradores podem registrar agendamento retroativo.");
      return;
    }
    if (!ofertasPanoramicasConsultadas) {
      setErroSugestoes("Gere as ofertas primeiro para registrar a tentativa do assistente.");
      return;
    }
    if (!isDataPassada(formData.data)) {
      setErroSugestoes("Fluxo retroativo disponivel apenas para datas passadas.");
      return;
    }
    setDecisaoAssistente("sem_opcao");
    setExcecaoConcedida(true);
    if (!(motivoSemOpcao || "").trim()) {
      setMotivoSemOpcao("Registro retroativo: atendimento realizado e lancado apos a data original.");
    }
    setErroSugestoes("");
    setMensagemSugestoes(
      "Modo retroativo liberado por admin. Revise data/hora, confirme o motivo e salve o agendamento."
    );
  };

  const registrarDesfechoSemAgendamento = async (
    tipo: "solicitacao_excecao" | "encerramento_sem_agendamento"
  ) => {
    const motivo = String(motivoSemOpcao || "").trim();
    if (!motivo) {
      setErroSugestoes("Registre o motivo antes de concluir sem agendamento.");
      return;
    }

    try {
      setRegistrandoEncerramento(true);
      const clinicaId = Number.parseInt(formData.clinica_id || "", 10);
      const tutorId = Number.parseInt(formData.tutor_id || "", 10);
      const servicoId = Number.parseInt(formData.servico_id || "", 10);
      await api.post("/agenda/assistente/encerramento", {
        tipo,
        motivo,
        origem_atendimento: formData.origem_atendimento,
        clinica_id: atendimentoDomiciliar ? null : (Number.isFinite(clinicaId) ? clinicaId : null),
        tutor_id: atendimentoDomiciliar && Number.isFinite(tutorId) ? tutorId : null,
        servico_id: Number.isFinite(servicoId) ? servicoId : null,
        data_referencia: String(formData.data || "").trim() || null,
        data_contato: String(dataContatoAssistente || "").trim() || null,
        contexto: {
          total_sugestoes: totalSugestoes,
          indice_sugestao_atual: indiceSugestaoAtual + 1,
          decisao_assistente: decisaoAssistente,
          destino_operacional: destinoOperacionalAtualLabel,
          perfil: isAdmin ? "admin" : "nao_admin",
        },
      });

      fortinho.notify({
        title: tipo === "solicitacao_excecao" ? "Solicitacao registrada" : "Encerramento registrado",
        message:
          tipo === "solicitacao_excecao"
            ? "Solicitacao de excecao enviada para administracao. Atendimento encerrado sem agendamento."
            : "Atendimento encerrado sem agendamento com motivo registrado.",
        mood: "happy",
        gesture: "wave",
      });
      onClose();
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? error?.message;
      setErroSugestoes(extrairMensagemErro(detail, "Nao foi possivel registrar este desfecho agora."));
    } finally {
      setRegistrandoEncerramento(false);
    }
  };

  const abrirExcecaoAdmin = () => {
    if (!isAdmin || isEditando) return;
    resetFluxoAssistente(false);
    setDecisaoAssistente("sem_opcao");
  };

  const concederExcecaoAdmin = () => {
    if (!isAdmin) {
      setErroSugestoes("Apenas administradores podem conceder excecao de horario.");
      return;
    }
    if (!(motivoSemOpcao || "").trim()) {
      setErroSugestoes("Registre o motivo antes de conceder excecao.");
      return;
    }
    setExcecaoConcedida(true);
    setMensagemSugestoes(
      "Excecao concedida por admin. Ajuste data/hora manualmente e conclua o agendamento."
    );
    setErroSugestoes("");
  };

  const revogarExcecaoAdmin = () => {
    setExcecaoConcedida(false);
    setMensagemSugestoes(
      "Excecao revogada. O fluxo voltou para bloqueio de data/hora manual."
    );
  };

  const extrairHoraDataHora = (value: string): string => {
    const [, hora] = String(value || "").split(" ");
    return hora || value;
  };

  const buscarSugestoesHorario = async () => {
    if (preferenciaResolvida.erro) {
      setErroSugestoes(preferenciaResolvida.erro);
      return;
    }
    const consultaId = ++sequenciaConsultaOfertasRef.current;
    setDecisaoAssistente("pendente");
    setMotivoSemOpcao("");
    setExcecaoConcedida(false);
    setMensagemSugestoes("");
    setErroSugestoes("");
    setErroSalvamento("");
    setIndiceOfertaEmValidacao(null);
    setSugestoesHorario([]);
    setOfertasPanoramicasConsultadas(false);

    const clinicaId = Number.parseInt(formData.clinica_id || "", 10);
    const tutorId = Number.parseInt(formData.tutor_id || "", 10);
    if (atendimentoDomiciliar) {
      if (!Number.isFinite(tutorId)) {
        setErroSugestoes("Selecione um tutor georreferenciado para sugerir horarios.");
        return;
      }
      if (!tutorSelecionadoGeorreferenciado) {
        setErroSugestoes("Georreferencie o tutor selecionado antes de gerar sugestoes de horario.");
        return;
      }
    } else {
      if (!Number.isFinite(clinicaId)) {
        setErroSugestoes("Selecione uma clinica cadastrada para sugerir horarios.");
        return;
      }
      const clinicaAtual = clinicas.find((item) => item.id === clinicaId) || null;
      if (!clinicaTemGeorreferenciamento(clinicaAtual)) {
        setErroSugestoes("Georreferencie a clinica selecionada antes de gerar sugestoes de horario.");
        return;
      }
    }
    if (!formData.servico_id) {
      setErroSugestoes("Selecione o servico para sugerir horarios operacionais com duracao correta.");
      return;
    }

    const dataSelecionada = String(formData.data || "").trim();

    try {
      setCarregandoSugestoes(true);
      const dataContato = !isEditando ? (dataContatoAssistente || hojeLocalIso()) : undefined;
      const response = await api.post<AssistenteOfertaResponse>("/agenda/assistente/ofertas", {
        origem_atendimento: formData.origem_atendimento,
        clinica_id: atendimentoDomiciliar ? null : clinicaId,
        tutor_id: atendimentoDomiciliar ? tutorId : null,
        data: dataSelecionada || null,
        data_contato: dataContato,
        servico_id: formData.servico_id ? parseInt(formData.servico_id, 10) : null,
        duracao_minutos: obterDuracaoServicoSelecionado(),
        intervalo_minutos: intervaloSugestaoMinutos,
        preferencia: preferenciaResolvida.preferencia,
        limite: 8,
        perfil_deslocamento: "comercial",
        limite_minutos: LIMITE_MINUTOS_PROXIMIDADE,
        ignorar_agendamento_id: isEditando ? agendamento?.id : null,
      });

      if (consultaId !== sequenciaConsultaOfertasRef.current) return;

      const dados = response?.data || null;
      const panorama = dados?.panorama_ofertas || null;
      const items = Array.isArray(panorama?.items) ? panorama.items : [];
      const motivo = String(panorama?.motivo || "").trim();
      const itensIgnorados = Number(panorama?.itens_ignorados_janela || 0);
      setItensIgnoradosJanela(itensIgnorados);
      setSugestoesHorario(items);
      setOfertasPanoramicasConsultadas(true);
      setIndiceSugestaoAtual(0);
      setDecisaoAssistente("pendente");
      setMotivoSemOpcao("");
      if (dados?.sugestao_proximidade) {
        setSugestaoProximidade(dados.sugestao_proximidade);
      }

      const mensagemOrquestrada = String(dados?.mensagem_panorama || "").trim();
      if (items.length === 0) {
        setDecisaoAssistente("pendente");
        setMensagemSugestoes(
          mensagemOrquestrada ||
            motivo ||
            "Nenhum horario operacional encontrado para essa data. Ajuste os filtros e gere novas ofertas antes de registrar recusa."
        );
      } else if (items.every((item) => !item.anterior && !item.proximo)) {
        setMensagemSugestoes(
          mensagemOrquestrada ||
            "Nao ha agendamentos vizinhos nesta data; por isso o deslocamento pode aparecer como 0 min."
        );
      } else if (mensagemOrquestrada) {
        setMensagemSugestoes(mensagemOrquestrada);
      }
    } catch (error: any) {
      if (consultaId !== sequenciaConsultaOfertasRef.current) return;
      const detail = error?.response?.data?.detail;
      setErroSugestoes(typeof detail === "string" ? detail : "Falha ao buscar sugestoes de horario.");
    } finally {
      if (consultaId === sequenciaConsultaOfertasRef.current) setCarregandoSugestoes(false);
    }
  };

  const extrairMensagemErro = (detail: any, fallback = "Falha inesperada."): string => {
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail && typeof detail === "object") {
      if (typeof detail.mensagem === "string" && detail.mensagem.trim()) return detail.mensagem;
      if (typeof detail.message === "string" && detail.message.trim()) return detail.message;
      if (typeof detail.detail === "string" && detail.detail.trim()) return detail.detail;
    }
    return fallback;
  };

  const extrairConflitoDeslocamento = (error: any): ConflitoDeslocamentoDetail | null => {
    if (error?.response?.status !== 409) return null;
    const detail = error?.response?.data?.detail;
    if (
      detail && typeof detail === "object" &&
      ["CONFLITO_DESLOCAMENTO", "PRIMEIRA_SAIDA_INVIAVEL"].includes(detail.codigo)
    ) {
      return detail as ConflitoDeslocamentoDetail;
    }

    const detailStr = String(detail || "");
    if (detailStr.toLowerCase().includes("deslocamento")) {
      return { mensagem: detailStr, confirmavel: false };
    }
    return null;
  };

  const extrairReservaExpirada = (error: any): ReservaExpiradaDetail | null => {
    if (error?.response?.status !== 409) return null;
    const detail = error?.response?.data?.detail;
    if (
      detail &&
      typeof detail === "object" &&
      [
        "CONFIRMACAO_SLOT_RESERVA_EXPIRADA",
        "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA",
      ].includes(detail.codigo)
    ) {
      return detail as ReservaExpiradaDetail;
    }
    return null;
  };

  const confirmarRevisaoReservaExpirada = async (
    detail: ReservaExpiradaDetail
  ): Promise<boolean> => {
    const reativandoMesmaReserva =
      detail.codigo === "CONFIRMACAO_REATIVACAO_RESERVA_EXPIRADA";
    const reserva = detail.reservas_expiradas?.[0];
    const contexto = reserva
      ? [
          `Clínica: ${reserva.clinica || "Pendente"}`,
          `Tutor: ${reserva.tutor || "Pendente"}`,
          `Pet: ${reserva.paciente || "Pendente"}`,
        ].join("\n")
      : "";

    return fortinho.confirm({
      title: reativandoMesmaReserva
        ? "Confirmação recebida após o prazo"
        : "ATENÇÃO: este horário teve uma reserva expirada",
      message:
        `${extrairMensagemErro(
          detail,
          "Este horário já teve uma reserva que expirou."
        )}` +
        `${contexto ? `\n\n${contexto}` : ""}` +
        (reativandoMesmaReserva
          ? "\n\nConfirme somente se este mesmo cliente respondeu depois do vencimento. O sistema verificará novamente se o horário continua livre antes de agendar."
          : "\n\nAntes de agendar outra pessoa, volte às mensagens do WhatsApp e confira se a clínica enviou os dados após o prazo. Só continue se não houver resposta."),
      mood: "alert",
      gesture: "open-arms",
      confirmLabel: reativandoMesmaReserva
        ? "Cliente confirmou; verificar e agendar"
        : "Revisei as mensagens e quero agendar",
      cancelLabel: reativandoMesmaReserva ? "Cancelar" : "Voltar e verificar WhatsApp",
    });
  };

  const motivoAgendaFechadaConfirmavel = (motivo?: string | null): boolean => {
    const texto = String(motivo || "").trim();
    return [
      "Agenda fechada",
      "Horario fora do funcionamento da agenda",
      "Horario fora da excecao desta data",
    ].some((prefixo) => texto.startsWith(prefixo));
  };

  const confirmarAgendamentoAgendaFechadaAdmin = async (motivo: string): Promise<boolean> =>
    fortinho.confirm({
      title: "Agenda fechada",
      message:
        `${motivo}\n\nEste agendamento ficará fora do horário de funcionamento. ` +
        "A confirmação não altera a configuração da agenda e ficará registrada na auditoria. Deseja continuar?",
      mood: "alert",
      gesture: "open-arms",
      confirmLabel: "Confirmar agendamento",
      cancelLabel: "Voltar",
    });

  const confirmarExcecaoConflitoAdmin = async (conflito: ConflitoDeslocamentoDetail): Promise<boolean> => {
    if (!isAdmin) return false;

    const mensagemConflito = extrairMensagemErro(
      conflito,
      "Conflito operacional de deslocamento detectado para este horario."
    );
    return fortinho.confirm({
      title: "Conflito operacional",
      message:
        `${mensagemConflito}\n\nComo admin, deseja conceder excecao para concluir o agendamento neste horario?`,
      mood: "alert",
      gesture: "open-arms",
      confirmLabel: "Conceder excecao",
      cancelLabel: "Cancelar",
    });
  };

  const abrirModalTutor = () => {
    if (tutorPanorama?.tutor) {
      preencherModalTutor(tutorPanorama.tutor);
    } else {
      setNovoTutor({ ...buildInitialTutorForm(), origem_cadastro: clinicas.find((c) => String(c.id) === formData.clinica_id)?.nome || "" });
      setStatusEnderecoTutor("");
      setConsultandoCepTutor(false);
      ultimoCepConsultadoTutorRef.current = "";
      consultaCepTutorSequenciaRef.current += 1;
    }
    setModalTutorAberto(true);
  };

  const abrirModalAnimal = () => {
    setNovoAnimal(buildInitialAnimalForm(formData.tutor_id));
    setNovaRaca("");
    setGestaoRacasAberta(false);
    setRacaEmEdicaoId("");
    setNomeRacaEmEdicao("");
    setModalAnimalAberto(true);
  };

  const nomesDeRacaIguais = (primeira: string, segunda: string): boolean =>
    primeira.localeCompare(segunda, "pt-BR", { sensitivity: "base" }) === 0;

  const cadastrarRacaAnimal = () => {
    const nome = novaRaca.trim();
    if (!nome) return;

    const racaExistente = racasCatalogo.find((raca) => nomesDeRacaIguais(raca.nome, nome));
    if (racaExistente) {
      setNovoAnimal((prev) => ({ ...prev, raca: racaExistente.nome }));
      setNovaRaca("");
      fortinho.notify({
        title: "Raça já cadastrada",
        message: `${racaExistente.nome} já está disponível para ${novoAnimal.especie.toLowerCase()}.`,
        mood: "happy",
        gesture: "idle",
      });
      return;
    }

    setRacasCustomPorEspecie((prev) => addRacaCustomPorEspecie(prev, novoAnimal.especie, nome));
    setNovoAnimal((prev) => ({ ...prev, raca: nome }));
    setNovaRaca("");
  };

  const iniciarEdicaoRacaAnimal = () => {
    if (!racaSelecionadaNoCatalogo) return;
    setRacaEmEdicaoId(racaSelecionadaNoCatalogo.id);
    setNomeRacaEmEdicao(racaSelecionadaNoCatalogo.nome);
  };

  const salvarEdicaoRacaAnimal = () => {
    const nome = nomeRacaEmEdicao.trim();
    const racaEmEdicao = racasCatalogo.find((raca) => raca.id === racaEmEdicaoId);
    if (!nome || !racaEmEdicao) return;

    const duplicada = racasCatalogo.some(
      (raca) => raca.id !== racaEmEdicao.id && nomesDeRacaIguais(raca.nome, nome),
    );
    if (duplicada) {
      fortinho.notify({
        title: "Raça já cadastrada",
        message: "Escolha um nome diferente para a raça.",
        mood: "alert",
        gesture: "idle",
      });
      return;
    }

    const atualizado = editarRacaCatalogo(
      racasCustomPorEspecie,
      ajustesRacasPorEspecie,
      novoAnimal.especie,
      racaEmEdicao,
      nome,
    );
    setRacasCustomPorEspecie(atualizado.racasCustomPorEspecie);
    setAjustesRacasPorEspecie(atualizado.ajustesPorEspecie);
    setNovoAnimal((prev) => ({ ...prev, raca: nome }));
    setRacaEmEdicaoId("");
    setNomeRacaEmEdicao("");
  };

  const excluirRacaAnimal = async () => {
    if (!racaSelecionadaNoCatalogo) return;

    const confirmou = await fortinho.confirm({
      title: "Excluir raça do catálogo",
      message:
        `Deseja excluir ${racaSelecionadaNoCatalogo.nome} das opções de ${novoAnimal.especie.toLowerCase()}? ` +
        "Os animais já cadastrados não serão alterados.",
      mood: "alert",
      gesture: "idle",
      confirmLabel: "Excluir raça",
      cancelLabel: "Cancelar",
    });
    if (!confirmou) return;

    const atualizado = excluirRacaCatalogo(
      racasCustomPorEspecie,
      ajustesRacasPorEspecie,
      novoAnimal.especie,
      racaSelecionadaNoCatalogo,
    );
    setRacasCustomPorEspecie(atualizado.racasCustomPorEspecie);
    setAjustesRacasPorEspecie(atualizado.ajustesPorEspecie);
    setNovoAnimal((prev) => ({ ...prev, raca: "" }));
    setRacaEmEdicaoId("");
    setNomeRacaEmEdicao("");
  };

  const salvarNovoTutor = async () => {
    const nome = novoTutor.nome.trim();
    if (!nome) {
      fortinho.notify({
        title: "Cadastro de tutor",
        message: "Informe o nome do tutor.",
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
      return;
    }

    try {
      setSalvandoTutor(true);
      const payload = {
        nome,
        identificacao_pendente: novoTutor.identificacao_pendente,
        origem_cadastro: novoTutor.origem_cadastro,
        identificacao_observacoes: novoTutor.identificacao_observacoes,
        telefone: novoTutor.telefone || null,
        whatsapp: novoTutor.whatsapp || novoTutor.telefone || null,
        email: novoTutor.email || null,
        cpf: novoTutor.cpf || null,
        cep: novoTutor.cep || null,
        endereco: novoTutor.endereco || null,
        numero: novoTutor.numero || null,
        complemento: novoTutor.complemento || null,
        bairro: novoTutor.bairro || null,
        cidade: novoTutor.cidade || null,
        estado: novoTutor.estado || null,
        latitude: normalizarCoordenadaOpcional(novoTutor.latitude),
        longitude: normalizarCoordenadaOpcional(novoTutor.longitude),
        place_id: novoTutor.place_id || null,
        endereco_normalizado: novoTutor.endereco_normalizado || null,
      };
      const response = novoTutor.id
        ? await api.put(`/tutores/${novoTutor.id}`, payload)
        : await api.post("/tutores", { ...payload, chave_operacao: await chaveOperacaoTutor("agenda-tutor", payload) });

      const tutorId = response?.data?.id;
      const tutorNome = response?.data?.nome || nome;
      if (!tutorId) {
        throw new Error("Nao foi possivel salvar o tutor.");
      }
      concluirOperacaoTutor("agenda-tutor");

      setTutores((prev) => {
        const tutorNormalizado: TutorOption = {
          id: Number(tutorId),
          nome: tutorNome,
          identificacao_pendente: response.data.identificacao_pendente,
          origem_cadastro: response.data.origem_cadastro,
          telefone: novoTutor.telefone || null,
          email: novoTutor.email || null,
          cidade: novoTutor.cidade || null,
          endereco_resumo: resumoEnderecoTutor(novoTutor),
          latitude: normalizarCoordenadaOpcional(novoTutor.latitude),
          longitude: normalizarCoordenadaOpcional(novoTutor.longitude),
          georreferenciado: tutorTemGeorreferenciamento(novoTutor),
        };
        const restantes = prev.filter((item) => item.id !== Number(tutorId));
        return [...restantes, tutorNormalizado].sort((a, b) => a.nome.localeCompare(b.nome));
      });

      setFormData((prev) => ({
        ...prev,
        tutor_id: String(tutorId),
        paciente_id: "",
      }));
      setTutorSelecionado(tutorNome);
      setModalTutorAberto(false);
      setNovoTutor(buildInitialTutorForm());
      setStatusEnderecoTutor("");
      ultimoCepConsultadoTutorRef.current = "";
      consultaCepTutorSequenciaRef.current += 1;
      await carregarPanoramaTutor(String(tutorId));
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? error?.message;
      fortinho.notify({
        title: "Erro ao salvar tutor",
        message: extrairMensagemErro(detail),
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
    } finally {
      setSalvandoTutor(false);
    }
  };

  const salvarNovoAnimal = async () => {
    const nomeAnimal = novoAnimal.nome.trim();
    if (!nomeAnimal) {
      fortinho.notify({
        title: "Cadastro de animal",
        message: "Informe o nome do animal.",
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
      return;
    }

    const tutorId = Number.parseInt(novoAnimal.tutor_id || "", 10);
    if (!Number.isFinite(tutorId)) {
      fortinho.notify({
        title: "Cadastro de animal",
        message: "Selecione um tutor para cadastrar o animal.",
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
      return;
    }

    const tutor = tutores.find((item) => item.id === tutorId);
    if (!tutor?.nome) {
      fortinho.notify({
        title: "Cadastro de animal",
        message: "Tutor selecionado nao encontrado.",
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
      return;
    }

    const pesoInformado = (novoAnimal.peso_kg || "").trim().replace(",", ".");
    const pesoKg = pesoInformado ? Number.parseFloat(pesoInformado) : NaN;

    try {
      setSalvandoAnimal(true);
      const payload = {
        nome: nomeAnimal,
        tutor_id: tutor.id,
        especie: (novoAnimal.especie || "").trim() || null,
        raca: novoAnimal.raca || "",
        sexo: novoAnimal.sexo || null,
        peso_kg: Number.isFinite(pesoKg) ? pesoKg : null,
        ...patientAgePayload(novoAnimal),
        microchip: novoAnimal.microchip || "",
        observacoes: novoAnimal.observacoes || "Cadastro via modal de animal na agenda",
      };
      const response = await api.post("/pacientes", { ...payload,
        chave_operacao: await chaveOperacaoTutor("agenda-animal", payload) });

      const novoPacienteId = response?.data?.id;
      if (!novoPacienteId) {
        throw new Error("Nao foi possivel salvar o animal.");
      }
      concluirOperacaoTutor("agenda-animal");

      const pacienteCriado: PacienteOption = {
        id: Number(novoPacienteId),
        nome: response?.data?.nome || nomeAnimal,
        tutor: tutor.nome,
        tutor_id: tutor.id,
        especie: response?.data?.especie || novoAnimal.especie || "",
        raca: response?.data?.raca || novoAnimal.raca || "",
      };

      setPacientes((prev) => {
        const restantes = prev.filter((item) => item.id !== pacienteCriado.id);
        return [...restantes, pacienteCriado].sort((a, b) => a.nome.localeCompare(b.nome));
      });
      setFormData((prev) => ({
        ...prev,
        tutor_id: String(tutor.id),
        paciente_id: String(pacienteCriado.id),
      }));
      setTutorSelecionado(tutor.nome);
      setModalAnimalAberto(false);
      setNovoAnimal(buildInitialAnimalForm(String(tutor.id)));
      await carregarPanoramaTutor(String(tutor.id));
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? error?.message;
      fortinho.notify({
        title: "Erro ao salvar animal",
        message: extrairMensagemErro(detail),
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
    } finally {
      setSalvandoAnimal(false);
    }
  };

  const construirMensagemAgendaPosCriacao = (): MensagemAgendaPosCriacao => {
    const tipo = formData.marcar_como_reserva ? "reserva" : "agendamento";
    const destinatarioTipo = formData.reserva_destinatario_manual;
    const destinatarioId = destinatarioTipo === "clinica" ? formData.clinica_id : formData.tutor_id;
    const destinatarioNome = destinatarioTipo === "clinica"
      ? nomeClinicaReservaManual
      : nomeTutorReservaManual;
    const telefones = destinatarioTipo === "clinica"
      ? telefonesClinicaMensagem
      : (telefoneTutorReservaManual ? [telefoneTutorReservaManual] : []);
    const telefoneLembrado = lerUltimoWhatsappSelecionado(destinatarioTipo, destinatarioId);
    const telefoneSugerido = telefoneLembrado && telefones.includes(telefoneLembrado)
      ? telefoneLembrado
      : (telefones[0] || "");
    const pacienteNome = String(pacienteSelecionadoMensagem?.nome || "").trim();
    const servicoSelecionado = servicos.find((servico) => String(servico.id) === formData.servico_id);
    const nomeServicoSelecionado = normalizeAgendaWhatsAppServiceName(servicoSelecionado?.nome);
    const servicoNome = nomeServicoSelecionado || (
      formData.servico_id === String(agendamento?.servico_id)
        ? normalizeAgendaWhatsAppServiceName(agendamento?.servico)
        : ""
    );
    const dataLabel = formData.data
      ? formData.data.split("-").reverse().join("/")
      : "";
    const modeloSugerido: AgendaWhatsAppTemplateKey = tipo === "reserva"
      ? "reservation"
      : statusFormulario === "Cancelado"
        ? "appointmentCancellation"
        : isEditando
          ? "appointmentChange"
          : "appointmentReminderService";

    return {
      agendamentoId: isEditando && agendamento?.id ? Number(agendamento.id) : null,
      tipo,
      destinatarioTipo,
      destinatarioId,
      destinatarioNome,
      telefones,
      telefoneSugerido,
      prazoLabel: tipo === "reserva"
        ? formatarPrazoReserva(formData.reserva_prazo_confirmacao)
        : undefined,
      pacienteNome,
      servicoNome,
      dataLabel,
      horaLabel: formData.hora,
      modeloSugerido,
    };
  };

  const mensagemAgendaServicoInvalido = modeloAgendaSelecionado === "appointmentReminderService" &&
    !isValidAgendaWhatsAppServiceName(mensagemAgendaCriada?.servicoNome);

  const obterMensagemAgendaAtual = (): string => {
    if (!mensagemAgendaCriada || mensagemAgendaServicoInvalido) return "";
    const pacienteNomeOuPlaceholder = mensagemAgendaCriada.pacienteNome
      || (modeloAgendaSelecionado === "reservation" || modeloAgendaSelecionado === "appointmentMissingData"
        ? "seu pet"
        : "");
    const parameters = [
      mensagemAgendaCriada.destinatarioNome,
      pacienteNomeOuPlaceholder,
      mensagemAgendaCriada.dataLabel,
      mensagemAgendaCriada.horaLabel,
    ];
    if (modeloAgendaSelecionado === "reservation") {
      parameters.push(mensagemAgendaCriada.prazoLabel || "");
    } else if (modeloAgendaSelecionado === "appointmentReminderService") {
      parameters.push(mensagemAgendaCriada.servicoNome);
    }
    return renderAgendaWhatsAppTemplate(modeloAgendaSelecionado, parameters);
  };

  const abrirWhatsAppMensagemAgenda = () => {
    if (!mensagemAgendaCriada || mensagemAgendaServicoInvalido) return;
    const url = montarLinkWhatsAppReserva(whatsappMensagemSelecionado, obterMensagemAgendaAtual());
    window.open(url, "_blank", "noopener,noreferrer");
    salvarUltimoWhatsappSelecionado(
      mensagemAgendaCriada.destinatarioTipo,
      mensagemAgendaCriada.destinatarioId,
      whatsappMensagemSelecionado,
    );
    setFeedbackMensagemAgenda(
      whatsappMensagemSelecionado
        ? "WhatsApp aberto com o destinatario e a mensagem preenchidos. Revise e envie manualmente."
        : "WhatsApp aberto sem destinatario fixo. Selecione o contato, revise e envie manualmente."
    );
  };

  const copiarMensagemAgenda = async () => {
    if (!mensagemAgendaCriada || mensagemAgendaServicoInvalido) return;
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard indisponivel");
      }
      await navigator.clipboard.writeText(obterMensagemAgendaAtual());
      salvarUltimoWhatsappSelecionado(
        mensagemAgendaCriada.destinatarioTipo,
        mensagemAgendaCriada.destinatarioId,
        whatsappMensagemSelecionado,
      );
      setFeedbackMensagemAgenda("Mensagem copiada.");
    } catch (_error) {
      setFeedbackMensagemAgenda("Nao foi possivel copiar automaticamente. Selecione o texto e copie manualmente.");
    }
  };

  const enviarModeloAgendaPeloFortCordis = async () => {
    if (
      !mensagemAgendaCriada?.agendamentoId ||
      mensagemAgendaServicoInvalido ||
      !whatsappMensagemSelecionado ||
      envioAutomaticoStatus === "sending" ||
      envioAutomaticoStatus === "sent"
    ) {
      return;
    }

    if (!envioAutomaticoIdempotencyRef.current) {
      envioAutomaticoIdempotencyRef.current = typeof globalThis.crypto?.randomUUID === "function"
        ? globalThis.crypto.randomUUID()
        : `agenda-${modeloAgendaSelecionado}-${mensagemAgendaCriada.agendamentoId}-${Date.now()}`;
    }

    setEnvioAutomaticoStatus("sending");
    setFeedbackMensagemAgenda("Enviando o modelo aprovado pela Meta...");
    try {
      const endpoint = modeloAgendaSelecionado === "reservation"
        ? `/agenda/${mensagemAgendaCriada.agendamentoId}/whatsapp/reserva`
        : `/agenda/${mensagemAgendaCriada.agendamentoId}/whatsapp/modelo`;
      await api.post(endpoint, {
        destination: whatsappMensagemSelecionado,
        recipient_type: mensagemAgendaCriada.destinatarioTipo,
        idempotency_key: envioAutomaticoIdempotencyRef.current,
        ...(modeloAgendaSelecionado === "reservation"
          ? {}
          : { template_key: modeloAgendaSelecionado }),
      });
      salvarUltimoWhatsappSelecionado(
        mensagemAgendaCriada.destinatarioTipo,
        mensagemAgendaCriada.destinatarioId,
        whatsappMensagemSelecionado,
      );

      let avisoDadosPendentesEnviado = false;
      if (modeloAgendaSelecionado === "reservation") {
        try {
          await api.post(`/agenda/${mensagemAgendaCriada.agendamentoId}/whatsapp/modelo`, {
            destination: whatsappMensagemSelecionado,
            recipient_type: mensagemAgendaCriada.destinatarioTipo,
            idempotency_key: typeof globalThis.crypto?.randomUUID === "function"
              ? globalThis.crypto.randomUUID()
              : `agenda-appointmentMissingData-${mensagemAgendaCriada.agendamentoId}-${Date.now()}`,
            template_key: "appointmentMissingData",
          });
          avisoDadosPendentesEnviado = true;
        } catch {
          // A reserva em si ja foi enviada com sucesso; o aviso de dados
          // pendentes e um complemento, nao deve derrubar o feedback principal.
        }
      }

      setEnvioAutomaticoStatus("sent");
      setFeedbackMensagemAgenda(
        modeloAgendaSelecionado === "reservation"
          ? avisoDadosPendentesEnviado
            ? "Reserva enviada, junto com o aviso de dados pendentes do tutor/paciente. Os botões Confirmar e Solicitar alteração estão vinculados ao agendamento."
            : "Reserva enviada pelo FortCordis, mas não foi possível enviar o aviso de dados pendentes automaticamente. Os botões Confirmar e Solicitar alteração estão vinculados ao agendamento."
          : "Modelo enviado pelo FortCordis. As respostas chegarão à Caixa de Entrada do WhatsApp para acompanhamento da equipe."
      );
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? error?.message;
      setEnvioAutomaticoStatus("idle");
      setFeedbackMensagemAgenda(
        extrairMensagemErro(detail, "Nao foi possivel enviar automaticamente. Use Abrir WhatsApp como alternativa.")
      );
    }
  };

  const iniciarEdicaoWhatsappDestinatario = () => {
    if (formData.reserva_destinatario_manual === "clinica") {
      if (!clinicaSelecionada) return;
      setWhatsappsDestinatarioEdicao(
        prepararWhatsappsFormulario(
          clinicaSelecionada.whatsapps,
          clinicaSelecionada.telefone,
        ),
      );
    } else {
      if (!formData.tutor_id) return;
      setWhatsappsDestinatarioEdicao([
        telefoneTutorReservaManual
          ? formatarWhatsAppVisual(telefoneTutorReservaManual)
          : "",
      ]);
    }

    setEditandoWhatsappDestinatario(true);
  };

  const cancelarEdicaoWhatsappDestinatario = () => {
    setEditandoWhatsappDestinatario(false);
    setWhatsappsDestinatarioEdicao([""]);
  };

  const atualizarWhatsappDestinatarioEdicao = (indice: number, valor: string) => {
    setWhatsappsDestinatarioEdicao((atuais) =>
      atuais.map((item, itemIndice) =>
        itemIndice === indice ? formatarWhatsAppVisual(valor) : item,
      ),
    );
  };

  const adicionarWhatsappClinicaEdicao = () => {
    setWhatsappsDestinatarioEdicao((atuais) =>
      atuais.length >= 10 ? atuais : [...atuais, ""],
    );
  };

  const removerWhatsappClinicaEdicao = (indice: number) => {
    setWhatsappsDestinatarioEdicao((atuais) => {
      const restantes = atuais.filter((_, itemIndice) => itemIndice !== indice);
      return restantes.length > 0 ? restantes : [""];
    });
  };

  const salvarWhatsappDestinatario = async () => {
    const numerosNormalizados = normalizarWhatsappsParaApi(whatsappsDestinatarioEdicao);
    if (numerosNormalizados.length === 0) {
      fortinho.notify({
        title: "WhatsApp não informado",
        message: "Informe pelo menos um número de WhatsApp antes de salvar.",
        mood: "alert",
        gesture: "idle",
      });
      return;
    }

    setSalvandoWhatsappDestinatario(true);
    try {
      if (formData.reserva_destinatario_manual === "clinica") {
        const clinicaId = Number.parseInt(formData.clinica_id, 10);
        if (!Number.isFinite(clinicaId)) {
          throw new Error("Selecione uma clínica antes de editar o WhatsApp.");
        }

        const response = await api.put(`/clinicas/${clinicaId}/whatsapps`, {
          whatsapps: numerosNormalizados,
        });
        const clinicaAtualizada = response?.data as ClinicaOption;
        setClinicas((atuais) =>
          atuais.map((clinica) =>
            clinica.id === clinicaId
              ? { ...clinica, ...clinicaAtualizada }
              : clinica,
          ),
        );
      } else {
        const tutorId = Number.parseInt(formData.tutor_id, 10);
        if (!Number.isFinite(tutorId)) {
          throw new Error("Selecione um tutor antes de editar o WhatsApp.");
        }

        const whatsapp = numerosNormalizados[0];
        const response = await api.put(`/tutores/${tutorId}`, { whatsapp });
        const tutorAtualizado = response?.data as TutorOption;
        setTutores((atuais) =>
          atuais.map((tutor) =>
            tutor.id === tutorId
              ? { ...tutor, ...tutorAtualizado, whatsapp }
              : tutor,
          ),
        );
        setTutorPanorama((atual) =>
          atual && atual.tutor.id === tutorId
            ? { ...atual, tutor: { ...atual.tutor, whatsapp } }
            : atual,
        );
      }

      setEditandoWhatsappDestinatario(false);
      setWhatsappsDestinatarioEdicao([""]);
      fortinho.notify({
        title: "WhatsApp atualizado",
        message: "O contato foi salvo e já será usado nesta mensagem.",
        mood: "happy",
        gesture: "wave",
      });
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? error?.message;
      fortinho.notify({
        title: "Erro ao salvar WhatsApp",
        message: extrairMensagemErro(detail),
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
    } finally {
      setSalvandoWhatsappDestinatario(false);
    }
  };

  const divergenciasWhatsApp = pedidoWhatsApp ? divergenciasPedido(pedidoWhatsApp, pacienteSelecionadoMensagem?.nome || "", tutorSelecionadoOption?.nome || tutorSelecionado || "") : [];
  const chaveDivergencia = JSON.stringify([pedidoWhatsApp?.pedido_id, formData.paciente_id, formData.tutor_id, divergenciasWhatsApp]);
  const [divergenciaAceita, setDivergenciaAceita] = useState("");
  useEffect(() => { setDivergenciaAceita(""); }, [chaveDivergencia]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErroSalvamento("");
    if (!isEditando && divergenciasWhatsApp.length && divergenciaAceita !== chaveDivergencia) {
      fortinho.notify({ title: "Confira o pedido do WhatsApp", message: "Confirme a divergência de pet/tutor antes de salvar.", mood: "alert", gesture: "idle", sticky: true });
      return;
    }
    setLoading(true);

    try {
      if (!isEditando) {
        if (editandoWhatsappDestinatario) {
          throw new Error("Salve ou cancele a edição do WhatsApp antes de criar o agendamento.");
        }
        if (!formData.servico_id) {
          throw new Error(
            atendimentoDomiciliar
              ? "Selecione o servico antes de concluir o agendamento domiciliar."
              : "Selecione o servico antes de concluir o agendamento guiado."
          );
        }
        if (atendimentoDomiciliar) {
          if (!formData.tutor_id) {
            throw new Error("Selecione um tutor com endereco georreferenciado para o atendimento domiciliar.");
          }
          if (!tutorSelecionadoGeorreferenciado) {
            throw new Error("Georreferencie o endereco do tutor antes de salvar o atendimento domiciliar.");
          }
        } else {
          if (!formData.clinica_id) {
            throw new Error("Selecione uma clinica ja cadastrada para iniciar o assistente de agendamento.");
          }
          if (!clinicaSelecionadaGeorreferenciada) {
            throw new Error("Georreferencie a clinica selecionada na tela de Clinicas antes de continuar.");
          }
        }
        if (decisaoAssistente === "pendente") {
          throw new Error(
            "Conclua o assistente guiado: confirme aceite do cliente ou marque que nenhuma opcao atendeu."
          );
        }
        if (decisaoAssistente === "sem_opcao" && !(motivoSemOpcao || "").trim()) {
          throw new Error("Descreva o motivo da excecao para seguir com horario manual.");
        }
        if (decisaoAssistente === "sem_opcao" && (!isAdmin || !excecaoConcedida)) {
          if (isAdmin) {
            throw new Error("Conceda excecao de horario ou encerre sem agendamento antes de salvar.");
          }
          throw new Error(
            "Seu perfil nao pode liberar horario manual. Solicite excecao ao administrador ou encerre sem agendamento."
          );
        }
      }

      const inicio = new Date(`${formData.data}T${formData.hora}:00`);
      if (Number.isNaN(inicio.getTime())) {
        throw new Error("Data ou hora invalida.");
      }
      if (!isEditando) {
        if (formData.reserva_destinatario_manual === "clinica" && !formData.clinica_id) {
          throw new Error("Selecione uma clinica para preparar a mensagem manual.");
        }
        if (formData.reserva_destinatario_manual === "tutor" && !formData.tutor_id) {
          throw new Error("Selecione um tutor para preparar a mensagem manual.");
        }
      }
      if (!isEditando && formData.marcar_como_reserva) {
        const prazoHoras = Number(formData.reserva_prazo_horas);
        if (!Number.isFinite(prazoHoras) || prazoHoras < 0.5 || prazoHoras > 72) {
          throw new Error("Informe um prazo entre 0,5 e 72 horas para confirmação da reserva.");
        }
        const prazoConfirmacao = new Date(formData.reserva_prazo_confirmacao);
        if (Number.isNaN(prazoConfirmacao.getTime())) {
          throw new Error("Informe um prazo valido para confirmacao da reserva.");
        }
        if (prazoConfirmacao.getTime() <= Date.now()) {
          throw new Error("O prazo de confirmacao da reserva deve estar no futuro.");
        }
        if (prazoConfirmacao.getTime() >= inicio.getTime()) {
          throw new Error("O prazo de confirmacao deve ser anterior ao horario reservado.");
        }
      }

      const duracaoEfetiva = obterDuracaoServicoSelecionado();
      const fim = new Date(inicio.getTime() + duracaoEfetiva * 60000);

      const validacaoHorario = validarHorarioAgendamento(
        inicio,
        fim,
        agendaSemanal,
        agendaFeriados,
        agendaExcecoes
      );
      let confirmarAgendaFechada = false;
      if (!validacaoHorario.valido) {
        const motivo = validacaoHorario.motivo || "Agenda fechada para este horario.";
        const inicioOriginal = isEditando ? parseAgendamentoInicio(agendamento) : null;
        const fimOriginal = isEditando && agendamento?.fim
          ? new Date(String(agendamento.fim).replace(" ", "T")) : null;
        const excecaoExistente = Boolean(
          isEditando && agendamento?.excecao_agenda_fechada_ativa &&
          inicioOriginal?.getTime() === inicio.getTime() &&
          fimOriginal?.getTime() === fim.getTime()
        );
        if (!excecaoExistente) {
          if (!isAdmin || !motivoAgendaFechadaConfirmavel(motivo)) {
            throw new Error(motivo);
          }
          const confirmou = await confirmarAgendamentoAgendaFechadaAdmin(motivo);
          if (!confirmou) return;
          confirmarAgendaFechada = true;
        }
      }

      let pacienteId = formData.paciente_id ? parseInt(formData.paciente_id, 10) : NaN;
      let tutorId = formData.tutor_id ? parseInt(formData.tutor_id, 10) : NaN;

      if (!Number.isFinite(pacienteId) && !permiteSemPacienteTutor) {
        if (formData.tutor_id) {
          throw new Error("Selecione um animal do tutor escolhido ou cadastre um novo animal.");
        }
        throw new Error("Selecione um animal para o agendamento.");
      }

      let clinicaId = formData.clinica_id ? parseInt(formData.clinica_id, 10) : NaN;
      if (atendimentoDomiciliar) {
        clinicaId = NaN;
        if (!Number.isFinite(tutorId)) {
          throw new Error("Selecione um tutor antes de salvar o atendimento domiciliar.");
        }
        if (!tutorSelecionadoGeorreferenciado) {
          throw new Error("Georreferencie o endereco do tutor antes de salvar o atendimento domiciliar.");
        }
      } else {
        if (!Number.isFinite(clinicaId)) {
          throw new Error("Selecione uma clinica ja cadastrada antes de salvar o agendamento.");
        }
        if (!clinicaSelecionadaGeorreferenciada) {
          throw new Error("Georreferencie a clinica selecionada na tela de Clinicas antes de salvar o agendamento.");
        }
      }

      const entregaMensagemAgenda = construirMensagemAgendaPosCriacao();

      const observacoesOriginais = String(formData.observacoes || "").trim();
      const observacoesAssistente: string[] = [];
      if (!isEditando) {
        if (decisaoAssistente === "aceito") {
          const sugestaoAceita = sugestoesHorario[indiceSugestaoAtual];
          observacoesAssistente.push(
            `[Assistente agenda] sugestao aceita (${indiceSugestaoAtual + 1}/${Math.max(1, sugestoesHorario.length)})`
          );
          if (sugestaoAceita?.inicio) {
            observacoesAssistente.push(
              `[Assistente agenda] horario ofertado: ${String(sugestaoAceita.inicio)}`
            );
          }
        } else if (decisaoAssistente === "sem_opcao") {
          observacoesAssistente.push("[Assistente agenda] horario manual solicitado.");
          observacoesAssistente.push(
            `[Assistente agenda] motivo informado: ${String(motivoSemOpcao || "").trim()}`
          );
          if (isAdmin && excecaoConcedida) {
            observacoesAssistente.push("[Assistente agenda] excecao manual concedida por admin.");
          }
        }
        if (entregaMensagemAgenda?.tipo === "reserva") {
          observacoesAssistente.push(
            `[Reserva manual] prazo de confirmacao: ${entregaMensagemAgenda.prazoLabel}`
          );
          observacoesAssistente.push(
            `[Reserva manual] destinatario: ${entregaMensagemAgenda.destinatarioTipo}`
          );
        }
      }
      const observacoesFinal = [observacoesOriginais, ...observacoesAssistente]
        .filter((item) => String(item || "").trim().length > 0)
        .join("\n");

      const payloadBase = {
        paciente_id: Number.isFinite(pacienteId) ? pacienteId : null,
        tutor_id: Number.isFinite(tutorId) ? tutorId : null,
        clinica_id: Number.isFinite(clinicaId) ? clinicaId : null,
        servico_id: formData.servico_id ? parseInt(formData.servico_id, 10) : null,
        origem_atendimento: formData.origem_atendimento,
        inicio: toApiDateTime(inicio),
        fim: toApiDateTime(fim),
        status: statusFormulario,
        reserva_expira_em: formData.marcar_como_reserva
          ? toApiDateTime(new Date(formData.reserva_prazo_confirmacao))
          : null,
        observacoes: observacoesFinal,
        excecao_operacional_concedida:
          !isEditando && decisaoAssistente === "sem_opcao" && isAdmin && excecaoConcedida,
        motivo_excecao_operacional:
          !isEditando && decisaoAssistente === "sem_opcao" && isAdmin && excecaoConcedida
            ? String(motivoSemOpcao || "").trim()
            : null,
        confirmar_alteracao_servico_hoje: false,
      };

      const servicoOriginalId = String(agendamento?.servico_id ?? "");
      const dataOriginalAgendamento = String(
        agendamento?.data || String(agendamento?.inicio || "").slice(0, 10)
      );
      const horaOriginalAgendamento = String(
        agendamento?.hora || String(agendamento?.inicio || "").slice(11, 16)
      );
      const inicioOriginalIso =
        dataOriginalAgendamento && horaOriginalAgendamento
          ? `${dataOriginalAgendamento}T${horaOriginalAgendamento.padEnd(8, ":00")}`
          : null;
      const atendimentoJaIniciado =
        !!inicioOriginalIso && inicioOriginalIso <= agoraFortalezaIso();
      const alterandoServicoDeHoje =
        isEditando &&
        servicoOriginalId !== String(formData.servico_id || "") &&
        atendimentoJaIniciado;

      if (alterandoServicoDeHoje) {
        if (!isAdmin) {
          throw new Error(
            "Somente administradores podem alterar o servico de um atendimento ja iniciado."
          );
        }
        const confirmouAlteracao = await fortinho.confirm({
          title: "Confirmar alteração do serviço",
          message:
            "Este atendimento já foi iniciado. Deseja confirmar a troca administrativa do serviço? O horário original será preservado.",
          mood: "alert",
          gesture: "open-arms",
          confirmLabel: "Confirmar alteração",
          cancelLabel: "Voltar",
        });
        if (!confirmouAlteracao) {
          return;
        }
        payloadBase.confirmar_alteracao_servico_hoje = true;
      }

      const enviarAgendamento = async (
        confirmarConflitoDeslocamento = false,
        confirmarSlotReservaExpirada = false,
        escopoSobreposicaoConfirmado: string | null = null
      ) => {
        const payload: typeof payloadBase & {
          confirmar_conflito_deslocamento: boolean;
          confirmar_slot_reserva_expirada: boolean;
          confirmar_agenda_fechada?: boolean;
          confirmar_sobreposicao: boolean;
          escopo_sobreposicao_confirmado: string | null;
          motivo_excecao_sobreposicao: string | null;
        } = {
          ...payloadBase,
          confirmar_conflito_deslocamento: confirmarConflitoDeslocamento,
          confirmar_slot_reserva_expirada: confirmarSlotReservaExpirada,
          confirmar_sobreposicao: Boolean(escopoSobreposicaoConfirmado),
          escopo_sobreposicao_confirmado: escopoSobreposicaoConfirmado,
          motivo_excecao_sobreposicao: escopoSobreposicaoConfirmado
            ? motivoSemOpcao.trim() || "Sobreposição exibida e autorizada explicitamente pelo administrador."
            : null,
        };
        if (confirmarAgendaFechada) {
          payload.confirmar_agenda_fechada = true;
        }
        if (isEditando) {
          return api.put(`/agenda/${agendamento.id}`, payload);
        }
        return api.post("/agenda", { ...payload, ...(pedidoWhatsApp ? {
          pedido_whatsapp_id: pedidoWhatsApp.pedido_id, pedido_whatsapp_versao: pedidoWhatsApp.versao,
          pedido_whatsapp_divergencia_confirmada: divergenciasWhatsApp.length > 0 && divergenciaAceita === chaveDivergencia,
        } : {}) });
      };

      let response;
      let confirmouConflitoDeslocamento = excecaoManualAtiva;
      let confirmouRevisaoReservaExpirada = false;
      let escopoSobreposicaoConfirmado: string | null = null;
      for (let tentativa = 0; tentativa < 5 && !response; tentativa += 1) {
        try {
          response = await enviarAgendamento(
            confirmouConflitoDeslocamento,
            confirmouRevisaoReservaExpirada,
            escopoSobreposicaoConfirmado
          );
          continue;
        } catch (error: any) {
          const sobreposicao = error?.response?.data?.detail;
          if (error?.response?.status === 409 && sobreposicao?.codigo === "CONFLITO_SOBREPOSICAO_AGENDA") {
            if (!isAdmin || typeof sobreposicao.escopo !== "string") throw error;
            const confirmou = await fortinho.confirm({
              title: "Autorizar sobreposição de horários",
              message: `${sobreposicao.mensagem}\n\nDeseja manter este horário mesmo com a sobreposição? A autorização ficará registrada neste agendamento.`,
              mood: "alert",
              gesture: "open-arms",
              confirmLabel: "Autorizar sobreposição",
              cancelLabel: "Voltar",
            });
            if (!confirmou) return;
            escopoSobreposicaoConfirmado = sobreposicao.escopo;
            continue;
          }
          const reservaExpirada = extrairReservaExpirada(error);
          if (reservaExpirada && !confirmouRevisaoReservaExpirada) {
            const confirmou = await confirmarRevisaoReservaExpirada(reservaExpirada);
            if (!confirmou) {
              return;
            }
            confirmouRevisaoReservaExpirada = true;
            continue;
          }

        const conflito = extrairConflitoDeslocamento(error);
        if (conflito) {
          if (!isAdmin || confirmouConflitoDeslocamento) {
            throw error;
          }

          const confirmouExcecao = await confirmarExcecaoConflitoAdmin(conflito);
          if (!confirmouExcecao) {
            throw error;
          }
          confirmouConflitoDeslocamento = true;
          continue;
        } else {
          throw error;
        }
        }
      }

      if (!response) {
        throw new Error(
          "Não foi possível concluir o agendamento após as confirmações. Revise o horário e tente novamente."
        );
      }

      // Ao completar uma reserva expirada, volte para a Agenda: a proxima acao
      // obrigatoria e a confirmacao tardia, nao o envio de uma mensagem de alteracao.
      if (entregaMensagemAgenda && !editandoReservaExpirada) {
        setMensagemAgendaCriada({
          ...entregaMensagemAgenda,
          agendamentoId: Number(response?.data?.id) || null,
          servicoNome: entregaMensagemAgenda.servicoNome || (
            String(response?.data?.servico_id) === formData.servico_id
              ? normalizeAgendaWhatsAppServiceName(response?.data?.servico)
              : ""
          ),
        });
        setWhatsappMensagemSelecionado(entregaMensagemAgenda.telefoneSugerido);
        setModeloAgendaSelecionado(entregaMensagemAgenda.modeloSugerido);
        setFeedbackMensagemAgenda("");
        setEnvioAutomaticoStatus("idle");
        envioAutomaticoIdempotencyRef.current = "";
        await onSuccess(response?.data, { manterModalAberto: true });
        return;
      }
      await onSuccess(response?.data);
      if (
        editandoReservaExpirada &&
        Number.isFinite(pacienteId) &&
        Number.isFinite(tutorId)
      ) {
        fortinho.notify({
          title: "Dados da reserva atualizados",
          message:
            "Tutor e animal foram vinculados. Agora use 'Agendar após confirmação tardia' na Agenda para concluir.",
          mood: "happy",
          gesture: "point-right",
          sticky: true,
        });
      }
      onClose();
      setFormData(buildInitialFormData(defaultDate, defaultTime));
      setTutorSelecionado("");
      setSugestoesHorario([]);
      setOfertasPanoramicasConsultadas(false);
      setIndiceSugestaoAtual(0);
      setDecisaoAssistente("pendente");
      setMotivoSemOpcao("");
      setExcecaoConcedida(false);
      setRegistrandoEncerramento(false);
      setItensIgnoradosJanela(0);
      setErroSugestoes("");
      setMensagemSugestoes("");
      setMensagemProximidade("");
      setSugestaoProximidade(null);
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? error?.message;
      const detailStr = extrairMensagemErro(detail);
      const ofertaInviavel = error?.response?.status === 409 && detail?.codigo === "PRIMEIRA_SAIDA_INVIAVEL";
      if (ofertaInviavel && !isEditando) {
        resetFluxoAssistente();
        setFormData((prev) => ({ ...prev, hora: "" }));
      }
      setErroSalvamento(ofertaInviavel ? `${detailStr} Gere novas ofertas e confirme outro horario.` : detailStr);
      fortinho.notify({
        title: `Erro ao ${isEditando ? "editar" : "criar"} agendamento`,
        message: detailStr,
        mood: "alert",
        gesture: "idle",
        sticky: true,
      });
    } finally {
      setLoading(false);
    }
  };

  const destinoPrincipalInformado = atendimentoDomiciliar ? Boolean(formData.tutor_id) : Boolean(formData.clinica_id);
  const assistenteProntoParaSugerir =
    destinoPrincipalInformado &&
    (atendimentoDomiciliar ? tutorSelecionadoGeorreferenciado : clinicaSelecionadaGeorreferenciada) &&
    Boolean(formData.servico_id) &&
    Boolean(formData.data);
  const tituloAssistente = isEditando ? "Sugerir horarios operacionais" : "Assistente guiado de agendamento";
  const descricaoAssistente = isEditando
    ? "Considera conflitos de agenda e tempo de deslocamento usando o destino operacional georreferenciado."
    : excecaoManualAtiva
      ? "Exceção administrativa ativa. Revise o horário manual e o motivo antes de salvar."
      : isAdmin
        ? "Gere ofertas para o cliente ou use a exceção administrativa para escolher um horário manual."
        : atendimentoDomiciliar
          ? "Fluxo obrigatorio: selecionar tutor georreferenciado/servico, oferecer sugestao, registrar aceite ou recusa do cliente."
          : "Fluxo obrigatorio: selecionar clinica georreferenciada/servico, oferecer sugestao, registrar aceite ou recusa do cliente.";
  const rotuloBotaoAssistente = carregandoSugestoes
    ? "Buscando..."
    : (isEditando ? "Sugerir horarios" : "Gerar melhor oferta");
  const totalSugestoes = sugestoesHorario.length;
  const indiceEtapaWizardNovo = resolverIndiceEtapaWizardNovo(
    assistenteProntoParaSugerir,
    decisaoAssistente
  );
  const etapaWizardAtual = !isEditando ? ETAPAS_WIZARD_NOVO[indiceEtapaWizardNovo] : null;
  const bloqueioManualAssistenteAtivo = !isEditando && !excecaoManualAtiva;
  const bloquearDataManual = bloqueioManualAssistenteAtivo && assistenteProntoParaSugerir;
  const bloquearHoraManual = bloqueioManualAssistenteAtivo;
  const semOpcaoSemExcecao = !isEditando && decisaoAssistente === "sem_opcao" && !excecaoManualAtiva;
  const dataSelecionadaPassada = !isEditando && isDataPassada(formData.data);
  const clienteComCredito = !isEditando && saldoCreditoCliente > 0;
  const destinatarioMensagemNome = formData.reserva_destinatario_manual === "clinica"
    ? nomeClinicaReservaManual
    : nomeTutorReservaManual;
  const destinatarioMensagemTelefones = formData.reserva_destinatario_manual === "clinica"
    ? telefonesClinicaMensagem
    : (telefoneTutorReservaManual ? [telefoneTutorReservaManual] : []);
  const bloquearSalvarNovo =
    !isEditando &&
    (
      indiceOfertaEmValidacao !== null ||
      decisaoAssistente === "pendente" ||
      (decisaoAssistente === "sem_opcao" && (!(motivoSemOpcao || "").trim() || semOpcaoSemExcecao))
    );

  if (!isOpen) return null;

  if (mensagemAgendaCriada) {
    const possuiTelefone = Boolean(whatsappMensagemSelecionado);
    const ehReserva = mensagemAgendaCriada.tipo === "reserva";
    const destinatarioLabel = mensagemAgendaCriada.destinatarioTipo === "clinica" ? "Clínica" : "Tutor";
    const mensagemAgendaAtual = obterMensagemAgendaAtual();
    const modelosAgendaDisponiveis: AgendaWhatsAppTemplateKey[] =
      mensagemAgendaCriada.modeloSugerido === "appointmentCancellation"
        ? ["appointmentCancellation"]
        : ["appointmentReminderService", "appointmentReminder", "appointmentChange", "appointmentMissingData"];

    return (
      <div className="fc-appointment-modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="fc-mensagem-agenda-title"
        >
          <div className="flex items-center justify-between border-b border-emerald-100 bg-emerald-50 px-5 py-4">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
                <Check className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
                  {ehReserva ? "Reserva criada" : "Agendamento criado"}
                </div>
                <h2 id="fc-mensagem-agenda-title" className="truncate text-xl font-bold text-gray-900">
                  {ehReserva ? "Envie o prazo pelo WhatsApp" : "Avise que o horário foi agendado"}
                </h2>
              </div>
            </div>
            <button
              type="button"
              onClick={() => (isEditando ? setMensagemAgendaCriada(null) : onClose())}
              className="rounded-full p-2 text-gray-500 transition hover:bg-white hover:text-gray-700"
              aria-label="Fechar mensagem da agenda"
              title="Fechar"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="max-h-[75vh] space-y-4 overflow-y-auto p-5">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                <div className="text-xs font-medium uppercase tracking-wide text-gray-500">Destinatário</div>
                <div className="mt-1 text-sm font-semibold text-gray-900">
                  {destinatarioLabel}: {mensagemAgendaCriada.destinatarioNome || "não identificado"}
                </div>
                {mensagemAgendaCriada.telefones.length > 1 ? (
                  <div className="mt-2">
                    <label htmlFor="fc-whatsapp-destino" className="mb-1 block text-xs font-medium text-gray-600">
                      Escolha o WhatsApp
                    </label>
                    <select
                      id="fc-whatsapp-destino"
                      value={whatsappMensagemSelecionado}
                      onChange={(event) => {
                        setWhatsappMensagemSelecionado(event.target.value);
                        setEnvioAutomaticoStatus("idle");
                        envioAutomaticoIdempotencyRef.current = "";
                        setFeedbackMensagemAgenda("");
                      }}
                      className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200"
                    >
                      {mensagemAgendaCriada.telefones.map((telefone, indice) => (
                        <option key={`${telefone}-${indice}`} value={telefone}>
                          WhatsApp {indice + 1} — {formatarWhatsAppVisual(telefone)}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <div className="mt-0.5 text-xs text-gray-600">
                    {possuiTelefone ? formatarWhatsAppVisual(whatsappMensagemSelecionado) : "Sem WhatsApp cadastrado"}
                  </div>
                )}
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                <div className="text-xs font-medium uppercase tracking-wide text-gray-500">
                  {ehReserva ? "Prazo informado" : "Situação"}
                </div>
                <div className="mt-1 text-sm font-semibold text-gray-900">
                  {ehReserva ? mensagemAgendaCriada.prazoLabel : "Horário agendado"}
                </div>
              </div>
            </div>

            <div>
              {!ehReserva ? (
                <div className="mb-4">
                  <label htmlFor="fc-modelo-whatsapp-agenda" className="mb-1 block text-sm font-medium text-gray-700">
                    Modelo de mensagem
                  </label>
                  <select
                    id="fc-modelo-whatsapp-agenda"
                    value={modeloAgendaSelecionado}
                    onChange={(event) => {
                      setModeloAgendaSelecionado(event.target.value as AgendaWhatsAppTemplateKey);
                      setEnvioAutomaticoStatus("idle");
                      envioAutomaticoIdempotencyRef.current = "";
                      setFeedbackMensagemAgenda("");
                    }}
                    className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
                  >
                    {modelosAgendaDisponiveis.map((templateKey) => (
                      <option key={templateKey} value={templateKey}>
                        {AGENDA_WHATSAPP_TEMPLATES[templateKey].label}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              <label htmlFor="fc-mensagem-agenda" className="mb-1 block text-sm font-medium text-gray-700">
                Mensagem pronta
              </label>
              <textarea
                id="fc-mensagem-agenda"
                readOnly
                rows={12}
                value={mensagemAgendaAtual}
                onFocus={(event) => event.currentTarget.select()}
                className="w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm leading-6 text-gray-800 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200"
              />
              {mensagemAgendaServicoInvalido ? (
                <div role="alert" className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  Confira o serviço salvo no agendamento antes de preparar o lembrete com serviço. O nome deve ter até 300 caracteres.
                </div>
              ) : null}
            </div>

            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {ehReserva ? "A reserva já foi salva." : "O agendamento já foi salvo."} Enviar pelo FortCordis usa o
              modelo aprovado; Abrir WhatsApp e Copiar mensagem continuam disponíveis como alternativa manual.
            </div>

            {isEditando ? (
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
                Esta mensagem foi gerada com os dados atuais do formulário. Se você alterou paciente, tutor ou
                outro campo, clique em <strong>Salvar Alterações</strong> depois de voltar para confirmar.
              </div>
            ) : null}

            {!possuiTelefone ? (
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
                O WhatsApp será aberto sem destinatário. Escolha o contato correto antes de enviar.
              </div>
            ) : null}

            {feedbackMensagemAgenda ? (
              <div aria-live="polite" className="text-sm font-medium text-gray-700">
                {feedbackMensagemAgenda}
              </div>
            ) : null}
          </div>

          <div className="flex flex-col-reverse gap-2 border-t border-gray-200 bg-gray-50 px-5 py-4 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => (isEditando ? setMensagemAgendaCriada(null) : onClose())}
              className="fc-appointment-button-secondary"
            >
              {isEditando ? "Voltar ao formulário" : "Concluir"}
            </button>
            <button
              type="button"
              onClick={() => void copiarMensagemAgenda()}
              disabled={mensagemAgendaServicoInvalido}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-emerald-600 bg-white px-4 py-2 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Copy className="h-4 w-4" />
              Copiar mensagem
            </button>
            <button
              type="button"
              onClick={() => void enviarModeloAgendaPeloFortCordis()}
              disabled={mensagemAgendaServicoInvalido || !possuiTelefone || !mensagemAgendaCriada.agendamentoId || envioAutomaticoStatus !== "idle"}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {envioAutomaticoStatus === "sending" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : envioAutomaticoStatus === "sent" ? (
                <Check className="h-4 w-4" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {envioAutomaticoStatus === "sending"
                ? "Enviando..."
                : envioAutomaticoStatus === "sent"
                  ? "Enviado pelo FortCordis"
                  : "Enviar pelo FortCordis"}
            </button>
            <button
              type="button"
              onClick={abrirWhatsAppMensagemAgenda}
              disabled={mensagemAgendaServicoInvalido}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <MessageCircle className="h-4 w-4" />
              {possuiTelefone ? "Abrir WhatsApp" : "Abrir e escolher contato"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fc-appointment-modal-backdrop fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="fc-appointment-modal w-full"
        role="dialog"
        aria-modal="true"
        aria-labelledby="fc-appointment-modal-title"
      >
        <div className="fc-appointment-modal-header">
          <div className="flex min-w-0 items-center gap-3">
            <span className="fc-appointment-modal-icon" aria-hidden="true">
              <Calendar className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <span className="fc-appointment-modal-kicker">Central de agenda</span>
              <h2 id="fc-appointment-modal-title" className="truncate text-xl font-black">
                {isEditando ? "Editar Agendamento" : "Novo Agendamento"}
              </h2>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="fc-appointment-modal-close"
            aria-label="Fechar agendamento"
            title="Fechar"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {erroSalvamento && (
          <div role="alert" className="max-h-40 flex-none overflow-y-auto border-b border-red-300 bg-red-50 px-5 py-3 text-sm font-medium text-red-900">
            {erroSalvamento}
          </div>
        )}

        <form onSubmit={handleSubmit} className="fc-appointment-form space-y-4">
          {pedidoWhatsApp && !isEditando && <section className="rounded-lg border border-emerald-200 bg-emerald-50 p-3" aria-label="Pedido recebido pelo WhatsApp">
            <strong>Agendar pedido #{pedidoWhatsApp.pedido_id}</strong>
            <p className="whitespace-pre-line text-sm">{pedidoWhatsApp.resumo}</p>
            {divergenciasWhatsApp.length > 0 && <div role="alert" className="my-2 rounded border border-amber-500 p-3">
              <strong>Pet ou tutor diferente do informado no WhatsApp</strong>
              {divergenciasWhatsApp.map(texto => <p key={texto}>{texto}</p>)}
              <label><input type="checkbox" checked={divergenciaAceita === chaveDivergencia} onChange={e => setDivergenciaAceita(e.target.checked ? chaveDivergencia : "")} /> Conferi a divergência e confirmo o agendamento com os cadastros selecionados.</label>
            </div>}
            {pedidoWhatsApp.avisos.map(aviso => <p key={aviso} className="text-sm text-amber-900">{aviso}</p>)}
            <p className="text-sm">Escolha e confira o horário. Ao salvar, o pedido será vinculado à agenda e a confirmação ficará disponível para revisão e envio.</p>
          </section>}
          {erroCarregamento && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {erroCarregamento}
            </div>
          )}

          {editandoReservaExpirada ? (
            <section
              aria-label="Como concluir a confirmação tardia"
              className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-950"
            >
              <strong>Como concluir a confirmação tardia</strong>
              <p className="mt-1">
                Busque e clique no tutor e no animal corretos, salve os dados da reserva e depois use
                <strong> Agendar após confirmação tardia</strong> na Agenda. Digitar um nome sem escolher o
                resultado não vincula o cadastro.
              </p>
            </section>
          ) : null}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Origem do atendimento</label>
            <div className="fc-appointment-origin grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => handleOrigemAtendimentoChange("clinica_parceira")}
                className={`fc-appointment-origin-option ${
                  !atendimentoDomiciliar
                    ? "fc-appointment-origin-option-active"
                    : ""
                }`}
              >
                Clinica parceira
              </button>
              <button
                type="button"
                disabled={Boolean(pedidoWhatsApp) && !isEditando}
                onClick={() => handleOrigemAtendimentoChange("domiciliar")}
                className={`fc-appointment-origin-option ${
                  atendimentoDomiciliar
                    ? "fc-appointment-origin-option-active"
                    : ""
                }`}
              >
                Domiciliar
              </button>
            </div>
            <div className="fc-appointment-context-note mt-2 rounded-lg border px-3 py-2 text-xs">
              {atendimentoDomiciliar
                ? "Use o endereco georreferenciado do tutor. Nao e necessario cadastrar uma clinica ficticia."
                : "Fluxo com clinica parceira, usando a clinica georreferenciada como base do assistente e da operacao."}
            </div>
          </div>

          {/* Tutor */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              <User className="w-4 h-4 inline mr-1" />
              Tutor {permiteSemPacienteTutor ? "(opcional para reserva)" : "*"}
            </label>
            <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2">
              <SearchableSelect
                value={formData.tutor_id}
                onChange={handleTutorChange}
                options={tutorOptions}
                placeholder="Selecione..."
                searchPlaceholder="Buscar tutor por nome ou telefone..."
                emptyText="Nenhum tutor encontrado."
                selectionHint="Digite para buscar e clique no tutor correto. O texto digitado sozinho não seleciona o cadastro."
                clearLabel="Selecione..."
                onSearchChange={setBuscaTutorRemota}
                isSearching={buscandoTutores}
                searchingText="Buscando tutores..."
              />
              <button
                type="button"
                onClick={abrirModalTutor}
                className="fc-appointment-inline-action"
              >
                {formData.tutor_id ? "Ver tutor" : "Novo tutor"}
              </button>
            </div>
            {!formData.tutor_id && !permiteSemPacienteTutor ? (
              <p className="mt-1 text-xs font-medium text-amber-800">
                Nenhum tutor cadastrado foi selecionado.
              </p>
            ) : null}
            {formData.tutor_id && (
              <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                {carregandoTutorPanorama ? (
                  <div className="text-sm text-slate-600">Carregando panorama do tutor...</div>
                ) : tutorPanorama?.tutor && String(tutorPanorama.tutor.id) === formData.tutor_id ? (
                  <div className="space-y-3">
                    <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">{tutorPanorama.tutor.nome}</div>
                        <div className="text-xs text-slate-600">
                          {[tutorPanorama.tutor.telefone, tutorPanorama.tutor.email].filter(Boolean).join(" - ") || "Contato ainda incompleto"}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          {resumoEnderecoTutor(tutorPanorama.tutor) || "Endereco do tutor ainda nao preenchido."}
                        </div>
                      </div>
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                          tutorTemGeorreferenciamento(tutorPanorama.tutor)
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {tutorTemGeorreferenciamento(tutorPanorama.tutor) ? "Endereco georreferenciado" : "Endereco pendente"}
                      </span>
                    </div>

                    <div className="rounded-md border border-slate-200 bg-white p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium text-slate-900">
                            Animais ativos vinculados: {petsAtivosDoTutor.length}
                          </div>
                          <div className="text-xs text-slate-500">
                            Selecione um pet existente ou cadastre outro a partir deste tutor.
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={abrirModalAnimal}
                          className="px-3 py-1.5 rounded-md border border-blue-200 text-blue-700 text-xs hover:bg-blue-50"
                        >
                          Adicionar pet
                        </button>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {petsAtivosDoTutor.length > 0 ? (
                          petsAtivosDoTutor.map((pet) => {
                            const selecionado = String(pet.id) === formData.paciente_id;
                            const descricao = [pet.especie, pet.raca].filter(Boolean).join(" - ");
                            return (
                              <button
                                key={pet.id}
                                type="button"
                                onClick={() => handlePacienteChange(String(pet.id), {
                                  id: pet.id,
                                  nome: pet.nome,
                                  tutor_id: tutorPanorama.tutor.id,
                                  tutor: tutorPanorama.tutor.nome,
                                  especie: pet.especie || "",
                                  raca: pet.raca || "",
                                })}
                                className={`rounded-lg border px-3 py-2 text-left text-xs ${
                                  selecionado
                                    ? "border-blue-300 bg-blue-50 text-blue-900"
                                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                                }`}
                              >
                                <div className="font-semibold">{pet.nome}</div>
                                {descricao ? <div className="mt-0.5 text-[11px] opacity-80">{descricao}</div> : null}
                              </button>
                            );
                          })
                        ) : (
                          <div className="text-xs text-slate-500">Este tutor ainda nao tem pets vinculados.</div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-slate-600">Selecione um tutor para ver os animais vinculados.</div>
                )}
              </div>
            )}
            {atendimentoDomiciliar && formData.tutor_id && !tutorSelecionadoGeorreferenciado && (
              <div className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                O tutor selecionado ainda nao possui endereco georreferenciado. Abra o cadastro do tutor e conclua o georreferenciamento antes de salvar.
              </div>
            )}
          </div>

          {/* Animal */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              <User className="w-4 h-4 inline mr-1" />
              {permiteSemPacienteTutor ? "Animal (opcional para reserva)" : "Animal *"}
            </label>
            <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2">
              <SearchableSelect
                value={formData.paciente_id}
                onChange={handlePacienteChange}
                options={pacienteOptions}
                placeholder="Selecione..."
                searchPlaceholder="Buscar animal ou tutor..."
                emptyText={
                  formData.tutor_id
                    ? "Nenhum animal encontrado para este tutor."
                    : "Nenhum animal encontrado."
                }
                selectionHint="Digite para buscar e clique no animal correto. O texto digitado sozinho não seleciona o cadastro."
                clearLabel="Selecione..."
                onSearchChange={setBuscaPacienteRemota}
                isSearching={buscandoPacientes || carregandoPacientesDoTutor}
                searchingText="Buscando animais..."
                searchError={erroBuscaPaciente}
              />
              <button
                type="button"
                onClick={abrirModalAnimal}
                className="fc-appointment-inline-action"
              >
                Novo animal
              </button>
            </div>

            {!formData.paciente_id && !permiteSemPacienteTutor ? (
              <p className="mt-1 text-xs font-medium text-amber-800">
                Nenhum animal cadastrado foi selecionado.
              </p>
            ) : null}

            {tutorSelecionado && (
              <div className="mt-2 flex items-center gap-2 text-sm text-gray-600 bg-blue-50 p-2 rounded-lg">
                <User className="w-4 h-4 text-blue-500" />
                <span className="font-medium">Tutor selecionado:</span>
                <span>{tutorSelecionado}</span>
              </div>
            )}
          </div>

          {/* Clínica */}
          {!atendimentoDomiciliar ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                <Building className="w-4 h-4 inline mr-1" />
                Clínica
              </label>
              <SearchableSelect
                value={formData.clinica_id}
                disabled={Boolean(pedidoWhatsApp) && !isEditando}
                onChange={handleClinicaChange}
                options={clinicaOptions}
                placeholder="Selecione..."
                searchPlaceholder="Buscar clinica ou endereco..."
                emptyText="Nenhuma clinica encontrada."
                clearLabel="Selecione..."
                showSelectedDescription
              />
              <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                O modal nao cria mais clinicas rapidamente. Para usar o assistente, selecione uma clinica ja cadastrada e
                com georreferenciamento concluido na tela de Clinicas.
              </div>
              {formData.clinica_id && !clinicaSelecionadaGeorreferenciada && (
                <div className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  A clinica selecionada ainda nao esta georreferenciada. Corrija o cadastro dela antes de sugerir ou salvar.
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-900">
              Este atendimento sera tratado como domiciliar e usara o endereco do tutor como referencia operacional.
            </div>
          )}

          {/* Serviço */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Serviço
            </label>
            <select
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              value={formData.servico_id}
              onChange={(e) => handleServicoChange(e.target.value)}
            >
              <option value="">Selecione...</option>
              {servicos.map((s) => (
                <option key={s.id} value={s.id.toString()}>
                  {s.nome}
                </option>
              ))}
            </select>
            {formData.servico_id && (
              <p className="mt-1 text-xs text-gray-500">
                Duração estimada: {
                  (() => {
                    const servicoSelecionado = servicos.find((s) => s.id?.toString() === formData.servico_id);
                    const duracaoMinutos = Number.parseInt(`${servicoSelecionado?.duracao_minutos ?? ""}`, 10);
                    return Number.isFinite(duracaoMinutos) && duracaoMinutos > 0 ? `${duracaoMinutos} min` : "30 min";
                  })()
                }
              </p>
            )}
          </div>

          <AgendaPreferenciasCampos
            value={filtrosPreferencia}
            referencia={referenciaPreferencia}
            onChange={alterarPreferencia}
            disabled={loading}
          />

          {!isEditando && isAdmin && decisaoAssistente !== "sem_opcao" && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-3 space-y-2">
              <p className="text-sm font-medium text-amber-900">Exceção administrativa</p>
              <p className="text-xs text-amber-900">
                Como admin, você pode escolher um horário manual com motivo e confirmação,
                sem gerar ou recusar ofertas do assistente.
              </p>
              <button
                type="button"
                onClick={abrirExcecaoAdmin}
                disabled={loading}
                className="px-3 py-2 rounded-md bg-amber-600 text-white text-sm hover:bg-amber-700 disabled:opacity-60"
              >
                Usar horário manual como admin
              </button>
            </div>
          )}

          {!isEditando && decisaoAssistente === "sem_opcao" && (
            <div className="rounded-md border border-amber-300 bg-white px-3 py-2 space-y-2">
              <div className="text-xs font-medium text-amber-800">
                {isAdmin ? "Exceção administrativa de horário" : "Nenhuma oferta panoramica atendeu. Registre o motivo para concluir o desfecho."}
              </div>
              {isAdmin && (
                <p className="text-xs text-amber-900">
                  Informe o motivo e confirme para escolher data/hora sem percorrer as ofertas.
                  A exceção permite ultrapassar as regras de saída de casa, deslocamento e margem segura
                  neste agendamento e fica registrada na auditoria. Horários ocupados continuam bloqueados.
                </p>
              )}
              <textarea
                aria-label={isAdmin ? "Motivo da exceção administrativa" : "Motivo da recusa das ofertas"}
                rows={2}
                value={motivoSemOpcao}
                onChange={(e) => setMotivoSemOpcao(e.target.value)}
                placeholder="Ex.: cliente so pode no turno da manha por urgencia clinica."
                className="w-full px-2 py-1 border border-amber-200 rounded-md text-xs focus:ring-2 focus:ring-amber-500"
              />
              <div className="flex flex-wrap gap-2">
                {isAdmin ? (
                  <>
                    {!excecaoConcedida ? (
                      <button
                        type="button"
                        onClick={concederExcecaoAdmin}
                        disabled={registrandoEncerramento}
                        className="px-3 py-1.5 rounded-md bg-amber-600 text-white text-xs hover:bg-amber-700 disabled:opacity-60"
                      >
                        Conceder excecao e liberar horario manual
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={revogarExcecaoAdmin}
                        disabled={registrandoEncerramento}
                        className="px-3 py-1.5 rounded-md border border-amber-300 text-amber-700 text-xs hover:bg-amber-50 disabled:opacity-60"
                      >
                        Revogar excecao
                      </button>
                    )}
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => void registrarDesfechoSemAgendamento("solicitacao_excecao")}
                    disabled={registrandoEncerramento}
                    className="px-3 py-1.5 rounded-md bg-amber-600 text-white text-xs hover:bg-amber-700 disabled:opacity-60"
                  >
                    {registrandoEncerramento
                      ? "Registrando..."
                      : "Solicitar excecao ao admin e encerrar"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void registrarDesfechoSemAgendamento("encerramento_sem_agendamento")}
                  disabled={registrandoEncerramento}
                  className="px-3 py-1.5 rounded-md border border-gray-300 text-gray-700 text-xs hover:bg-gray-50 disabled:opacity-60"
                >
                  Encerrar sem agendamento
                </button>
              </div>
              {isAdmin && excecaoConcedida && (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs text-emerald-800">
                  Excecao concedida por admin. Data/hora manual liberadas para concluir o agendamento.
                </div>
              )}
            </div>
          )}

          {/* Data e Hora */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                <Calendar className="w-4 h-4 inline mr-1" />
                Data *
              </label>
              <input
                type="date"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                value={formData.data}
                onChange={(e) => handleDataChange(e.target.value)}
                disabled={bloquearDataManual}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                <Clock className="w-4 h-4 inline mr-1" />
                Hora *
              </label>
              <input
                type="time"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                value={formData.hora}
                onChange={(e) => setFormData({...formData, hora: e.target.value})}
                disabled={bloquearHoraManual}
              />
            </div>
          </div>
          <div className="fc-appointment-assistant rounded-lg border px-3 py-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="space-y-1">
                <div className="text-sm font-medium text-blue-900 flex items-center gap-2">
                  <Sparkles className="h-4 w-4" />
                  {tituloAssistente}
                </div>
                <p className="text-xs text-blue-800">
                  {descricaoAssistente}
                </p>
              </div>
              <button
                type="button"
                onClick={buscarSugestoesHorario}
                disabled={carregandoSugestoes || Boolean(preferenciaResolvida.erro) || (!isEditando && !assistenteProntoParaSugerir)}
                className="w-full md:w-auto px-3 py-2 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-60"
              >
                {rotuloBotaoAssistente}
              </button>
            </div>
          </div>
          {!isEditando && bloqueioManualAssistenteAtivo && (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
              {decisaoAssistente !== "sem_opcao" && (
                <span>
                  {isAdmin
                    ? "Data/hora manuais ficam bloqueadas até você conceder a exceção administrativa acima."
                    : "Data/hora manuais ficam bloqueadas enquanto o assistente guiado estiver ativo. Se nenhuma oferta atender, marque a recusa para seguir o fluxo de excecao."}
                </span>
              )}
              {decisaoAssistente === "sem_opcao" && isAdmin && !excecaoConcedida && (
                <span>
                  Como admin, registre o motivo e clique em <strong>Conceder excecao</strong> para liberar ajuste manual.
                </span>
              )}
              {decisaoAssistente === "sem_opcao" && !isAdmin && (
                <span>
                  Seu perfil nao pode liberar horario manual. Registre o motivo e solicite excecao ao administrador.
                </span>
              )}
            </div>
          )}

          <div className="fc-appointment-assistant-detail rounded-lg border p-3 space-y-3">
            <div className="text-sm font-medium text-blue-900 flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              Panorama e desfecho do assistente
            </div>

            <p className="text-xs text-blue-800">
              {descricaoAssistente}
            </p>

            {mensagemProximidade && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                <strong>Assistente inteligente:</strong> {mensagemProximidade}
                {!isEditando && (
                  <div className="mt-1">
                    Proximo passo: gerar melhor oferta para visualizar o panorama completo antes de confirmar com o cliente.
                  </div>
                )}
              </div>
            )}

            {!isEditando && etapaWizardAtual && (
              <div className="rounded-md border border-blue-200 bg-white px-2 py-2 space-y-2">
                <div className="text-xs font-semibold text-blue-900">
                  Etapa atual: {indiceEtapaWizardNovo + 1}/{ETAPAS_WIZARD_NOVO.length} - {etapaWizardAtual.titulo}
                </div>
                <div className="text-[11px] text-blue-700">
                  {etapaWizardAtual.descricao}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {ETAPAS_WIZARD_NOVO.map((etapa, idx) => {
                    const concluida = idx < indiceEtapaWizardNovo;
                    const ativa = idx === indiceEtapaWizardNovo;
                    const className = ativa
                      ? "rounded-md border border-blue-300 bg-blue-50 px-2 py-1"
                      : concluida
                        ? "rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1"
                        : "rounded-md border border-gray-200 bg-gray-50 px-2 py-1";
                    const tituloClass = ativa
                      ? "text-[11px] font-semibold text-blue-900"
                      : concluida
                        ? "text-[11px] font-semibold text-emerald-900"
                        : "text-[11px] font-semibold text-gray-600";
                    const descClass = ativa
                      ? "text-[11px] text-blue-700"
                      : concluida
                        ? "text-[11px] text-emerald-700"
                        : "text-[11px] text-gray-500";

                    return (
                      <div key={etapa.id} className={className}>
                        <div className={tituloClass}>Etapa {idx + 1}: {etapa.titulo}</div>
                        <div className={descClass}>{etapa.descricao}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {!isEditando && !assistenteProntoParaSugerir && (
              <div className="rounded-md border border-blue-200 bg-white px-2 py-1 text-xs text-blue-700">
                Preencha {atendimentoDomiciliar ? "tutor georreferenciado" : "clinica georreferenciada"}, servico e data para iniciar o assistente guiado.
              </div>
            )}

            {itensIgnoradosJanela > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
                {itensIgnoradosJanela} opcao(oes) foram ignoradas por estarem fora da janela operacional/agenda fechada.
              </div>
            )}

            {erroSugestoes && (
              <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">
                {erroSugestoes}
              </div>
            )}

            {mensagemSugestoes && !erroSugestoes && (
              <div className="rounded-md border border-blue-200 bg-white px-2 py-1 text-xs text-blue-700">
                {mensagemSugestoes}
              </div>
            )}

            {!isEditando && assistenteProntoParaSugerir && ofertasPanoramicasConsultadas && totalSugestoes === 0 && dataSelecionadaPassada && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 space-y-2">
                <div className="text-xs text-amber-900">
                  Data passada detectada sem oferta operacional. Para lancamento retroativo, e obrigatorio registrar justificativa.
                </div>
                {isAdmin ? (
                  <button
                    type="button"
                    onClick={liberarFluxoRetroativoAdmin}
                    className="px-3 py-1.5 rounded-md bg-amber-600 text-white text-xs hover:bg-amber-700"
                  >
                    Liberar lancamento retroativo (admin)
                  </button>
                ) : (
                  <div className="text-xs text-amber-800">
                    Seu perfil nao pode liberar lancamento retroativo. Solicite um administrador.
                  </div>
                )}
              </div>
            )}

            {!isEditando && totalSugestoes > 0 && (
              <div className="rounded-md border border-blue-300 bg-white px-3 py-3 space-y-2">
                <div className="text-xs font-semibold text-blue-900">
                  Panorama de ofertas: {totalSugestoes} opcao(oes) sugerida(s)
                </div>
                <div className="space-y-2">
                  {sugestoesHorario.map((item, idx) => (
                    <div
                      key={`${item.inicio}-${idx}`}
                      className="rounded-md border border-blue-100 bg-blue-50/30 px-2 py-2"
                    >
                      <div className="text-sm font-medium text-gray-900">
                        Oferta {idx + 1}: {toBrDate(String(item.inicio || "").split(" ")[0])} - {extrairHoraDataHora(item.inicio)} a{" "}
                        {extrairHoraDataHora(item.fim)}
                      </div>
                      <div className="text-xs text-gray-600">
                        Entre atendimentos: {item.tempo_deslocamento_total_min} min | Risco: {item.risco}
                      </div>
                      {resumirPrimeiraSaidaSugestao(item) && (
                        <div className="text-xs font-medium text-teal-800">
                          {resumirPrimeiraSaidaSugestao(item)}
                        </div>
                      )}
                      <div className="text-xs text-gray-500">
                        {resumirDeslocamentoSugestao(item)}
                      </div>
                      <div className="pt-1">
                        <button
                          type="button"
                          onClick={() => void confirmarAceiteSugestao(item, idx)}
                          disabled={indiceOfertaEmValidacao !== null || loading}
                          className="px-3 py-1.5 rounded-md bg-emerald-600 text-white text-xs hover:bg-emerald-700 disabled:cursor-wait disabled:opacity-60"
                        >
                          {indiceOfertaEmValidacao === idx ? "Revalidando oferta..." : "Cliente aceitou esta oferta"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!isEditando && assistenteProntoParaSugerir && ofertasPanoramicasConsultadas && totalSugestoes > 0 && decisaoAssistente === "pendente" && (
              <button
                type="button"
                onClick={liberarFluxoManual}
                disabled={indiceOfertaEmValidacao !== null}
                className="px-3 py-1.5 rounded-md border border-amber-300 text-amber-700 text-xs hover:bg-amber-50"
              >
                Nenhuma oferta atende a necessidade do cliente (recusar todas)
              </button>
            )}

            {!isEditando && decisaoAssistente === "aceito" && (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs text-emerald-800">
                Aceite do cliente registrado. Agora basta salvar o agendamento.
              </div>
            )}

            {!isEditando && carregandoCreditoCliente && (
              <div className="rounded-md border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs text-cyan-800">
                Verificando se o cliente possui credito disponivel...
              </div>
            )}

            {!isEditando && erroCreditoCliente && !carregandoCreditoCliente && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-800">
                {erroCreditoCliente}
              </div>
            )}

            {clienteComCredito && !carregandoCreditoCliente && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Cliente com credito ativo: <strong>{formatarMoedaBRL(saldoCreditoCliente)}</strong>. Confirme com
                o cliente se deseja abater esse valor neste novo agendamento.
              </div>
            )}

            {isEditando && sugestoesHorario.length > 0 && (
              <div className="space-y-2">
                {sugestoesHorario.map((item, idx) => (
                  <button
                    key={`${item.inicio}-${idx}`}
                    type="button"
                    onClick={() => aplicarSugestaoHorario(item)}
                    className="w-full rounded-md border border-blue-200 bg-white px-3 py-2 text-left hover:border-blue-400"
                  >
                    <div className="text-sm font-medium text-gray-900">
                      {extrairHoraDataHora(item.inicio)} - {extrairHoraDataHora(item.fim)}
                    </div>
                    <div className="text-xs text-gray-600">
                      Entre atendimentos: {item.tempo_deslocamento_total_min} min | Risco: {item.risco}
                    </div>
                    {resumirPrimeiraSaidaSugestao(item) && (
                      <div className="mt-1 text-xs font-medium text-teal-800">
                        {resumirPrimeiraSaidaSugestao(item)}
                      </div>
                    )}
                    <div className="mt-1 text-xs text-gray-500">
                      {resumirDeslocamentoSugestao(item)}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {!pedidoWhatsApp && (!isEditando || formData.marcar_como_reserva) && (
            <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900">
              {!isEditando && (
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={formData.marcar_como_reserva}
                    onChange={(event) => {
                      const marcada = event.target.checked;
                      setFormData((prev) => ({
                        ...prev,
                        marcar_como_reserva: marcada,
                        reserva_prazo_horas: marcada ? "3" : prev.reserva_prazo_horas,
                        reserva_prazo_confirmacao: marcada
                          ? criarPrazoPadraoReserva()
                          : prev.reserva_prazo_confirmacao,
                      }));
                    }}
                    className="mt-0.5 h-4 w-4 rounded border-amber-300 text-amber-600 focus:ring-amber-500"
                  />
                  <span>
                    Marcar como <strong>reserva de horário</strong> (bloqueia o slot como pendente de confirmação).
                  </span>
                </label>
              )}

              <div className={isEditando ? "space-y-3" : "space-y-3 border-t border-amber-200 pt-3"}>
                <div>
                  <div className="mb-1 block text-xs font-semibold uppercase tracking-wide text-amber-800">
                    Mensagem {isEditando ? "de confirmação" : "após salvar"}
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <label
                      className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition ${
                        formData.reserva_destinatario_manual === "clinica"
                          ? "border-amber-500 bg-white"
                          : "border-amber-200 bg-amber-50/50"
                      } ${atendimentoDomiciliar || !formData.clinica_id ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
                    >
                      <input
                        type="radio"
                        name="reserva_destinatario_manual"
                        value="clinica"
                        checked={formData.reserva_destinatario_manual === "clinica"}
                        disabled={atendimentoDomiciliar || !formData.clinica_id}
                        onChange={() => setFormData((prev) => ({ ...prev, reserva_destinatario_manual: "clinica" }))}
                        className="h-4 w-4 border-amber-300 text-amber-600 focus:ring-amber-500"
                      />
                      <span className="min-w-0">
                        <span className="block font-semibold">Clínica</span>
                        <span className="block truncate text-xs text-amber-800">
                          {nomeClinicaReservaManual || "Selecione uma clínica"}
                        </span>
                      </span>
                    </label>

                    <label
                      className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition ${
                        formData.reserva_destinatario_manual === "tutor"
                          ? "border-amber-500 bg-white"
                          : "border-amber-200 bg-amber-50/50"
                      } ${!formData.tutor_id ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
                    >
                      <input
                        type="radio"
                        name="reserva_destinatario_manual"
                        value="tutor"
                        checked={formData.reserva_destinatario_manual === "tutor"}
                        disabled={!formData.tutor_id}
                        onChange={() => setFormData((prev) => ({ ...prev, reserva_destinatario_manual: "tutor" }))}
                        className="h-4 w-4 border-amber-300 text-amber-600 focus:ring-amber-500"
                      />
                      <span className="min-w-0">
                        <span className="block font-semibold">Tutor/cliente</span>
                        <span className="block truncate text-xs text-amber-800">
                          {nomeTutorReservaManual || "Selecione um tutor"}
                        </span>
                      </span>
                    </label>
                  </div>
                </div>

                {!isEditando && (
                  formData.marcar_como_reserva ? (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <label htmlFor="fc-reserva-prazo-horas" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-amber-800">
                          Prazo para confirmação
                        </label>
                        <div className="flex max-w-xs overflow-hidden rounded-lg border border-amber-300 bg-white focus-within:border-amber-500 focus-within:ring-2 focus-within:ring-amber-200">
                          <input
                            id="fc-reserva-prazo-horas"
                            type="number"
                            required
                            min="0.5"
                            max="72"
                            step="0.5"
                            inputMode="decimal"
                            value={formData.reserva_prazo_horas}
                            onChange={(event) => {
                              const valor = event.target.value;
                              const horas = Number(valor);
                              setFormData((prev) => ({
                                ...prev,
                                reserva_prazo_horas: valor,
                                reserva_prazo_confirmacao:
                                  Number.isFinite(horas) && horas >= 0.5 && horas <= 72
                                    ? criarPrazoReservaPorHoras(horas)
                                    : prev.reserva_prazo_confirmacao,
                              }));
                            }}
                            className="min-w-0 flex-1 border-0 px-3 py-2 text-gray-900 outline-none"
                          />
                          <span className="flex items-center border-l border-amber-200 bg-amber-50 px-3 font-medium text-amber-800">
                            horas
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-amber-800">
                          O padrão é 3 horas; ajuste conforme o combinado com o cliente.
                        </div>
                      </div>
                      <div>
                        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-800">
                          Confirmar até
                        </div>
                        <div className="rounded-lg border border-amber-200 bg-white/80 px-3 py-2 font-medium text-gray-900">
                          {formatarPrazoReserva(formData.reserva_prazo_confirmacao)}
                        </div>
                        <div className="mt-1 text-xs text-amber-800">
                          O prazo precisa ser anterior ao horário reservado.
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                      Depois de salvar, o sistema mostrará o botão para avisar que o horário solicitado foi agendado.
                    </div>
                  )
                )}

                <div className="rounded-lg border border-amber-200 bg-white/70 px-3 py-3 text-xs text-amber-900">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      Contato atual: <strong>{destinatarioMensagemNome || "não selecionado"}</strong>
                      {destinatarioMensagemTelefones.length > 0
                        ? ` — ${destinatarioMensagemTelefones.map(formatarWhatsAppVisual).join(" / ")}`
                        : " — sem WhatsApp cadastrado"}.
                    </div>
                    {!editandoWhatsappDestinatario ? (
                      <button
                        type="button"
                        onClick={iniciarEdicaoWhatsappDestinatario}
                        disabled={
                          formData.reserva_destinatario_manual === "clinica"
                            ? !formData.clinica_id
                            : !formData.tutor_id
                        }
                        className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2.5 py-1.5 font-semibold text-amber-900 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        {destinatarioMensagemTelefones.length > 0 ? "Editar WhatsApp" : "Adicionar WhatsApp"}
                      </button>
                    ) : null}
                  </div>

                  {editandoWhatsappDestinatario ? (
                    <div className="mt-3 rounded-lg border border-amber-200 bg-white p-3">
                      <div className="space-y-2">
                        {whatsappsDestinatarioEdicao.map((telefone, indice) => (
                          <div key={`whatsapp-destinatario-${indice}`} className="flex items-end gap-2">
                            <label className="min-w-0 flex-1">
                              <span className="mb-1 block font-semibold text-amber-900">
                                WhatsApp{formData.reserva_destinatario_manual === "clinica" ? ` ${indice + 1}` : ""}
                              </span>
                              <input
                                type="tel"
                                inputMode="tel"
                                value={telefone}
                                onChange={(event) => atualizarWhatsappDestinatarioEdicao(indice, event.target.value)}
                                placeholder="(85) 99999-9999"
                                className="w-full rounded-md border border-amber-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-200"
                              />
                            </label>
                            {formData.reserva_destinatario_manual === "clinica" && whatsappsDestinatarioEdicao.length > 1 ? (
                              <button
                                type="button"
                                onClick={() => removerWhatsappClinicaEdicao(indice)}
                                className="rounded-md border border-red-200 p-2 text-red-600 transition hover:bg-red-50"
                                aria-label={`Remover WhatsApp ${indice + 1}`}
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>

                      {formData.reserva_destinatario_manual === "clinica" && whatsappsDestinatarioEdicao.length < 10 ? (
                        <button
                          type="button"
                          onClick={adicionarWhatsappClinicaEdicao}
                          className="mt-2 inline-flex items-center gap-1 font-semibold text-amber-800 hover:text-amber-950"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          Adicionar outro número
                        </button>
                      ) : null}

                      <div className="mt-3 flex flex-wrap justify-end gap-2">
                        <button
                          type="button"
                          onClick={cancelarEdicaoWhatsappDestinatario}
                          disabled={salvandoWhatsappDestinatario}
                          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          Cancelar
                        </button>
                        <button
                          type="button"
                          onClick={() => void salvarWhatsappDestinatario()}
                          disabled={salvandoWhatsappDestinatario}
                          className="rounded-md bg-amber-700 px-3 py-1.5 font-semibold text-white hover:bg-amber-800 disabled:opacity-50"
                        >
                          {salvandoWhatsappDestinatario ? "Salvando..." : "Salvar contato"}
                        </button>
                      </div>
                    </div>
                  ) : null}

                  <div className="mt-2">
                    A alteração fica salva no cadastro. Se houver mais de um WhatsApp, você escolherá o número antes de abrir a conversa. O envio continua manual enquanto a Meta analisa a empresa.
                  </div>
                </div>

              </div>
            </div>
          )}

          {/* Observações */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Observações
            </label>
            <textarea
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              placeholder="Observações sobre o agendamento..."
              value={formData.observacoes}
              onChange={(e) => setFormData({...formData, observacoes: e.target.value})}
            />
          </div>

          {/* Botões */}
          {!isEditando && bloquearSalvarNovo && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Conclua o assistente guiado para habilitar o salvamento do agendamento.
            </div>
          )}
          <div className="fc-appointment-actions flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="fc-appointment-button-secondary"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading || bloquearSalvarNovo || registrandoEncerramento}
              className="fc-appointment-button-primary"
            >
              {loading 
                ? (isEditando ? "Salvando..." : "Criando...") 
                : (isEditando
                    ? (editandoReservaExpirada ? "Salvar dados da reserva" : "Salvar Alterações")
                    : "Salvar Agendamento")
              }
            </button>
          </div>
        </form>
      </div>

      {modalTutorAberto && (
        <div className="fc-appointment-submodal-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="fc-appointment-submodal w-full max-w-3xl" role="dialog" aria-modal="true" aria-labelledby="fc-tutor-modal-title">
            <div className="fc-appointment-submodal-header flex items-center justify-between px-5 py-4">
              <h3 className="text-lg font-semibold text-gray-900">
                <span id="fc-tutor-modal-title">
                {novoTutor.id ? "Cadastro do Tutor" : "Cadastrar Tutor"}
                </span>
              </h3>
              <button
                type="button"
                onClick={() => setModalTutorAberto(false)}
                className="fc-appointment-submodal-close"
                disabled={salvandoTutor}
                aria-label="Fechar cadastro do tutor"
                title="Fechar"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="fc-appointment-submodal-body space-y-3 px-5 py-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Nome *</label>
                  <input
                    type="text"
                    value={novoTutor.nome}
                    onChange={(e) => setNovoTutor((prev) => ({ ...prev, nome: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Nome do tutor"
                  />
                </div>
                <TutorIdentificacaoFields value={novoTutor} onChange={(value) => setNovoTutor((prev) => ({ ...prev, ...value }))} />
                {!novoTutor.id && <p className="col-span-full text-sm text-slate-600">Pode informar só o primeiro nome. O cadastro ficará pendente para complementar no atendimento; nomes iguais continuam separados.</p>}
                {novoTutor.id && <button type="button" disabled={salvandoTutor}
                  className="col-span-full rounded-lg border px-3 py-2 text-sm text-blue-700"
                  onClick={() => setNovoTutor({ ...buildInitialTutorForm(), nome: novoTutor.nome,
                    origem_cadastro: clinicas.find((c) => String(c.id) === formData.clinica_id)?.nome || "" })}>
                  Criar outra pessoa com este nome
                </button>}

                <details className="col-span-full" open={Boolean(novoTutor.id)}>
                  <summary className="cursor-pointer text-sm font-medium text-blue-700">Contato e documento — preencher se disponíveis</summary>
                  <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">CPF</label>
                  <input
                    type="text"
                    value={novoTutor.cpf}
                    inputMode="numeric"
                    maxLength={14}
                    onChange={(e) => setNovoTutor((prev) => ({ ...prev, cpf: formatarCpfVisual(e.target.value) }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="000.000.000-00"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Telefone</label>
                  <input
                    type="text"
                    value={novoTutor.telefone}
                    inputMode="tel"
                    maxLength={15}
                    onChange={(e) => setNovoTutor((prev) => ({ ...prev, telefone: formatarTelefoneVisual(e.target.value) }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="(00) 00000-0000"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">WhatsApp</label>
                  <input
                    type="text"
                    value={novoTutor.whatsapp}
                    inputMode="tel"
                    maxLength={15}
                    onChange={(e) => setNovoTutor((prev) => ({ ...prev, whatsapp: formatarTelefoneVisual(e.target.value) }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="(00) 00000-0000"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                  <input
                    type="email"
                    value={novoTutor.email}
                    onChange={(e) => setNovoTutor((prev) => ({ ...prev, email: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="email@exemplo.com"
                  />
                </div>
                  </div>
                </details>
              </div>

              <details open={atendimentoDomiciliar || Boolean(novoTutor.id)} className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-3">
                <summary className="cursor-pointer text-sm font-medium text-slate-700">Endereço — necessário para atendimento domiciliar</summary>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">Endereco do tutor</div>
                    <div className="text-xs text-slate-500">
                      O agendamento domiciliar depende do endereco georreferenciado pela API Google.
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={geocodificarTutorEndereco}
                    disabled={geocodificandoTutor}
                    className="px-3 py-1.5 rounded-md border border-blue-200 text-blue-700 text-xs hover:bg-blue-50 disabled:opacity-60"
                  >
                    {geocodificandoTutor ? "Georreferenciando..." : "Georreferenciar endereco"}
                  </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">CEP</label>
                    <input
                      type="text"
                      value={novoTutor.cep}
                      inputMode="numeric"
                      maxLength={9}
                      onChange={(e) => {
                        const valor = formatarCepVisual(e.target.value);
                        const cepAtual = normalizarCep(valor);
                        const cepAnterior = normalizarCep(novoTutor.cep);
                        const mudouCep = cepAtual !== cepAnterior;

                        if (mudouCep) {
                          ultimoCepConsultadoTutorRef.current = "";
                          consultaCepTutorSequenciaRef.current += 1;
                          setConsultandoCepTutor(false);
                          setStatusEnderecoTutor("");
                        }

                        setNovoTutor((prev) => ({
                          ...prev,
                          cep: valor,
                          ...(mudouCep
                            ? {
                                latitude: null,
                                longitude: null,
                                place_id: "",
                                endereco_normalizado: "",
                              }
                            : {}),
                        }));

                        if (cepAtual.length === 8) {
                          void consultarCepTutor(valor);
                        }
                      }}
                      onBlur={() => {
                        if (normalizarCep(novoTutor.cep).length === 8) {
                          void consultarCepTutor();
                        }
                      }}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="00000-000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Bairro</label>
                    <input
                      type="text"
                      value={novoTutor.bairro}
                      onChange={(e) => setNovoTutor((prev) => ({ ...prev, bairro: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Bairro"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Endereco</label>
                    <input
                      type="text"
                      value={novoTutor.endereco}
                      onChange={(e) => setNovoTutor((prev) => ({ ...prev, endereco: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Rua / Avenida"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Numero</label>
                    <input
                      type="text"
                      value={novoTutor.numero}
                      onChange={(e) => setNovoTutor((prev) => ({ ...prev, numero: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="123"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Complemento</label>
                    <input
                      type="text"
                      value={novoTutor.complemento}
                      onChange={(e) => setNovoTutor((prev) => ({ ...prev, complemento: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Apto, bloco, sala"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Cidade</label>
                    <input
                      type="text"
                      value={novoTutor.cidade}
                      onChange={(e) => setNovoTutor((prev) => ({ ...prev, cidade: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Cidade"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">UF</label>
                    <input
                      type="text"
                      value={novoTutor.estado}
                      onChange={(e) => setNovoTutor((prev) => ({ ...prev, estado: e.target.value.toUpperCase().slice(0, 2) }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="CE"
                    />
                  </div>
                </div>
                {statusEnderecoTutor && (
                  <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700">
                    {consultandoCepTutor ? "Consultando CEP..." : statusEnderecoTutor}
                  </div>
                )}
                {(novoTutor.latitude !== null || novoTutor.longitude !== null) && (
                  <div className="text-xs text-slate-500">
                    Lat/Lng: {novoTutor.latitude ?? "-"}, {novoTutor.longitude ?? "-"}
                    {novoTutor.endereco_normalizado ? ` - ${novoTutor.endereco_normalizado}` : ""}
                  </div>
                )}
              </details>

              {tutorPanorama?.tutor?.id && String(tutorPanorama.tutor.id) === String(novoTutor.id || "") && (
                <div className="rounded-lg border border-slate-200 p-4">
                  <div className="text-sm font-semibold text-slate-900">Panorama dos animais do tutor</div>
                  <div className="mt-1 text-xs text-slate-500">
                    {Number(tutorPanorama.resumo?.total_pets || tutorPanorama.pets.length || 0)} pet(s) vinculado(s)
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {tutorPanorama.pets.length > 0 ? (
                      tutorPanorama.pets.map((pet) => (
                        <button
                          key={pet.id}
                          type="button"
                          onClick={() => {
                            handlePacienteChange(String(pet.id));
                            setModalTutorAberto(false);
                          }}
                          className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs text-slate-700 hover:border-blue-300 hover:bg-blue-50"
                        >
                          <div className="font-semibold">{pet.nome}</div>
                          <div className="mt-0.5 opacity-80">
                            {[pet.especie, pet.raca].filter(Boolean).join(" - ") || "Sem detalhes"}
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="text-xs text-slate-500">Nenhum pet vinculado ainda.</div>
                    )}
                  </div>
                </div>
              )}
            </div>
            <div className="fc-appointment-submodal-footer flex justify-end gap-2 px-5 py-4">
              <button
                type="button"
                onClick={() => setModalTutorAberto(false)}
                className="fc-appointment-button-secondary"
                disabled={salvandoTutor}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void salvarNovoTutor()}
                className="fc-appointment-button-primary"
                disabled={salvandoTutor}
              >
                {salvandoTutor ? "Salvando..." : novoTutor.id ? "Salvar Tutor" : "Criar Tutor"}
              </button>
            </div>
          </div>
        </div>
      )}

      {modalAnimalAberto && (
        <div className="fc-appointment-submodal-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="fc-appointment-submodal w-full max-w-2xl" role="dialog" aria-modal="true" aria-labelledby="fc-animal-modal-title">
            <div className="fc-appointment-submodal-header flex items-center justify-between px-5 py-4">
              <h3 id="fc-animal-modal-title" className="text-lg font-semibold text-gray-900">Cadastrar Animal</h3>
              <button
                type="button"
                onClick={() => setModalAnimalAberto(false)}
                className="fc-appointment-submodal-close"
                disabled={salvandoAnimal}
                aria-label="Fechar cadastro do animal"
                title="Fechar"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="fc-appointment-submodal-body space-y-3 px-5 py-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Tutor *</label>
                <select
                  value={novoAnimal.tutor_id}
                  onChange={(e) => setNovoAnimal((prev) => ({ ...prev, tutor_id: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Selecione...</option>
                  {tutores.map((tutor) => (
                    <option key={tutor.id} value={tutor.id.toString()}>
                      {tutor.nome} #{tutor.id}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Nome do Animal *</label>
                  <input
                    type="text"
                    value={novoAnimal.nome}
                    onChange={(e) => setNovoAnimal((prev) => ({ ...prev, nome: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Nome do animal"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Especie</label>
                  <select
                    value={novoAnimal.especie}
                    onChange={(e) => {
                      setNovoAnimal((prev) => ({ ...prev, especie: e.target.value, raca: "" }));
                      setNovaRaca("");
                      setRacaEmEdicaoId("");
                      setNomeRacaEmEdicao("");
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">Não informada</option>
                    {["Canina", "Felina", "Equina", "Outra"].map((especie) => (
                      <option key={especie} value={especie}>
                        {especie}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Raça</label>
                  <select
                    value={novoAnimal.raca}
                    onChange={(e) => setNovoAnimal((prev) => ({ ...prev, raca: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">Selecione...</option>
                    {opcoesRacaAnimal.map((raca) => (
                      <option key={raca} value={raca}>
                        {raca}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setGestaoRacasAberta((aberta) => !aberta)}
                    className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-900"
                    aria-expanded={gestaoRacasAberta}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    {gestaoRacasAberta ? "Fechar gestão de raças" : "Cadastrar ou gerenciar raças"}
                  </button>

                  {gestaoRacasAberta && (
                    <div className="mt-2 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <p className="text-xs text-slate-600">
                        Catálogo de raças {novoAnimal.especie.toLowerCase()}, em ordem alfabética.
                      </p>

                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={novaRaca}
                          onChange={(e) => setNovaRaca(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              cadastrarRacaAnimal();
                            }
                          }}
                          className="min-w-0 flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                          placeholder="Nova raça"
                        />
                        <button
                          type="button"
                          onClick={cadastrarRacaAnimal}
                          disabled={!novaRaca.trim()}
                          className="inline-flex items-center gap-1 rounded-lg border border-blue-200 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          Cadastrar
                        </button>
                      </div>

                      {racaEmEdicaoId ? (
                        <div className="space-y-2 rounded-md border border-blue-100 bg-white p-2">
                          <label className="block text-xs font-medium text-slate-700" htmlFor="fc-raca-em-edicao">
                            Editar raça
                          </label>
                          <div className="flex gap-2">
                            <input
                              id="fc-raca-em-edicao"
                              type="text"
                              value={nomeRacaEmEdicao}
                              onChange={(e) => setNomeRacaEmEdicao(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  salvarEdicaoRacaAnimal();
                                }
                              }}
                              className="min-w-0 flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                            />
                            <button
                              type="button"
                              onClick={salvarEdicaoRacaAnimal}
                              disabled={!nomeRacaEmEdicao.trim()}
                              className="rounded-lg bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              Salvar
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setRacaEmEdicaoId("");
                                setNomeRacaEmEdicao("");
                              }}
                              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
                            >
                              Cancelar
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="mr-auto text-xs text-slate-600">
                            {racaSelecionadaNoCatalogo
                              ? `Selecionada: ${racaSelecionadaNoCatalogo.nome}`
                              : "Selecione uma raça acima para editar ou excluir."}
                          </span>
                          <button
                            type="button"
                            onClick={iniciarEdicaoRacaAnimal}
                            disabled={!racaSelecionadaNoCatalogo}
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                            Editar
                          </button>
                          <button
                            type="button"
                            onClick={() => void excluirRacaAnimal()}
                            disabled={!racaSelecionadaNoCatalogo}
                            className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Excluir
                          </button>
                        </div>
                      )}

                      <p className="text-xs text-slate-500">
                        Alterações no catálogo não modificam a raça de animais já cadastrados.
                      </p>
                    </div>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Sexo</label>
                  <select
                    value={novoAnimal.sexo}
                    onChange={(e) => setNovoAnimal((prev) => ({ ...prev, sexo: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">Não informado</option>
                    {["Macho", "Femea"].map((sexo) => (
                      <option key={sexo} value={sexo}>
                        {sexo}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Peso (kg)</label>
                  <input
                    type="text"
                    value={novoAnimal.peso_kg}
                    onChange={(e) => setNovoAnimal((prev) => ({ ...prev, peso_kg: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Ex: 12.5"
                  />
                </div>
                <PatientAgeFields value={novoAnimal} onChange={(patch) => setNovoAnimal((prev) => ({ ...prev, ...patch }))} />
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Microchip</label>
                  <input
                    type="text"
                    value={novoAnimal.microchip}
                    onChange={(e) => setNovoAnimal((prev) => ({ ...prev, microchip: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Codigo"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Observacoes</label>
                <textarea
                  rows={3}
                  value={novoAnimal.observacoes}
                  onChange={(e) => setNovoAnimal((prev) => ({ ...prev, observacoes: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  placeholder="Informacoes adicionais"
                />
              </div>
            </div>
            <div className="fc-appointment-submodal-footer flex justify-end gap-2 px-5 py-4">
              <button
                type="button"
                onClick={() => setModalAnimalAberto(false)}
                className="fc-appointment-button-secondary"
                disabled={salvandoAnimal}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={salvarNovoAnimal}
                className="fc-appointment-button-primary"
                disabled={salvandoAnimal}
              >
                {salvandoAnimal ? "Salvando..." : "Salvar Animal"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
