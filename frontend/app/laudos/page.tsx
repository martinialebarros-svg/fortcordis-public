"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import { useRoutePerformanceReady } from "@/lib/use-route-performance-ready";
import api from "@/lib/axios";
import {
  getLaudoEditPath,
  getLaudoViewPath,
  getTipoLaudoLabel,
  TIPO_LAUDO_ELETROCARDIOGRAMA,
} from "@/lib/laudos";
import { baixarLaudoPdf, baixarLaudoPdfOriginal } from "@/lib/laudo-pdf";
import { formatCalendarDate, formatOperationalDate } from "@/lib/calendar-date";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import {
  getTituloBotaoAvisoWhatsApp,
  podeAvisarWhatsApp,
  resumirRespostaAvisoWhatsApp,
  type EnvioDestinoWhatsApp,
  type RespostaAvisoWhatsApp,
} from "@/lib/laudo-whatsapp-aviso";
import AvisoWhatsAppDialog from "./components/AvisoWhatsAppDialog";
import {
  AlertCircle,
  AlertTriangle,
  Calendar,
  Check,
  ChevronDown,
  Clock,
  Download,
  Edit,
  Eye,
  FileCheck,
  FileText,
  Gauge,
  Minus,
  MessageCircle,
  Plus,
  Search,
  Send,
  Star,
  Trash2,
  TrendingDown,
  TrendingUp,
  User,
} from "lucide-react";

interface Laudo {
  id: number;
  paciente_id: number;
  paciente_nome?: string;
  paciente_tutor?: string;
  clinica?: string;
  clinic_id?: number | null;
  atendimento_domiciliar?: boolean;
  veterinario_parceiro_id?: number | null;
  veterinario_parceiro_nome?: string;
  tipo: string;
  titulo: string;
  status: string;
  data_laudo: string;
  data_exame?: string;
  tem_pdf_externo?: boolean;
  portal_clinica_disponivel?: boolean;
  portal_clinica_liberado?: boolean;
  portal_veterinario_disponivel?: boolean;
  portal_veterinario_liberado?: boolean;
  portal_destinos_pendentes?: string[];
  portal_pode_liberar?: boolean;
  whatsapp_liberacao_status?: "enviado" | "falhou" | null;
  whatsapp_liberacao_em?: string | null;
  whatsapp_liberacao_erro?: string | null;
  whatsapp_parceiro_status?: "enviado" | "falhou" | null;
  whatsapp_parceiro_em?: string | null;
  whatsapp_parceiro_erro?: string | null;
  whatsapp_envios?: Record<string, EnvioDestinoWhatsApp> | null;
  portal_clinica_baixado_em?: string | null;
  portal_veterinario_baixado_em?: string | null;
}

interface Exame {
  id: number;
  paciente_id: number;
  tipo_exame: string;
  status: string;
  valor: number;
  data_solicitacao: string;
}

interface LaudoPendenteItem {
  exame_id: number | null;
  atendimento_id: number | null;
  agendamento_id: number | null;
  laudo_id: number | null;
  tem_rascunho: boolean;
  urgente: boolean;
  paciente_nome: string | null;
  tutor_nome: string | null;
  clinica_nome: string | null;
  tipo_exame: string;
  data_atendimento: string | null;
  horas_uteis_decorridas: number;
  atrasado: boolean;
}

interface AgilidadeJanela {
  total_finalizados: number;
  no_prazo: number;
  percentual_no_prazo: number | null;
  media_horas_uteis: number | null;
}

interface AgilidadeLaudos {
  prazo_horas_uteis: number;
  janela_atual: AgilidadeJanela;
  janela_anterior: AgilidadeJanela;
  tendencia: "melhorou" | "piorou" | "estavel" | null;
}

const LAUDOS_PAGE_SIZE = 100;
const PORTAL_RELEASE_STATUS = "Liberado no portal";

function isPortalReleased(status?: string) {
  return status === PORTAL_RELEASE_STATUS;
}

function isLaudoPdfExterno(laudo: Laudo) {
  return laudo.tipo === TIPO_LAUDO_ELETROCARDIOGRAMA || Boolean(laudo.tem_pdf_externo);
}

function getPortalPendingDestinations(laudo: Laudo) {
  if (Array.isArray(laudo.portal_destinos_pendentes)) {
    return laudo.portal_destinos_pendentes;
  }

  const pending: string[] = [];
  if (laudo.clinic_id && !isPortalReleased(laudo.status)) {
    pending.push("clinica");
  }
  if (laudo.veterinario_parceiro_id && !laudo.portal_veterinario_liberado) {
    pending.push("veterinario_parceiro");
  }
  return pending;
}

function canReleasePortal(laudo: Laudo) {
  return getPortalPendingDestinations(laudo).length > 0;
}

function getPortalConfirmMessage(laudo: Laudo) {
  const pending = getPortalPendingDestinations(laudo);
  if (pending.includes("clinica") && pending.includes("veterinario_parceiro")) {
    return "Liberar este laudo no portal da clinica parceira e do veterinario parceiro?";
  }
  if (pending.includes("clinica")) {
    return "Liberar este laudo para o portal da clinica parceira?";
  }
  return "Liberar este laudo para o portal do veterinario parceiro?";
}

