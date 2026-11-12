"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { validateOrderSelection } from "@/lib/ordens-selection";
import { loadCompleteBillingGroup, type BillingGroup } from "@/lib/cobrancas-loading";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";
import {
  appendUniqueLoadFailure,
  deveRecarregarResumo,
  getFinanceiroLoadingPlan,
  loadFinanceiroSection,
  removeLoadFailure,
  type FinanceiroActiveTab,
  type FinanceiroLoadOrigin,
} from "@/lib/financeiro-loading";
import TransacaoModal from "./TransacaoModal";
import DesfazerRecebimentoModal from "./DesfazerRecebimentoModal";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { calendarDateInput, formatCalendarDate, operationalTodayDateInput } from "@/lib/calendar-date";
import {
  FORMA_PAGAMENTO_FALLBACK,
  FORMA_PAGAMENTO_PADRAO,
  descricaoFormaPagamentoConfig,
  normalizarCodigoFormaPagamento,
  type FormaPagamentoConfig,
} from "@/lib/agenda-shared-actions";
import BaixaCredito from "@/components/financeiro/BaixaCredito";
import { consultarSaldoCreditoCliente } from "@/lib/credito-cliente";
import { 
  DollarSign, TrendingUp, TrendingDown, Plus, Search, 
  Calendar, CheckCircle, XCircle, Clock, Edit, Trash2,
  Filter, Download, BarChart3, PieChart, ArrowUpRight, ArrowDownRight,
  ChevronDown, ChevronLeft, ChevronRight, FileText, Receipt, Undo2, MessageCircle, Copy, Mail
} from "lucide-react";

interface Transacao {
  id: number;
  tipo: "entrada" | "saida";
  categoria: string;
  descricao: string;
  valor: number;
  valor_final: number;
  desconto: number;
  status: string;
  forma_pagamento: string;
  data_transacao: string;
  data_vencimento: string;
  paciente_nome?: string;
  parcelas?: number;
  parcela_atual?: number;
}

interface OrdemServico {
  id: number;
  numero_os: string;
  agendamento_id?: number | null;
  laudo_id?: number | null;
  paciente_id?: number | null;
  clinica_id?: number | null;
  servico_id?: number | null;
  origem_atendimento?: "clinica_parceira" | "domiciliar" | string | null;
  paciente: string;
  tutor_id?: number | null;
  tutor?: string;
  tutor_telefone?: string | null;
  tutor_whatsapp?: string | null;
  tutor_email?: string | null;
  clinica: string;
  clinica_telefone?: string | null;
  clinica_email?: string | null;
  destinatario_tipo?: "clinica" | "tutor" | string | null;
  destinatario_nome?: string | null;
  destinatario_telefone?: string | null;
  destinatario_email?: string | null;
  servico: string;
  data_atendimento: string;
  tipo_horario: string;
  valor_servico: number;
  desconto: number;
  valor_final: number;
  status: string;
  observacoes?: string | null;
  created_at: string;
}

interface PagamentoRecebimentoItem {
  id: string;
  forma_codigo: string;
  valor: string;
}

interface ClinicaOption {
  id: number;
  nome: string;
  telefone?: string | null;
  email?: string | null;
}

interface BandeiraCartaoOption {
  id: number;
  nome: string;
  codigo: string;
  ativo: boolean;
}

interface ServicoOption {
  id: number;
  nome: string;
}

const CATEGORIAS_TRANSACAO = [
  { id: "consulta", nome: "Consulta" },
  { id: "exame", nome: "Exame" },
  { id: "cirurgia", nome: "Cirurgia" },
  { id: "medicamento", nome: "Medicamento" },
  { id: "banho_tosa", nome: "Banho e Tosa" },
  { id: "produto", nome: "Produto" },
  { id: "salario", nome: "Salario" },
  { id: "aluguel", nome: "Aluguel" },
  { id: "fornecedor", nome: "Fornecedor" },
  { id: "imposto", nome: "Imposto" },
  { id: "manutencao", nome: "Manutencao" },
  { id: "marketing", nome: "Marketing" },
  { id: "outros", nome: "Outros" },
];

const MODELO_MENSAGEM_COBRANCA_PADRAO = [
  "Ola, {{destinatario}}.",
  "Segue resumo das ordens de servico pendentes ate {{data}}:",
  "",
  "{{lista_os}}",
  "",
  "Total pendente: {{total_pendente}}.",
  "Favor confirmar a previsao de pagamento. Obrigado!",
].join("\n");

const MODELO_MENSAGEM_RECIBO_INDIVIDUAL_PADRAO = [
  "Ola, segue o recibo da OS {{os_numero}}.",
  "Paciente: {{paciente}}.",
  "Destinatario: {{destinatario}}.",
  "Valor recebido: {{valor_recebido}}.",
  "Data de emissao: {{data}}.",
  "",
  "PDF em anexo.",
].join("\n");

const MODELO_MENSAGEM_RECIBO_AGRUPADO_PADRAO = [
  "Ola, segue o recibo consolidado das ordens de servico recebidas.",
  "Destinatario: {{destinatario}}.",
  "Quantidade de OS: {{quantidade_os}}.",
  "Total recebido: {{total_recebido}}.",
  "Data de emissao: {{data}}.",
  "",
  "{{lista_os}}",
  "",
  "PDF em anexo.",
].join("\n");

const PLACEHOLDERS_MENSAGEM_COBRANCA = [
  { label: "Destinatario", valor: "{{destinatario}}" },
  { label: "Data", valor: "{{data}}" },
  { label: "Lista OS", valor: "{{lista_os}}" },
  { label: "Total pendente", valor: "{{total_pendente}}" },
];

const PLACEHOLDERS_MENSAGEM_RECIBO = [
  { label: "Destinatario", valor: "{{destinatario}}" },
  { label: "Data", valor: "{{data}}" },
  { label: "OS", valor: "{{os_numero}}" },
  { label: "Paciente", valor: "{{paciente}}" },
  { label: "Valor", valor: "{{valor_recebido}}" },
  { label: "Total", valor: "{{total_recebido}}" },
  { label: "Qtd. OS", valor: "{{quantidade_os}}" },
  { label: "Lista OS", valor: "{{lista_os}}" },
];

interface Resumo {
  entradas: number;
  saidas: number;
  saldo: number;
  a_receber: number;
  a_pagar: number;
  pendente_entrada: number;
  pendente_saida: number;
  taxas_pagamento: number;
  creditos_gerados: number;
}

interface ContatoDestinatario {
  chave: string;
  tipo_destinatario: "clinica" | "tutor";
  nome_destinatario: string;
  telefone_destinatario: string;
  email_destinatario: string;
  clinica_id?: number | null;
  tutor_id?: number | null;
}

interface GrupoCobrancaDestinatario extends ContatoDestinatario {
  total_pendente: number;
  quantidade_os: number;
  quantidade_total: number;
  ordens: OrdemServico[];
}

interface CompartilhamentoReciboState {
  canal: "whatsapp" | "email";
  ids: number[];
  agrupar: boolean;
  mensagem: string;
  assunto: string;
  telefone: string;
  email: string;
}

interface PreviewReciboState {
  ids: number[];
  agrupar: boolean;
  titulo: string;
  filename: string;
  url: string;
  blob: Blob;
}

function ReciboPdfPreview({
  blob,
  titulo,
}: {
  blob: Blob;
  titulo: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [quantidadePaginas, setQuantidadePaginas] = useState(0);

  useEffect(() => {
    let cancelado = false;
    let documentoPdf: any = null;

    const renderizar = async () => {
      const container = containerRef.current;
      if (!container) return;

      container.innerHTML = "";
      setCarregando(true);
      setErro("");
      setQuantidadePaginas(0);

      try {
        const pdfjsLib = await import("pdfjs-dist/legacy/build/pdf.mjs");
        pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
          import.meta.url
        ).toString();

        const data = new Uint8Array(await blob.arrayBuffer());
        const loadingTask = pdfjsLib.getDocument({
          data,
          useWorkerFetch: false,
          isEvalSupported: false,
        });
        documentoPdf = await loadingTask.promise;

        if (cancelado) return;

        setQuantidadePaginas(documentoPdf.numPages);
        const larguraDisponivel = Math.max((container.clientWidth || 0) - 24, 320);
        const escalaSaida = window.devicePixelRatio || 1;

        for (let paginaAtual = 1; paginaAtual <= documentoPdf.numPages; paginaAtual += 1) {
          if (cancelado) return;

          const pagina = await documentoPdf.getPage(paginaAtual);
          const viewportBase = pagina.getViewport({ scale: 1 });
          const escala = Math.max(0.8, larguraDisponivel / viewportBase.width);
          const viewport = pagina.getViewport({ scale: escala });

          const wrapper = document.createElement("div");
          wrapper.className = "mb-4 flex justify-center last:mb-0";

          const canvas = document.createElement("canvas");
          canvas.className = "bg-white shadow-sm";
          canvas.width = Math.floor(viewport.width * escalaSaida);
          canvas.height = Math.floor(viewport.height * escalaSaida);
          canvas.style.width = `${Math.floor(viewport.width)}px`;
          canvas.style.height = `${Math.floor(viewport.height)}px`;

          const context = canvas.getContext("2d");
          if (!context) {
            throw new Error("Nao foi possivel inicializar o canvas da previa.");
          }

          wrapper.appendChild(canvas);
          container.appendChild(wrapper);

          await pagina.render({
            canvasContext: context,
            viewport,
            transform:
              escalaSaida !== 1 ? [escalaSaida, 0, 0, escalaSaida, 0, 0] : undefined,
          }).promise;
        }
      } catch (err) {
        console.error("Erro ao renderizar previa do recibo:", err);
        if (!cancelado) {
          setErro("A previa inline do PDF nao carregou neste navegador.");
        }
      } finally {
        if (!cancelado) {
          setCarregando(false);
        }
      }
    };

    renderizar();

    return () => {
      cancelado = true;
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
      documentoPdf?.destroy?.();
    };
  }, [blob]);

  return (
    <div className="h-full overflow-auto bg-gray-100 p-3">
      {carregando && (
        <div className="mb-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-700">
          Carregando previa{quantidadePaginas > 0 ? ` (${quantidadePaginas} pagina(s))` : ""}...
        </div>
      )}
      {erro && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {erro} Abra em nova aba para usar o visualizador nativo do navegador.
        </div>
      )}
      {!carregando && !erro && quantidadePaginas > 1 && (
        <div className="mb-3 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600">
          Exibindo {quantidadePaginas} paginas do arquivo `{titulo}`. Role para ver todas as OS.
        </div>
      )}
      <div ref={containerRef} className="min-h-full" />
    </div>
  );
}