function getPortalButtonTitle(laudo: Laudo) {
  const pending = getPortalPendingDestinations(laudo);
  if (!pending.length) {
    return "Laudo ja liberado para todos os destinos vinculados";
  }
  if (pending.includes("clinica") && pending.includes("veterinario_parceiro")) {
    return "Liberar no portal da clinica e do veterinario parceiro";
  }
  if (pending.includes("clinica")) {
    return "Liberar no portal da clinica";
  }
  return "Liberar no portal do veterinario parceiro";
}

function getResponseTotal(payload: { total?: number } | undefined, fallback: number) {
  return typeof payload?.total === "number" ? payload.total : fallback;
}

function getStatusColor(status: string) {
  const colors: Record<string, string> = {
    Rascunho: "bg-gray-100 text-gray-800",
    Finalizado: "bg-green-100 text-green-800",
    Arquivado: "bg-blue-100 text-blue-800",
    Solicitado: "bg-yellow-100 text-yellow-800",
    "Em andamento": "bg-blue-100 text-blue-800",
    Concluido: "bg-green-100 text-green-800",
    [PORTAL_RELEASE_STATUS]: "bg-teal-100 text-teal-800",
  };
  return colors[status] || "bg-gray-100 text-gray-800";
}

export default function LaudosPage() {
  const [laudos, setLaudos] = useState<Laudo[]>([]);
  const [totalLaudos, setTotalLaudos] = useState(0);
  const [exames, setExames] = useState<Exame[]>([]);
  const [totalExames, setTotalExames] = useState(0);
  const [tab, setTab] = useState<"laudos" | "exames" | "pendentes">("laudos");
  const [pendentes, setPendentes] = useState<LaudoPendenteItem[]>([]);
  const [totalPendentes, setTotalPendentes] = useState(0);
  const [loadingPendentes, setLoadingPendentes] = useState(true);
  const [agilidade, setAgilidade] = useState<AgilidadeLaudos | null>(null);
  const [loadingAgilidade, setLoadingAgilidade] = useState(true);
  const [togglingUrgenteId, setTogglingUrgenteId] = useState<number | null>(null);
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [dataFiltro, setDataFiltro] = useState("");
  const [loadingLaudos, setLoadingLaudos] = useState(true);
  const [loadingExames, setLoadingExames] = useState(true);
  const [loadingMoreLaudos, setLoadingMoreLaudos] = useState(false);
  useRoutePerformanceReady(loadingPendentes || loadingAgilidade || loadingLaudos || loadingExames);
  const [liberandoLaudoId, setLiberandoLaudoId] = useState<number | null>(null);
  const [avisandoLaudoId, setAvisandoLaudoId] = useState<number | null>(null);
  const [laudoParaAvisar, setLaudoParaAvisar] = useState<Laudo | null>(null);
  const [toastWhatsapp, setToastWhatsapp] = useState<{ texto: string; classe: string } | null>(null);
  const toastWhatsappTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const envioTutorKeysRef = useRef<Record<number, string>>({});
  const laudosRequestIdRef = useRef(0);
  const novoLaudoMenuRef = useRef<HTMLDivElement | null>(null);
  const [novoLaudoMenuAberto, setNovoLaudoMenuAberto] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setBuscaAplicada(busca.trim());
    }, 300);

    return () => window.clearTimeout(timeoutId);
  }, [busca]);

  useEffect(() => {
    if (!novoLaudoMenuAberto) {
      return;
    }

    const handleClickFora = (event: MouseEvent) => {
      if (!novoLaudoMenuRef.current) {
        return;
      }

      if (!novoLaudoMenuRef.current.contains(event.target as Node)) {
        setNovoLaudoMenuAberto(false);
      }
    };

    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setNovoLaudoMenuAberto(false);
      }
    };

    document.addEventListener("mousedown", handleClickFora);
    document.addEventListener("keydown", handleEsc);

    return () => {
      document.removeEventListener("mousedown", handleClickFora);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [novoLaudoMenuAberto]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }

    let ativo = true;

    const carregarExames = async () => {
      setLoadingExames(true);

      try {
        const response = await api.get("/exames");
        if (!ativo) {
          return;
        }

        const items = response.data.items || [];
        setExames(items);
        setTotalExames(getResponseTotal(response.data, items.length));
      } catch (error) {
        if (!ativo) {
          return;
        }

        console.error("Erro ao carregar exames:", error);
        setExames([]);
        setTotalExames(0);
      } finally {
        if (ativo) {
          setLoadingExames(false);
        }
      }
    };

    carregarExames();

    return () => {
      ativo = false;
    };
  }, [router]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      return;
    }

    if (tab !== "laudos") {
      return;
    }

    let ativo = true;
    const requestId = ++laudosRequestIdRef.current;

    const carregarLaudos = async () => {
      setLoadingLaudos(true);

      try {
        const response = await api.get("/laudos", {
          params: {
            skip: 0,
            limit: LAUDOS_PAGE_SIZE,
            search: buscaAplicada || undefined,
            data: dataFiltro || undefined,
          },
        });

        if (!ativo || requestId !== laudosRequestIdRef.current) {
          return;
        }

        const items = response.data.items || [];
        setLaudos(items);
        setTotalLaudos(getResponseTotal(response.data, items.length));
      } catch (error) {
        if (!ativo || requestId !== laudosRequestIdRef.current) {
          return;
        }

        console.error("Erro ao carregar laudos:", error);
        setLaudos([]);
        setTotalLaudos(0);
      } finally {
        if (ativo && requestId === laudosRequestIdRef.current) {
          setLoadingLaudos(false);
        }
      }
    };

    carregarLaudos();

    return () => {
      ativo = false;
    };
  }, [buscaAplicada, dataFiltro, router, tab]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      return;
    }

    let ativo = true;

    const carregarPendentes = async () => {
      setLoadingPendentes(true);
      try {
        const response = await api.get("/laudos/pendentes", { params: { skip: 0, limit: 100 } });
        if (!ativo) return;
        const items = response.data.items || [];
        setPendentes(items);
        setTotalPendentes(getResponseTotal(response.data, items.length));
      } catch (error) {
        if (!ativo) return;
        console.error("Erro ao carregar fila de laudos pendentes:", error);
        setPendentes([]);
        setTotalPendentes(0);
      } finally {
        if (ativo) setLoadingPendentes(false);
      }
    };

    const carregarAgilidade = async () => {
      setLoadingAgilidade(true);
      try {
        const response = await api.get("/laudos/agilidade");
        if (!ativo) return;
        setAgilidade(response.data);
      } catch (error) {
        if (!ativo) return;
        console.error("Erro ao carregar indicador de agilidade:", error);
        setAgilidade(null);
      } finally {
        if (ativo) setLoadingAgilidade(false);
      }
    };

    carregarPendentes();
    carregarAgilidade();

    return () => {
      ativo = false;
    };
  }, []);

  const toggleUrgente = async (item: LaudoPendenteItem) => {
    if (!item.agendamento_id) return;
    const agendamentoId = item.agendamento_id;
    setTogglingUrgenteId(agendamentoId);
    try {
      await api.put(`/agenda/${agendamentoId}`, { urgente_laudo: !item.urgente });
      setPendentes((prev) =>
        prev
          .map((p) => (p.agendamento_id === agendamentoId ? { ...p, urgente: !p.urgente } : p))
          .sort((a, b) => {
            if (a.urgente !== b.urgente) return a.urgente ? -1 : 1;
            return (a.data_atendimento || "").localeCompare(b.data_atendimento || "");
          })
      );
    } catch (error) {
      console.error("Erro ao marcar/desmarcar urgencia:", error);
      alert("Nao foi possivel atualizar a urgencia deste item.");
    } finally {
      setTogglingUrgenteId(null);
    }
  };

  const examesFiltrados = exames.filter((exame) => {
    if (!busca.trim()) {
      return true;
    }

    const termo = busca.toLowerCase();
    return (
      exame.tipo_exame?.toLowerCase().includes(termo) ||
      exame.status?.toLowerCase().includes(termo) ||
      exame.paciente_id?.toString().includes(termo)
    );
  });

  const filtrosLaudosAtivos = Boolean(buscaAplicada || dataFiltro);
  const haMaisLaudos = laudos.length < totalLaudos;
  const resumoLaudos = filtrosLaudosAtivos
    ? `Mostrando ${laudos.length} de ${totalLaudos} resultado(s)`
    : haMaisLaudos
      ? `Mostrando ${laudos.length} laudos mais recentes de ${totalLaudos}`
      : `${totalLaudos} laudo(s)`;

  const downloadPDF = async (laudoId: number, titulo: string) => {
    try {
      const laudo = laudos.find((item) => item.id === laudoId);
      const filename = `${titulo.replace(/\s+/g, "_")}.pdf`;
      if (laudo && isLaudoPdfExterno(laudo)) {
        await baixarLaudoPdfOriginal(laudoId, filename);
        return;
      }
      await baixarLaudoPdf(laudoId, filename);
    } catch (error) {
      alert("Erro ao gerar PDF. Tente novamente.");
    }
  };

  const liberarNoPortalClinica = async (laudo: Laudo) => {
    if (!canReleasePortal(laudo)) {
      return;
    }
    if (!laudo.clinic_id && !laudo.veterinario_parceiro_id) {
      alert("Vincule uma clinica ou um veterinario parceiro ao laudo antes de liberar no portal.");
      return;
    }
    if (!confirm(getPortalConfirmMessage(laudo))) {
      return;
    }

    setLiberandoLaudoId(laudo.id);
    try {
      const response = await api.post(`/laudos/${laudo.id}/portal/liberar`);
      const novoStatus = response.data?.status || PORTAL_RELEASE_STATUS;
      setLaudos((prev) =>
        prev.map((item) =>
          item.id === laudo.id
            ? {
                ...item,
                status: novoStatus,
                portal_clinica_liberado: response.data?.portal_clinica_liberado,
                portal_veterinario_liberado: response.data?.portal_veterinario_liberado,
                portal_destinos_pendentes: response.data?.portal_destinos_pendentes || [],
                portal_pode_liberar: response.data?.portal_pode_liberar,
              }
            : item
        )
      );
      alert(response.data?.message || "Laudo liberado no portal.");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      alert(detail || "Erro ao liberar laudo no portal. Tente novamente.");
    } finally {
      setLiberandoLaudoId(null);
    }
  };

  const mostrarToastWhatsapp = (texto: string, classe: string) => {
    setToastWhatsapp({ texto, classe });
    if (toastWhatsappTimeoutRef.current) {
      clearTimeout(toastWhatsappTimeoutRef.current);
    }
    toastWhatsappTimeoutRef.current = setTimeout(() => {
      setToastWhatsapp(null);
      toastWhatsappTimeoutRef.current = null;
    }, 4000);
  };

  const abrirSeletorAvisoWhatsApp = (laudo: Laudo) => {
    if (!podeAvisarWhatsApp(laudo)) {
      alert("Libere o laudo no portal antes de enviar o aviso por WhatsApp.");
      return;
    }
    setLaudoParaAvisar(laudo);
  };

  const avisarLaudoPorWhatsApp = async (laudo: Laudo, destinos: string[]) => {
    if (destinos.length === 0) {
      return;
    }
    const idempotencyKey = typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `laudo-portal-${laudo.id}-${Date.now()}`;
    setAvisandoLaudoId(laudo.id);
    try {
      const response = await api.post<RespostaAvisoWhatsApp>(`/laudos/${laudo.id}/portal/whatsapp`, {
        idempotency_key: idempotencyKey,
        destinos,
      });
      const dados = response.data;
      const agora = new Date().toISOString();
      setLaudoParaAvisar(null);
      setLaudos((prev) =>
        prev.map((item) =>
          item.id === laudo.id
            ? {
                ...item,
                whatsapp_liberacao_status: dados?.whatsapp_liberacao_status ?? item.whatsapp_liberacao_status,
                whatsapp_liberacao_em: dados?.whatsapp_liberacao_em ?? agora,
                whatsapp_liberacao_erro: dados?.whatsapp_liberacao_erro ?? null,
                whatsapp_parceiro_status: dados?.whatsapp_parceiro_status ?? item.whatsapp_parceiro_status,
                whatsapp_parceiro_em: dados?.whatsapp_parceiro_em ?? item.whatsapp_parceiro_em,
                whatsapp_parceiro_erro: dados?.whatsapp_parceiro_erro ?? null,
                whatsapp_envios: dados?.whatsapp_envios ?? item.whatsapp_envios,
              }
            : item
        )
      );
      const resumo = resumirRespostaAvisoWhatsApp(dados);
      mostrarToastWhatsapp(
        resumo.texto,
        resumo.tom === "alerta"
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-teal-200 bg-teal-50 text-teal-900"
      );
    } catch (error) {
      const detail = extractApiErrorMessageSync(error, "Erro ao enviar o aviso por WhatsApp.");
      const agora = new Date().toISOString();
      // A janela fica aberta: o erro pode ser de um destino so, e reabrir a
      // selecao do zero perderia a escolha que acabou de ser feita.
      if (destinos.includes("clinica")) {
        setLaudos((prev) =>
          prev.map((item) =>
            item.id === laudo.id
              ? { ...item, whatsapp_liberacao_status: "falhou", whatsapp_liberacao_em: agora, whatsapp_liberacao_erro: detail }
              : item
          )
        );
      }
      mostrarToastWhatsapp(detail, "border-rose-200 bg-rose-50 text-rose-900");
    } finally {
      setAvisandoLaudoId(null);
    }
  };

  const enviarLaudoDomiciliarPorWhatsApp = async (laudo: Laudo) => {
    if (!confirm(`Enviar o PDF do laudo de ${laudo.paciente_nome} ao WhatsApp cadastrado do tutor ${laudo.paciente_tutor}? Confirme que o tutor autorizou este contato.`)) {
      return;
    }
    const idempotencyKey = envioTutorKeysRef.current[laudo.id] || (
      typeof globalThis.crypto?.randomUUID === "function"
        ? globalThis.crypto.randomUUID()
        : `laudo-tutor-${laudo.id}-${Date.now()}`
    );
    envioTutorKeysRef.current[laudo.id] = idempotencyKey;
    setAvisandoLaudoId(laudo.id);
    try {
      await api.post(`/laudos/${laudo.id}/whatsapp-tutor`, { idempotency_key: idempotencyKey });
      delete envioTutorKeysRef.current[laudo.id];
      mostrarToastWhatsapp("PDF do laudo enviado ao tutor pelo WhatsApp oficial.", "border-teal-200 bg-teal-50 text-teal-900");
    } catch (error) {
      mostrarToastWhatsapp(
        extractApiErrorMessageSync(error, "Erro ao enviar o PDF do laudo ao tutor."),
        "border-rose-200 bg-rose-50 text-rose-900"
      );
    } finally {
      setAvisandoLaudoId(null);
    }
  };

  const carregarMaisLaudos = async () => {
    if (loadingMoreLaudos || !haMaisLaudos) {
      return;
    }

    const requestId = ++laudosRequestIdRef.current;
    setLoadingMoreLaudos(true);

    try {
      const response = await api.get("/laudos", {
        params: {
          skip: laudos.length,
          limit: LAUDOS_PAGE_SIZE,
          search: buscaAplicada || undefined,
          data: dataFiltro || undefined,
        },
      });

      if (requestId !== laudosRequestIdRef.current) {
        return;
      }

      const items = response.data.items || [];
      setLaudos((prev) => {
        const ids = new Set(prev.map((item) => item.id));
        const novos = items.filter((item: Laudo) => !ids.has(item.id));
        return [...prev, ...novos];
      });
      setTotalLaudos(getResponseTotal(response.data, totalLaudos));
    } catch (error) {
      if (requestId !== laudosRequestIdRef.current) {
        return;
      }

      console.error("Erro ao carregar mais laudos:", error);
    } finally {
      if (requestId === laudosRequestIdRef.current) {
        setLoadingMoreLaudos(false);
      }
    }
  };

  const limparFiltrosLaudos = () => {
    setBusca("");
    setBuscaAplicada("");
    setDataFiltro("");
  };

  const deletarLaudo = async (laudoId: number) => {
    if (!confirm("Tem certeza que deseja excluir este laudo? Esta acao nao pode ser desfeita.")) {
      return;
    }

    try {
      await api.delete(`/laudos/${laudoId}`);
      setLaudos((prev) => prev.filter((laudo) => laudo.id !== laudoId));
      setTotalLaudos((prev) => Math.max(prev - 1, 0));
      alert("Laudo excluido com sucesso!");
    } catch (error) {
      alert("Erro ao excluir laudo. Tente novamente.");
    }
  };

  const deletarExame = async (exameId: number) => {
    if (!confirm("Tem certeza que deseja excluir este exame? Esta acao nao pode ser desfeita.")) {
      return;
    }

    try {
      await api.delete(`/exames/${exameId}`);
      setExames((prev) => prev.filter((exame) => exame.id !== exameId));
      setTotalExames((prev) => Math.max(prev - 1, 0));
      alert("Exame excluido com sucesso!");
    } catch (error) {
      alert("Erro ao excluir exame. Tente novamente.");
    }
  };

  const atalhosNovoLaudo = [
    {
      titulo: "Laudo estruturado",
      descricao: "Ecocardiograma e pressao arterial",
      href: "/laudos/novo",
    },
    {
      titulo: "Upload de eletrocardiograma",
      descricao: "PDF externo com fluxo de telemedicina",
      href: "/laudos/eletrocardiograma/upload",
    },
  ];

  const abrirNovoLaudo = (href: string) => {
    setNovoLaudoMenuAberto(false);
    router.push(href);
  };

  return (
    <DashboardLayout>
      <div className="fc-clinical-page">
        {toastWhatsapp && (
          <div className="fixed right-4 top-[calc(env(safe-area-inset-top)+4.5rem)] z-[70] lg:top-4">
            <div className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-xs shadow-lg ${toastWhatsapp.classe}`}>
              <span className="font-medium">{toastWhatsapp.texto}</span>
            </div>
          </div>
        )}
        {laudoParaAvisar && (
          <AvisoWhatsAppDialog
            laudo={laudoParaAvisar}
            enviando={avisandoLaudoId === laudoParaAvisar.id}
            onCancelar={() => setLaudoParaAvisar(null)}
            onEnviar={(destinos) => avisarLaudoPorWhatsApp(laudoParaAvisar, destinos)}
          />
        )}
        <header className="fc-clinical-header">
          <div>
            <span className="fc-clinical-kicker">
              <FileCheck className="h-4 w-4" />
              Documentação clínica
            </span>
            <h1>Central de laudos</h1>
            <p>Exames, documentos e liberações para o portal organizados por paciente.</p>
          </div>
          <div className="fc-clinical-primary-menu" ref={novoLaudoMenuRef}>
            <button
              type="button"
              onClick={() => setNovoLaudoMenuAberto((aberto) => !aberto)}
              className="fc-clinical-primary"
              aria-haspopup="menu"
              aria-expanded={novoLaudoMenuAberto}
            >
              <Plus className="w-4 h-4" />
              Novo Laudo
              <ChevronDown className={`h-4 w-4 transition ${novoLaudoMenuAberto ? "rotate-180" : ""}`} />
            </button>

            {novoLaudoMenuAberto && (
              <div className="fc-clinical-primary-menu-panel" role="menu" aria-label="Escolher fluxo de laudo">
                <div className="fc-clinical-primary-menu-header">
                  <strong>Escolha o fluxo</strong>
                  <span>Eletrocardiograma e telemedicina agora aparecem aqui.</span>
                </div>

                <div className="fc-clinical-primary-menu-list">
                  {atalhosNovoLaudo.map((atalho) => (
                    <button
                      key={atalho.href}
                      type="button"
                      className="fc-clinical-primary-menu-item"
                      role="menuitem"
                      onClick={() => abrirNovoLaudo(atalho.href)}
                    >
                      <span>{atalho.titulo}</span>
                      <small>{atalho.descricao}</small>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </header>

        <div className="fc-clinical-tabs" role="tablist" aria-label="Tipo de documento">
          <button
            onClick={() => setTab("laudos")}
            className={`fc-clinical-tab ${tab === "laudos" ? "fc-clinical-tab-active" : ""}`}
            role="tab"
            aria-selected={tab === "laudos"}
          >
            <FileText className="h-4 w-4" />
            Laudos ({totalLaudos})
          </button>
          <button
            onClick={() => setTab("exames")}
            className={`fc-clinical-tab ${tab === "exames" ? "fc-clinical-tab-active" : ""}`}
            role="tab"
            aria-selected={tab === "exames"}
          >
            <FileCheck className="h-4 w-4" />
            Exames ({totalExames})
          </button>
          <button
            onClick={() => setTab("pendentes")}
            className={`fc-clinical-tab ${tab === "pendentes" ? "fc-clinical-tab-active" : ""}`}
            role="tab"
            aria-selected={tab === "pendentes"}
          >
            <Gauge className="h-4 w-4" />
            Pendentes ({totalPendentes})
          </button>
        </div>

        {tab !== "pendentes" && (
        <div className="fc-clinical-filters">
          <div className="flex flex-col gap-3 lg:flex-row">
            <div className="fc-clinical-control flex-1">
              <Search className="h-5 w-5" />
              <input
                type="text"
                placeholder={
                  tab === "laudos"
                    ? "Buscar por animal, tutor, clinica ou parceiro"
                    : "Buscar exames por tipo, status ou paciente"
                }
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
            </div>

            {tab === "laudos" && (
              <>
                <div className="fc-clinical-control lg:w-56">
                  <Calendar className="h-5 w-5" />
                  <input
                    type="date"
                    value={dataFiltro}
                    onChange={(e) => setDataFiltro(e.target.value)}
                    aria-label="Filtrar laudos por data"
                  />
                </div>

                {(busca || dataFiltro) && (
                  <button
                    type="button"
                    onClick={limparFiltrosLaudos}
                    className="fc-clinical-secondary"
                  >
                    Limpar filtros
                  </button>
                )}
              </>
            )}
          </div>

          {tab === "laudos" && (
            <p className="fc-clinical-filter-note">
              A busca consulta toda a base. A lista abre mostrando apenas os {LAUDOS_PAGE_SIZE} laudos mais recentes.
            </p>
          )}
        </div>
        )}

        {tab === "pendentes" && (
          <div className="fc-clinical-filters">
            {loadingAgilidade ? (
              <p className="fc-clinical-filter-note">Carregando indicador de agilidade...</p>
            ) : !agilidade || agilidade.janela_atual.total_finalizados === 0 ? (
              <p className="fc-clinical-filter-note">
                Sem laudos finalizados nos ultimos 90 dias para calcular o indicador de agilidade.
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-6 rounded-lg border border-ink-100 bg-white p-4">
                <div>
                  <p className="text-xs font-bold uppercase tracking-wide text-gray-500">
                    No prazo (ultimos 90 dias)
                  </p>
                  <p className="text-2xl font-bold text-gray-900">
                    {agilidade.janela_atual.percentual_no_prazo}%
                  </p>
                  <p className="text-xs text-gray-500">
                    {agilidade.janela_atual.no_prazo} de {agilidade.janela_atual.total_finalizados} laudo(s)
                  </p>
                </div>
                <div>
                  <p className="text-xs font-bold uppercase tracking-wide text-gray-500">Tempo medio</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {agilidade.janela_atual.media_horas_uteis}h uteis
                  </p>
                  <p className="text-xs text-gray-500">prazo: {agilidade.prazo_horas_uteis}h uteis</p>
                </div>
                <div className="flex items-center gap-2">
                  {agilidade.tendencia === "melhorou" ? (
                    <TrendingUp className="h-5 w-5 text-green-600" />
                  ) : agilidade.tendencia === "piorou" ? (
                    <TrendingDown className="h-5 w-5 text-red-600" />
                  ) : agilidade.tendencia === "estavel" ? (
                    <Minus className="h-5 w-5 text-gray-500" />
                  ) : null}
                  <span className="text-sm font-medium text-gray-700">
                    {agilidade.tendencia === "melhorou"
                      ? "Melhorou em relacao aos 90 dias anteriores"
                      : agilidade.tendencia === "piorou"
                        ? "Piorou em relacao aos 90 dias anteriores"
                        : agilidade.tendencia === "estavel"
                          ? "Estavel em relacao aos 90 dias anteriores"
                          : "Sem dados suficientes nos 90 dias anteriores para comparar"}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="fc-clinical-list">
          <div className="fc-clinical-list-summary">
            {tab === "laudos"
              ? resumoLaudos
              : tab === "pendentes"
              ? `${totalPendentes} laudo(s) pendente(s)`
              : `Mostrando ${examesFiltrados.length} de ${totalExames} exame(s)`}
          </div>

          {tab === "laudos" ? (
            loadingLaudos ? (
              <div className="fc-registry-loading" aria-label="Carregando laudos">
                {[0, 1, 2].map((item) => <span key={item} />)}
              </div>
            ) : laudos.length === 0 ? (
              <div className="fc-registry-empty">
                <div><FileText className="h-6 w-6" /></div>
                <span>Arquivo clínico vazio</span>
                <p>Nenhum laudo encontrado</p>
              </div>
            ) : (
              <>
                <div className="divide-y divide-ink-100">
                  {laudos.map((laudo) => (
                    <div key={laudo.id} className="fc-clinical-row">
                      <div className="fc-clinical-row-layout">
                        <div className="fc-clinical-row-icon">
                          <FileText className="h-5 w-5" />
                        </div>
                        <div className="fc-clinical-row-main">
                          <h3>
                            {laudo.paciente_nome || `Paciente #${laudo.paciente_id}`}
                          </h3>
                          <div>
                            <span className="flex items-center gap-1">
                              <User className="w-3 h-3" />
                              {laudo.paciente_tutor || "Sem tutor"}
                            </span>
                            {laudo.clinica && (
                              <span className="flex items-center gap-1">
                                <FileText className="w-3 h-3" />
                                {laudo.clinica}
                              </span>
                            )}
                            {laudo.veterinario_parceiro_nome && (
                              <span className="flex items-center gap-1">
                                <User className="w-3 h-3" />
                                Vet parceiro: {laudo.veterinario_parceiro_nome}
                              </span>
                            )}
                            <span className="flex items-center gap-1">
                              <Calendar className="w-3 h-3" />
                              {laudo.data_exame
                                ? formatCalendarDate(laudo.data_exame)
                                : formatOperationalDate(laudo.data_laudo)}
                            </span>
                          </div>
                        </div>
                        <div className="fc-clinical-actions">
                          <span className="px-2 py-1 rounded-full text-xs bg-indigo-100 text-indigo-800">
                            {getTipoLaudoLabel(laudo.tipo)}
                          </span>
                          <span className={`px-2 py-1 rounded-full text-xs ${getStatusColor(laudo.status)}`}>
                            {laudo.status}
                          </span>
                          {laudo.whatsapp_liberacao_status && (
                            <span
                              className={`fc-wa-envio-badge fc-wa-envio-badge-${laudo.whatsapp_liberacao_status}`}
                              title={
                                laudo.whatsapp_liberacao_status === "falhou"
                                  ? laudo.whatsapp_liberacao_erro || "Falha ao enviar o aviso por WhatsApp."
                                  : laudo.whatsapp_liberacao_em
                                  ? `Enviado em ${formatOperationalDate(laudo.whatsapp_liberacao_em)}`
                                  : "Aviso enviado por WhatsApp."
                              }
                            >
                              {laudo.whatsapp_liberacao_status === "enviado" ? (
                                <Check className="h-3 w-3" />
                              ) : (
                                <AlertCircle className="h-3 w-3" />
                              )}
                              {laudo.whatsapp_liberacao_status === "enviado" ? "WhatsApp enviado" : "WhatsApp falhou"}
                            </span>
                          )}
                          {laudo.whatsapp_parceiro_status && (
                            <span
                              className={`fc-wa-envio-badge fc-wa-envio-badge-${laudo.whatsapp_parceiro_status}`}
                              title={
                                laudo.whatsapp_parceiro_status === "falhou"
                                  ? laudo.whatsapp_parceiro_erro ||
                                    "Falha ao enviar o aviso por WhatsApp ao veterinário parceiro."
                                  : laudo.whatsapp_parceiro_em
                                  ? `Enviado ao veterinário parceiro em ${formatOperationalDate(laudo.whatsapp_parceiro_em)}`
                                  : "Aviso enviado por WhatsApp ao veterinário parceiro."
                              }
                            >
                              {laudo.whatsapp_parceiro_status === "enviado" ? (
                                <Check className="h-3 w-3" />
                              ) : (
                                <AlertCircle className="h-3 w-3" />
                              )}
                              {laudo.whatsapp_parceiro_status === "enviado"
                                ? "WhatsApp parceiro enviado"
                                : "WhatsApp parceiro falhou"}
                            </span>
                          )}
                          {(laudo.portal_clinica_baixado_em || laudo.portal_veterinario_baixado_em) && (
                            <span
                              className="inline-flex items-center justify-center rounded-full bg-emerald-100 p-1.5 text-emerald-700"
                              title={[
                                laudo.portal_clinica_baixado_em
                                  ? `Baixado pela clínica parceira em ${formatOperationalDate(laudo.portal_clinica_baixado_em)}`
                                  : null,
                                laudo.portal_veterinario_baixado_em
                                  ? `Baixado pelo veterinário parceiro em ${formatOperationalDate(laudo.portal_veterinario_baixado_em)}`
                                  : null,
                              ].filter(Boolean).join(" • ")}
                              aria-label="Laudo baixado por parceiro externo"
                            >
                              <FileCheck className="h-4 w-4" />
                            </span>
                          )}
                          {canReleasePortal(laudo) && (
                            <button
                              onClick={() => liberarNoPortalClinica(laudo)}
                              disabled={liberandoLaudoId === laudo.id}
                              className="fc-clinical-action"
                              title={getPortalButtonTitle(laudo)}
                              aria-label={`Liberar laudo de ${laudo.paciente_nome || `paciente ${laudo.paciente_id}`} no portal`}
                            >
                              <Send className="w-4 h-4" />
                            </button>
                          )}
                          {podeAvisarWhatsApp(laudo) && (
                            <button
                              onClick={() => abrirSeletorAvisoWhatsApp(laudo)}
                              disabled={avisandoLaudoId === laudo.id}
                              className="fc-clinical-action"
                              title={getTituloBotaoAvisoWhatsApp(laudo)}
                              aria-label={`${getTituloBotaoAvisoWhatsApp(laudo)} sobre o laudo de ${
                                laudo.paciente_nome || `paciente ${laudo.paciente_id}`
                              }`}
                            >
                              <MessageCircle className="w-4 h-4" />
                            </button>
                          )}
                          {laudo.atendimento_domiciliar && (laudo.status === "Finalizado" || isPortalReleased(laudo.status)) && (
                            <button
                              onClick={() => enviarLaudoDomiciliarPorWhatsApp(laudo)}
                              disabled={avisandoLaudoId === laudo.id}
                              className="fc-clinical-action"
                              title="Enviar PDF do laudo ao tutor pelo WhatsApp oficial"
                              aria-label={`Enviar PDF do laudo de ${laudo.paciente_nome || `paciente ${laudo.paciente_id}`} ao tutor pelo WhatsApp`}
                            >
                              <MessageCircle className="w-4 h-4" />
                            </button>
                          )}
                          <button
                            onClick={() => router.push(getLaudoViewPath(laudo.id, laudo.tipo))}
                            className="fc-clinical-action"
                            title="Visualizar"
                            aria-label={`Visualizar laudo de ${laudo.paciente_nome || `paciente ${laudo.paciente_id}`}`}
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                          {!isLaudoPdfExterno(laudo) && (
                            <button
                              onClick={() => router.push(getLaudoEditPath(laudo.id, laudo.tipo))}
                              className="fc-clinical-action"
                              title="Editar"
                              aria-label={`Editar laudo de ${laudo.paciente_nome || `paciente ${laudo.paciente_id}`}`}
                            >
                              <Edit className="w-4 h-4" />
                            </button>
                          )}
                          <button
                            onClick={() => downloadPDF(laudo.id, laudo.titulo)}
                            className="fc-clinical-action"
                            title="Baixar PDF"
                            aria-label={`Baixar PDF do laudo de ${laudo.paciente_nome || `paciente ${laudo.paciente_id}`}`}
                          >
                            <Download className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => deletarLaudo(laudo.id)}
                            className="fc-clinical-action fc-clinical-action-danger"
                            title="Excluir"
                            aria-label={`Excluir laudo de ${laudo.paciente_nome || `paciente ${laudo.paciente_id}`}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {haMaisLaudos && (
                  <div className="fc-clinical-load-more">
                    <button
                      type="button"
                      onClick={carregarMaisLaudos}
                      disabled={loadingMoreLaudos}
                      className="fc-clinical-secondary"
                    >
                      {loadingMoreLaudos ? "Carregando..." : "Carregar mais laudos"}
                    </button>
                  </div>
                )}
              </>
            )
          ) : tab === "pendentes" ? (
            loadingPendentes ? (
              <div className="fc-registry-loading" aria-label="Carregando fila de pendentes">
                {[0, 1, 2].map((item) => <span key={item} />)}
              </div>
            ) : pendentes.length === 0 ? (
              <div className="fc-registry-empty">
                <div><Gauge className="h-6 w-6" /></div>
                <span>Nenhum laudo pendente</span>
                <p>Tudo em dia - todos os exames realizados ja tem laudo finalizado.</p>
              </div>
            ) : (
              <div className="divide-y divide-ink-100">
                {pendentes.map((item) => (
                  <div
                    key={item.exame_id ?? `agendamento-${item.agendamento_id}-${item.tipo_exame}`}
                    className="fc-clinical-row"
                  >
                    <div className="fc-clinical-row-layout">
                      <div
                        className={`fc-clinical-row-icon ${
                          item.atrasado ? "fc-clinical-row-icon-exam" : ""
                        }`}
                      >
                        {item.atrasado ? (
                          <AlertTriangle className="h-5 w-5" />
                        ) : (
                          <Clock className="h-5 w-5" />
                        )}
                      </div>
                      <div className="fc-clinical-row-main">
                        <h3>{getTipoLaudoLabel(item.tipo_exame)}</h3>
                        <div>
                          <span>{item.paciente_nome || "Paciente nao informado"}</span>
                          {item.tutor_nome ? <span>Tutor: {item.tutor_nome}</span> : null}
                          {item.clinica_nome ? <span>{item.clinica_nome}</span> : null}
                          <span>{formatCalendarDate(item.data_atendimento)}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-2">
                          {item.atrasado && (
                            <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-800">
                              Atrasado ({item.horas_uteis_decorridas}h uteis)
                            </span>
                          )}
                          {item.tem_rascunho && (
                            <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-gray-100 text-gray-800">
                              Rascunho em aberto
                            </span>
                          )}
                          {item.urgente && (
                            <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800">
                              Urgente
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="fc-clinical-actions">
                        <button
                          onClick={() => toggleUrgente(item)}
                          disabled={togglingUrgenteId === item.agendamento_id}
                          className="fc-clinical-action"
                          title={item.urgente ? "Remover urgencia" : "Marcar como urgente"}
                          aria-label={item.urgente ? "Remover urgencia" : "Marcar como urgente"}
                        >
                          <Star className={`w-4 h-4 ${item.urgente ? "fill-current text-amber-600" : ""}`} />
                        </button>
                        <button
                          onClick={() => {
                            if (item.tem_rascunho && item.laudo_id) {
                              router.push(getLaudoEditPath(item.laudo_id, item.tipo_exame));
                            } else if (item.atendimento_id) {
                              router.push(
                                `/laudos/novo?atendimento_id=${item.atendimento_id}&tipo=${encodeURIComponent(item.tipo_exame)}`
                              );
                            } else if (item.agendamento_id) {
                              router.push(
                                `/laudos/novo?agendamento_id=${item.agendamento_id}&tipo=${encodeURIComponent(item.tipo_exame)}`
                              );
                            }
                          }}
                          className="fc-clinical-action"
                          title={item.tem_rascunho ? "Continuar laudo" : "Criar laudo"}
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : loadingExames ? (
            <div className="fc-registry-loading" aria-label="Carregando exames">
              {[0, 1, 2].map((item) => <span key={item} />)}
            </div>
          ) : examesFiltrados.length === 0 ? (
            <div className="fc-registry-empty">
              <div><FileCheck className="h-6 w-6" /></div>
              <span>Fila de exames vazia</span>
              <p>Nenhum exame encontrado</p>
            </div>
          ) : (
            <div className="divide-y divide-ink-100">
              {examesFiltrados.map((exame) => (
                <div key={exame.id} className="fc-clinical-row">
                  <div className="fc-clinical-row-layout">
                    <div className="fc-clinical-row-icon fc-clinical-row-icon-exam">
                      <Clock className="h-5 w-5" />
                    </div>
                    <div className="fc-clinical-row-main">
                      <h3>{exame.tipo_exame}</h3>
                      <div>
                        <span>Paciente #{exame.paciente_id}</span>
                        <span>R$ {exame.valor?.toFixed(2)}</span>
                      </div>
                    </div>
                    <div className="fc-clinical-actions">
                      <span className={`px-2 py-1 rounded-full text-xs ${getStatusColor(exame.status)}`}>
                        {exame.status}
                      </span>
                      <button
                        onClick={() => deletarExame(exame.id)}
                        className="fc-clinical-action fc-clinical-action-danger"
                        title="Excluir"
                        aria-label={`Excluir exame ${exame.tipo_exame}`}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