export default function FinanceiroPage() {
  const [transacoes, setTransacoes] = useState<Transacao[]>([]);
  const [ordensServico, setOrdensServico] = useState<OrdemServico[]>([]);
  const [ordensPagina, setOrdensPagina] = useState<OrdemServico[]>([]);
  const [gruposRemotos, setGruposRemotos] = useState<BillingGroup[]>([]);
  const [totalGrupos, setTotalGrupos] = useState(0);
  const [grupoAberto, setGrupoAberto] = useState<string | null>(null);
  const [carregandoGrupo, setCarregandoGrupo] = useState(false);
  const [erroGrupo, setErroGrupo] = useState("");
  const grupoControllerRef = useRef<AbortController | null>(null);
  useEffect(() => () => grupoControllerRef.current?.abort(), []);
  const [osAlvoId, setOsAlvoId] = useState<number | null>(null);
  const selecaoEpochRef = useRef(0);
  useEffect(() => () => { selecaoEpochRef.current += 1; }, []);
  const [erroSelecao, setErroSelecao] = useState("");
  const [validandoSelecao, setValidandoSelecao] = useState(false);
  const validandoSelecaoRef = useRef(false);
  const [totalOrdens, setTotalOrdens] = useState(0);
  const [resumoOrdens, setResumoOrdens] = useState({ pendentes: 0, valor_pendente: 0 });
  const [resumo, setResumo] = useState<Resumo>({
    entradas: 0,
    saidas: 0,
    saldo: 0,
    a_receber: 0,
    a_pagar: 0,
    pendente_entrada: 0,
    pendente_saida: 0,
    taxas_pagamento: 0,
    creditos_gerados: 0,
  });
  const [periodo, setPeriodo] = useState("mes");
  const [loadingTransacoes, setLoadingTransacoes] = useState(true);
  const [loadingOrdens, setLoadingOrdens] = useState(false);
  const [transacoesCarregadas, setTransacoesCarregadas] = useState(false);
  const [ordensCarregadas, setOrdensCarregadas] = useState(false);
  const [falhasCarregamento, setFalhasCarregamento] = useState<string[]>([]);
  const [modalAberto, setModalAberto] = useState(false);
  const [transacaoEditando, setTransacaoEditando] = useState<any>(null);
  const [filtroTipo, setFiltroTipo] = useState<string>("todos");
  const [filtroCategoria, setFiltroCategoria] = useState<string>("todos");
  const [filtroFormaPagamento, setFiltroFormaPagamento] = useState<string>("todos");
  const [filtroStatusTransacao, setFiltroStatusTransacao] = useState<string>("todos");
  const [filtroStatusOS, setFiltroStatusOS] = useState<string>("todos");
  const [filtroOrigemAtendimentoOS, setFiltroOrigemAtendimentoOS] = useState<string>("todos");
  const [filtroClinicaOS, setFiltroClinicaOS] = useState<string>("todos");
  const [filtroServicoOS, setFiltroServicoOS] = useState<string>("todos");
  const [filtroTipoHorarioOS, setFiltroTipoHorarioOS] = useState<string>("todos");
  const [filtroDataInicio, setFiltroDataInicio] = useState("");
  const [filtroDataFim, setFiltroDataFim] = useState("");
  const [busca, setBusca] = useState("");
  const [buscaTransacoes, setBuscaTransacoes] = useState("");
  const [totalTransacoes, setTotalTransacoes] = useState(0);
  const [paginaTransacoes, setPaginaTransacoes] = useState({ chave: "", numero: 0 });
  const chaveTransacoes = JSON.stringify([
    filtroTipo, filtroCategoria, filtroFormaPagamento, filtroStatusTransacao,
    filtroDataInicio, filtroDataFim, buscaTransacoes,
  ]);
  const paginaAtualTransacoes = paginaTransacoes.chave === chaveTransacoes ? paginaTransacoes.numero : 0;
  const [chaveResultadoTransacoes, setChaveResultadoTransacoes] = useState("");
  const chavePedidoTransacoes = `${chaveTransacoes}:${paginaAtualTransacoes}`;
  const buscaTransacoesPendente = busca.trim() !== buscaTransacoes;

  useEffect(() => {
    setPaginaTransacoes((current) => current.chave === chaveTransacoes ? current : { chave: chaveTransacoes, numero: 0 });
  }, [chaveTransacoes]);

  useEffect(() => {
    const timer = window.setTimeout(() => setBuscaTransacoes(busca.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [busca]);
  const [abaAtiva, setAbaAtiva] = useState<FinanceiroActiveTab>("transacoes");
  const [paginaOrdens, setPaginaOrdens] = useState({ chave: "", numero: 0 });
  const chaveOrdens = JSON.stringify([filtroStatusOS, filtroOrigemAtendimentoOS,
    filtroClinicaOS, filtroServicoOS, filtroTipoHorarioOS, filtroDataInicio, filtroDataFim, buscaTransacoes, osAlvoId]);
  const paginaAtualOrdens = paginaOrdens.chave === chaveOrdens ? paginaOrdens.numero : 0;
  const [chaveResultadoOrdens, setChaveResultadoOrdens] = useState("");
  const chavePedidoOrdens = `${chaveOrdens}:${paginaAtualOrdens}`;
  const [paginaCobrancas, setPaginaCobrancas] = useState({ chave: "", numero: 0 });
  const paginaAtualCobrancas = paginaCobrancas.chave === chaveOrdens ? paginaCobrancas.numero : 0;
  const chavePedidoCobrancas = `${chaveOrdens}:${paginaAtualCobrancas}`;
  const [chaveResultadoCobrancas, setChaveResultadoCobrancas] = useState("");
  const cobrancasDesatualizadas = abaAtiva === "cobrancas" && (chavePedidoCobrancas !== chaveResultadoCobrancas || buscaTransacoesPendente);
  const ordensDesatualizadas = abaAtiva === "ordens" && (chaveResultadoOrdens !== chavePedidoOrdens || buscaTransacoesPendente);
  useEffect(() => {
    setPaginaOrdens((p) => p.chave === chaveOrdens ? p : { chave: chaveOrdens, numero: 0 });
  }, [chaveOrdens]);
  useEffect(() => {
    setPaginaCobrancas((p) => p.chave === chaveOrdens ? p : { chave: chaveOrdens, numero: 0 });
  }, [chaveOrdens]);
  const [rotaFinanceiroResolvida, setRotaFinanceiroResolvida] = useState(false);
  const [modalReceberOS, setModalReceberOS] = useState<OrdemServico | null>(null);
  const [modalDesfazerRecebimentoOS, setModalDesfazerRecebimentoOS] = useState<OrdemServico | null>(null);
  const [desfazendoRecebimentoOS, setDesfazendoRecebimentoOS] = useState(false);
  const desfazendoRecebimentoOSRef = useRef(false);
  const [erroDesfazerRecebimentoOS, setErroDesfazerRecebimentoOS] = useState("");
  const [mensagemDesfazerRecebimentoOS, setMensagemDesfazerRecebimentoOS] = useState("");
  const [modalReceberLoteOS, setModalReceberLoteOS] = useState<OrdemServico[] | null>(null);
  const [erroRecebimentoLoteOS, setErroRecebimentoLoteOS] = useState("");
  const [loteExigeRevisao, setLoteExigeRevisao] = useState(false);
  const [modalEditarOS, setModalEditarOS] = useState<OrdemServico | null>(null);
  const [modalAjustarValorOS, setModalAjustarValorOS] = useState<OrdemServico | null>(null);
  const [novoValorFinalOS, setNovoValorFinalOS] = useState("");
  const [motivoAjusteOS, setMotivoAjusteOS] = useState("");
  const [erroAjusteOS, setErroAjusteOS] = useState("");
  const [mensagemAjusteOS, setMensagemAjusteOS] = useState("");
  const [carregandoAjusteOS, setCarregandoAjusteOS] = useState(false);
  const [ajusteOSConferido, setAjusteOSConferido] = useState(false);
  const [salvandoAjusteOS, setSalvandoAjusteOS] = useState(false);
  const [formasPagamentoDisponiveis, setFormasPagamentoDisponiveis] = useState<FormaPagamentoConfig[]>(FORMA_PAGAMENTO_FALLBACK);
  const [carregandoFormasPagamento, setCarregandoFormasPagamento] = useState(false);
  const [pagamentosRecebimentoOS, setPagamentosRecebimentoOS] = useState<PagamentoRecebimentoItem[]>([]);
  const [dataRecebimentoOS, setDataRecebimentoOS] = useState("");
  const [destinoCreditoExcedenteOS, setDestinoCreditoExcedenteOS] = useState<"cliente" | "clinica" | "nenhum">("cliente");
  const [saldoCreditoClienteOS, setSaldoCreditoClienteOS] = useState(0);
  const [carregandoSaldoCreditoClienteOS, setCarregandoSaldoCreditoClienteOS] = useState(false);
  const [erroSaldoCreditoClienteOS, setErroSaldoCreditoClienteOS] = useState("");
  const [usarCreditoClienteOS, setUsarCreditoClienteOS] = useState(false);
  const [baixandoCredito, setBaixandoCredito] = useState(false);
  const [valorCreditoUtilizadoOS, setValorCreditoUtilizadoOS] = useState("0.00");
  const [enviarReciboPdfWhatsAppAposRecebimento, setEnviarReciboPdfWhatsAppAposRecebimento] = useState(false);
  const [salvandoOS, setSalvandoOS] = useState(false);
  const [clinicas, setClinicas] = useState<ClinicaOption[]>([]);
  const [servicos, setServicos] = useState<ServicoOption[]>([]);
  const [bandeirasCartao, setBandeirasCartao] = useState<BandeiraCartaoOption[]>([]);
  const [formEditarOS, setFormEditarOS] = useState({
    clinica_id: "",
    servico_id: "",
    tipo_horario: "comercial",
    desconto: 0,
    observacoes: "",
  });
  const [mensagemCobrancaModelo, setMensagemCobrancaModelo] = useState(MODELO_MENSAGEM_COBRANCA_PADRAO);
  const [mensagemReciboIndividualModelo, setMensagemReciboIndividualModelo] = useState(
    MODELO_MENSAGEM_RECIBO_INDIVIDUAL_PADRAO
  );
  const [mensagemReciboAgrupadoModelo, setMensagemReciboAgrupadoModelo] = useState(
    MODELO_MENSAGEM_RECIBO_AGRUPADO_PADRAO
  );
  const textareaMensagemRef = useRef<HTMLTextAreaElement | null>(null);
  const textareaMensagemReciboIndividualRef = useRef<HTMLTextAreaElement | null>(null);
  const textareaMensagemReciboAgrupadoRef = useRef<HTMLTextAreaElement | null>(null);
  const [osHighlightId, setOsHighlightId] = useState<number | null>(null);
  const [osHighlightUntil, setOsHighlightUntil] = useState<number>(0);
  const [osSelecionadasRecibo, setOsSelecionadasRecibo] = useState<number[]>([]);
  const [osSelecionadasBaixa, setOsSelecionadasBaixa] = useState<number[]>([]);
  const [recebendoLoteOS, setRecebendoLoteOS] = useState(false);
  const recebendoLoteOSRef = useRef(false);
  const [modalCompartilharRecibo, setModalCompartilharRecibo] = useState<CompartilhamentoReciboState | null>(null);
  const [enviandoCompartilhamentoRecibo, setEnviandoCompartilhamentoRecibo] = useState(false);
  const [previewRecibo, setPreviewRecibo] = useState<PreviewReciboState | null>(null);
  const [carregandoPreviewRecibo, setCarregandoPreviewRecibo] = useState(false);
  const [enviandoWhatsAppOficialOsId, setEnviandoWhatsAppOficialOsId] = useState<number | null>(null);
  const [enviandoWhatsAppOficialGrupoKey, setEnviandoWhatsAppOficialGrupoKey] = useState<string | null>(null);
  const highlightedRowRef = useRef<HTMLDivElement | null>(null);
  const ajusteRequestIdRef = useRef(0);
  const carregarDadosControllerRef = useRef<AbortController | null>(null);
  const carregarCobrancasControllerRef = useRef<AbortController | null>(null);
  /** Periodo do ultimo resumo aplicado com sucesso. Evita refazer a chamada a
   *  cada troca de pagina, filtro ou aba, que nao mudam o resumo. */
  const periodoResumoCarregadoRef = useRef<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    return () => {
      if (previewRecibo?.url) {
        window.URL.revokeObjectURL(previewRecibo.url);
      }
    };
  }, [previewRecibo]);

  useEffect(() => {
    if (!rotaFinanceiroResolvida) return;
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarDados("efeito");
    return () => {
      carregarDadosControllerRef.current?.abort();
      carregarCobrancasControllerRef.current?.abort();
      grupoControllerRef.current?.abort();
    };
  }, [
    router,
    rotaFinanceiroResolvida,
    abaAtiva,
    periodo,
    filtroTipo,
    filtroCategoria,
    filtroFormaPagamento,
    filtroStatusTransacao,
    filtroStatusOS,
    filtroOrigemAtendimentoOS,
    filtroClinicaOS,
    filtroServicoOS,
    filtroTipoHorarioOS,
    filtroDataInicio,
    filtroDataFim,
    paginaAtualTransacoes,
    buscaTransacoes,
    paginaAtualOrdens,
    paginaAtualCobrancas,
    osAlvoId,
  ]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const searchParams = new URLSearchParams(window.location.search);
    const abaParam = String(searchParams.get("aba") || "").toLowerCase();
    if (abaParam === "transacoes" || abaParam === "cobrancas" || abaParam === "ordens") {
      setAbaAtiva(abaParam as FinanceiroActiveTab);
    }

    const osIdParam = Number(searchParams.get("os_id") || "");
    if (Number.isFinite(osIdParam) && osIdParam > 0) {
      setAbaAtiva("ordens");
      setFiltroStatusOS("todos");
      setFiltroOrigemAtendimentoOS("todos");
      setFiltroClinicaOS("todos");
      setFiltroServicoOS("todos");
      setFiltroTipoHorarioOS("todos");
      setFiltroDataInicio("");
      setFiltroDataFim("");
      setBusca("");
      setOsHighlightId(osIdParam);
      setOsAlvoId(osIdParam);
      setOsHighlightUntil(Date.now() + 25000);
    }
    setRotaFinanceiroResolvida(true);
  }, []);

  useEffect(() => {
    if (!modalReceberOS) {
      setSaldoCreditoClienteOS(0);
      setCarregandoSaldoCreditoClienteOS(false);
      setErroSaldoCreditoClienteOS("");
      return;
    }

    const pacienteId = Number(modalReceberOS.paciente_id || 0);
    if (!Number.isFinite(pacienteId) || pacienteId <= 0) {
      setSaldoCreditoClienteOS(0);
      setCarregandoSaldoCreditoClienteOS(false);
      setErroSaldoCreditoClienteOS("");
      return;
    }

    let ativo = true;
    setCarregandoSaldoCreditoClienteOS(true);
    setErroSaldoCreditoClienteOS("");
    (async () => {
      try {
        const saldo = await consultarSaldoCreditoCliente({ pacienteId });
        if (!ativo) return;
        setSaldoCreditoClienteOS(saldo > 0 ? saldo : 0);
      } catch (error) {
        console.error("Erro ao consultar credito do cliente no financeiro:", error);
        if (!ativo) return;
        setSaldoCreditoClienteOS(0);
        setErroSaldoCreditoClienteOS("Nao foi possivel consultar o credito do cliente.");
      } finally {
        if (!ativo) return;
        setCarregandoSaldoCreditoClienteOS(false);
      }
    })();

    return () => {
      ativo = false;
    };
  }, [modalReceberOS]);

  const montarQueryString = (params: Record<string, string | number | undefined>) => {
    const query = new URLSearchParams();
    for (const [chave, valor] of Object.entries(params)) {
      if (valor === undefined || valor === null || valor === "") {
        continue;
      }
      query.set(chave, String(valor));
    }
    const encoded = query.toString();
    return encoded ? `?${encoded}` : "";
  };

  const filtrosRemotosOS = () => ({
    status: filtroStatusOS !== "todos" ? filtroStatusOS : undefined,
    origem_atendimento: filtroOrigemAtendimentoOS !== "todos" ? filtroOrigemAtendimentoOS : undefined,
    clinica_id: filtroClinicaOS !== "todos" ? filtroClinicaOS : undefined,
    servico_id: filtroServicoOS !== "todos" ? filtroServicoOS : undefined,
    tipo_horario: filtroTipoHorarioOS !== "todos" ? filtroTipoHorarioOS : undefined,
    data_inicio: filtroDataInicio || undefined,
    data_fim: filtroDataFim || undefined,
    search: buscaTransacoes || undefined,
  });

  const fecharGrupo = () => {
    grupoControllerRef.current?.abort();
    grupoControllerRef.current = null;
    selecaoEpochRef.current++;
    setGrupoAberto(null);
    setOrdensPagina([]);
    setOrdensServico([]);
    setOsSelecionadasBaixa([]);
    setOsSelecionadasRecibo([]);
    setCarregandoGrupo(false);
    setErroGrupo("");
  };

  const abrirDetalhesGrupo = async (grupo: BillingGroup) => {
    if (loadingOrdens || cobrancasDesatualizadas || validandoSelecao) return;
    fecharGrupo();
    const controller = new AbortController();
    grupoControllerRef.current = controller;
    setGrupoAberto(grupo.chave);
    setCarregandoGrupo(true);
    let expirou = false;
    const timer = window.setTimeout(() => { expirou = true; controller.abort(); }, 30000);
    try {
      const items = await loadCompleteBillingGroup<OrdemServico>(grupo, async (skip, limit) => {
        const query = montarQueryString({ ...filtrosRemotosOS(), destinatario_chave: grupo.chave, skip, limit, incluir_resumo: "true" });
        return (await api.get(`/ordens-servico${query}`, { signal: controller.signal })).data;
      }, controller.signal);
      if (controller.signal.aborted || grupoControllerRef.current !== controller) return;
      if (items.some((os) => obterContatoDestinatarioDaOS(os).chave !== grupo.chave)) {
        throw new Error("Destinatario inconsistente. Atualize a lista e tente novamente.");
      }
      setOrdensPagina(items);
      setOrdensServico(items);
      setGrupoAberto(grupo.chave);
    } catch (error) {
      if (grupoControllerRef.current === controller) setErroGrupo(expirou
        ? "Tempo de leitura excedido. Restrinja os filtros ou tente abrir novamente."
        : error instanceof Error ? error.message : "Falha ao abrir destinatario. Tente novamente.");
    } finally {
      window.clearTimeout(timer);
      if (grupoControllerRef.current === controller) { setCarregandoGrupo(false); grupoControllerRef.current = null; }
    }
  };

  const recarregarCobrancas = async () => {
    carregarCobrancasControllerRef.current?.abort();
    const controller = new AbortController();
    carregarCobrancasControllerRef.current = controller;
    const chavePedido = chavePedidoCobrancas;

    fecharGrupo();
    setLoadingOrdens(true);
    setFalhasCarregamento((current) => removeLoadFailure(current, "Cobrancas"));

    try {
      const data = (
        await api.get<{
          items: BillingGroup[];
          total: number;
          total_os: number;
          pendentes: number;
          total_pendente: number;
        }>(
          `/ordens-servico/cobrancas${montarQueryString({
            ...filtrosRemotosOS(),
            limit: 50,
            skip: paginaAtualCobrancas * 50,
          })}`,
          { signal: controller.signal }
        )
      ).data;

      if (controller.signal.aborted || carregarCobrancasControllerRef.current !== controller) return;
      if (!Array.isArray(data.items) || !Number.isInteger(data.total) || data.total < 0 ||
        !Number.isInteger(data.pendentes) || !Number.isFinite(data.total_pendente)) {
        throw new Error("Resposta de cobrancas sem totais validos.");
      }

      setGruposRemotos(data.items);
      setTotalGrupos(data.total);
      setTotalOrdens(data.total_os);
      setResumoOrdens({ pendentes: data.pendentes, valor_pendente: data.total_pendente });
      setChaveResultadoCobrancas(chavePedido);
      setOrdensCarregadas(true);
      if (paginaAtualCobrancas > 0 && !data.items.length) {
        setPaginaCobrancas({
          chave: chaveOrdens,
          numero: Math.max(0, Math.ceil(data.total / 50) - 1),
        });
      }
      return data.items;
    } catch (error) {
      if (!controller.signal.aborted && carregarCobrancasControllerRef.current === controller) {
        console.error("Erro ao carregar Cobrancas:", error);
        setFalhasCarregamento((current) => appendUniqueLoadFailure(current, "Cobrancas"));
      }
    } finally {
      if (carregarCobrancasControllerRef.current === controller) {
        setLoadingOrdens(false);
        carregarCobrancasControllerRef.current = null;
      }
    }
  };

  const carregarDados = async (origem: FinanceiroLoadOrigin = "manual") => {
    carregarDadosControllerRef.current?.abort();
    carregarCobrancasControllerRef.current?.abort();
    const controller = new AbortController();
    carregarDadosControllerRef.current = controller;
    const loadingPlan = getFinanceiroLoadingPlan(abaAtiva);

    setLoadingTransacoes(loadingPlan.transacoes);
    setLoadingOrdens(loadingPlan.ordens);
    setCarregandoFormasPagamento(true);
    setFalhasCarregamento([]);

    const registrarCarga = async <T,>(
      section: string,
      request: Promise<T>,
      onSuccess: (value: T) => void,
      onSettled?: () => void
    ) => {
      const result = await loadFinanceiroSection({
        section,
        request,
        signal: controller.signal,
        onSuccess,
        onSettled,
      });

      if (result.status === "failed" && carregarDadosControllerRef.current === controller) {
        console.error(`Erro ao carregar ${section}:`, result.error);
        setFalhasCarregamento((current) => appendUniqueLoadFailure(current, section));
      }

      return result;
    };

    try {
      const queryTransacoes = montarQueryString({
        limit: 100,
        skip: paginaAtualTransacoes * 100,
        search: buscaTransacoes || undefined,
        tipo: filtroTipo !== "todos" ? filtroTipo : undefined,
        categoria: filtroCategoria !== "todos" ? filtroCategoria : undefined,
        forma_pagamento: filtroFormaPagamento !== "todos" ? filtroFormaPagamento : undefined,
        status: filtroStatusTransacao !== "todos" ? filtroStatusTransacao : undefined,
        data_inicio: filtroDataInicio || undefined,
        data_fim: filtroDataFim || undefined,
      });
      const queryOS = montarQueryString({
        limit: abaAtiva === "ordens" ? 100 : 500,
        skip: abaAtiva === "ordens" ? paginaAtualOrdens * 100 : undefined,
        search: abaAtiva === "ordens" ? buscaTransacoes || undefined : undefined,
        incluir_resumo: abaAtiva === "ordens" ? "true" : undefined,
        os_id: abaAtiva === "ordens" ? osAlvoId || undefined : undefined,
        status: filtroStatusOS !== "todos" ? filtroStatusOS : undefined,
        origem_atendimento: filtroOrigemAtendimentoOS !== "todos" ? filtroOrigemAtendimentoOS : undefined,
        clinica_id: filtroClinicaOS !== "todos" ? filtroClinicaOS : undefined,
        servico_id: filtroServicoOS !== "todos" ? filtroServicoOS : undefined,
        tipo_horario: filtroTipoHorarioOS !== "todos" ? filtroTipoHorarioOS : undefined,
        data_inicio: filtroDataInicio || undefined,
        data_fim: filtroDataFim || undefined,
      });

      const signal = controller.signal;
      const cargaTransacoes = loadingPlan.transacoes
        ? registrarCarga(
            "Transacoes",
            api
              .get<{ items?: Transacao[]; total: number }>(`/financeiro/transacoes${queryTransacoes}`, { signal })
              .then((response) => response.data),
            (data) => {
              setTransacoes(data.items || []);
              setTotalTransacoes(data.total);
              setChaveResultadoTransacoes(chavePedidoTransacoes);
              // A deletion or concurrent update can remove the last page.
              if (paginaAtualTransacoes > 0 && !data.items?.length) {
                setPaginaTransacoes({ chave: chaveTransacoes, numero: Math.max(0, Math.ceil(data.total / 100) - 1) });
              }
              setTransacoesCarregadas(true);
            },
            () => setLoadingTransacoes(false)
          )
        : Promise.resolve();
      // O resumo so varia com `periodo`. Sem esta guarda ele era refeito a cada
      // troca de pagina, filtro ou aba, sempre devolvendo o mesmo valor.
      const cargaResumo = deveRecarregarResumo({
        origem,
        periodoAtual: periodo,
        periodoCarregado: periodoResumoCarregadoRef.current,
      })
        ? registrarCarga(
            "Resumo financeiro",
            api.get<Resumo>(`/financeiro/resumo?periodo=${periodo}`, { signal }).then((response) => response.data),
            (data) => {
              setResumo(data);
              // So marca depois do sucesso: falha ou cancelamento deixa o
              // proximo carregamento tentar de novo.
              periodoResumoCarregadoRef.current = periodo;
            }
          )
        : Promise.resolve();
      const cargaOrdens = loadingPlan.ordens && abaAtiva === "ordens"
        ? registrarCarga(
            "Ordens de servico",
            api
              .get<{ items?: OrdemServico[]; total: number; resumo?: {pendentes: number; valor_pendente: number} }>(`/ordens-servico${queryOS}`, { signal })
              .then((response) => response.data),
            (data) => {
              if (abaAtiva === "ordens" && (!Number.isInteger(data.total) || data.total < 0 ||
                  !data.resumo || !Number.isFinite(data.resumo.valor_pendente) || !Number.isInteger(data.resumo.pendentes))) {
                throw new Error("Resposta de OS sem totais validos. Confira a versao do backend.");
              }
              const items = data.items || [];
              setOrdensPagina(items);
              // Retain selected snapshots outside this page; visible rows stay separate.
              setOrdensServico((prev) => Array.from(new Map([
                ...items,
                ...prev.filter((os) => osSelecionadasBaixa.includes(os.id) || osSelecionadasRecibo.includes(os.id)),
              ].map((os) => [os.id, os])).values()));
              setTotalOrdens(data.total);
              if (data.resumo) setResumoOrdens(data.resumo);
              setChaveResultadoOrdens(chavePedidoOrdens);
              if (abaAtiva === "ordens" && paginaAtualOrdens > 0 && !items.length) {
                setPaginaOrdens({ chave: chaveOrdens, numero: Math.max(0, Math.ceil(data.total / 100) - 1) });
              }
              setOrdensCarregadas(true);
            },
            () => setLoadingOrdens(false)
          )
        : Promise.resolve();
      const cargaGrupos = abaAtiva === "cobrancas" ? recarregarCobrancas() : Promise.resolve();
      const cargaClinicas = loadingPlan.catalogosOrdens
        ? registrarCarga(
            "Clinicas",
            loadStableCatalog({
              catalog: "clinicas",
              variant: "limit=1000",
              load: () => api.get<{ items?: ClinicaOption[] }>("/clinicas?limit=1000").then((response) => response.data),
            }),
            (data) => setClinicas(data.items || [])
          )
        : Promise.resolve();
      const cargaServicos = loadingPlan.catalogosOrdens
        ? registrarCarga(
            "Servicos",
            loadStableCatalog({
              catalog: "servicos",
              variant: "limit=1000",
              load: () => api.get<{ items?: ServicoOption[] }>("/servicos?limit=1000").then((response) => response.data),
            }),
            (data) => setServicos(data.items || [])
          )
        : Promise.resolve();
      const cargaFormas = registrarCarga(
        "Formas de pagamento",
        api
          .get<{ items?: any[] }>("/financeiro/formas-pagamento", {
            params: { apenas_ativas: true, limit: 300 },
            signal,
          })
          .then((response) => response.data),
        (data) => {
          const formasApi = Array.isArray(data.items) ? data.items : [];
          if (formasApi.length === 0) {
            setFormasPagamentoDisponiveis(FORMA_PAGAMENTO_FALLBACK);
            return;
          }

          const normalizadas: FormaPagamentoConfig[] = formasApi.map((item: any) => ({
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
          setFormasPagamentoDisponiveis(normalizadas);
        }
      );
      const cargaBandeiras = registrarCarga(
        "Bandeiras de cartao",
        api
          .get<{ items?: BandeiraCartaoOption[] }>("/financeiro/bandeiras-cartao", {
            params: { ativo: true, limit: 300 },
            signal,
          })
          .then((response) => response.data),
        (data) => setBandeirasCartao(data.items || [])
      );
      const cargaMeiosPagamento = Promise.all([cargaFormas, cargaBandeiras]).finally(() => {
        if (!controller.signal.aborted && carregarDadosControllerRef.current === controller) {
          setCarregandoFormasPagamento(false);
        }
      });

      await Promise.all([
        cargaTransacoes,
        cargaResumo,
        cargaOrdens,
        cargaGrupos,
        cargaClinicas,
        cargaServicos,
        cargaMeiosPagamento,
      ]);
    } finally {
      if (!controller.signal.aborted && carregarDadosControllerRef.current === controller) {
        setLoadingTransacoes(false);
        if (abaAtiva !== "cobrancas") setLoadingOrdens(false);
        setCarregandoFormasPagamento(false);
        carregarDadosControllerRef.current = null;
      }
    }
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

  const formatarValor = (valor: number) => {
    return valor?.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) || 'R$ 0,00';
  };

  const formatarData = (data: string) => {
    return formatCalendarDate(data);
  };

  const formatarDataHoraCurta = (data: string) => {
    if (!data) return "-";
    return new Date(data).toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const hojeLocalISO = () => {
    return operationalTodayDateInput();
  };

  const normalizarDataISO = (valor?: string | null) => {
    return calendarDateInput(valor);
  };

  const estaNoPeriodo = (valor?: string | null) => {
    if (!filtroDataInicio && !filtroDataFim) return true;
    const data = normalizarDataISO(valor);
    if (!data) return false;
    if (filtroDataInicio && data < filtroDataInicio) return false;
    if (filtroDataFim && data > filtroDataFim) return false;
    return true;
  };

  const limparFiltros = () => {
    setBusca("");
    setFiltroTipo("todos");
    setFiltroCategoria("todos");
    setFiltroFormaPagamento("todos");
    setFiltroStatusTransacao("todos");
    setFiltroStatusOS("todos");
    setFiltroOrigemAtendimentoOS("todos");
    setFiltroClinicaOS("todos");
    setFiltroServicoOS("todos");
    setFiltroTipoHorarioOS("todos");
    setFiltroDataInicio("");
    setFiltroDataFim("");
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'Pago':
      case 'Recebido':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'Pendente':
        return <Clock className="w-4 h-4 text-yellow-500" />;
      case 'Cancelado':
        return <XCircle className="w-4 h-4 text-red-500" />;
      default:
        return <Clock className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'Pago':
      case 'Recebido':
        return 'bg-green-100 text-green-800';
      case 'Pendente':
        return 'bg-yellow-100 text-yellow-800';
      case 'Cancelado':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getCategoriaNome = (categoria: string) => {
    const categorias: Record<string, string> = {
      consulta: "Consulta",
      exame: "Exame",
      cirurgia: "Cirurgia",
      medicamento: "Medicamento",
      banho_tosa: "Banho e Tosa",
      produto: "Produto",
      salario: "Salario",
      aluguel: "Aluguel",
      fornecedor: "Fornecedor",
      imposto: "Imposto",
      manutencao: "Manutencao",
      marketing: "Marketing",
      outros: "Outros",
    };
    return categorias[categoria] || categoria;
  };

  const getFormaPagamentoNome = (forma: string) => {
    const codigo = normalizarCodigoFormaPagamento(forma);
    const configurada = formasPagamentoDisponiveis.find(
      (item) => normalizarCodigoFormaPagamento(item.codigo) === codigo
    );
    if (configurada) {
      return descricaoFormaPagamentoConfig(configurada);
    }
    const formas: Record<string, string> = {
      dinheiro: "Dinheiro",
      cartao_credito: "Cartao Credito",
      cartao_debito: "Cartao Debito",
      pix: "PIX",
      boleto: "Boleto",
      transferencia: "Transferencia",
    };
    return formas[forma] || forma;
  };

  const obterFormaPagamentoPadraoCodigo = () => {
    const formaPadrao =
      formasPagamentoDisponiveis.find(
        (forma) => normalizarCodigoFormaPagamento(forma.codigo) === FORMA_PAGAMENTO_PADRAO
      ) || formasPagamentoDisponiveis[0];
    return normalizarCodigoFormaPagamento(formaPadrao?.codigo || FORMA_PAGAMENTO_PADRAO);
  };

  const resumoPagamentoOS = useMemo(() => {
    const linhas = pagamentosRecebimentoOS.map((item) => {
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
    const valorOS = Number(modalReceberOS?.valor_final || 0);
    const limiteCredito = Math.max(0, Number(saldoCreditoClienteOS || 0));
    const creditoSolicitado = parseMoneyValue(valorCreditoUtilizadoOS);
    const creditoUtilizado = usarCreditoClienteOS
      ? Math.max(0, Math.min(creditoSolicitado, limiteCredito))
      : 0;
    const totalCoberto = Number((totalBruto + creditoUtilizado).toFixed(2));
    const diferenca = Number((totalCoberto - valorOS).toFixed(2));
    return {
      linhas,
      totalBruto,
      totalTaxa,
      totalLiquido,
      totalCoberto,
      valorOS,
      limiteCredito,
      creditoSolicitado,
      creditoUtilizado,
      excedente: diferenca > 0 ? diferenca : 0,
      faltante: diferenca < 0 ? Math.abs(diferenca) : 0,
    };
  }, [
    formasPagamentoDisponiveis,
    modalReceberOS?.valor_final,
    pagamentosRecebimentoOS,
    saldoCreditoClienteOS,
    usarCreditoClienteOS,
    valorCreditoUtilizadoOS,
  ]);

  // Preserve the complete reviewed batch even if a refresh changes its orders.
  const ordensRecebimentoLote = useMemo(() => modalReceberLoteOS || [], [modalReceberLoteOS]);

  const recebimentoLoteMesmoDestinatario = useMemo(() => {
    const chaves = new Set(
      ordensRecebimentoLote.map((os) =>
        os.origem_atendimento === "domiciliar"
          ? `tutor:${os.tutor_id ?? "sem-tutor"}`
          : `clinica:${os.clinica_id ?? "sem-clinica"}`
      )
    );
    return ordensRecebimentoLote.length > 0 && chaves.size === 1;
  }, [ordensRecebimentoLote]);
  const permiteReciboWhatsAppLote = recebimentoLoteMesmoDestinatario && ordensRecebimentoLote.length <= 20;

  const resumoPagamentoLoteOS = useMemo(() => {
    const linhas = pagamentosRecebimentoOS.map((item) => {
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
    const valorOS = ordensRecebimentoLote.reduce((acc, os) => acc + Number(os.valor_final || 0), 0);
    const diferenca = Number((totalBruto - valorOS).toFixed(2));
    return {
      linhas,
      totalBruto,
      totalTaxa,
      totalLiquido,
      totalCoberto: totalBruto,
      valorOS,
      excedente: diferenca > 0 ? diferenca : 0,
      faltante: diferenca < 0 ? Math.abs(diferenca) : 0,
    };
  }, [formasPagamentoDisponiveis, ordensRecebimentoLote, pagamentosRecebimentoOS]);

  const atualizarLinhaPagamentoOS = (id: string, campo: "forma_codigo" | "valor", valor: string) => {
    setPagamentosRecebimentoOS((prev) =>
      prev.map((item) => (item.id === id ? { ...item, [campo]: valor } : item))
    );
  };

  const adicionarLinhaPagamentoOS = () => {
    const codigo = obterFormaPagamentoPadraoCodigo();
    setPagamentosRecebimentoOS((prev) => [
      ...prev,
      {
        id: gerarPagamentoId(),
        forma_codigo: codigo,
        valor: "0.00",
      },
    ]);
  };

  const removerLinhaPagamentoOS = (id: string) => {
    setPagamentosRecebimentoOS((prev) => {
      if (prev.length <= 1) return prev;
      return prev.filter((item) => item.id !== id);
    });
  };

  const cadastrarBandeiraRapido = async () => {
    const nome = window.prompt("Nome da bandeira (ex.: Visa):");
    if (!nome) return;
    const codigoSugerido = normalizarCodigoFormaPagamento(nome);
    const codigo = window.prompt("Codigo da bandeira:", codigoSugerido);
    if (!codigo) return;
    try {
      await api.post("/financeiro/bandeiras-cartao", {
        nome: nome.trim(),
        codigo: normalizarCodigoFormaPagamento(codigo),
        ativo: true,
      });
      alert("Bandeira cadastrada com sucesso.");
      await carregarDados();
    } catch (error: any) {
      console.error("Erro ao cadastrar bandeira:", error);
      alert("Nao foi possivel cadastrar bandeira: " + (error.response?.data?.detail || error.message));
    }
  };

  const cadastrarFormaPagamentoRapido = async () => {
    const nome = window.prompt("Nome da forma de pagamento (ex.: Cartao credito - TON):");
    if (!nome) return;
    const codigoSugerido = normalizarCodigoFormaPagamento(nome);
    const codigo = window.prompt("Codigo unico da forma de pagamento:", codigoSugerido);
    if (!codigo) return;
    const tipo = window
      .prompt("Tipo (dinheiro, pix, cartao_credito, cartao_debito, boleto, transferencia, credito, outro):", "pix")
      ?.trim();
    if (!tipo) return;
    const adquirente = window.prompt("Adquirente/maquininha (opcional):", "") || "";
    const taxaPercentualStr = window.prompt("Taxa percentual (ex.: 4.99):", "0") || "0";
    const taxaFixaStr = window.prompt("Taxa fixa em R$ (ex.: 0.40):", "0") || "0";
    const ordemStr = window.prompt("Ordem de exibicao (numero):", "0") || "0";

    const bandeirasTexto = bandeirasCartao.map((b) => `${b.id}=${b.nome}`).join(" | ");
    const bandeiraIdStr = window.prompt(
      bandeirasTexto
        ? `ID da bandeira (opcional). Disponiveis: ${bandeirasTexto}`
        : "ID da bandeira (opcional):",
      ""
    );
    const bandeiraId = bandeiraIdStr ? Number(bandeiraIdStr) : null;

    try {
      await api.post("/financeiro/formas-pagamento", {
        nome: nome.trim(),
        codigo: normalizarCodigoFormaPagamento(codigo),
        tipo: normalizarCodigoFormaPagamento(tipo),
        adquirente: adquirente.trim() || null,
        bandeira_id: Number.isFinite(bandeiraId as number) && (bandeiraId as number) > 0 ? Number(bandeiraId) : null,
        taxa_percentual: Number.parseFloat(taxaPercentualStr.replace(",", ".")) || 0,
        taxa_fixa: Number.parseFloat(taxaFixaStr.replace(",", ".")) || 0,
        ordem_exibicao: Number.parseInt(ordemStr, 10) || 0,
        ativo: true,
      });
      alert("Forma de pagamento cadastrada com sucesso.");
      await carregarDados();
    } catch (error: any) {
      console.error("Erro ao cadastrar forma de pagamento:", error);
      alert("Nao foi possivel cadastrar forma: " + (error.response?.data?.detail || error.message));
    }
  };

  const desativarFormaPagamento = async (formaId?: number) => {
    if (!formaId) return;
    if (!confirm("Desativar esta forma de pagamento?")) return;
    try {
      await api.delete(`/financeiro/formas-pagamento/${formaId}`);
      await carregarDados();
    } catch (error: any) {
      console.error("Erro ao desativar forma de pagamento:", error);
      alert("Nao foi possivel desativar: " + (error.response?.data?.detail || error.message));
    }
  };

  const editarTaxasFormaPagamento = async (forma: FormaPagamentoConfig) => {
    if (!forma.id) return;
    const taxaPercentualAtual = Number(forma.taxa_percentual || 0).toFixed(2);
    const taxaPercentualStr = window.prompt(
      `Taxa percentual (%) para "${forma.nome}":`,
      taxaPercentualAtual
    );
    if (taxaPercentualStr === null) return;

    const taxaFixaAtual = Number(forma.taxa_fixa || 0).toFixed(2);
    const taxaFixaStr = window.prompt(
      `Taxa fixa (R$) para "${forma.nome}":`,
      taxaFixaAtual
    );
    if (taxaFixaStr === null) return;

    const taxaPercentual = Number.parseFloat(String(taxaPercentualStr).replace(",", "."));
    const taxaFixa = Number.parseFloat(String(taxaFixaStr).replace(",", "."));
    if (!Number.isFinite(taxaPercentual) || taxaPercentual < 0) {
      alert("Taxa percentual invalida.");
      return;
    }
    if (!Number.isFinite(taxaFixa) || taxaFixa < 0) {
      alert("Taxa fixa invalida.");
      return;
    }

    try {
      await api.put(`/financeiro/formas-pagamento/${forma.id}`, {
        taxa_percentual: Number(taxaPercentual.toFixed(4)),
        taxa_fixa: Number(taxaFixa.toFixed(2)),
      });
      await carregarDados();
      alert("Taxas atualizadas com sucesso.");
    } catch (error: any) {
      console.error("Erro ao atualizar taxas da forma de pagamento:", error);
      alert("Nao foi possivel atualizar as taxas: " + (error.response?.data?.detail || error.message));
    }
  };

  const handleEditar = (transacao: Transacao) => {
    setTransacaoEditando(transacao);
    setModalAberto(true);
  };

  const handleNova = () => {
    setTransacaoEditando(null);
    setModalAberto(true);
  };

  const handleExcluir = async (id: number) => {
    if (!confirm("Tem certeza que deseja excluir esta transacao?")) return;

    try {
      await api.delete(`/financeiro/transacoes/${id}`);
      carregarDados();
    } catch (error) {
      console.error("Erro ao excluir:", error);
      alert("Erro ao excluir transacao");
    }
  };

  const handlePagar = async (id: number) => {
    try {
      await api.patch(`/financeiro/transacoes/${id}/pagar`);
      carregarDados();
    } catch (error) {
      console.error("Erro ao pagar:", error);
      alert("Erro ao atualizar status");
    }
  };

  const handlePagarOS = (os: OrdemServico) => {
    setModalReceberOS(os);
    const codigo = obterFormaPagamentoPadraoCodigo();
    setPagamentosRecebimentoOS([
      {
        id: gerarPagamentoId(),
        forma_codigo: codigo,
        valor: toMoneyInput(Number(os.valor_final || 0)),
      },
    ]);
    setDataRecebimentoOS(hojeLocalISO());
    setDestinoCreditoExcedenteOS("cliente");
    setSaldoCreditoClienteOS(0);
    setCarregandoSaldoCreditoClienteOS(false);
    setErroSaldoCreditoClienteOS("");
    setUsarCreditoClienteOS(false);
    setValorCreditoUtilizadoOS("0.00");
    setEnviarReciboPdfWhatsAppAposRecebimento(false);
  };

  const validarSelecao = async (ids: number[], status: string, snapshots = ordensServico) => {
    if (validandoSelecaoRef.current) return false;
    validandoSelecaoRef.current = true;
    setValidandoSelecao(true);
    const epoch = selecaoEpochRef.current;
    setErroSelecao("");
    try {
      await validateOrderSelection(ids, snapshots, status, async (id) =>
        (await api.get<OrdemServico>(`/ordens-servico/${id}`)).data);
      return epoch === selecaoEpochRef.current;
    } catch (error) {
      setErroSelecao(error instanceof Error ? error.message : "Nao foi possivel conferir a selecao. Tente novamente.");
      return false;
    } finally {
      validandoSelecaoRef.current = false;
      setValidandoSelecao(false);
    }
  };

  const abrirRecebimentoLoteOS = async (ids: number[]) => {
    const idsPendentes = Array.from(new Set(ids));
    if (idsPendentes.length === 0) {
      alert("Selecione ao menos uma OS pendente para receber em lote.");
      return;
    }
    if (idsPendentes.length > 200) {
      setErroSelecao("Selecione no maximo 200 OS por recebimento em lote.");
      return;
    }
    if (!(await validarSelecao(idsPendentes, "Pendente"))) return;

    const total = idsPendentes.reduce((acc, id) => {
      const os = ordensServico.find((item) => item.id === id);
      return acc + Number(os?.valor_final || 0);
    }, 0);

    setModalReceberLoteOS(idsPendentes.map((id) => ({ ...ordensServico.find((os) => os.id === id)! })));
    setErroRecebimentoLoteOS("");
    setLoteExigeRevisao(false);
    setPagamentosRecebimentoOS([
      {
        id: gerarPagamentoId(),
        forma_codigo: obterFormaPagamentoPadraoCodigo(),
        valor: toMoneyInput(total),
      },
    ]);
    setDataRecebimentoOS(hojeLocalISO());
    setDestinoCreditoExcedenteOS("cliente");
    setUsarCreditoClienteOS(false);
    setValorCreditoUtilizadoOS("0.00");
    setEnviarReciboPdfWhatsAppAposRecebimento(false);
  };

  const handleEditarOS = (os: OrdemServico) => {
    setModalEditarOS(os);
    setFormEditarOS({
      clinica_id: os.clinica_id ? String(os.clinica_id) : "",
      servico_id: os.servico_id ? String(os.servico_id) : "",
      tipo_horario: os.tipo_horario || "comercial",
      desconto: Number(os.desconto || 0),
      observacoes: os.observacoes || "",
    });
  };

  const fecharAjusteValorOS = () => {
    if (salvandoAjusteOS) return;
    ajusteRequestIdRef.current += 1;
    setModalAjustarValorOS(null);
    setErroAjusteOS("");
  };

  const abrirAjusteValorOS = async (os: OrdemServico) => {
    const requestId = ++ajusteRequestIdRef.current;
    setModalAjustarValorOS(os);
    setNovoValorFinalOS("");
    setMotivoAjusteOS("");
    setErroAjusteOS("");
    setMensagemAjusteOS("");
    setCarregandoAjusteOS(true);
    setAjusteOSConferido(false);
    try {
      const atual = (await api.get<OrdemServico>(`/ordens-servico/${os.id}`)).data;
      if (requestId !== ajusteRequestIdRef.current) return;
      setModalAjustarValorOS(atual);
      if (atual.status !== "Pendente") {
        setErroAjusteOS("Esta OS nao esta mais pendente. Atualize a lista antes de ajustar o valor.");
        return;
      }
      setNovoValorFinalOS(toMoneyInput(Number(atual.valor_final || 0)));
      setAjusteOSConferido(true);
    } catch (error: any) {
      if (requestId !== ajusteRequestIdRef.current) return;
      setErroAjusteOS(error?.userMessage || "Nao foi possivel conferir a OS. Feche o ajuste e tente novamente.");
    } finally {
      if (requestId === ajusteRequestIdRef.current) setCarregandoAjusteOS(false);
    }
  };

  const parseNovoValorFinalOS = (raw: string): number | null => {
    const normalizado = raw.trim().replace(",", ".");
    if (!/^\d+(?:\.\d{1,2})?$/.test(normalizado)) return null;
    const centavos = Math.round(Number(normalizado) * 100);
    if (!Number.isSafeInteger(centavos) || centavos <= 0 || centavos > 9_999_999_999) return null;
    return centavos / 100;
  };

  const recarregarOSComGrupoAberto = async () => {
    if (abaAtiva === "cobrancas") {
      const grupoAnterior = grupoAberto;
      const gruposAtualizados = await recarregarCobrancas();
      const grupoAtualizado = gruposAtualizados?.find((item) => item.chave === grupoAnterior);
      if (grupoAtualizado) await abrirDetalhesGrupo(grupoAtualizado);
    } else {
      await carregarDados();
    }
  };

  const confirmarAjusteValorOS = async () => {
    const os = modalAjustarValorOS;
    if (!os || !ajusteOSConferido || carregandoAjusteOS || salvandoAjusteOS) return;
    if (os.status !== "Pendente") {
      setErroAjusteOS("Esta OS nao esta mais pendente. Atualize a lista antes de ajustar o valor.");
      return;
    }
    const novoValor = parseNovoValorFinalOS(novoValorFinalOS);
    if (novoValor === null) {
      setErroAjusteOS("Informe um valor final maior que zero, com ate duas casas decimais.");
      return;
    }
    const valorAtual = Math.round(Number(os.valor_final || 0) * 100) / 100;
    const descontoCentavos = Math.round(Number(os.desconto || 0) * 100);
    if (Math.round(novoValor * 100) + descontoCentavos > 9_999_999_999) {
      setErroAjusteOS("O valor final somado ao desconto excede o limite permitido para a OS.");
      return;
    }
    if (novoValor === valorAtual) {
      setErroAjusteOS("O novo valor deve ser diferente do valor atual da OS.");
      return;
    }
    const motivo = motivoAjusteOS.trim();
    if (!motivo) {
      setErroAjusteOS("Informe o motivo do ajuste para registrar a alteracao.");
      return;
    }
    if (motivo.length > 500) {
      setErroAjusteOS("O motivo deve ter no maximo 500 caracteres.");
      return;
    }

    setErroAjusteOS("");
    setSalvandoAjusteOS(true);
    try {
      await api.patch(`/ordens-servico/${os.id}/ajustar-valor`, {
        valor_final_esperado: valorAtual,
        novo_valor_final: novoValor,
        motivo,
      });
      ajusteRequestIdRef.current += 1;
      setModalAjustarValorOS(null);
      setOsSelecionadasBaixa([]);
      selecaoEpochRef.current += 1;
      setMensagemAjusteOS(`Valor da OS ${os.numero_os} ajustado para ${formatarValor(novoValor)}.`);

      await recarregarOSComGrupoAberto();
      setOsHighlightId(os.id);
      setOsHighlightUntil(Date.now() + 25000);
    } catch (error: any) {
      if (error?.response?.status === 409) {
        setErroAjusteOS("Esta OS mudou desde a conferencia. Recarregue a OS e confira o valor antes de tentar novamente.");
      } else {
        const detalhe = error?.response?.data?.detail;
        const mensagem = typeof detalhe === "string" ? detalhe :
          Array.isArray(detalhe) ? detalhe.map((item: { msg?: string }) => item.msg).filter(Boolean).join("; ") : "";
        setErroAjusteOS(error?.userMessage || mensagem || "Nao foi possivel ajustar o valor da OS.");
      }
    } finally {
      setSalvandoAjusteOS(false);
    }
  };

  const confirmarRecebimentoOS = async () => {
    if (modalReceberOS && !(await validarSelecao([modalReceberOS.id], "Pendente", [modalReceberOS]))) return;
    if (!modalReceberOS) return;

    try {
      const pagamentosPayload = resumoPagamentoOS.linhas
        .filter((item) => item.valor > 0)
        .map((item) => ({
          forma_pagamento: normalizarCodigoFormaPagamento(item.forma_codigo),
          forma_pagamento_config_id: item.forma?.id ?? undefined,
          valor: Number(item.valor.toFixed(2)),
        }));
      const creditoUtilizado = Number(resumoPagamentoOS.creditoUtilizado || 0);
      if (pagamentosPayload.length === 0 && creditoUtilizado <= 0) {
        alert("Informe ao menos um pagamento com valor maior que zero ou utilize credito disponivel.");
        return;
      }
      await api.patch(`/ordens-servico/${modalReceberOS.id}/receber`, {
        pagamentos: pagamentosPayload,
        data_recebimento: dataRecebimentoOS || null,
        valor_final_esperado: Number(Number(modalReceberOS.valor_final || 0).toFixed(2)),
        valor_credito_utilizado: Number(creditoUtilizado.toFixed(2)),
        destino_credito_excedente: destinoCreditoExcedenteOS,
      });

      let avisoRecibo = "";
      if (enviarReciboPdfWhatsAppAposRecebimento) {
        try {
          await api.post(`/ordens-servico/${modalReceberOS.id}/whatsapp/recibo-pdf`, {
            idempotency_key: criarIdempotencyKeyWhatsApp("recibo-pdf", modalReceberOS.id),
          });
        } catch (error: any) {
          avisoRecibo =
            error.response?.data?.detail ||
            "O recebimento foi registrado, mas nao foi possivel enviar o recibo PDF pelo WhatsApp.";
        }
      }

      setModalReceberOS(null);
      setPagamentosRecebimentoOS([]);
      setSaldoCreditoClienteOS(0);
      setCarregandoSaldoCreditoClienteOS(false);
      setErroSaldoCreditoClienteOS("");
      setUsarCreditoClienteOS(false);
      setValorCreditoUtilizadoOS("0.00");
      setEnviarReciboPdfWhatsAppAposRecebimento(false);
      alert(
        avisoRecibo
          ? `Recebimento registrado com sucesso.\n\nAviso do WhatsApp: ${avisoRecibo}`
          : enviarReciboPdfWhatsAppAposRecebimento
            ? "Recebimento registrado e recibo PDF enviado pelo WhatsApp!"
            : "Recebimento registrado com sucesso!"
      );
      carregarDados();
    } catch (error: any) {
      console.error("Erro ao pagar OS:", error);
      if (error?.response?.status === 409) {
        setModalReceberOS(null);
        setPagamentosRecebimentoOS([]);
        setOsSelecionadasBaixa([]);
        setUsarCreditoClienteOS(false);
        setValorCreditoUtilizadoOS("0.00");
        setEnviarReciboPdfWhatsAppAposRecebimento(false);
        await recarregarOSComGrupoAberto();
        alert("O valor ou o estado da OS mudou. Nenhum recebimento foi registrado. Reabra a OS e confira o valor antes de tentar novamente.");
        return;
      }
      alert("Erro ao processar pagamento: " + (error.response?.data?.detail || error.message));
    }
  };

  const confirmarRecebimentoLoteOS = async () => {
    if (recebendoLoteOSRef.current || loteExigeRevisao || ordensRecebimentoLote.length === 0) return;

    const pagamentosPayload = resumoPagamentoLoteOS.linhas
      .filter((item) => item.valor > 0)
      .map((item) => ({
        forma_pagamento: normalizarCodigoFormaPagamento(item.forma_codigo),
        forma_pagamento_config_id: item.forma?.id ?? undefined,
        valor: Number(item.valor.toFixed(2)),
      }));
    if (pagamentosPayload.length === 0) {
      setErroRecebimentoLoteOS("Informe ao menos um pagamento com valor maior que zero.");
      return;
    }
    if (pagamentosPayload.length > 20) {
      setErroRecebimentoLoteOS("Informe no maximo 20 pagamentos por recebimento em lote.");
      return;
    }
    if (resumoPagamentoLoteOS.faltante > 0) {
      setErroRecebimentoLoteOS(`Falta cobrir ${formatarValor(resumoPagamentoLoteOS.faltante)} para receber as OS selecionadas.`);
      return;
    }
    if (resumoPagamentoLoteOS.excedente > 0) {
      setErroRecebimentoLoteOS("A baixa em lote precisa bater exatamente com o total das OS selecionadas. Ajuste o valor informado.");
      return;
    }

    const idsSelecionadas = ordensRecebimentoLote.map((os) => os.id);
    const orientarRevisao = "Confira a lista atualizada, feche este painel e selecione novamente as OS antes de outra tentativa.";
    const enviarReciboLote = enviarReciboPdfWhatsAppAposRecebimento && permiteReciboWhatsAppLote;
    const atualizarListaAposLote = async () => {
      try {
        await recarregarOSComGrupoAberto();
      } catch {
        const mensagem = "Nao foi possivel atualizar a lista. Recarregue as ordens antes de continuar.";
        setErroSelecao(mensagem);
        setErroRecebimentoLoteOS((atual) => atual ? `${atual} ${mensagem}` : atual);
      }
    };
    recebendoLoteOSRef.current = true;
    setRecebendoLoteOS(true);
    setErroRecebimentoLoteOS("");
    try {
      let idsRecebidas: number[];
      try {
        const response = await api.patch<{ os_ids: number[]; mensagem: string }>("/ordens-servico/receber-lote", {
          ordens: ordensRecebimentoLote.map((os) => ({
            os_id: os.id,
            valor_final_esperado: Number(os.valor_final).toFixed(2),
          })),
          pagamentos: pagamentosPayload,
          data_recebimento: dataRecebimentoOS || null,
        });
        idsRecebidas = response.data?.os_ids;
        const selecaoCompleta = Array.isArray(idsRecebidas)
          && idsRecebidas.length === idsSelecionadas.length
          && new Set(idsRecebidas).size === idsSelecionadas.length
          && idsRecebidas.every((id) => idsSelecionadas.includes(id));
        if (!selecaoCompleta) {
          setLoteExigeRevisao(true);
          setErroRecebimentoLoteOS(`Nao foi possivel confirmar o recebimento de todas as OS. O recibo nao foi solicitado. ${orientarRevisao}`);
          await atualizarListaAposLote();
          return;
        }
      } catch (error: any) {
        const status = error?.response?.status;
        const detalhe = error?.response?.data?.detail;
        setLoteExigeRevisao(true);
        if (status === 409) {
          setErroRecebimentoLoteOS(`Uma OS mudou desde a conferencia. Nenhuma baixa deste lote foi registrada por esta operacao. ${orientarRevisao}`);
        } else if (status >= 400 && status < 500) {
          setErroRecebimentoLoteOS(`${typeof detalhe === "string" ? detalhe : "O recebimento do lote foi recusado."} ${orientarRevisao}`);
        } else {
          setErroRecebimentoLoteOS(`Nao foi possivel confirmar o resultado do recebimento. O lote pode ter sido registrado. O recibo nao foi solicitado. ${orientarRevisao}`);
        }
        await atualizarListaAposLote();
        return;
      }

      let avisoRecibo = "";
      if (enviarReciboLote) {
        try {
          if (idsRecebidas.length === 1) {
            await api.post(`/ordens-servico/${idsRecebidas[0]}/whatsapp/recibo-pdf`, {
              idempotency_key: criarIdempotencyKeyWhatsApp("recibo-pdf", idsRecebidas[0]),
            });
          } else {
            await api.post("/ordens-servico/whatsapp/recibos-pdf", {
              os_ids: idsRecebidas,
              idempotency_key: criarIdempotencyKeyWhatsApp("recibo-pdf-lote", idsRecebidas[0]),
            });
          }
        } catch (error: any) {
          avisoRecibo =
            error.response?.data?.detail ||
            "As baixas foram registradas, mas nao foi possivel confirmar o envio do recibo PDF pelo WhatsApp.";
        }
      }

      setModalReceberLoteOS(null);
      setPagamentosRecebimentoOS([]);
      setOsSelecionadasBaixa([]);
      setEnviarReciboPdfWhatsAppAposRecebimento(false);
      await atualizarListaAposLote();
      alert(avisoRecibo
        ? `Baixa em lote registrada com sucesso.\n\nAviso do WhatsApp: ${avisoRecibo}`
        : enviarReciboLote
          ? "Baixa em lote registrada e recibo PDF consolidado enviado pelo WhatsApp!"
          : "Baixa em lote registrada com sucesso!");
    } finally {
      recebendoLoteOSRef.current = false;
      setRecebendoLoteOS(false);
    }
  };

  const abrirDesfazerRecebimentoOS = (os: OrdemServico) => {
    if (desfazendoRecebimentoOSRef.current) return;
    setErroDesfazerRecebimentoOS("");
    setMensagemDesfazerRecebimentoOS("");
    setModalDesfazerRecebimentoOS(os);
  };

  const fecharDesfazerRecebimentoOS = () => {
    if (desfazendoRecebimentoOSRef.current) return;
    setModalDesfazerRecebimentoOS(null);
    setErroDesfazerRecebimentoOS("");
  };

  const confirmarDesfazerRecebimentoOS = async () => {
    const os = modalDesfazerRecebimentoOS;
    if (!os || desfazendoRecebimentoOSRef.current) return;
    desfazendoRecebimentoOSRef.current = true;
    setDesfazendoRecebimentoOS(true);
    setErroDesfazerRecebimentoOS("");
    try {
      await api.patch(`/ordens-servico/${os.id}/desfazer-recebimento`);
    } catch (error: unknown) {
      console.error("Erro ao desfazer recebimento:", error);
      const detalhe = extractApiErrorMessageSync(error, "Não foi possível confirmar a reversão.");
      setErroDesfazerRecebimentoOS(`${detalhe} Confira o estado da OS antes de tentar novamente.`);
      return;
    } finally {
      desfazendoRecebimentoOSRef.current = false;
      setDesfazendoRecebimentoOS(false);
    }
    setModalDesfazerRecebimentoOS(null);
    setMensagemDesfazerRecebimentoOS(`Recebimento da OS ${os.numero_os} desfeito com sucesso.`);
    void carregarDados();
  };

  const salvarEdicaoOS = async () => {
    if (!modalEditarOS) return;
    const osDomiciliar = modalEditarOS.origem_atendimento === "domiciliar";
    const clinicaAlterada = !osDomiciliar && formEditarOS.clinica_id !== String(modalEditarOS.clinica_id || "");
    const servicoAlterado = formEditarOS.servico_id !== String(modalEditarOS.servico_id || "");
    if ((clinicaAlterada && !formEditarOS.clinica_id) || (servicoAlterado && !formEditarOS.servico_id)) {
      alert(
        osDomiciliar
          ? "Selecione o servico para atualizar a OS domiciliar."
          : "Selecione clinica e servico para atualizar a OS."
      );
      return;
    }

    try {
      setSalvandoOS(true);
      const payload: Record<string, unknown> = {};
      if (clinicaAlterada) {
        payload.clinica_id = Number(formEditarOS.clinica_id);
      }
      if (servicoAlterado) payload.servico_id = Number(formEditarOS.servico_id);
      if (formEditarOS.tipo_horario !== (modalEditarOS.tipo_horario || "comercial")) {
        payload.tipo_horario = formEditarOS.tipo_horario;
      }
      if (Math.round(Number(formEditarOS.desconto || 0) * 100) !== Math.round(Number(modalEditarOS.desconto || 0) * 100)) {
        payload.desconto = Number(formEditarOS.desconto || 0);
      }
      if (formEditarOS.observacoes !== (modalEditarOS.observacoes || "")) {
        payload.observacoes = formEditarOS.observacoes;
      }
      if (Object.keys(payload).length === 0) {
        setModalEditarOS(null);
        return;
      }
      await api.put(`/ordens-servico/${modalEditarOS.id}`, payload);
      setModalEditarOS(null);
      alert("OS atualizada com sucesso!");
      carregarDados();
    } catch (error: any) {
      console.error("Erro ao atualizar OS:", error);
      alert("Erro ao atualizar OS: " + (error.response?.data?.detail || error.message));
    } finally {
      setSalvandoOS(false);
    }
  };

  const handleExcluirOS = async (os: OrdemServico) => {
    if (os.laudo_id) {
      if (os.status !== "Pendente") {
        alert(os.status === "Pago"
          ? "Desfaca o recebimento antes de cancelar a OS vinculada ao laudo."
          : "Esta OS vinculada ao laudo ja esta cancelada.");
        return;
      }
      if (!confirm(`Cancelar a OS ${os.numero_os}? O laudo e o historico do envio serao preservados.`)) return;
      try {
        await api.put(`/ordens-servico/${os.id}`, { status: "Cancelado" });
        alert("OS cancelada com sucesso!");
        carregarDados();
      } catch (error: any) {
        console.error("Erro ao cancelar OS:", error);
        alert("Erro ao cancelar OS: " + (error.response?.data?.detail || error.message));
      }
      return;
    }
    if (!confirm(`Tem certeza que deseja excluir a OS ${os.numero_os}?`)) return;
    
    try {
      await api.delete(`/ordens-servico/${os.id}`);
      alert("OS excluida com sucesso!");
      carregarDados();
    } catch (error: any) {
      console.error("Erro ao excluir OS:", error);
      alert("Erro ao excluir OS: " + (error.response?.data?.detail || error.message));
    }
  };

  // All transaction filters and counts are authoritative on the server.
  const transacoesFiltradas = transacoes;
  const transacoesDesatualizadas = chaveResultadoTransacoes !== chavePedidoTransacoes || buscaTransacoesPendente;

  // Filtrar OS
  const osFiltradas = ordensPagina;

  const osRecebidasFiltradas = useMemo(
    () => osFiltradas.filter((os) => os.status === "Pago"),
    [osFiltradas]
  );
  const osPendentesFiltradas = useMemo(
    () => osFiltradas.filter((os) => os.status === "Pendente"),
    [osFiltradas]
  );
  const totalSelecionadoBaixa = useMemo(
    () =>
      ordensServico
        .filter((os) => osSelecionadasBaixa.includes(os.id) && os.status === "Pendente")
        .reduce((acc, os) => acc + Number(os.valor_final || 0), 0),
    [ordensServico, osSelecionadasBaixa]
  );

  useEffect(() => {
    // A filter/tab change starts a new selection scope, but page changes do not.
    selecaoEpochRef.current += 1;
    setOsSelecionadasRecibo([]);
    setOsSelecionadasBaixa([]);
  }, [chaveOrdens, abaAtiva]);

  useEffect(() => {
    if (osHighlightId == null) return;
    if (Date.now() >= osHighlightUntil) {
      setOsHighlightId(null);
      return;
    }
    const timeout = window.setTimeout(() => {
      setOsHighlightId(null);
    }, Math.max(1000, osHighlightUntil - Date.now()));
    return () => window.clearTimeout(timeout);
  }, [osHighlightId, osHighlightUntil]);

  useEffect(() => {
    if ((abaAtiva !== "ordens" && abaAtiva !== "cobrancas") || osHighlightId == null) return;
    const row = document.getElementById(`os-row-${osHighlightId}`);
    if (!row) return;
    highlightedRowRef.current = row as HTMLDivElement;
    row.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [abaAtiva, osFiltradas, grupoAberto, osHighlightId]);

  const clinicaContatoPorId = useMemo(() => {
    const mapa = new Map<number, ClinicaOption>();
    for (const clinica of clinicas) {
      if (!clinica?.id) continue;
      mapa.set(clinica.id, clinica);
    }
    return mapa;
  }, [clinicas]);

  const osCobrancaFiltradas = useMemo(
    () => osFiltradas.filter((os) => os.status !== "Cancelado"),
    [osFiltradas]
  );

  const obterContatoDestinatarioDaOS = useCallback((os: OrdemServico): ContatoDestinatario => {
    const tipoDestinatario =
      os.destinatario_tipo === "tutor" || os.origem_atendimento === "domiciliar" ? "tutor" : "clinica";
    const clinicaCadastro =
      os.clinica_id != null ? clinicaContatoPorId.get(os.clinica_id) || null : null;
    const nomeDestinatario = String(
      os.destinatario_nome ||
        (tipoDestinatario === "tutor" ? os.tutor : os.clinica) ||
        (tipoDestinatario === "tutor" ? "Tutor nao informado" : "Clinica nao informada")
    ).trim();
    const telefoneDestinatario = String(
      os.destinatario_telefone ||
        (tipoDestinatario === "tutor"
          ? os.tutor_whatsapp || os.tutor_telefone
          : os.clinica_telefone || clinicaCadastro?.telefone) ||
        ""
    ).trim();
    const emailDestinatario = String(
      os.destinatario_email ||
        (tipoDestinatario === "tutor" ? os.tutor_email : os.clinica_email || clinicaCadastro?.email) ||
        ""
    ).trim();
    const chave =
      tipoDestinatario === "tutor"
        ? os.tutor_id != null
          ? `tutor:${os.tutor_id}`
          : `tutor-nome:${nomeDestinatario.toLowerCase()}`
        : os.clinica_id != null
          ? `clinica:${os.clinica_id}`
          : `clinica-nome:${nomeDestinatario.toLowerCase()}`;

    return {
      chave,
      tipo_destinatario: tipoDestinatario,
      nome_destinatario: nomeDestinatario || (tipoDestinatario === "tutor" ? "Tutor nao informado" : "Clinica nao informada"),
      telefone_destinatario: telefoneDestinatario,
      email_destinatario: emailDestinatario,
      clinica_id: os.clinica_id ?? null,
      tutor_id: os.tutor_id ?? null,
    };
  }, [clinicaContatoPorId]);

  const gruposCobrancaDestinatario = useMemo<GrupoCobrancaDestinatario[]>(() => {
    const mapa = new Map<string, GrupoCobrancaDestinatario>();

    for (const os of osCobrancaFiltradas) {
      const destinatario = obterContatoDestinatarioDaOS(os);

      if (!mapa.has(destinatario.chave)) {
        mapa.set(destinatario.chave, {
          ...destinatario,
          total_pendente: 0,
          quantidade_os: 0,
          quantidade_total: 0,
          ordens: [],
        });
      }

      const grupo = mapa.get(destinatario.chave)!;
      if (os.status === "Pendente") {
        grupo.total_pendente += Number(os.valor_final || 0);
        grupo.quantidade_os += 1;
      }
      grupo.quantidade_total += 1;
      grupo.ordens.push(os);
    }

    return Array.from(mapa.values())
      .map((grupo) => ({
        ...grupo,
        ordens: [...grupo.ordens].sort((a, b) => {
          const da = a.data_atendimento ? new Date(a.data_atendimento).getTime() : 0;
          const db = b.data_atendimento ? new Date(b.data_atendimento).getTime() : 0;
          return da - db;
        }),
      }))
      .sort((a, b) => b.total_pendente - a.total_pendente);
  }, [obterContatoDestinatarioDaOS, osCobrancaFiltradas]);

  const totalPendenteAgrupado = resumoOrdens.valor_pendente;

  const normalizarTelefoneWhatsApp = (telefone: string) => {
    let digitos = String(telefone || "").replace(/\D/g, "");
    while (digitos.startsWith("0")) {
      digitos = digitos.slice(1);
    }
    if (!digitos) return "";
    if (digitos.startsWith("55")) return digitos;
    if (digitos.length >= 10 && digitos.length <= 11) return `55${digitos}`;
    return digitos;
  };

  const formatarDataArquivo = () => operationalTodayDateInput();

  const obterContatoCompartilhamento = (ids: number[]) => {
    const selecionadas = ordensServico.filter((os) => ids.includes(os.id));
    const contatosUnicos = Array.from(
      new Map(selecionadas.map((os) => {
        const contato = obterContatoDestinatarioDaOS(os);
        return [contato.chave, contato] as const;
      })).values()
    );
    if (contatosUnicos.length === 1) {
      return contatosUnicos[0];
    }
    return null;
  };

  const montarMensagemCompartilhamentoRecibo = (ids: number[], agrupar: boolean) => {
    const selecionadas = ordensServico.filter((os) => ids.includes(os.id));
    const total = selecionadas.reduce((acc, item) => acc + Number(item.valor_final || 0), 0);
    const primeiraOS = selecionadas[0];
    const destinatarios = Array.from(
      new Map(selecionadas.map((os) => {
        const contato = obterContatoDestinatarioDaOS(os);
        return [contato.chave, contato] as const;
      })).values()
    );
    const destinatarioTexto =
      destinatarios.length === 1
        ? destinatarios[0].nome_destinatario
        : destinatarios.length > 1
          ? "Multiplos destinatarios"
          : "Nao informado";
    const dataHoje = formatCalendarDate(operationalTodayDateInput());
    const listaOS = selecionadas
      .map(
        (os, index) =>
          `${index + 1}. OS ${os.numero_os} | ${os.paciente || "Paciente"} | ${formatarValor(Number(os.valor_final || 0))}`
      )
      .join("\n");

    let modelo =
      agrupar || selecionadas.length > 1
        ? mensagemReciboAgrupadoModelo || MODELO_MENSAGEM_RECIBO_AGRUPADO_PADRAO
        : mensagemReciboIndividualModelo || MODELO_MENSAGEM_RECIBO_INDIVIDUAL_PADRAO;

    modelo = modelo
      .replace(/{{\s*destinatario\s*}}/gi, destinatarioTexto)
      .replace(/{{\s*clinica\s*}}/gi, destinatarioTexto)
      .replace(/{{\s*data\s*}}/gi, dataHoje)
      .replace(/{{\s*os_numero\s*}}/gi, primeiraOS?.numero_os || "-")
      .replace(/{{\s*paciente\s*}}/gi, primeiraOS?.paciente || "Nao informado")
      .replace(/{{\s*valor_recebido\s*}}/gi, formatarValor(Number(primeiraOS?.valor_final || 0)))
      .replace(/{{\s*total_recebido\s*}}/gi, formatarValor(total))
      .replace(/{{\s*quantidade_os\s*}}/gi, String(selecionadas.length))
      .replace(/{{\s*lista_os\s*}}/gi, listaOS || "1. Nenhuma OS selecionada.");

    return modelo;
  };

  const montarAssuntoCompartilhamentoRecibo = (ids: number[], agrupar: boolean) => {
    if (ids.length === 1) {
      const ordem = ordensServico.find((os) => os.id === ids[0]);
      return `Recibo da OS ${ordem?.numero_os || ids[0]}`;
    }
    return agrupar
      ? "Recibo agrupado de ordens de servico recebidas"
      : "Recibos de ordens de servico recebidas";
  };

  const inserirPlaceholderModeloRecibo = (
    placeholder: string,
    tipo: "individual" | "agrupado"
  ) => {
    const textarea =
      tipo === "individual" ? textareaMensagemReciboIndividualRef.current : textareaMensagemReciboAgrupadoRef.current;
    const textoAtual =
      tipo === "individual" ? mensagemReciboIndividualModelo || "" : mensagemReciboAgrupadoModelo || "";

    if (!textarea) {
      if (tipo === "individual") {
        setMensagemReciboIndividualModelo(`${textoAtual}${placeholder}`);
      } else {
        setMensagemReciboAgrupadoModelo(`${textoAtual}${placeholder}`);
      }
      return;
    }

    const inicio = textarea.selectionStart ?? textoAtual.length;
    const fim = textarea.selectionEnd ?? inicio;
    const novoTexto = `${textoAtual.slice(0, inicio)}${placeholder}${textoAtual.slice(fim)}`;
    const novaPosicao = inicio + placeholder.length;

    if (tipo === "individual") {
      setMensagemReciboIndividualModelo(novoTexto);
    } else {
      setMensagemReciboAgrupadoModelo(novoTexto);
    }

    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(novaPosicao, novaPosicao);
    });
  };

  const restaurarModeloMensagemRecibo = (tipo: "individual" | "agrupado") => {
    if (tipo === "individual") {
      setMensagemReciboIndividualModelo(MODELO_MENSAGEM_RECIBO_INDIVIDUAL_PADRAO);
    } else {
      setMensagemReciboAgrupadoModelo(MODELO_MENSAGEM_RECIBO_AGRUPADO_PADRAO);
    }
  };

  const abrirDownloadBlob = (blob: Blob, filename: string) => {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const fecharPreviewRecibo = () => {
    setPreviewRecibo((prev) => {
      if (prev?.url) {
        window.URL.revokeObjectURL(prev.url);
      }
      return null;
    });
  };

  const abrirMailtoComMensagem = (email: string, subject: string, body: string) => {
    const params = new URLSearchParams();
    params.set("subject", subject);
    params.set("body", body);
    const to = email ? email.trim() : "";
    window.open(`mailto:${to}?${params.toString()}`, "_self");
  };

  const abrirWhatsAppComMensagem = (telefone: string, mensagem: string) => {
    const numero = normalizarTelefoneWhatsApp(telefone || "");
    const destino = numero ? `https://wa.me/${numero}?text=${encodeURIComponent(mensagem)}` : `https://wa.me/?text=${encodeURIComponent(mensagem)}`;
    window.open(destino, "_blank", "noopener,noreferrer");
  };

  const compartilharArquivoSeDisponivel = async (blob: Blob, filename: string, title: string, text: string) => {
    if (typeof navigator === "undefined" || typeof navigator.share !== "function") {
      return false;
    }

    try {
      const file = new File([blob], filename, { type: "application/pdf" });
      const payload = { title, text, files: [file] };
      if (typeof navigator.canShare === "function" && !navigator.canShare(payload)) {
        return false;
      }
      await navigator.share(payload);
      return true;
    } catch (error: any) {
      if (error?.name === "AbortError") {
        return true;
      }
      return false;
    }
  };

  const extrairDetalheErroDownload = async (error: any) => {
    const payload = error?.response?.data;
    if (payload instanceof Blob) {
      try {
        const texto = await payload.text();
        const json = JSON.parse(texto);
        return String(json?.detail || texto || "");
      } catch {
        return "";
      }
    }
    if (typeof payload?.detail === "string") {
      return payload.detail;
    }
    return "";
  };

  const abrirComposerCompartilhamentoRecibo = async (
    canal: "whatsapp" | "email",
    ids: number[],
    agrupar: boolean
  ) => {
    if (ids.length === 0) {
      alert("Selecione ao menos uma OS recebida para compartilhar o recibo.");
      return;
    }

    if (!(await validarSelecao(ids, "Pago"))) return;

    const contato = obterContatoCompartilhamento(ids);
    setModalCompartilharRecibo({
      canal,
      ids,
      agrupar,
      mensagem: montarMensagemCompartilhamentoRecibo(ids, agrupar),
      assunto: montarAssuntoCompartilhamentoRecibo(ids, agrupar),
      telefone: String(contato?.telefone_destinatario || ""),
      email: String(contato?.email_destinatario || ""),
    });
  };

  const montarLinhasPendentes = (grupo: GrupoCobrancaDestinatario) => {
    const ordensPendentes = grupo.ordens.filter((os) => os.status === "Pendente");
    return ordensPendentes.map(
      (os, index) =>
        `${index + 1}. OS ${os.numero_os} | ${formatarData(os.data_atendimento)} | ${os.servico || "Servico"} | ` +
        `Tutor: ${os.tutor || "Nao informado"} | Pet: ${os.paciente || "Nao informado"} | ${formatarValor(os.valor_final)}`
    );
  };

  const preencherMensagemCobranca = (grupo: GrupoCobrancaDestinatario) => {
    const hoje = formatCalendarDate(operationalTodayDateInput());
    const linhasOS = montarLinhasPendentes(grupo);
    const listaOS = linhasOS.length > 0 ? linhasOS.join("\n") : "1. Nenhuma OS pendente.";

    let mensagem = (mensagemCobrancaModelo || "").trim() || MODELO_MENSAGEM_COBRANCA_PADRAO;

    mensagem = mensagem
      .replace(/{{\s*destinatario\s*}}/gi, grupo.nome_destinatario)
      .replace(/{{\s*clinica\s*}}/gi, grupo.nome_destinatario)
      .replace(/{{\s*data\s*}}/gi, hoje)
      .replace(/{{\s*lista_os\s*}}/gi, listaOS)
      .replace(/{{\s*total_pendente\s*}}/gi, formatarValor(grupo.total_pendente));

    if (mensagem.includes("________")) {
      mensagem = mensagem.replace(/________/g, grupo.nome_destinatario);
    }
    if (mensagem.includes("___/___/___")) {
      mensagem = mensagem.replace(/___\/___\/___/g, hoje);
    }

    if (/R\$\s*valor total das OS pendentes/gi.test(mensagem)) {
      mensagem = mensagem.replace(/R\$\s*valor total das OS pendentes/gi, formatarValor(grupo.total_pendente));
    }

    if (/OS numero da os/gi.test(mensagem)) {
      mensagem = mensagem.replace(/^.*OS numero da os.*$/gim, listaOS);
    } else if (!/{{\s*lista_os\s*}}/gi.test(mensagem) && !mensagem.includes(listaOS)) {
      mensagem = `${mensagem}\n\n${listaOS}`;
    }

    return mensagem;
  };

  const restaurarModeloMensagem = () => {
    setMensagemCobrancaModelo(MODELO_MENSAGEM_COBRANCA_PADRAO);
  };

  const inserirPlaceholderNoModelo = (placeholder: string) => {
    const textarea = textareaMensagemRef.current;
    const textoAtual = mensagemCobrancaModelo || "";

    if (!textarea) {
      setMensagemCobrancaModelo(`${textoAtual}${placeholder}`);
      return;
    }

    const inicio = textarea.selectionStart ?? textoAtual.length;
    const fim = textarea.selectionEnd ?? inicio;
    const novoTexto = `${textoAtual.slice(0, inicio)}${placeholder}${textoAtual.slice(fim)}`;
    const novaPosicao = inicio + placeholder.length;

    setMensagemCobrancaModelo(novoTexto);

    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(novaPosicao, novaPosicao);
    });
  };

  const criarIdempotencyKeyWhatsApp = (prefixo: string, osId: number) =>
    typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `${prefixo}-${osId}-${Date.now()}`;

  const enviarCobrancaWhatsApp = async (grupo: GrupoCobrancaDestinatario) => {
    const ordensPendentes = grupo.ordens.filter((os) => os.status === "Pendente");
    if (ordensPendentes.length === 0) {
      alert("Nao ha OS pendente neste grupo para enviar.");
      return;
    }
    if (ordensPendentes.length === 1) {
      const ordem = ordensPendentes[0];
      if (!confirm(`Enviar pelo WhatsApp oficial a cobrança da OS ${ordem.numero_os}?`)) return;

      setEnviandoWhatsAppOficialOsId(ordem.id);
      try {
        await api.post(`/ordens-servico/${ordem.id}/whatsapp/cobranca`, {
          idempotency_key: criarIdempotencyKeyWhatsApp("cobranca", ordem.id),
        });
        alert("Cobrança enviada pelo WhatsApp oficial da Fort Cordis.");
      } catch (error) {
        const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        alert(detail || "Erro ao enviar a cobrança pelo WhatsApp oficial.");
      } finally {
        setEnviandoWhatsAppOficialOsId(null);
      }
      return;
    }

    if (!confirm(`Enviar uma unica cobranca oficial com ${ordensPendentes.length} OS para ${grupo.nome_destinatario}?`)) {
      return;
    }
    setEnviandoWhatsAppOficialGrupoKey(grupo.chave);
    try {
      await api.post("/ordens-servico/whatsapp/cobranca-agrupada", {
        os_ids: ordensPendentes.map((os) => os.id),
        idempotency_key: criarIdempotencyKeyWhatsApp("cobranca-agrupada", ordensPendentes[0].id),
      });
      alert("Cobranca consolidada enviada pelo WhatsApp oficial da Fort Cordis.");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      alert(detail || "Erro ao enviar a cobranca consolidada pelo WhatsApp oficial.");
    } finally {
      setEnviandoWhatsAppOficialGrupoKey(null);
    }
  };

  const avisarReciboPeloWhatsAppOficial = async (os: OrdemServico) => {
    if (!confirm(`Enviar pelo WhatsApp oficial o aviso do recibo da OS ${os.numero_os}?`)) return;

    setEnviandoWhatsAppOficialOsId(os.id);
    try {
      await api.post(`/ordens-servico/${os.id}/whatsapp/recibo`, {
        idempotency_key: criarIdempotencyKeyWhatsApp("recibo", os.id),
      });
      alert("Aviso de recibo enviado pelo WhatsApp oficial da Fort Cordis.");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      alert(detail || "Erro ao enviar o aviso de recibo pelo WhatsApp oficial.");
    } finally {
      setEnviandoWhatsAppOficialOsId(null);
    }
  };

  const copiarMensagemCobranca = async (grupo: GrupoCobrancaDestinatario) => {
    const mensagem = preencherMensagemCobranca(grupo);
    try {
      await navigator.clipboard.writeText(mensagem);
      alert(`Mensagem de cobranca copiada para ${grupo.nome_destinatario}.`);
    } catch (_err) {
      alert("Nao foi possivel copiar automaticamente. Tente novamente.");
    }
  };
  const baixarRelatorioPendenciasPDF = async (grupo?: GrupoCobrancaDestinatario) => {
    if (loadingOrdens || cobrancasDesatualizadas || falhasCarregamento.includes("Cobrancas")) return;
    if (totalGrupos === 0) {
      alert("Nao ha pendencias para gerar relatorio.");
      return;
    }

    try {
      const mensagemRelatorio = grupo ? preencherMensagemCobranca(grupo) : undefined;

      const query = montarQueryString({
        status: filtroStatusOS !== "todos" ? filtroStatusOS : "Pendente",
        origem_atendimento: filtroOrigemAtendimentoOS !== "todos" ? filtroOrigemAtendimentoOS : undefined,
        destinatario_chave: grupo?.chave,
        clinica_id: filtroClinicaOS !== "todos" ? filtroClinicaOS : undefined,
        servico_id: filtroServicoOS !== "todos" ? filtroServicoOS : undefined,
        tipo_horario: filtroTipoHorarioOS !== "todos" ? filtroTipoHorarioOS : undefined,
        data_inicio: filtroDataInicio || undefined,
        data_fim: filtroDataFim || undefined,
        search: buscaTransacoes || undefined,
        mensagem: mensagemRelatorio,
      });

      const response = await api.get(`/ordens-servico/relatorios/pendencias/pdf${query}`, {
        responseType: "blob",
      });
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      const disposition = response.headers?.["content-disposition"] as string | undefined;
      const match = disposition?.match(/filename=\"?([^\";]+)\"?/i);
      const sufixoClinica = (grupo?.nome_destinatario || "")
        .toLowerCase()
        .replace(/\s+/g, "_")
        .replace(/[^a-z0-9_]/g, "")
        .slice(0, 40);
      const fallback = sufixoClinica
        ? `relatorio_cobranca_${sufixoClinica}_${operationalTodayDateInput()}.pdf`
        : `relatorio_cobranca_pendencias_${operationalTodayDateInput()}.pdf`;
      link.href = url;
      link.download = match?.[1] || fallback;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error: any) {
      console.error("Erro ao baixar relatorio PDF:", error);
      const detail = await extrairDetalheErroDownload(error);
      alert(detail || "Erro ao gerar relatorio PDF de pendencias.");
    }
  };

  const atualizarSnapshotsPagina = () => {
    setOrdensServico((prev) => Array.from(new Map([
      ...prev, ...ordensPagina.filter((os) => !osSelecionadasBaixa.includes(os.id) && !osSelecionadasRecibo.includes(os.id)),
    ].map((os) => [os.id, os])).values()));
  };

  const toggleSelecaoReciboOS = (osId: number) => {
    atualizarSnapshotsPagina();
    setOsSelecionadasRecibo((prev) =>
      prev.includes(osId) ? prev.filter((id) => id !== osId) : [...prev, osId]
    );
  };

  const toggleSelecaoBaixaOS = (osId: number) => {
    atualizarSnapshotsPagina();
    setOsSelecionadasBaixa((prev) =>
      prev.includes(osId) ? prev.filter((id) => id !== osId) : [...prev, osId]
    );
  };

  const selecionarTodasRecebidasVisiveis = () => {
    atualizarSnapshotsPagina();
    setOsSelecionadasRecibo((prev) => Array.from(new Set([...prev, ...osRecebidasFiltradas.map((os) => os.id)])));
  };

  const selecionarTodasPendentesVisiveis = () => {
    atualizarSnapshotsPagina();
    setOsSelecionadasBaixa((prev) => Array.from(new Set([...prev, ...osPendentesFiltradas.map((os) => os.id)])));
  };

  const limparSelecaoRecibo = () => {
    setOsSelecionadasRecibo([]);
  };

  const limparSelecaoBaixa = () => {
    setOsSelecionadasBaixa([]);
  };

  const obterReciboOSPDF = async (ids: number[], agrupar: boolean) => {
    if (ids.length === 0) {
      alert("Selecione ao menos uma OS recebida para gerar o recibo.");
      return null;
    }
    if (!(await validarSelecao(ids, "Pago"))) return null;

    try {
      const query = montarQueryString({
        os_ids: ids.join(","),
        agrupar: agrupar ? "true" : "false",
      });
      const response = await api.get(`/ordens-servico/relatorios/recibos/pdf${query}`, {
        responseType: "blob",
      });
      const blob = new Blob([response.data], { type: "application/pdf" });
      const disposition = response.headers?.["content-disposition"] as string | undefined;
      const match = disposition?.match(/filename=\"?([^\";]+)\"?/i);
      const filename =
        ids.length === 1
          ? `recibo_os_${ids[0]}.pdf`
          : agrupar
            ? `recibo_os_agrupado_${operationalTodayDateInput()}.pdf`
            : `recibos_os_${operationalTodayDateInput()}.pdf`;
      return { blob, filename: match?.[1] || filename };
    } catch (error: any) {
      console.error("Erro ao gerar recibo PDF:", error);
      const detail = await extrairDetalheErroDownload(error);
      alert(detail || "Erro ao gerar recibo das OS recebidas.");
      return null;
    }
  };

  const baixarReciboOSPDF = async (ids: number[], agrupar: boolean) => {
    const arquivo = await obterReciboOSPDF(ids, agrupar);
    if (!arquivo) return;
    abrirDownloadBlob(arquivo.blob, arquivo.filename);
  };

  const abrirPreviewRecibo = async (ids: number[], agrupar: boolean) => {
    setCarregandoPreviewRecibo(true);
    try {
      const arquivo = await obterReciboOSPDF(ids, agrupar);
      if (!arquivo) return;

      const titulo =
        ids.length === 1
          ? `Previa do recibo da OS ${ordensServico.find((os) => os.id === ids[0])?.numero_os || ids[0]}`
          : agrupar
            ? `Previa do recibo agrupado`
            : `Previa dos recibos selecionados`;

      const url = window.URL.createObjectURL(arquivo.blob);
      setPreviewRecibo((prev) => {
        if (prev?.url) {
          window.URL.revokeObjectURL(prev.url);
        }
        return {
          ids,
          agrupar,
          titulo,
          filename: arquivo.filename,
          url,
          blob: arquivo.blob,
        };
      });
    } finally {
      setCarregandoPreviewRecibo(false);
    }
  };

  const abrirPreviewReciboNovaAba = () => {
    if (!previewRecibo?.url) return;
    window.open(previewRecibo.url, "_blank", "noopener,noreferrer");
  };

  const compartilharReciboPorEmail = async (
    ids: number[],
    agrupar: boolean,
    overrides?: { assunto?: string; mensagem?: string; email?: string }
  ) => {
    const arquivo = await obterReciboOSPDF(ids, agrupar);
    if (!arquivo) return;

    const contato = obterContatoCompartilhamento(ids);
    const subject = String(overrides?.assunto || montarAssuntoCompartilhamentoRecibo(ids, agrupar)).trim();
    const body = String(overrides?.mensagem || montarMensagemCompartilhamentoRecibo(ids, agrupar)).trim();
    const emailDestino = String(overrides?.email || contato?.email_destinatario || "").trim();
    const textoFallback = `${body}\n\nCaso o anexo nao seja compartilhado automaticamente, o PDF foi baixado neste dispositivo para envio manual.`;
    const compartilhado = await compartilharArquivoSeDisponivel(arquivo.blob, arquivo.filename, subject, textoFallback);
    if (compartilhado) return;
    abrirDownloadBlob(arquivo.blob, arquivo.filename);
    abrirMailtoComMensagem(emailDestino, subject, textoFallback);
  };

  const compartilharReciboPorWhatsApp = async (
    ids: number[],
    agrupar: boolean,
    overrides?: { mensagem?: string; telefone?: string }
  ) => {
    const arquivo = await obterReciboOSPDF(ids, agrupar);
    if (!arquivo) return;

    const contato = obterContatoCompartilhamento(ids);
    const title =
      montarAssuntoCompartilhamentoRecibo(ids, agrupar);
    const telefoneDestino = String(overrides?.telefone || contato?.telefone_destinatario || "").trim();
    const mensagem = String(overrides?.mensagem || montarMensagemCompartilhamentoRecibo(ids, agrupar)).trim();
    const textoFallback = `${mensagem}\n\nSe o PDF nao seguir automaticamente, ele foi baixado neste dispositivo para anexar na conversa.`;
    const compartilhado = await compartilharArquivoSeDisponivel(arquivo.blob, arquivo.filename, title, textoFallback);
    if (compartilhado) return;
    abrirDownloadBlob(arquivo.blob, arquivo.filename);
    abrirWhatsAppComMensagem(telefoneDestino, textoFallback);
  };

  const confirmarCompartilhamentoRecibo = async () => {
    if (!modalCompartilharRecibo) return;
    setEnviandoCompartilhamentoRecibo(true);
    try {
      if (modalCompartilharRecibo.canal === "email") {
        await compartilharReciboPorEmail(modalCompartilharRecibo.ids, modalCompartilharRecibo.agrupar, {
          assunto: modalCompartilharRecibo.assunto,
          mensagem: modalCompartilharRecibo.mensagem,
          email: modalCompartilharRecibo.email,
        });
      } else {
        await compartilharReciboPorWhatsApp(modalCompartilharRecibo.ids, modalCompartilharRecibo.agrupar, {
          mensagem: modalCompartilharRecibo.mensagem,
          telefone: modalCompartilharRecibo.telefone,
        });
      }
      setModalCompartilharRecibo(null);
    } finally {
      setEnviandoCompartilhamentoRecibo(false);
    }
  };

  // Calcular resumo de OS
  const osPendentes = ordensPagina.filter(os => os.status === 'Pendente');
  const valorPendenteOS = resumoOrdens.valor_pendente;
  const novoValorParaPrevia = parseNovoValorFinalOS(novoValorFinalOS);

  return (
    <DashboardLayout>
      <div className="fc-finance-page">
        {/* Header */}
        <header className="fc-finance-header">
          <div>
            <span className="fc-finance-kicker">
              <DollarSign className="h-4 w-4" />
              Gestão financeira
            </span>
            <h1>Central financeira</h1>
            <p>Movimentações, recebimentos e ordens de serviço em uma visão comparável.</p>
          </div>
          <div>
            <button 
              onClick={handleNova}
              className="fc-finance-primary"
            >
              <Plus className="w-4 h-4" />
              Nova Transacao
            </button>
          </div>
        </header>

        {mensagemAjusteOS && (
          <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
            {mensagemAjusteOS}
          </div>
        )}

        {mensagemDesfazerRecebimentoOS && (
          <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
            {mensagemDesfazerRecebimentoOS}
          </div>
        )}

        {falhasCarregamento.length > 0 && (
          <div
            role="alert"
            aria-live="polite"
            className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950"
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-semibold">Algumas informacoes nao carregaram.</p>
                <p className="mt-1">
                  Secoes indisponiveis: {falhasCarregamento.join(", ")}. Os demais dados podem continuar sendo usados.
                </p>
              </div>
              <button type="button" onClick={() => void carregarDados()} className="fc-finance-secondary shrink-0">
                Tentar novamente
              </button>
            </div>
          </div>
        )}

        {/* Periodo */}
        <div className="fc-finance-periods" aria-label="Período do resumo">
          {['dia', 'semana', 'mes', 'ano'].map((p) => (
            <button
              key={p}
              onClick={() => setPeriodo(p)}
              className={`fc-finance-period ${periodo === p ? "fc-finance-period-active" : ""}`}
            >
              {p === 'mes' ? 'Mes' : p}
            </button>
          ))}
        </div>

        {/* Cards Resumo */}
	        <div className="fc-finance-metrics">
          <div className="fc-finance-metric fc-finance-metric-income">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">Entradas</p>
                <p className="text-2xl font-bold text-green-600">{formatarValor(resumo.entradas)}</p>
              </div>
              <div className="w-12 h-12 bg-green-50 rounded-lg flex items-center justify-center">
                <TrendingUp className="w-6 h-6 text-green-600" />
              </div>
            </div>
            {resumo.pendente_entrada > 0 && (
              <p className="text-xs text-yellow-600 mt-2">
                + {formatarValor(resumo.pendente_entrada)} pendente
              </p>
            )}
          </div>

          <div className="fc-finance-metric fc-finance-metric-expense">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">Saidas</p>
                <p className="text-2xl font-bold text-red-600">{formatarValor(resumo.saidas)}</p>
              </div>
              <div className="w-12 h-12 bg-red-50 rounded-lg flex items-center justify-center">
                <TrendingDown className="w-6 h-6 text-red-600" />
              </div>
            </div>
            {resumo.pendente_saida > 0 && (
              <p className="text-xs text-yellow-600 mt-2">
                + {formatarValor(resumo.pendente_saida)} pendente
              </p>
            )}
          </div>

          <div className="fc-finance-metric fc-finance-metric-balance">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">Saldo</p>
                <p className={`text-2xl font-bold ${resumo.saldo >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {formatarValor(resumo.saldo)}
                </p>
              </div>
              <div className="w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center">
                <DollarSign className="w-6 h-6 text-blue-600" />
              </div>
            </div>
          </div>

	          <div className="fc-finance-metric fc-finance-metric-pending">
	            <div className="flex items-center justify-between">
	              <div>
	                <p className="text-sm text-gray-500">OS Pendentes</p>
	                <p className="text-2xl font-bold text-yellow-600">
                  {ordensCarregadas && !ordensDesatualizadas ? formatarValor(valorPendenteOS) : "—"}
	                </p>
              </div>
              <div className="w-12 h-12 bg-yellow-50 rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-yellow-600" />
              </div>
            </div>
	            <p className="text-xs text-gray-500 mt-2">
	              {ordensCarregadas
                ? `${resumoOrdens.pendentes} ordem(ns) pendente(s)`
	                : "Disponivel ao abrir Cobrancas ou Ordens"}
	            </p>
	          </div>

	          <div className="fc-finance-metric fc-finance-metric-fee">
	            <div className="flex items-center justify-between">
	              <div>
	                <p className="text-sm text-gray-500">Taxas de pagamento</p>
	                <p className="text-2xl font-bold text-amber-600">{formatarValor(resumo.taxas_pagamento || 0)}</p>
	              </div>
	              <div className="w-12 h-12 bg-amber-50 rounded-lg flex items-center justify-center">
	                <Receipt className="w-6 h-6 text-amber-600" />
	              </div>
	            </div>
	          </div>

	          <div className="fc-finance-metric fc-finance-metric-credit">
	            <div className="flex items-center justify-between">
	              <div>
	                <p className="text-sm text-gray-500">Creditos gerados</p>
	                <p className="text-2xl font-bold text-cyan-600">{formatarValor(resumo.creditos_gerados || 0)}</p>
	              </div>
	              <div className="w-12 h-12 bg-cyan-50 rounded-lg flex items-center justify-center">
	                <TrendingUp className="w-6 h-6 text-cyan-600" />
	              </div>
	            </div>
	          </div>
	        </div>

	        <div className="fc-finance-panel">
	          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
	            <div>
	              <h2 className="text-base font-semibold text-gray-900">Cadastro de meios de pagamento</h2>
	              <p className="text-xs text-gray-500">
	                Cadastre bandeiras e formas com taxa para uso no recebimento da OS.
	              </p>
	            </div>
	            <div className="flex gap-2">
	              <button
	                onClick={cadastrarBandeiraRapido}
	                className="fc-finance-secondary"
	              >
	                Nova bandeira
	              </button>
	              <button
	                onClick={cadastrarFormaPagamentoRapido}
	                className="fc-finance-primary"
	              >
	                Nova forma
	              </button>
	            </div>
	          </div>
	          <div className="mt-3 overflow-x-auto">
	            <table className="fc-finance-table">
	              <thead className="bg-gray-50 text-gray-600">
	                <tr>
	                  <th className="text-left px-3 py-2">Forma</th>
	                  <th className="text-left px-3 py-2">Tipo</th>
	                  <th className="text-left px-3 py-2">Adquirente</th>
	                  <th className="text-right px-3 py-2">Taxa %</th>
	                  <th className="text-right px-3 py-2">Taxa fixa</th>
	                  <th className="text-left px-3 py-2">Bandeira</th>
	                  <th className="text-right px-3 py-2">Acao</th>
	                </tr>
	              </thead>
	              <tbody>
	                {formasPagamentoDisponiveis.length === 0 ? (
	                  <tr>
	                    <td colSpan={7} className="px-3 py-4 text-center text-gray-500">
	                      Nenhuma forma de pagamento cadastrada.
	                    </td>
	                  </tr>
	                ) : (
	                  formasPagamentoDisponiveis.map((forma) => {
	                    const bandeira = bandeirasCartao.find((b) => b.id === forma.bandeira_id);
	                    return (
	                      <tr key={`${forma.id ?? forma.codigo}`} className="border-t">
	                        <td className="px-3 py-2">{forma.nome}</td>
	                        <td className="px-3 py-2">{forma.tipo || "-"}</td>
	                        <td className="px-3 py-2">{forma.adquirente || "-"}</td>
	                        <td className="px-3 py-2 text-right">{Number(forma.taxa_percentual || 0).toFixed(2)}%</td>
	                        <td className="px-3 py-2 text-right">{formatarValor(Number(forma.taxa_fixa || 0))}</td>
	                        <td className="px-3 py-2">{forma.bandeira_nome || bandeira?.nome || "-"}</td>
		                        <td className="px-3 py-2 text-right">
		                          {forma.id ? (
		                            <div className="flex justify-end gap-3">
		                              <button
		                                onClick={() => editarTaxasFormaPagamento(forma)}
		                                className="text-blue-600 hover:text-blue-700"
		                              >
		                                Editar taxas
		                              </button>
		                              <button
		                                onClick={() => desativarFormaPagamento(forma.id)}
		                                className="text-red-600 hover:text-red-700"
		                              >
		                                Desativar
		                              </button>
		                            </div>
		                          ) : (
		                            <span className="text-gray-400">-</span>
		                          )}
		                        </td>
	                      </tr>
	                    );
	                  })
	                )}
	              </tbody>
	            </table>
	          </div>
	        </div>

	        {/* Abas */}
	        <div className="fc-finance-tabs" role="tablist" aria-label="Área financeira">
          <button
            onClick={() => setAbaAtiva("transacoes")}
            className={`fc-finance-tab ${abaAtiva === "transacoes" ? "fc-finance-tab-active" : ""}`}
            role="tab"
            aria-selected={abaAtiva === "transacoes"}
          >
            <Receipt className="w-4 h-4" />
            Transacoes
            <span className="fc-finance-tab-count">
              {transacoesCarregadas && !transacoesDesatualizadas ? totalTransacoes : "—"}
            </span>
          </button>
          <button
            onClick={() => setAbaAtiva("cobrancas")}
            className={`fc-finance-tab ${abaAtiva === "cobrancas" ? "fc-finance-tab-active" : ""}`}
            role="tab"
            aria-selected={abaAtiva === "cobrancas"}
          >
            <MessageCircle className="w-4 h-4" />
            Cobrancas
            <span className="fc-finance-tab-count fc-finance-tab-count-amber">
              {ordensCarregadas ? `${totalGrupos} destinatario(s)` : "—"}
            </span>
          </button>
          <button
            onClick={() => setAbaAtiva("ordens")}
            className={`fc-finance-tab ${abaAtiva === "ordens" ? "fc-finance-tab-active" : ""}`}
            role="tab"
            aria-selected={abaAtiva === "ordens"}
          >
            <FileText className="w-4 h-4" />
            Ordens de Servico
            <span className="fc-finance-tab-count fc-finance-tab-count-amber">
              {ordensCarregadas && !ordensDesatualizadas ? totalOrdens : "—"}
            </span>
          </button>
        </div>

        {/* Filtros */}
        <div className="fc-finance-filters">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="relative md:col-span-2 lg:col-span-2">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
              <input
                type="text"
                placeholder={
                  abaAtiva === "transacoes"
                    ? "Buscar transacao..."
                    : abaAtiva === "cobrancas"
                      ? "Buscar destinatario, paciente ou OS..."
                      : "Buscar OS..."
                }
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
              />
            </div>

            <select
              value={abaAtiva === "transacoes" ? filtroStatusTransacao : filtroStatusOS}
              onChange={(e) =>
                abaAtiva === "transacoes"
                  ? setFiltroStatusTransacao(e.target.value)
                  : setFiltroStatusOS(e.target.value)
              }
              className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
            >
              <option value="todos">Todos os status</option>
              <option value="Pendente">Pendente</option>
              {abaAtiva === "transacoes" ? (
                <option value="Recebido">Recebido</option>
              ) : null}
              <option value="Pago">Pago</option>
              <option value="Cancelado">Cancelado</option>
            </select>

            <div className="grid grid-cols-2 gap-2">
              <input
                type="date"
                value={filtroDataInicio}
                onChange={(e) => setFiltroDataInicio(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                title="Data inicio"
              />
              <input
                type="date"
                value={filtroDataFim}
                onChange={(e) => setFiltroDataFim(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                title="Data fim"
              />
            </div>

            {abaAtiva === "transacoes" && (
              <>
                <select
                  value={filtroTipo}
                  onChange={(e) => setFiltroTipo(e.target.value)}
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                >
                  <option value="todos">Todos os tipos</option>
                  <option value="entrada">Entradas</option>
                  <option value="saida">Saidas</option>
                </select>

                <select
                  value={filtroCategoria}
                  onChange={(e) => setFiltroCategoria(e.target.value)}
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                >
                  <option value="todos">Todas categorias</option>
                  {CATEGORIAS_TRANSACAO.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.nome}
                    </option>
                  ))}
                </select>

	                <select
	                  value={filtroFormaPagamento}
	                  onChange={(e) => setFiltroFormaPagamento(e.target.value)}
	                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
	                >
	                  <option value="todos">Todas formas</option>
	                  {formasPagamentoDisponiveis.map((fp) => {
	                    const codigo = normalizarCodigoFormaPagamento(fp.codigo);
	                    return (
	                      <option key={`${codigo}-${fp.id ?? "fallback"}`} value={codigo}>
	                        {descricaoFormaPagamentoConfig(fp)}
	                      </option>
	                    );
	                  })}
	                </select>
              </>
            )}

            {(abaAtiva === "ordens" || abaAtiva === "cobrancas") && (
              <>
                <select
                  value={filtroClinicaOS}
                  onChange={(e) => setFiltroClinicaOS(e.target.value)}
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                >
                  <option value="todos">Todas clinicas</option>
                  {clinicas.map((c) => (
                    <option key={c.id} value={String(c.id)}>
                      {c.nome}
                    </option>
                  ))}
                </select>

                <select
                  value={filtroOrigemAtendimentoOS}
                  onChange={(e) => setFiltroOrigemAtendimentoOS(e.target.value)}
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                >
                  <option value="todos">Todas origens</option>
                  <option value="clinica_parceira">Clinica parceira</option>
                  <option value="domiciliar">Atendimento domiciliar</option>
                </select>

                <select
                  value={filtroServicoOS}
                  onChange={(e) => setFiltroServicoOS(e.target.value)}
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                >
                  <option value="todos">Todos servicos</option>
                  {servicos.map((s) => (
                    <option key={s.id} value={String(s.id)}>
                      {s.nome}
                    </option>
                  ))}
                </select>

                <select
                  value={filtroTipoHorarioOS}
                  onChange={(e) => setFiltroTipoHorarioOS(e.target.value)}
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                >
                  <option value="todos">Todos horarios</option>
                  <option value="comercial">Comercial</option>
                  <option value="plantao">Plantao</option>
                </select>
              </>
            )}
          </div>

          <div className="flex flex-wrap gap-2 mt-3">
            <button
              onClick={() => void carregarDados()}
              className="fc-finance-secondary"
            >
              Atualizar
            </button>
            <button
              onClick={limparFiltros}
              className="fc-finance-secondary"
            >
              Limpar filtros
            </button>
          </div>
        </div>

        {/* Conteudo - Transacoes */}
        {abaAtiva === "transacoes" && (
          <div className="fc-finance-content">
            <div className="p-5 border-b flex justify-between items-center">
              <h2 className="text-lg font-semibold text-gray-900">
                Transacoes 
                <span className="text-sm font-normal text-gray-500 ml-2">
                  ({transacoesDesatualizadas ? "—" : totalTransacoes})
                </span>
              </h2>
            </div>
            
            {falhasCarregamento.includes("Transacoes") ? (
              <div role="alert" className="p-8 text-center">
                <p>Nao foi possivel carregar as transacoes.</p>
                <button className="fc-finance-secondary" onClick={() => void carregarDados()}>Recarregar transacoes</button>
              </div>
            ) : loadingTransacoes || transacoesDesatualizadas ? (
              <div className="p-8 text-center text-gray-500">Carregando...</div>
            ) : transacoesFiltradas.length === 0 ? (
              <div className="p-12 text-center">
                <DollarSign className="w-12 h-12 text-gray-300 mx-auto mb-4" />
                <p className="text-gray-500">Nenhuma transacao encontrada</p>
              </div>
            ) : (
              <div className="divide-y">
                {transacoesFiltradas.map((t) => (
                  <div key={t.id} className="p-4 hover:bg-gray-50">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                      {/* Icon */}
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        t.tipo === 'entrada' ? 'bg-green-100' : 'bg-red-100'
                      }`}>
                        {t.tipo === 'entrada' ? (
                          <ArrowUpRight className="w-5 h-5 text-green-600" />
                        ) : (
                          <ArrowDownRight className="w-5 h-5 text-red-600" />
                        )}
                      </div>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-medium text-gray-900">{t.descricao}</p>
                          <span className={`px-2 py-0.5 text-xs rounded-full ${getStatusColor(t.status)}`}>
                            {getStatusIcon(t.status)}
                            <span className="ml-1">{t.status}</span>
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500 mt-1">
                          <span className="bg-gray-100 px-2 py-0.5 rounded text-xs">
                            {getCategoriaNome(t.categoria)}
                          </span>
                          {t.paciente_nome && <span>- {t.paciente_nome}</span>}
                          <span>- {formatarData(t.data_transacao)}</span>
                          <span>- {getFormaPagamentoNome(t.forma_pagamento)}</span>
                        </div>
                      </div>

                      {/* Valor e Acoes */}
                      <div className="flex items-center gap-4">
                        <div className="text-right">
                          <p className={`font-medium ${
                            t.tipo === 'entrada' ? 'text-green-600' : 'text-red-600'
                          }`}>
                            {t.tipo === 'entrada' ? '+' : '-'}{formatarValor(t.valor_final)}
                          </p>
                          {(t.desconto || 0) > 0 && (
                            <p className="text-xs text-gray-400">
                              Desc: {formatarValor(t.desconto)}
                            </p>
                          )}
                        </div>

                        {/* Acoes */}
                        <div className="flex gap-1">
                          {t.status === 'Pendente' && (
                            <button
                              onClick={() => handlePagar(t.id)}
                              className="p-1.5 text-green-600 hover:bg-green-50 rounded"
                              title="Marcar como pago/recebido"
                            >
                              <CheckCircle className="w-4 h-4" />
                            </button>
                          )}
                          <button
                            onClick={() => handleEditar(t)}
                            className="p-1.5 text-blue-600 hover:bg-blue-50 rounded"
                            title="Editar"
                          >
                            <Edit className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleExcluir(t.id)}
                            className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                            title="Excluir"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {abaAtiva === "transacoes" && (
          <nav aria-label="Paginacao de transacoes" className="flex items-center justify-between gap-3 p-4">
            <button className="fc-finance-secondary" disabled={loadingTransacoes || transacoesDesatualizadas || paginaAtualTransacoes === 0}
              onClick={() => setPaginaTransacoes({ chave: chaveTransacoes, numero: paginaAtualTransacoes - 1 })}>Anterior</button>
            <span aria-live="polite">
              Pagina {paginaAtualTransacoes + 1} de {Math.max(1, Math.ceil(totalTransacoes / 100))} — ate 100 por pagina
            </span>
            <button className="fc-finance-secondary" disabled={loadingTransacoes || transacoesDesatualizadas || falhasCarregamento.includes("Transacoes") || (paginaAtualTransacoes + 1) * 100 >= totalTransacoes}
              onClick={() => setPaginaTransacoes({ chave: chaveTransacoes, numero: paginaAtualTransacoes + 1 })}>Proxima</button>
          </nav>
        )}

        {/* Conteudo - Cobrancas */}
        {abaAtiva === "cobrancas" && (
          <div className="fc-finance-content">
            <div className="p-5 border-b flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">
                  Cobrancas por Destinatario
                  <span className="text-sm font-normal text-gray-500 ml-2">
                    ({totalGrupos})
                  </span>
                </h2>
                <p className="text-xs text-amber-700 mt-1">
                  Pendencias totais: <span className="font-semibold">{formatarValor(totalPendenteAgrupado)}</span>
                </p>
              </div>
              <button
                onClick={() => baixarRelatorioPendenciasPDF()}
                disabled={loadingOrdens || cobrancasDesatualizadas || falhasCarregamento.includes("Cobrancas")}
                className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-white border border-amber-300 text-amber-800 rounded-lg hover:bg-amber-100"
              >
                <Download className="w-4 h-4" />
                Baixar relatorio pendente (PDF)
              </button>
              <button
                onClick={() => abrirRecebimentoLoteOS(osSelecionadasBaixa)}
                disabled={osSelecionadasBaixa.length === 0 || loadingOrdens || cobrancasDesatualizadas || validandoSelecao || carregandoGrupo}
                className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50"
              >
                <CheckCircle className="w-4 h-4" />
                Receber selecionadas
                {osSelecionadasBaixa.length > 0 ? ` (${osSelecionadasBaixa.length})` : ""}
              </button>
            </div>

            <div className="p-4 border-b bg-white">
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm font-medium text-gray-700">Mensagem da cobranca (modelo unico)</label>
                <button
                  onClick={restaurarModeloMensagem}
                  className="text-xs text-blue-600 hover:text-blue-700"
                >
                  Restaurar padrao
                </button>
              </div>
              <p className="text-xs text-gray-500 mb-2">
                Campos automaticos: <code>{"{{destinatario}}"}</code> ou <code>________</code> destinatario,{" "}
                <code>{"{{data}}"}</code>, <code>{"{{lista_os}}"}</code> e <code>{"{{total_pendente}}"}</code>.
              </p>
              <div className="flex flex-wrap gap-2 mb-2">
                {PLACEHOLDERS_MENSAGEM_COBRANCA.map((item) => (
                  <button
                    key={item.valor}
                    type="button"
                    onClick={() => inserirPlaceholderNoModelo(item.valor)}
                    className="px-2.5 py-1 text-xs rounded-full border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                    title={`Inserir ${item.valor}`}
                  >
                    {item.label}: <span className="font-mono">{item.valor}</span>
                  </button>
                ))}
              </div>
              <textarea
                ref={textareaMensagemRef}
                rows={6}
                value={mensagemCobrancaModelo}
                onChange={(e) => setMensagemCobrancaModelo(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent bg-white"
              />
            </div>

            <nav aria-label="Paginacao de cobrancas" className="flex items-center justify-between gap-3 p-4">
              <button disabled={loadingOrdens || cobrancasDesatualizadas || validandoSelecao || paginaAtualCobrancas === 0}
                onClick={() => setPaginaCobrancas({ chave: chaveOrdens, numero: paginaAtualCobrancas - 1 })}>Anterior</button>
              <span>Pagina {paginaAtualCobrancas + 1} de {Math.max(1, Math.ceil(totalGrupos / 50))} — ate 50 destinatarios por pagina</span>
              <button disabled={loadingOrdens || cobrancasDesatualizadas || validandoSelecao || falhasCarregamento.includes("Cobrancas") || (paginaAtualCobrancas + 1) * 50 >= totalGrupos}
                onClick={() => setPaginaCobrancas({ chave: chaveOrdens, numero: paginaAtualCobrancas + 1 })}>Proxima</button>
              <button disabled={loadingOrdens} onClick={() => void recarregarCobrancas()}>Atualizar destinatarios</button>
            </nav>
            {falhasCarregamento.includes("Cobrancas") ? <p role="alert" className="p-4 text-red-700">Falha ao carregar destinatarios. Use Atualizar destinatarios para tentar novamente.</p> :
              loadingOrdens || cobrancasDesatualizadas ? <p className="p-4">Carregando destinatarios...</p> :
              gruposRemotos.length === 0 ? <p className="p-4">Nenhuma cobranca encontrada para os filtros atuais</p> :
              <div className="p-4 space-y-2">
                {gruposRemotos.map((grupo) => {
                  const expandido = grupoAberto === grupo.chave;
                  const detalhesId = `cobrancas-detalhes-${grupo.chave.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
                  const grupoDetalhado = gruposCobrancaDestinatario.find(
                    (detalhe) => detalhe.chave === grupo.chave
                  );
                  const ordensPendentes = grupoDetalhado?.ordens.filter(
                    (os) => os.status === "Pendente"
                  ) || [];

                  return (
                    <section
                      key={grupo.chave}
                      aria-label={`Cobrancas de ${grupo.nome_destinatario}`}
                      className="overflow-hidden rounded-lg border border-gray-200 bg-white"
                    >
                      <div className="flex items-center justify-between gap-3 p-3">
                        <span>
                          {grupo.nome_destinatario} — {grupo.quantidade_os} pendente(s) de {grupo.quantidade_total} OS — {formatarValor(grupo.total_pendente)}
                        </span>
                        <button
                          type="button"
                          aria-controls={detalhesId}
                          aria-expanded={expandido}
                          aria-label={`${expandido ? "Fechar" : "Abrir"} destinatario ${grupo.nome_destinatario}`}
                          disabled={validandoSelecao}
                          onClick={() => expandido ? fecharGrupo() : void abrirDetalhesGrupo(grupo)}
                          className="inline-flex items-center gap-2 text-right text-sm font-medium text-gray-700 hover:text-gray-950 disabled:opacity-50"
                        >
                          {expandido ? "Fechar destinatario" : "Abrir destinatario"} {grupo.nome_destinatario}
                          <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${expandido ? "rotate-180" : ""}`} />
                        </button>
                      </div>

                      {expandido && (
                        <div id={detalhesId} className="border-t border-amber-200 bg-amber-50/30">
                          {carregandoGrupo ? (
                            <p role="status" className="p-4 text-sm text-gray-600">
                              Carregando as OS pendentes deste destinatario; as acoes aguardam a conferencia.
                            </p>
                          ) : erroGrupo ? (
                            <div role="alert" className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm text-red-700">
                              <span>{erroGrupo}</span>
                              <button
                                type="button"
                                onClick={() => void abrirDetalhesGrupo(grupo)}
                                className="rounded-lg border border-red-200 bg-white px-3 py-1.5 font-medium hover:bg-red-50"
                              >
                                Tentar novamente
                              </button>
                            </div>
                          ) : grupoDetalhado ? (
                            <fieldset disabled={validandoSelecao}>
                              <legend className="sr-only">OS pendentes de {grupo.nome_destinatario}</legend>
                              <div className="flex flex-col gap-3 border-b border-amber-100 p-4 lg:flex-row lg:items-center lg:justify-between">
                                <div>
                                  <p className="text-xs text-gray-500">
                                    {grupoDetalhado.tipo_destinatario === "tutor" ? "Atendimento domiciliar" : "Clinica parceira"}
                                  </p>
                                  <p className="text-xs text-gray-500">
                                    Contato: {grupoDetalhado.telefone_destinatario || grupoDetalhado.email_destinatario || "nao informado"}
                                  </p>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                  <button
                                    onClick={() => abrirRecebimentoLoteOS(ordensPendentes.map((os) => os.id))}
                                    disabled={ordensPendentes.length === 0}
                                    className="flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
                                  >
                                    <CheckCircle className="h-4 w-4" />
                                    Receber pendentes
                                  </button>
                                  <button
                                    onClick={() => baixarRelatorioPendenciasPDF(grupoDetalhado)}
                                    className="flex items-center gap-1 rounded-lg bg-blue-100 px-3 py-1.5 text-sm text-blue-700 hover:bg-blue-200"
                                  >
                                    <FileText className="h-4 w-4" />
                                    Baixar PDF
                                  </button>
                                  <button
                                    onClick={() => copiarMensagemCobranca(grupoDetalhado)}
                                    className="flex items-center gap-1 rounded-lg bg-gray-100 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-200"
                                  >
                                    <Copy className="h-4 w-4" />
                                    Copiar mensagem
                                  </button>
                                  <button
                                    onClick={() => void enviarCobrancaWhatsApp(grupoDetalhado)}
                                    disabled={
                                      enviandoWhatsAppOficialGrupoKey === grupoDetalhado.chave ||
                                      ordensPendentes.some((os) => enviandoWhatsAppOficialOsId === os.id)
                                    }
                                    className="flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-sm text-white hover:bg-green-700 disabled:opacity-50"
                                  >
                                    <MessageCircle className="h-4 w-4" />
                                    {enviandoWhatsAppOficialGrupoKey === grupoDetalhado.chave ? "Enviando..." : "Enviar FortCordis"}
                                  </button>
                                </div>
                              </div>

                              {ordensPendentes.length === 0 ? (
                                <p className="p-4 text-sm text-gray-500">Nenhuma OS pendente para este destinatario.</p>
                              ) : (
                                <div className="divide-y divide-gray-100 bg-white">
                                  {ordensPendentes.map((os) => (
                                    <div key={os.id} id={`os-row-${os.id}`} className={`p-4 ${osHighlightId === os.id ? "bg-amber-50 ring-2 ring-amber-200" : ""}`}>
                                      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
                                        <div className="flex items-center gap-3">
                                          <input
                                            type="checkbox"
                                            checked={osSelecionadasBaixa.includes(os.id)}
                                            onChange={() => toggleSelecaoBaixaOS(os.id)}
                                            className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                                            title="Selecionar para baixa em lote"
                                          />
                                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-100">
                                            <FileText className="h-5 w-5 text-blue-600" />
                                          </div>
                                        </div>
                                        <div className="min-w-0 flex-1 space-y-2">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <span className="text-sm font-semibold text-gray-900">
                                              {formatarDataHoraCurta(os.data_atendimento)}
                                            </span>
                                            <span className={`rounded-full px-2 py-0.5 text-xs ${getStatusColor(os.status)}`}>
                                              {getStatusIcon(os.status)}
                                              <span className="ml-1">{os.status}</span>
                                            </span>
                                            <span className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
                                              {os.tipo_horario === "plantao" ? "Plantao" : "Comercial"}
                                            </span>
                                            <span className="text-xs text-gray-400">OS #{os.numero_os}</span>
                                          </div>
                                          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-700">
                                            <span className="font-semibold">{os.paciente || "Paciente nao informado"}</span>
                                            <span>Tutor: {os.tutor || "Nao informado"}</span>
                                            <span>Servico: {os.servico || "Nao informado"}</span>
                                          </div>
                                          {(os.observacoes || "").trim() && (
                                            <p className="line-clamp-2 text-xs text-gray-500">Obs: {os.observacoes}</p>
                                          )}
                                        </div>
                                        <div className="flex items-center gap-3 lg:ml-2">
                                          <div className="min-w-[120px] text-right">
                                            <p className="font-bold text-gray-900">{formatarValor(os.valor_final)}</p>
                                            {(os.desconto || 0) > 0 && (
                                              <p className="text-xs text-gray-400">Desc: {formatarValor(os.desconto)}</p>
                                            )}
                                          </div>
                                          <div className="flex flex-wrap justify-end gap-2">
                                            <button
                                              onClick={() => handlePagarOS(os)}
                                              className="flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-sm text-white hover:bg-green-700"
                                            >
                                              <CheckCircle className="h-4 w-4" />
                                              Receber
                                            </button>
                                            <button
                                              onClick={() => handleEditarOS(os)}
                                              className="flex items-center gap-1 rounded-lg bg-blue-100 px-3 py-1.5 text-sm text-blue-700 hover:bg-blue-200"
                                            >
                                              <Edit className="h-4 w-4" />
                                              Editar
                                            </button>
                                            <button
                                              onClick={() => void abrirAjusteValorOS(os)}
                                              aria-label={`Ajustar valor da OS ${os.numero_os}`}
                                              className="flex items-center gap-1 rounded-lg bg-amber-100 px-3 py-1.5 text-sm text-amber-800 hover:bg-amber-200"
                                            >
                                              <DollarSign className="h-4 w-4" />
                                              Ajustar valor
                                            </button>
                                            <button
                                              onClick={() => handleExcluirOS(os)}
                                              className="rounded p-1.5 text-red-600 hover:bg-red-50"
                                              aria-label={`Excluir OS ${os.numero_os}`}
                                            >
                                              <Trash2 className="h-4 w-4" />
                                            </button>
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </fieldset>
                          ) : (
                            <p className="p-4 text-sm text-gray-500">Nenhuma OS pendente para este destinatario.</p>
                          )}
                        </div>
                      )}
                    </section>
                  );
                })}
              </div>}
          </div>
        )}

        {/* Conteudo - Ordens de Servico */}
        {erroSelecao && <div role="alert" className="p-4 text-red-700">{erroSelecao}</div>}
        {abaAtiva === "ordens" && (
          <nav aria-label="Paginacao de ordens" className="flex flex-wrap items-center gap-3 p-4">
            <button className="fc-finance-secondary" disabled={loadingOrdens || ordensDesatualizadas || validandoSelecao || paginaAtualOrdens === 0}
              onClick={() => setPaginaOrdens({ chave: chaveOrdens, numero: paginaAtualOrdens - 1 })}>Anterior</button>
            <span aria-live="polite">Pagina {paginaAtualOrdens + 1} de {Math.max(1, Math.ceil(totalOrdens / 100))} — ate 100 OS por pagina</span>
            <button className="fc-finance-secondary" disabled={loadingOrdens || ordensDesatualizadas || validandoSelecao || (paginaAtualOrdens + 1) * 100 >= totalOrdens}
              onClick={() => setPaginaOrdens({ chave: chaveOrdens, numero: paginaAtualOrdens + 1 })}>Proxima</button>
            {osAlvoId && <button className="fc-finance-secondary" onClick={() => setOsAlvoId(null)}>Ver todas as ordens</button>}
            <p className="w-full text-sm">Selecoes mantidas entre paginas. Alterar filtros ou aba limpa a selecao. Selecionar pendentes/recebidas inclui apenas a pagina visivel.</p>
            {validandoSelecao && <p role="status">Conferindo OS selecionadas...</p>}
            {falhasCarregamento.includes("Ordens de servico") && <div role="alert">
              Nao foi possivel carregar as ordens.
              <button onClick={() => carregarDados()}>Recarregar ordens</button>
            </div>}
          </nav>
        )}
        {abaAtiva === "ordens" && (
          <fieldset className="fc-finance-content min-w-0" disabled={loadingOrdens || ordensDesatualizadas || validandoSelecao || falhasCarregamento.includes("Ordens de servico")}>
            <div className="p-5 border-b flex flex-col lg:flex-row lg:justify-between lg:items-center gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">
                  Ordens de Servico
                  <span className="text-sm font-normal text-gray-500 ml-2">
                    ({ordensDesatualizadas ? "—" : totalOrdens})
                  </span>
                </h2>
                <p className="text-sm text-gray-500">
                  Geradas por agendamentos ou pelo upload de laudos
                </p>
                <p className="text-xs text-emerald-700 mt-1">
                  {osRecebidasFiltradas.length} OS recebida(s) visivel(is) | {osSelecionadasRecibo.length} selecionada(s) para recibo
                </p>
                <p className="text-xs text-amber-700 mt-1">
                  {osPendentesFiltradas.length} OS pendente(s) visivel(is) | {osSelecionadasBaixa.length} selecionada(s) para baixa
                  {osSelecionadasBaixa.length > 0 ? ` | Total ${formatarValor(totalSelecionadoBaixa)}` : ""}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={selecionarTodasPendentesVisiveis}
                  disabled={osPendentesFiltradas.length === 0}
                  className="px-3 py-1.5 text-sm bg-white border border-amber-300 text-amber-800 rounded-lg hover:bg-amber-50 disabled:opacity-50"
                >
                  Selecionar pendentes
                </button>
                <button
                  onClick={limparSelecaoBaixa}
                  disabled={osSelecionadasBaixa.length === 0}
                  className="px-3 py-1.5 text-sm bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Limpar baixa
                </button>
                <button
                  onClick={() => abrirRecebimentoLoteOS(osSelecionadasBaixa)}
                  disabled={osSelecionadasBaixa.length === 0}
                  className="px-3 py-1.5 text-sm bg-emerald-600 text-white hover:bg-emerald-700 rounded-lg flex items-center gap-1 disabled:opacity-50"
                >
                  <CheckCircle className="w-4 h-4" />
                  Receber selecionadas
                </button>
                <button
                  onClick={selecionarTodasRecebidasVisiveis}
                  disabled={osRecebidasFiltradas.length === 0}
                  className="px-3 py-1.5 text-sm bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Selecionar recebidas
                </button>
                <button
                  onClick={limparSelecaoRecibo}
                  disabled={osSelecionadasRecibo.length === 0}
                  className="px-3 py-1.5 text-sm bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Limpar selecao
                </button>
                <button
                  onClick={() => abrirPreviewRecibo(osSelecionadasRecibo, osSelecionadasRecibo.length > 1)}
                  disabled={osSelecionadasRecibo.length === 0 || carregandoPreviewRecibo}
                  className="px-3 py-1.5 text-sm bg-white border border-blue-200 text-blue-700 rounded-lg hover:bg-blue-50 flex items-center gap-1 disabled:opacity-50"
                >
                  <FileText className="w-4 h-4" />
                  {carregandoPreviewRecibo ? "Abrindo previa..." : "Previa"}
                </button>
                <button
                  onClick={() => baixarReciboOSPDF(osSelecionadasRecibo, false)}
                  disabled={osSelecionadasRecibo.length === 0}
                  className="px-3 py-1.5 text-sm bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg flex items-center gap-1 disabled:opacity-50"
                >
                  <Receipt className="w-4 h-4" />
                  Gerar recibo
                </button>
                <button
                  onClick={() => baixarReciboOSPDF(osSelecionadasRecibo, true)}
                  disabled={osSelecionadasRecibo.length === 0}
                  className="px-3 py-1.5 text-sm bg-emerald-600 text-white hover:bg-emerald-700 rounded-lg flex items-center gap-1 disabled:opacity-50"
                >
                  <Receipt className="w-4 h-4" />
                  Gerar recibo agrupado
                </button>
                <button
                  onClick={() => abrirComposerCompartilhamentoRecibo("whatsapp", osSelecionadasRecibo, osSelecionadasRecibo.length > 1)}
                  disabled={osSelecionadasRecibo.length === 0}
                  className="px-3 py-1.5 text-sm bg-green-600 text-white hover:bg-green-700 rounded-lg flex items-center gap-1 disabled:opacity-50"
                >
                  <MessageCircle className="w-4 h-4" />
                  WhatsApp
                </button>
                <button
                  onClick={() => abrirComposerCompartilhamentoRecibo("email", osSelecionadasRecibo, osSelecionadasRecibo.length > 1)}
                  disabled={osSelecionadasRecibo.length === 0}
                  className="px-3 py-1.5 text-sm bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-lg flex items-center gap-1 disabled:opacity-50"
                >
                  <Mail className="w-4 h-4" />
                  E-mail
                </button>
              </div>
            </div>

            <div className="p-4 border-b bg-white space-y-5">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700">Mensagem base do recibo individual</label>
                  <button
                    onClick={() => restaurarModeloMensagemRecibo("individual")}
                    className="text-xs text-blue-600 hover:text-blue-700"
                  >
                    Restaurar padrao
                  </button>
                </div>
                <div className="flex flex-wrap gap-2 mb-2">
                  {PLACEHOLDERS_MENSAGEM_RECIBO.map((item) => (
                    <button
                      key={`individual-${item.valor}`}
                      type="button"
                      onClick={() => inserirPlaceholderModeloRecibo(item.valor, "individual")}
                      className="px-2.5 py-1 text-xs rounded-full border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                    >
                      {item.label}: <span className="font-mono">{item.valor}</span>
                    </button>
                  ))}
                </div>
                <textarea
                  ref={textareaMensagemReciboIndividualRef}
                  rows={6}
                  value={mensagemReciboIndividualModelo}
                  onChange={(e) => setMensagemReciboIndividualModelo(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent bg-white"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700">Mensagem base do recibo agrupado</label>
                  <button
                    onClick={() => restaurarModeloMensagemRecibo("agrupado")}
                    className="text-xs text-blue-600 hover:text-blue-700"
                  >
                    Restaurar padrao
                  </button>
                </div>
                <div className="flex flex-wrap gap-2 mb-2">
                  {PLACEHOLDERS_MENSAGEM_RECIBO.map((item) => (
                    <button
                      key={`agrupado-${item.valor}`}
                      type="button"
                      onClick={() => inserirPlaceholderModeloRecibo(item.valor, "agrupado")}
                      className="px-2.5 py-1 text-xs rounded-full border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                    >
                      {item.label}: <span className="font-mono">{item.valor}</span>
                    </button>
                  ))}
                </div>
                <textarea
                  ref={textareaMensagemReciboAgrupadoRef}
                  rows={7}
                  value={mensagemReciboAgrupadoModelo}
                  onChange={(e) => setMensagemReciboAgrupadoModelo(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent bg-white"
                />
              </div>
            </div>

            {loadingOrdens || ordensDesatualizadas || falhasCarregamento.includes("Ordens de servico") ? (
              <div className="p-8 text-center text-gray-500">Carregando...</div>
            ) : osFiltradas.length === 0 ? (
              <div className="p-12 text-center">
                <FileText className="w-12 h-12 text-gray-300 mx-auto mb-4" />
                <p className="text-gray-500">Nenhuma ordem de servico encontrada</p>
              </div>
            ) : (
              <div className="divide-y">
                {osFiltradas.map((os) => (
                  <div
                    key={os.id}
                    id={`os-row-${os.id}`}
                    className={`p-4 transition-colors ${
                      osHighlightId === os.id
                        ? "bg-amber-50 ring-2 ring-amber-200"
                        : "hover:bg-gray-50"
                    }`}
                  >
                    <div className="flex flex-col lg:flex-row lg:items-start gap-4">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={
                            os.status === "Pago"
                              ? osSelecionadasRecibo.includes(os.id)
                              : osSelecionadasBaixa.includes(os.id)
                          }
                          disabled={os.status !== "Pago" && os.status !== "Pendente"}
                          onChange={() => {
                            if (os.status === "Pago") {
                              toggleSelecaoReciboOS(os.id);
                            } else if (os.status === "Pendente") {
                              toggleSelecaoBaixaOS(os.id);
                            }
                          }}
                          className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
                          title={
                            os.status === "Pago"
                              ? "Selecionar para recibo"
                              : os.status === "Pendente"
                                ? "Selecionar para baixa em lote"
                                : "Apenas OS recebidas geram recibo e OS pendentes podem ser recebidas em lote"
                          }
                        />
                        <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 bg-blue-100">
                          <FileText className="w-5 h-5 text-blue-600" />
                        </div>
                      </div>

                      <div className="flex-1 min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-gray-900">
                            {formatarDataHoraCurta(os.data_atendimento)}
                          </span>
                          <span className="text-sm font-semibold text-gray-900">
                            - {os.clinica || "Clinica nao informada"}
                          </span>
                          <span className={`px-2 py-0.5 text-xs rounded-full ${getStatusColor(os.status)}`}>
                            {getStatusIcon(os.status)}
                            <span className="ml-1">{os.status}</span>
                          </span>
                          <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                            {os.tipo_horario === "plantao" ? "Plantao" : "Comercial"}
                          </span>
                          <span className="text-xs text-gray-400">OS #{os.numero_os}</span>
                        </div>

                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-700">
                          <span className="font-semibold">{os.paciente || "Paciente nao informado"}</span>
                          <span>Tutor: {os.tutor || "Nao informado"}</span>
                          <span>Servico: {os.servico || "Nao informado"}</span>
                        </div>

                        {(os.observacoes || "").trim() && (
                          <p className="text-xs text-gray-500 line-clamp-2">
                            Obs: {os.observacoes}
                          </p>
                        )}
                      </div>

                      <div className="flex items-center gap-3 lg:ml-2">
                        <div className="text-right min-w-[120px]">
                          <p className="font-bold text-gray-900">{formatarValor(os.valor_final)}</p>
                          {(os.desconto || 0) > 0 && (
                            <p className="text-xs text-gray-400">Desc: {formatarValor(os.desconto)}</p>
                          )}
                        </div>

                        <div className="flex flex-wrap justify-end gap-2">
                          {os.status === "Pendente" && (
                            <button
                              onClick={() => handlePagarOS(os)}
                              className="px-3 py-1.5 text-sm bg-green-600 text-white hover:bg-green-700 rounded-lg flex items-center gap-1"
                              title="Marcar como pago e criar transacao"
                            >
                              <CheckCircle className="w-4 h-4" />
                              Receber
                            </button>
                          )}
                          {os.status === "Pago" && (
                            <button
                              onClick={() => abrirPreviewRecibo([os.id], false)}
                              className="px-3 py-1.5 text-sm bg-white border border-blue-200 text-blue-700 hover:bg-blue-50 rounded-lg flex items-center gap-1"
                              title="Visualizar recibo desta OS"
                            >
                              <FileText className="w-4 h-4" />
                              Previa
                            </button>
                          )}
                          {os.status === "Pago" && (
                            <button
                              onClick={() => baixarReciboOSPDF([os.id], false)}
                              className="px-3 py-1.5 text-sm bg-emerald-100 text-emerald-700 hover:bg-emerald-200 rounded-lg flex items-center gap-1"
                              title="Gerar recibo desta OS"
                            >
                              <Receipt className="w-4 h-4" />
                              Recibo
                            </button>
                          )}
                          {os.status === "Pago" && (
                            <button
                              onClick={() => abrirComposerCompartilhamentoRecibo("whatsapp", [os.id], false)}
                              className="px-3 py-1.5 text-sm bg-green-100 text-green-700 hover:bg-green-200 rounded-lg flex items-center gap-1"
                              title="Compartilhar recibo por WhatsApp"
                            >
                              <MessageCircle className="w-4 h-4" />
                              WhatsApp
                            </button>
                          )}
                          {os.status === "Pago" && (
                            <button
                              onClick={() => void avisarReciboPeloWhatsAppOficial(os)}
                              disabled={enviandoWhatsAppOficialOsId === os.id}
                              className="px-3 py-1.5 text-sm bg-green-600 text-white hover:bg-green-700 rounded-lg flex items-center gap-1 disabled:opacity-50"
                              title="Avisar pelo WhatsApp oficial que o recibo esta disponivel"
                            >
                              <MessageCircle className="w-4 h-4" />
                              {enviandoWhatsAppOficialOsId === os.id ? "Enviando..." : "FortCordis"}
                            </button>
                          )}
                          {os.status === "Pago" && (
                            <button
                              onClick={() => abrirComposerCompartilhamentoRecibo("email", [os.id], false)}
                              className="px-3 py-1.5 text-sm bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-lg flex items-center gap-1"
                              title="Compartilhar recibo por e-mail"
                            >
                              <Mail className="w-4 h-4" />
                              E-mail
                            </button>
                          )}
                          {os.status === "Pago" && (
                            <button
                              onClick={() => abrirDesfazerRecebimentoOS(os)}
                              className="px-3 py-1.5 text-sm bg-amber-100 text-amber-700 hover:bg-amber-200 rounded-lg flex items-center gap-1"
                              title="Desfazer recebimento"
                            >
                              <Undo2 className="w-4 h-4" />
                              Desfazer
                            </button>
                          )}
                          <button
                            onClick={() => handleEditarOS(os)}
                            className="px-3 py-1.5 text-sm bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg flex items-center gap-1"
                            title="Editar OS"
                          >
                            <Edit className="w-4 h-4" />
                            Editar
                          </button>
                          {os.status === "Pendente" && (
                            <button
                              onClick={() => void abrirAjusteValorOS(os)}
                              aria-label={`Ajustar valor da OS ${os.numero_os}`}
                              className="px-3 py-1.5 text-sm bg-amber-100 text-amber-800 hover:bg-amber-200 rounded-lg flex items-center gap-1"
                            >
                              <DollarSign className="w-4 h-4" />
                              Ajustar valor
                            </button>
                          )}
                          {(!os.laudo_id || os.status !== "Cancelado") && <button
                            onClick={() => handleExcluirOS(os)}
                            disabled={Boolean(os.laudo_id) && os.status !== "Pendente"}
                            className="p-1.5 text-red-600 hover:bg-red-50 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                            title={os.laudo_id
                              ? os.status === "Pago" ? "Desfaca o recebimento antes de cancelar esta OS" : "Cancelar OS"
                              : "Excluir OS"}
                            aria-label={os.laudo_id ? "Cancelar OS" : "Excluir OS"}
                          >
                            {os.laudo_id ? "Cancelar" : <Trash2 className="w-4 h-4" />}
                          </button>}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </fieldset>
        )}

        {/* Links para relatorios */}
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <a 
            href="/financeiro/relatorios"
            className="bg-white p-4 rounded-xl shadow-sm border hover:shadow-md transition-shadow flex items-center gap-3"
          >
            <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
              <BarChart3 className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="font-medium text-gray-900">Relatorios</p>
              <p className="text-sm text-gray-500">Analises detalhadas</p>
            </div>
          </a>
          <a 
            href="/financeiro/dashboard"
            className="bg-white p-4 rounded-xl shadow-sm border hover:shadow-md transition-shadow flex items-center gap-3"
          >
            <div className="w-10 h-10 bg-purple-50 rounded-lg flex items-center justify-center">
              <PieChart className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="font-medium text-gray-900">Dashboard</p>
              <p className="text-sm text-gray-500">Graficos e metricas</p>
            </div>
          </a>
          <a 
            href="/financeiro/contas"
            className="bg-white p-4 rounded-xl shadow-sm border hover:shadow-md transition-shadow flex items-center gap-3"
          >
            <div className="w-10 h-10 bg-orange-50 rounded-lg flex items-center justify-center">
              <Calendar className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <p className="font-medium text-gray-900">Contas</p>
              <p className="text-sm text-gray-500">A pagar / A receber</p>
            </div>
          </a>
        </div>
      </div>

      {modalDesfazerRecebimentoOS && (
        <DesfazerRecebimentoModal
          numeroOS={modalDesfazerRecebimentoOS.numero_os}
          paciente={modalDesfazerRecebimentoOS.paciente}
          clinica={modalDesfazerRecebimentoOS.clinica}
          valor={formatarValor(modalDesfazerRecebimentoOS.valor_final)}
          processando={desfazendoRecebimentoOS}
          erro={erroDesfazerRecebimentoOS}
          onCancel={fecharDesfazerRecebimentoOS}
          onConfirm={() => void confirmarDesfazerRecebimentoOS()}
        />
      )}

      {/* Modal de Transacao */}
      <TransacaoModal
        isOpen={modalAberto}
        onClose={() => setModalAberto(false)}
        onSuccess={carregarDados}
        transacao={transacaoEditando}
      />

      {/* Modal de Edicao de OS */}
      {modalEditarOS && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-40 p-4">
          <div className="bg-white rounded-lg w-full max-w-lg">
            <div className="p-6 border-b">
              <h3 className="text-lg font-semibold text-gray-900">Editar Ordem de Servico</h3>
              <p className="text-sm text-gray-500 mt-1">
                OS #{modalEditarOS.numero_os} - {modalEditarOS.paciente || "Paciente nao informado"}
              </p>
            </div>

            <div className="p-6 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {modalEditarOS.origem_atendimento !== "domiciliar" ? (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Clinica</label>
                    <select
                      value={formEditarOS.clinica_id}
                      aria-label="Clinica da OS"
                      disabled={Boolean(modalEditarOS.laudo_id) && modalEditarOS.status !== "Cancelado"}
                      onChange={(e) => setFormEditarOS((prev) => ({ ...prev, clinica_id: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                    >
                      <option value="">Selecione...</option>
                      {clinicas.map((c) => (
                        <option key={c.id} value={String(c.id)}>
                          {c.nome}
                        </option>
                      ))}
                    </select>
                    {modalEditarOS.laudo_id && modalEditarOS.status !== "Cancelado" ? (
                      <p className="mt-1 text-xs text-slate-500">A clinica acompanha o laudo. Cancele a OS antes de alterar esse vinculo.</p>
                    ) : null}
                  </div>
                ) : (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Origem</label>
                    <div className="w-full rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                      Atendimento domiciliar
                    </div>
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Servico</label>
                  <select
                    value={formEditarOS.servico_id}
                    onChange={(e) => setFormEditarOS((prev) => ({ ...prev, servico_id: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                  >
                    <option value="">Selecione...</option>
                    {servicos.map((s) => (
                      <option key={s.id} value={String(s.id)}>
                        {s.nome}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                {modalEditarOS.origem_atendimento === "domiciliar"
                  ? "Ao alterar serviço ou horário, o preço domiciliar cadastrado será aplicado à OS e poderá substituir um ajuste manual de valor."
                  : "Ao alterar clínica, serviço ou horário, o preço cadastrado será aplicado à OS e poderá substituir um ajuste manual de valor."}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Tipo de horario</label>
                  <select
                    value={formEditarOS.tipo_horario}
                    onChange={(e) => setFormEditarOS((prev) => ({ ...prev, tipo_horario: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                  >
                    <option value="comercial">Comercial</option>
                    <option value="plantao">Plantao</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Desconto (R$)</label>
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    value={formEditarOS.desconto}
                    onChange={(e) =>
                      setFormEditarOS((prev) => ({ ...prev, desconto: Number(e.target.value || 0) }))
                    }
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Observacoes</label>
                <textarea
                  rows={3}
                  value={formEditarOS.observacoes}
                  onChange={(e) => setFormEditarOS((prev) => ({ ...prev, observacoes: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                />
              </div>
            </div>

            <div className="p-6 border-t flex justify-end gap-3">
              <button
                onClick={() => setModalEditarOS(null)}
                className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg border"
              >
                Cancelar
              </button>
              <button
                onClick={salvarEdicaoOS}
                disabled={salvandoOS}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-60"
              >
                {salvandoOS ? "Salvando..." : "Salvar alteracoes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {modalAjustarValorOS && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black bg-opacity-50 p-4">
          <div role="dialog" aria-modal="true" aria-labelledby="titulo-ajuste-valor-os" className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white">
            <div className="border-b p-6">
              <h3 id="titulo-ajuste-valor-os" className="text-lg font-semibold text-gray-900">Ajustar valor da OS</h3>
              <p className="mt-1 text-sm text-gray-500">
                OS #{modalAjustarValorOS.numero_os} - {modalAjustarValorOS.paciente || "Paciente nao informado"}
              </p>
            </div>

            <div className="space-y-4 p-6">
              {carregandoAjusteOS ? (
                <p role="status" className="text-sm text-gray-600">Conferindo o valor e a situação atual da OS...</p>
              ) : (
                <>
                  <div className="grid grid-cols-1 gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm sm:grid-cols-2">
                    <div>
                      <p className="text-gray-600">Valor final atual</p>
                      <p className="font-semibold text-gray-900">{formatarValor(Number(modalAjustarValorOS.valor_final || 0))}</p>
                    </div>
                    <div>
                      <p className="text-gray-600">Desconto existente, mantido</p>
                      <p className="font-semibold text-gray-900">{formatarValor(Number(modalAjustarValorOS.desconto || 0))}</p>
                    </div>
                  </div>

                  <div>
                    <label htmlFor="novo-valor-final-os" className="mb-1 block text-sm font-medium text-gray-700">Novo valor final (R$)</label>
                    <input
                      id="novo-valor-final-os"
                      type="text"
                      inputMode="decimal"
                      value={novoValorFinalOS}
                      onChange={(event) => { setNovoValorFinalOS(event.target.value); setErroAjusteOS(""); }}
                      placeholder="0,00"
                      disabled={!ajusteOSConferido || salvandoAjusteOS}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-amber-500 focus:ring-2 focus:ring-amber-500 disabled:bg-gray-100"
                    />
                    <p className="mt-1 text-xs text-gray-500">Informe um valor maior que zero, com até duas casas decimais.</p>
                  </div>

                  {novoValorParaPrevia !== null && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
                      <p>O valor final passará de <strong>{formatarValor(Number(modalAjustarValorOS.valor_final || 0))}</strong> para <strong>{formatarValor(novoValorParaPrevia)}</strong>.</p>
                      <p className="mt-1">Desconto mantido: {formatarValor(Number(modalAjustarValorOS.desconto || 0))}. Valor do serviço resultante: {formatarValor(novoValorParaPrevia + Number(modalAjustarValorOS.desconto || 0))}.</p>
                    </div>
                  )}

                  <div>
                    <label htmlFor="motivo-ajuste-os" className="mb-1 block text-sm font-medium text-gray-700">Motivo do ajuste</label>
                    <textarea
                      id="motivo-ajuste-os"
                      rows={3}
                      maxLength={500}
                      value={motivoAjusteOS}
                      onChange={(event) => { setMotivoAjusteOS(event.target.value); setErroAjusteOS(""); }}
                      disabled={!ajusteOSConferido || salvandoAjusteOS}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-amber-500 focus:ring-2 focus:ring-amber-500 disabled:bg-gray-100"
                    />
                    <p className="mt-1 text-xs text-gray-500">O motivo será registrado na auditoria da OS. {motivoAjusteOS.length}/500 caracteres.</p>
                  </div>
                </>
              )}

              {erroAjusteOS && (
                <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                  <p>{erroAjusteOS}</p>
                  {erroAjusteOS.includes("mudou desde a conferencia") && (
                    <button type="button" onClick={() => void abrirAjusteValorOS(modalAjustarValorOS)} className="mt-2 font-semibold underline">
                      Recarregar OS
                    </button>
                  )}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 border-t p-6">
              <button type="button" onClick={fecharAjusteValorOS} disabled={salvandoAjusteOS} className="rounded-lg border px-4 py-2 text-gray-700 hover:bg-gray-100 disabled:opacity-60">
                Cancelar
              </button>
              <button type="button" onClick={() => void confirmarAjusteValorOS()} disabled={!ajusteOSConferido || carregandoAjusteOS || salvandoAjusteOS} className="rounded-lg bg-amber-600 px-4 py-2 text-white hover:bg-amber-700 disabled:opacity-60">
                {salvandoAjusteOS ? "Salvando..." : "Confirmar ajuste"}
              </button>
            </div>
          </div>
        </div>
      )}

      {modalCompartilharRecibo && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-40 p-4">
          <div className="bg-white rounded-lg w-full max-w-2xl">
            <div className="p-6 border-b">
              <h3 className="text-lg font-semibold text-gray-900">
                {modalCompartilharRecibo.canal === "email" ? "Revisar e-mail do recibo" : "Revisar mensagem do recibo"}
              </h3>
              <p className="text-sm text-gray-500 mt-1">
                {modalCompartilharRecibo.ids.length === 1
                  ? `1 OS selecionada`
                  : `${modalCompartilharRecibo.ids.length} OS selecionadas`}{" "}
                {modalCompartilharRecibo.agrupar ? "com recibo agrupado" : "com recibo individual"}
              </p>
            </div>

            <div className="p-6 space-y-4">
              {modalCompartilharRecibo.canal === "email" ? (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">E-mail de destino</label>
                  <input
                    type="email"
                    value={modalCompartilharRecibo.email}
                    onChange={(e) =>
                      setModalCompartilharRecibo((prev) =>
                        prev ? { ...prev, email: e.target.value } : prev
                      )
                    }
                    placeholder="destinatario@exemplo.com"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                  />
                </div>
              ) : (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">WhatsApp de destino</label>
                  <input
                    type="text"
                    value={modalCompartilharRecibo.telefone}
                    onChange={(e) =>
                      setModalCompartilharRecibo((prev) =>
                        prev ? { ...prev, telefone: e.target.value } : prev
                      )
                    }
                    placeholder="(85) 99999-9999"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                  />
                </div>
              )}

              {modalCompartilharRecibo.canal === "email" && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Assunto</label>
                  <input
                    type="text"
                    value={modalCompartilharRecibo.assunto}
                    onChange={(e) =>
                      setModalCompartilharRecibo((prev) =>
                        prev ? { ...prev, assunto: e.target.value } : prev
                      )
                    }
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                  />
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Mensagem</label>
                <textarea
                  rows={10}
                  value={modalCompartilharRecibo.mensagem}
                  onChange={(e) =>
                    setModalCompartilharRecibo((prev) =>
                      prev ? { ...prev, mensagem: e.target.value } : prev
                    )
                  }
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
                />
              </div>

              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                O sistema tenta compartilhar o PDF automaticamente. Se o navegador nao permitir, ele baixa o arquivo e abre o {modalCompartilharRecibo.canal === "email" ? "e-mail" : "WhatsApp"} com essa mensagem para anexo manual.
              </div>
            </div>

            <div className="p-6 border-t flex justify-end gap-3">
              <button
                onClick={() => setModalCompartilharRecibo(null)}
                disabled={enviandoCompartilhamentoRecibo}
                className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg border disabled:opacity-60"
              >
                Cancelar
              </button>
              <button
                onClick={confirmarCompartilhamentoRecibo}
                disabled={enviandoCompartilhamentoRecibo}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-60 flex items-center gap-2"
              >
                {modalCompartilharRecibo.canal === "email" ? <Mail className="w-4 h-4" /> : <MessageCircle className="w-4 h-4" />}
                {enviandoCompartilhamentoRecibo ? "Preparando..." : modalCompartilharRecibo.canal === "email" ? "Abrir e-mail" : "Abrir WhatsApp"}
              </button>
            </div>
          </div>
        </div>
      )}

      {previewRecibo && (
        <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-40 p-4">
          <div className="bg-white rounded-lg w-full max-w-6xl h-[90vh] flex flex-col overflow-hidden">
            <div className="p-4 border-b flex items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">{previewRecibo.titulo}</h3>
                <p className="text-sm text-gray-500">{previewRecibo.filename}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={abrirPreviewReciboNovaAba}
                  className="px-3 py-1.5 text-sm bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 rounded-lg flex items-center gap-1"
                >
                  <FileText className="w-4 h-4" />
                  Abrir em nova aba
                </button>
                <button
                  onClick={() => baixarReciboOSPDF(previewRecibo.ids, previewRecibo.agrupar)}
                  className="px-3 py-1.5 text-sm bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg flex items-center gap-1"
                >
                  <Download className="w-4 h-4" />
                  Baixar PDF
                </button>
                <button
                  onClick={fecharPreviewRecibo}
                  className="px-3 py-1.5 text-sm border rounded-lg text-gray-700 hover:bg-gray-50"
                >
                  Fechar
                </button>
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <ReciboPdfPreview blob={previewRecibo.blob} titulo={previewRecibo.filename} />
            </div>
          </div>
        </div>
      )}

      {/* Modal de Receber OS em lote */}
      {modalReceberLoteOS && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-40 p-4">
          <div role="dialog" aria-modal="true" aria-labelledby="receber-lote-titulo" className="bg-white rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b">
              <h3 id="receber-lote-titulo" className="text-lg font-semibold text-gray-900">Receber OS em lote</h3>
              <p className="text-sm text-gray-500 mt-1">
                {ordensRecebimentoLote.length} OS selecionada(s) para este lote
              </p>
            </div>

            <fieldset disabled={recebendoLoteOS || loteExigeRevisao} className="p-6 space-y-4 min-w-0">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                <div className="flex justify-between text-sm">
                  <span className="text-amber-900">Total das OS selecionadas</span>
                  <span className="font-semibold text-amber-950">{formatarValor(resumoPagamentoLoteOS.valorOS)}</span>
                </div>
                <div className="mt-2 max-h-32 overflow-auto text-xs text-amber-900">
                  {ordensRecebimentoLote.map((os) => (
                    <div key={os.id} className="flex justify-between gap-3 py-0.5">
                      <span>
                        OS {os.numero_os} - {os.paciente || "Paciente nao informado"}
                      </span>
                      <span className="font-medium">{formatarValor(Number(os.valor_final || 0))}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                {pagamentosRecebimentoOS.map((pagamento, index) => (
                  <div key={pagamento.id} className="rounded-lg border border-gray-200 p-3">
                    <div className="mb-2 text-xs font-medium text-gray-500">Pagamento {index + 1}</div>
                    <label className="block text-xs font-medium text-gray-600">Forma de pagamento</label>
                    <select
                      aria-label={`Forma do pagamento ${index + 1}`}
                      value={pagamento.forma_codigo}
                      onChange={(event) => atualizarLinhaPagamentoOS(pagamento.id, "forma_codigo", event.target.value)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
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
                      aria-label={`Valor do pagamento ${index + 1}`}
                      min="0"
                      step="0.01"
                      value={pagamento.valor}
                      onChange={(event) => atualizarLinhaPagamentoOS(pagamento.id, "valor", event.target.value)}
                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
                    />
                    <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
                      <span>Taxa estimada: {formatarValor(resumoPagamentoLoteOS.linhas[index]?.taxa || 0)}</span>
                      {pagamentosRecebimentoOS.length > 1 && (
                        <button
                          type="button"
                          onClick={() => removerLinhaPagamentoOS(pagamento.id)}
                          className="text-red-600 hover:text-red-700"
                        >
                          Remover
                        </button>
                      )}
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={adicionarLinhaPagamentoOS}
                  disabled={pagamentosRecebimentoOS.length >= 20}
                  className="text-sm font-medium text-blue-600 hover:text-blue-700"
                >
                  + Adicionar forma de pagamento
                </button>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Data do Recebimento</label>
                <input
                  type="date"
                  aria-label="Data do Recebimento"
                  value={dataRecebimentoOS}
                  onChange={(e) => setDataRecebimentoOS(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
                />
              </div>

              <div className="rounded-lg border border-green-200 bg-green-50 p-3">
                <label className="flex items-start gap-2 text-sm font-medium text-green-900">
                  <input
                    type="checkbox"
                    checked={enviarReciboPdfWhatsAppAposRecebimento}
                    disabled={!permiteReciboWhatsAppLote}
                    onChange={(event) => setEnviarReciboPdfWhatsAppAposRecebimento(event.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Enviar um recibo PDF consolidado pelo WhatsApp oficial após a baixa
                    <span className="mt-1 block text-xs font-normal text-green-800">
                      O PDF detalha OS, data do atendimento, serviço, tutor e pet.
                    </span>
                  </span>
                </label>
                {!recebimentoLoteMesmoDestinatario && (
                  <p className="mt-2 text-xs text-amber-800">
                    Para enviar um único recibo, selecione somente OS do mesmo destinatário.
                  </p>
                )}
                {ordensRecebimentoLote.length > 20 && (
                  <p className="mt-2 text-xs text-amber-800">
                    O envio de recibo consolidado pelo WhatsApp permite no maximo 20 OS por vez.
                  </p>
                )}
              </div>

              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
                <div className="flex justify-between">
                  <span>Total das OS</span>
                  <strong>{formatarValor(resumoPagamentoLoteOS.valorOS || 0)}</strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Total informado</span>
                  <strong>{formatarValor(resumoPagamentoLoteOS.totalBruto || 0)}</strong>
                </div>
                <div className="mt-1 flex justify-between">
                  <span>Total de taxas estimadas</span>
                  <strong>{formatarValor(resumoPagamentoLoteOS.totalTaxa || 0)}</strong>
                </div>
                {resumoPagamentoLoteOS.faltante > 0 && (
                  <p className="mt-1 text-red-700">
                    Falta cobrir {formatarValor(resumoPagamentoLoteOS.faltante)}.
                  </p>
                )}
                {resumoPagamentoLoteOS.excedente > 0 && (
                  <p className="mt-1 text-red-700">
                    Valor informado excede o total em {formatarValor(resumoPagamentoLoteOS.excedente)}.
                  </p>
                )}
              </div>
            </fieldset>

            <div className="sticky bottom-0 z-10 bg-white p-6 border-t">
              {erroRecebimentoLoteOS && (
                <p role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                  {erroRecebimentoLoteOS}
                </p>
              )}
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => {
                    setModalReceberLoteOS(null);
                    setErroRecebimentoLoteOS("");
                    if (loteExigeRevisao) setOsSelecionadasBaixa([]);
                    setLoteExigeRevisao(false);
                    setPagamentosRecebimentoOS([]);
                    setEnviarReciboPdfWhatsAppAposRecebimento(false);
                  }}
                  disabled={recebendoLoteOS}
                  className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg border disabled:opacity-60"
                >
                  {loteExigeRevisao ? "Fechar e revisar selecao" : "Cancelar"}
                </button>
                <button
                  onClick={confirmarRecebimentoLoteOS}
                  disabled={
                    recebendoLoteOS ||
                    loteExigeRevisao ||
                    resumoPagamentoLoteOS.faltante > 0 ||
                    resumoPagamentoLoteOS.excedente > 0 ||
                    ordensRecebimentoLote.length === 0
                  }
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-60"
                >
                  <CheckCircle className="w-4 h-4" />
                  {recebendoLoteOS ? "Recebendo..." : "Confirmar baixa em lote"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Receber OS */}
	      {modalReceberOS && (
	        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-40 p-4">
	          <div className="bg-white rounded-lg w-full max-w-md max-h-[90dvh] flex flex-col overflow-hidden">
	            <div className="shrink-0 p-6 border-b">
              <h3 className="text-lg font-semibold text-gray-900">Receber Ordem de Servico</h3>
              <p className="text-sm text-gray-500 mt-1">
                OS {modalReceberOS.numero_os} - {modalReceberOS.paciente}
              </p>
            </div>
            
	            <div className="min-h-0 flex-1 overflow-y-auto p-6 space-y-4">
	              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Valor:</span>
                  <span className="font-medium">{formatarValor(modalReceberOS.valor_final)}</span>
                </div>
                <div className="flex justify-between text-sm mt-1">
                  <span className="text-gray-600">Clinica:</span>
                  <span className="font-medium">{modalReceberOS.clinica}</span>
                </div>
                <div className="flex justify-between text-sm mt-1">
                  <span className="text-gray-600">Servico:</span>
	                  <span className="font-medium">{modalReceberOS.servico}</span>
	                </div>
	              </div>

              {carregandoSaldoCreditoClienteOS && (
                <div className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs text-cyan-800">
                  Consultando credito ativo do cliente...
                </div>
              )}
              {!carregandoSaldoCreditoClienteOS && erroSaldoCreditoClienteOS && (
                <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  {erroSaldoCreditoClienteOS}
                </div>
              )}
              {!carregandoSaldoCreditoClienteOS && saldoCreditoClienteOS > 0 && (
                <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Cliente com credito ativo: <strong>{formatarValor(saldoCreditoClienteOS)}</strong>. Avalie com o
                  cliente se deseja usar esse saldo antes de confirmar o recebimento.
                </div>
              )}

              <BaixaCredito
                onBusy={setBaixandoCredito}
                key={modalReceberOS.id}
                pacienteId={modalReceberOS.paciente_id}
                clinicaId={modalReceberOS.clinica_id}
                onSaldoCliente={(saldo) => {
                  setSaldoCreditoClienteOS(Math.max(0, saldo));
                  setUsarCreditoClienteOS(false);
                  setValorCreditoUtilizadoOS("0.00");
                }}
              />

	              <div className="space-y-3">
	                {pagamentosRecebimentoOS.map((pagamento, index) => (
	                  <div key={pagamento.id} className="rounded-lg border border-gray-200 p-3">
	                    <div className="mb-2 text-xs font-medium text-gray-500">Pagamento {index + 1}</div>
	                    <label className="block text-xs font-medium text-gray-600">Forma de pagamento</label>
	                    <select
	                      value={pagamento.forma_codigo}
	                      onChange={(event) => atualizarLinhaPagamentoOS(pagamento.id, "forma_codigo", event.target.value)}
	                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
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
	                      onChange={(event) => atualizarLinhaPagamentoOS(pagamento.id, "valor", event.target.value)}
	                      className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
	                    />
	                    <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
	                      <span>
	                        Taxa estimada: {formatarValor(resumoPagamentoOS.linhas[index]?.taxa || 0)}
	                      </span>
	                      {pagamentosRecebimentoOS.length > 1 && (
	                        <button
	                          type="button"
	                          onClick={() => removerLinhaPagamentoOS(pagamento.id)}
	                          className="text-red-600 hover:text-red-700"
	                        >
	                          Remover
	                        </button>
	                      )}
	                    </div>
	                  </div>
	                ))}
	                <button
	                  type="button"
	                  onClick={adicionarLinhaPagamentoOS}
	                  className="text-sm font-medium text-blue-600 hover:text-blue-700"
	                >
	                  + Adicionar forma de pagamento
	                </button>
	              </div>

	              <div>
	                <label className="block text-sm font-medium text-gray-700 mb-2">
	                  Data do Recebimento
	                </label>
                <input
                  type="date"
                  value={dataRecebimentoOS}
                  onChange={(e) => setDataRecebimentoOS(e.target.value)}
	                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
	                />
	              </div>

              <div className="rounded-lg border border-green-200 bg-green-50 p-3">
                <label className="flex items-start gap-2 text-sm font-medium text-green-900">
                  <input
                    type="checkbox"
                    checked={enviarReciboPdfWhatsAppAposRecebimento}
                    onChange={(event) => setEnviarReciboPdfWhatsAppAposRecebimento(event.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Enviar o recibo em PDF pelo WhatsApp oficial após registrar
                    <span className="mt-1 block text-xs font-normal text-green-800">
                      O documento informa OS, data do atendimento, serviço, tutor e pet.
                    </span>
                  </span>
                </label>
              </div>

              {!carregandoSaldoCreditoClienteOS && saldoCreditoClienteOS > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-amber-900">
                    <input
                      type="checkbox"
                      checked={usarCreditoClienteOS}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setUsarCreditoClienteOS(checked);
                        if (checked) {
                          const coberturaAtual = Math.max(
                            0,
                            Number(resumoPagamentoOS.valorOS || 0) - Number(resumoPagamentoOS.totalBruto || 0)
                          );
                          const sugestao = Math.min(
                            Number(saldoCreditoClienteOS || 0),
                            coberturaAtual > 0 ? coberturaAtual : Number(resumoPagamentoOS.valorOS || 0)
                          );
                          setValorCreditoUtilizadoOS(toMoneyInput(sugestao));
                        }
                      }}
                    />
                    Usar credito do cliente neste recebimento
                  </label>
                  {usarCreditoClienteOS && (
                    <div className="mt-2">
                      <label className="block text-xs font-medium text-amber-900">Valor do credito a usar</label>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        max={Number(saldoCreditoClienteOS || 0)}
                        value={valorCreditoUtilizadoOS}
                        onChange={(event) => setValorCreditoUtilizadoOS(event.target.value)}
                        className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-2 text-sm focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                      />
                      <div className="mt-1 text-xs text-amber-800">
                        Saldo disponivel: {formatarValor(saldoCreditoClienteOS)}.
                      </div>
                    </div>
                  )}
                </div>
              )}

	              {resumoPagamentoOS.excedente > 0 && (
	                <div>
	                  <label className="block text-sm font-medium text-gray-700 mb-2">
	                    Excedente detectado. Destino do credito
	                  </label>
	                  <select
	                    value={destinoCreditoExcedenteOS}
	                    onChange={(event) =>
	                      setDestinoCreditoExcedenteOS(event.target.value as "cliente" | "clinica" | "nenhum")
	                    }
	                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-green-500 focus:border-transparent"
	                  >
	                    <option value="cliente">Cliente</option>
	                    <option value="clinica">Clinica</option>
	                    <option value="nenhum">Nao gerar credito</option>
	                  </select>
	                </div>
	              )}

	              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
	                <div className="flex justify-between">
	                  <span>Valor da OS</span>
	                  <strong>{formatarValor(resumoPagamentoOS.valorOS || 0)}</strong>
	                </div>
	                <div className="flex justify-between">
	                  <span>Total bruto informado</span>
	                  <strong>{formatarValor(resumoPagamentoOS.totalBruto || 0)}</strong>
	                </div>
	                <div className="mt-1 flex justify-between">
	                  <span>Credito aplicado</span>
	                  <strong>{formatarValor(resumoPagamentoOS.creditoUtilizado || 0)}</strong>
	                </div>
	                <div className="mt-1 flex justify-between">
	                  <span>Total coberto</span>
	                  <strong>{formatarValor(resumoPagamentoOS.totalCoberto || 0)}</strong>
	                </div>
	                <div className="mt-1 flex justify-between">
	                  <span>Total de taxas estimadas</span>
	                  <strong>{formatarValor(resumoPagamentoOS.totalTaxa || 0)}</strong>
	                </div>
	                {resumoPagamentoOS.faltante > 0 && (
	                  <p className="mt-1 text-red-700">
	                    Falta cobrir {formatarValor(resumoPagamentoOS.faltante)} para atingir o valor da OS.
	                  </p>
	                )}
	                {resumoPagamentoOS.excedente > 0 && (
	                  <p className="mt-1 text-emerald-700">
	                    Excedente para credito: {formatarValor(resumoPagamentoOS.excedente)}.
	                  </p>
	                )}
	              </div>
	            </div>
	            
	            <div className="shrink-0 p-6 border-t flex justify-end gap-3">
              <button
                  disabled={baixandoCredito}
                onClick={() => {
                  setModalReceberOS(null);
                  setSaldoCreditoClienteOS(0);
                  setCarregandoSaldoCreditoClienteOS(false);
                  setErroSaldoCreditoClienteOS("");
                  setUsarCreditoClienteOS(false);
                  setValorCreditoUtilizadoOS("0.00");
                  setEnviarReciboPdfWhatsAppAposRecebimento(false);
                }}
                className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg border"
              >
                Cancelar
              </button>
	              <button
	                onClick={confirmarRecebimentoOS}
                    disabled={baixandoCredito || carregandoFormasPagamento || resumoPagamentoOS.faltante > 0}
	                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-60"
	              >
	                <CheckCircle className="w-4 h-4" />
	                Confirmar Recebimento
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
