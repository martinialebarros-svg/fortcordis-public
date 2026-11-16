"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import {
  getLaudoViewPath,
  TIPO_LAUDO_ECOCARDIOGRAMA,
  TIPO_LAUDO_ELETROCARDIOGRAMA,
  TIPO_LAUDO_PRESSAO_ARTERIAL,
  TIPO_LAUDO_ULTRASSOM_ABDOMINAL,
} from "@/lib/laudos";
import { baixarLaudoPdf, baixarLaudoPdfOriginal } from "@/lib/laudo-pdf";
import { formatCalendarDate, formatOperationalDate } from "@/lib/calendar-date";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";
import { extrairQualitativaEcoDaDescricao, type QualitativaEcoLegada } from "@/lib/ecocardiograma-estruturado";
import { buildEchoReportGroups, prepareEchoReportMeasurements, splitReportObservations } from "@/lib/echo-report-presentation";
import { useReferenciaEco } from "../hooks/useReferenciaEco";
import { makeLowWeightReference } from "@/lib/echo-low-weight-reference";
import type { ReferenciaEco } from "../types/referencia-eco";
import {
  getTituloBotaoAvisoWhatsApp,
  podeAvisarWhatsApp,
  resumirRespostaAvisoWhatsApp,
  type DestinoVeterinarioLaudo,
  type EnvioDestinoWhatsApp,
  type RespostaAvisoWhatsApp,
} from "@/lib/laudo-whatsapp-aviso";
import { getConfirmacaoRevogarVeterinario } from "@/lib/laudo-portal-destinos";
import AvisoWhatsAppDialog from "../components/AvisoWhatsAppDialog";
import PortalLiberadoPara from "../components/PortalLiberadoPara";
import EchoNarrativeConsistencyNotice from "../components/EchoNarrativeConsistencyNotice";
import EchoPreviousExamComparison from "../components/EchoPreviousExamComparison";
import { ArrowLeft, CheckCircle, Download, FileText, Loader2, MessageCircle, Printer, Send, Upload } from "lucide-react";

const PORTAL_RELEASE_STATUS = "Liberado no portal";
const ROTULOS_QUALITATIVOS: Record<keyof QualitativaEcoLegada, string> = {
  valvas: "Valvas",
  camaras: "Câmaras esquerdas",
  ad_vd: "Câmaras direitas",
  funcao: "Função",
  pericardio: "Pericárdio",
  vasos: "Vasos sanguíneos",
};

function isPortalReleased(status?: string) {
  return status === PORTAL_RELEASE_STATUS;
}

interface Paciente {
  id: number;
  nome: string;
  especie: string;
  raca: string;
  sexo: string;
  peso_kg: number;
  idade?: string;
  tutor?: string;
  telefone?: string;
}

interface Laudo {
  id: number;
  paciente_id: number;
  paciente?: Paciente;
  tipo: string;
  titulo: string;
  descricao: string;
  medidas?: Record<string, string>;
  diagnostico: string;
  observacoes: string;
  status: string;
  data_laudo: string;
  data_exame?: string;
  clinica?: string;
  clinic_id?: number | null;
  veterinario_parceiro_id?: number | null;
  veterinario_parceiro_nome?: string | null;
  veterinario_parceiro_crmv?: string | null;
  portal_clinica_disponivel?: boolean;
  portal_clinica_liberado?: boolean;
  portal_veterinario_disponivel?: boolean;
  portal_veterinario_liberado?: boolean;
  portal_destinos_pendentes?: string[];
  portal_pode_liberar?: boolean;
  portal_veterinarios_destinos?: DestinoVeterinarioLaudo[];
  whatsapp_envios?: Record<string, EnvioDestinoWhatsApp> | null;
  criado_por_nome: string;
  ordem_servico?: {
    id: number;
    numero_os: string;
    valor_final: number;
    status: string;
  } | null;
  pdf_externo?: {
    anexo_id?: number;
    nome_original?: string;
  } | null;
  pressao_arterial?: {
    pas_1?: number | null;
    pas_2?: number | null;
    pas_3?: number | null;
    pas_media?: number | null;
    metodo?: string | null;
    manguito?: string | null;
    membro?: string | null;
    decubito?: string | null;
    obs_extra?: string | null;
  } | null;
}

function getPortalPendingDestinations(laudo: Laudo | null) {
  if (!laudo) {
    return [] as string[];
  }
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

function canReleasePortal(laudo: Laudo | null) {
  return getPortalPendingDestinations(laudo).length > 0;
}

function getPortalConfirmMessage(laudo: Laudo | null) {
  const pending = getPortalPendingDestinations(laudo);
  if (pending.includes("clinica") && pending.includes("veterinario_parceiro")) {
    return "Liberar este laudo no portal da clinica parceira e do veterinario parceiro?";
  }
  if (pending.includes("clinica")) {
    return "Liberar este laudo para o portal da clinica parceira?";
  }
  return "Liberar este laudo para o portal do veterinario parceiro?";
}

function getPortalButtonTitle(laudo: Laudo | null) {
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

export default function VisualizarLaudoPage() {
  const router = useRouter();
  const routeParams = useParams<{ id?: string | string[] }>();
  const laudoId = Array.isArray(routeParams.id) ? routeParams.id[0] : routeParams.id;
  const [loading, setLoading] = useState(true);
  const [laudo, setLaudo] = useState<Laudo | null>(null);
  const [paciente, setPaciente] = useState<Paciente | null>(null);
  const [medidas, setMedidas] = useState<Record<string, string>>({});
  const [qualitativa, setQualitativa] = useState<Partial<QualitativaEcoLegada>>({});
  const [referenciaEco, setReferenciaEco] = useState<ReferenciaEco | null>(null);
  const { buscarReferencia, loading: carregandoReferencia } = useReferenciaEco();
  const [liberandoPortal, setLiberandoPortal] = useState(false);
  const [avisandoWhatsApp, setAvisandoWhatsApp] = useState(false);
  const [seletorAvisoAberto, setSeletorAvisoAberto] = useState(false);
  const [revogandoPartnerId, setRevogandoPartnerId] = useState<number | null>(null);
  const [arquivoSubstituicao, setArquivoSubstituicao] = useState<File | null>(null);
  const [substituindoPdf, setSubstituindoPdf] = useState(false);
  const [fileInputKey, setFileInputKey] = useState(0);
  const laudoEhEletrocardiograma = laudo?.tipo === TIPO_LAUDO_ELETROCARDIOGRAMA;
  const laudoEhPressao = laudo?.tipo === TIPO_LAUDO_PRESSAO_ARTERIAL;
  const laudoEhEco = laudo?.tipo === TIPO_LAUDO_ECOCARDIOGRAMA;
  const { measurements: medidasExibidas, alerts: alertasCalculo, ambiguousKeys } = prepareEchoReportMeasurements(medidas, paciente?.peso_kg, paciente?.especie, paciente?.idade);
  const referenciaParaPrevia = referenciaEco || makeLowWeightReference(paciente?.especie, paciente?.peso_kg, 0, {}, paciente?.idade);
  const gruposMedidas = buildEchoReportGroups(medidasExibidas, referenciaParaPrevia, ambiguousKeys, paciente?.peso_kg, paciente?.especie, paciente?.idade);
  const observacoes = splitReportObservations(laudo?.observacoes || "");

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    if (!laudoId) return;
    carregarLaudo();
  }, [router, laudoId]);

  useEffect(() => {
    let active = true;
    setReferenciaEco(null);
    if (laudoEhEco && paciente?.especie && paciente.peso_kg > 0) {
      buscarReferencia(paciente.especie, paciente.peso_kg, paciente.idade).then((reference) => {
        if (active) setReferenciaEco(reference);
      });
    }
    return () => { active = false; };
  }, [laudoEhEco, paciente?.especie, paciente?.peso_kg, paciente?.idade, buscarReferencia]);

  const carregarLaudo = async () => {
    if (!laudoId) return;
    try {
      setLoading(true);

      // Carregar laudo
      const respLaudo = await api.get(`/laudos/${laudoId}`);
      if (respLaudo.data.tipo === TIPO_LAUDO_ULTRASSOM_ABDOMINAL) {
        router.replace(getLaudoViewPath(laudoId, respLaudo.data.tipo));
        return;
      }
      setLaudo(respLaudo.data);

      // Carregar dados do paciente (agora vem no laudo)
      if (respLaudo.data.paciente) {
        setPaciente(respLaudo.data.paciente);
      } else if (respLaudo.data.paciente_id) {
        // Fallback: buscar paciente separadamente (para laudos antigos)
        try {
          const respPaciente = await api.get(`/pacientes/${respLaudo.data.paciente_id}`);
          setPaciente(respPaciente.data);
        } catch (e) {
          console.error("Erro ao carregar paciente:", e);
        }
      }

      // Extrair medidas e qualitativa da descrição
      if (respLaudo.data.descricao) {
        const descricao = respLaudo.data.descricao;

        // Extrair medidas (formato: - DIVEd: 1.50)
        // Regex atualizada para capturar nomes com underscores
        const medidasExtraidas = parseStoredEchoMeasurements(
          respLaudo.data.medidas,
          descricao
        );
        setMedidas(medidasExtraidas);

        // Extrair qualitativa
        setQualitativa(extrairQualitativaEcoDaDescricao(descricao));
      }
    } catch (error) {
      console.error("Erro ao carregar laudo:", error);
      alert("Erro ao carregar laudo.");
    } finally {
      setLoading(false);
    }
  };

  const downloadPDF = async () => {
    if (!laudoId) return;
    try {
      if (laudo?.tipo === TIPO_LAUDO_ELETROCARDIOGRAMA) {
        return await baixarLaudoPdfOriginal(Number(laudoId), laudo.pdf_externo?.nome_original || `eletrocardiograma_${laudoId}.pdf`);
      }
      return await baixarLaudoPdf(Number(laudoId), `laudo_${laudoId}.pdf`);
      const token = localStorage.getItem("token");
      const response = await fetch(`/api/v1/laudos/${laudoId}/pdf`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });

      if (!response.ok) {
        throw new Error('Erro ao baixar PDF');
      }

      // Extrair nome do arquivo do header Content-Disposition
      let filename = `laudo_${laudoId}.pdf`;
      const contentDisposition = response.headers.get('content-disposition');

      if (contentDisposition) {
        // Regex que aceita tanto filename="..." quanto filename=...
        const match = contentDisposition?.match(/filename="?([^";\s]+)"?/);
        if (match?.[1]) {
          filename = match?.[1] || filename;
        }
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Erro:', error);
      alert('Erro ao baixar PDF.');
    }
  };

  const imprimir = () => {
    window.print();
  };

  const liberarNoPortalClinica = async () => {
    if (!laudo || !laudoId || !canReleasePortal(laudo)) {
      return;
    }
    if (!laudo.clinic_id && !laudo.veterinario_parceiro_id) {
      alert("Vincule uma clinica ou um veterinario parceiro ao laudo antes de liberar no portal.");
      return;
    }
    if (!confirm(getPortalConfirmMessage(laudo))) {
      return;
    }

    setLiberandoPortal(true);
    try {
      const response = await api.post(`/laudos/${laudoId}/portal/liberar`);
      setLaudo((current) =>
        current
          ? {
              ...current,
              status: response.data?.status || PORTAL_RELEASE_STATUS,
              portal_clinica_liberado: response.data?.portal_clinica_liberado,
              portal_veterinario_liberado: response.data?.portal_veterinario_liberado,
              portal_destinos_pendentes: response.data?.portal_destinos_pendentes || [],
              portal_pode_liberar: response.data?.portal_pode_liberar,
            }
          : current
      );
      alert(response.data?.message || "Laudo liberado no portal.");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      alert(detail || "Erro ao liberar laudo no portal. Tente novamente.");
    } finally {
      setLiberandoPortal(false);
    }
  };

  const revogarAcessoDoVeterinario = async (partnerId: number, nome: string) => {
    if (!laudo || !laudoId) return;
    if (!confirm(getConfirmacaoRevogarVeterinario(nome))) {
      return;
    }

    setRevogandoPartnerId(partnerId);
    try {
      const response = await api.post(`/laudos/${laudo.id}/portal/veterinarios/${partnerId}/revogar`);
      const dados = response.data;
      setLaudo((atual) =>
        atual
          ? {
              ...atual,
              portal_clinica_liberado: dados?.portal_clinica_liberado ?? atual.portal_clinica_liberado,
              portal_veterinario_liberado: dados?.portal_veterinario_liberado,
              portal_veterinarios_destinos: dados?.portal_veterinarios_destinos ?? atual.portal_veterinarios_destinos,
              portal_destinos_pendentes: dados?.portal_destinos_pendentes || [],
              portal_pode_liberar: dados?.portal_pode_liberar,
            }
          : atual
      );
      alert(`${nome} não tem mais acesso a este laudo no portal.`);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      alert(detail || "Erro ao revogar o acesso no portal. Tente novamente.");
    } finally {
      setRevogandoPartnerId(null);
    }
  };

  const abrirSeletorAvisoWhatsApp = () => {
    if (!laudo) return;
    if (!podeAvisarWhatsApp(laudo)) {
      alert("Libere o laudo no portal antes de enviar o aviso por WhatsApp.");
      return;
    }
    setSeletorAvisoAberto(true);
  };

  const avisarLaudoPorWhatsApp = async (destinos: string[]) => {
    if (!laudo || !laudoId || destinos.length === 0) return;
    const idempotencyKey = typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `laudo-portal-${laudo.id}-${Date.now()}`;
    setAvisandoWhatsApp(true);
    try {
      const response = await api.post<RespostaAvisoWhatsApp>(`/laudos/${laudo.id}/portal/whatsapp`, {
        idempotency_key: idempotencyKey,
        destinos,
      });
      const dados = response.data;
      setSeletorAvisoAberto(false);
      // O resultado por destino volta na resposta: guarda para o seletor abrir
      // ja sabendo quem acabou de receber.
      setLaudo((atual) => (atual ? { ...atual, whatsapp_envios: dados?.whatsapp_envios ?? atual.whatsapp_envios } : atual));
      alert(resumirRespostaAvisoWhatsApp(dados).texto);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      alert(detail || "Erro ao enviar o aviso por WhatsApp.");
    } finally {
      setAvisandoWhatsApp(false);
    }
  };

  const selecionarPdfSubstituto = (file: File | null) => {
    if (!file) {
      setArquivoSubstituicao(null);
      return;
    }

    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      alert("Selecione um arquivo PDF.");
      setArquivoSubstituicao(null);
      setFileInputKey((current) => current + 1);
      return;
    }

    setArquivoSubstituicao(file);
  };

  const substituirPdfEletrocardiograma = async () => {
    if (!laudoId || !laudoEhEletrocardiograma) {
      return;
    }
    if (!arquivoSubstituicao) {
      alert("Selecione o novo PDF antes de substituir.");
      return;
    }

    const confirmMessage = isPortalReleased(laudo?.status)
      ? "Este laudo ja foi liberado no portal. Deseja trocar o PDF e atualizar imediatamente o arquivo baixavel dos destinatarios autorizados?"
      : "Deseja substituir o PDF anexado a este laudo de eletrocardiograma?";
    if (!confirm(confirmMessage)) {
      return;
    }

    const formData = new FormData();
    formData.append("arquivo", arquivoSubstituicao);

    setSubstituindoPdf(true);
    try {
      await api.put(`/laudos/${laudoId}/eletrocardiograma/pdf`, formData);
      setArquivoSubstituicao(null);
      setFileInputKey((current) => current + 1);
      await carregarLaudo();
      alert(
        isPortalReleased(laudo?.status)
          ? "PDF substituido e portal atualizado."
          : "PDF substituido com sucesso.",
      );
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      alert(detail || "Erro ao substituir PDF do eletrocardiograma.");
    } finally {
      setSubstituindoPdf(false);
    }
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="fc-report-view-page">
          <div className="fc-report-loading"><span aria-hidden="true" />Carregando laudo...</div>
        </div>
      </DashboardLayout>
    );
  }

  if (!laudo) {
    return (
      <DashboardLayout>
        <div className="fc-report-view-page">
          <div className="fc-report-empty">
          <h1 className="text-2xl font-bold text-gray-900">Laudo não encontrado</h1>
          <p className="text-gray-500 mt-2">O laudo solicitado não existe ou foi removido.</p>
          <button
            type="button"
            onClick={() => router.push("/laudos")}
            className="fc-report-editor-save mt-4"
          >
            Voltar para Laudos
          </button>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="fc-report-view-page">
        {seletorAvisoAberto && (
          <AvisoWhatsAppDialog
            laudo={laudo}
            enviando={avisandoWhatsApp}
            onCancelar={() => setSeletorAvisoAberto(false)}
            onEnviar={avisarLaudoPorWhatsApp}
          />
        )}
        <header className="fc-report-view-header">
          <div className="fc-report-editor-heading">
            <button
              type="button"
              onClick={() => router.push("/laudos")}
              className="fc-report-editor-back"
              aria-label="Voltar para laudos"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            {podeAvisarWhatsApp(laudo) ? (
              <button
                type="button"
                onClick={abrirSeletorAvisoWhatsApp}
                disabled={avisandoWhatsApp}
                className="fc-report-view-portal"
                title={getTituloBotaoAvisoWhatsApp(laudo)}
              >
                {avisandoWhatsApp ? <Loader2 className="w-4 h-4 animate-spin" /> : <MessageCircle className="w-4 h-4" />}
                {avisandoWhatsApp ? "Enviando..." : "Avisar WhatsApp"}
              </button>
            ) : null}
            <div>
              <span className="fc-report-editor-kicker">
                <FileText className="h-4 w-4" />
                Documento clínico
              </span>
              <h1>Visualizar laudo</h1>
              <p>{laudo.titulo}</p>
            </div>
          </div>

          <div className="fc-report-view-actions">
            <button
              type="button"
              onClick={liberarNoPortalClinica}
              disabled={liberandoPortal || !canReleasePortal(laudo)}
              className={`fc-report-view-portal ${!canReleasePortal(laudo) ? "fc-report-view-portal-released" : ""}`}
              title={getPortalButtonTitle(laudo)}
            >
              {!canReleasePortal(laudo) ? (
                <CheckCircle className="w-4 h-4" />
              ) : (
                <Send className="w-4 h-4" />
              )}
              {!canReleasePortal(laudo)
                ? "No portal"
                : liberandoPortal
                  ? "Liberando..."
                  : "Liberar portal"}
            </button>
            <button
              type="button"
              onClick={downloadPDF}
              className="fc-report-view-pdf"
            >
              <Download className="w-4 h-4" />
              PDF
            </button>
            <button
              type="button"
              onClick={imprimir}
              className="fc-report-view-print"
            >
              <Printer className="w-4 h-4" />
              Imprimir
            </button>
          </div>
        </header>

        {laudo.ordem_servico ? (
          <section className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-teal-200 bg-teal-50 p-4 print:hidden" aria-label="Ordem de serviço vinculada">
            <div>
              <p className="font-bold text-teal-900">Ordem de serviço {laudo.ordem_servico.numero_os}</p>
              <p className="mt-1 text-sm text-slate-700">
                {laudo.ordem_servico.status.toLowerCase() === "pendente" ? "Pendente no Financeiro" : laudo.ordem_servico.status}
                {" · "}{Number(laudo.ordem_servico.valor_final).toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}
              </p>
            </div>
            <Link href={`/financeiro?aba=ordens&os_id=${laudo.ordem_servico.id}`} className="text-sm font-bold text-teal-800 underline">Ver no Financeiro</Link>
          </section>
        ) : null}

        <PortalLiberadoPara
          laudo={laudo}
          revogandoPartnerId={revogandoPartnerId}
          onRevogar={revogarAcessoDoVeterinario}
        />

        {/* Conteúdo do Laudo */}
        <article className="fc-report-view-document print:shadow-none print:border-none">
          {/* Cabeçalho do Laudo */}
          <div className="text-center mb-8">
            <h2 className="text-xl font-bold text-gray-900">
              {laudoEhEletrocardiograma
                ? "LAUDO DE ELETROCARDIOGRAMA"
                : laudoEhPressao
                  ? "LAUDO DE PRESSAO ARTERIAL"
                  : "LAUDO ECOCARDIOGRAFICO"}
            </h2>
            <div className="w-full h-px bg-gray-300 mt-4"></div>
          </div>

          {/* Dados do Paciente */}
          <div className="mb-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">Dados do Paciente</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Nome:</span>
                <p className="font-medium">{paciente?.nome || "N/A"}</p>
              </div>
              <div>
                <span className="text-gray-500">Espécie:</span>
                <p className="font-medium">{paciente?.especie || "N/A"}</p>
              </div>
              <div>
                <span className="text-gray-500">Raça:</span>
                <p className="font-medium">{paciente?.raca || "N/A"}</p>
              </div>
              <div>
                <span className="text-gray-500">Sexo:</span>
                <p className="font-medium">{paciente?.sexo || "N/A"}</p>
              </div>
              {paciente?.peso_kg && (
                <div>
                  <span className="text-gray-500">Peso:</span>
                  <p className="font-medium">{paciente.peso_kg} kg</p>
                </div>
              )}
              {paciente?.idade && (
                <div>
                  <span className="text-gray-500">Idade:</span>
                  <p className="font-medium">{paciente.idade}</p>
                </div>
              )}
              {paciente?.tutor && (
                <div>
                  <span className="text-gray-500">Tutor:</span>
                  <p className="font-medium">{paciente.tutor}</p>
                </div>
              )}
              {paciente?.telefone && (
                <div>
                  <span className="text-gray-500">Telefone:</span>
                  <p className="font-medium">{paciente.telefone}</p>
                </div>
              )}
              <div>
                <span className="text-gray-500">Data do Exame:</span>
                <p className="font-medium">
                  {laudo.data_exame
                    ? formatCalendarDate(laudo.data_exame)
                    : formatOperationalDate(laudo.data_laudo)}
                </p>
              </div>
              {laudo.clinica && (
                <div>
                  <span className="text-gray-500">Clínica:</span>
                  <p className="font-medium">{laudo.clinica}</p>
                </div>
              )}
              {laudo.veterinario_parceiro_nome && (
                <div>
                  <span className="text-gray-500">Veterinário parceiro:</span>
                  <p className="font-medium">
                    {laudo.veterinario_parceiro_nome}
                    {laudo.veterinario_parceiro_crmv ? ` • CRMV ${laudo.veterinario_parceiro_crmv}` : ""}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Status */}
          <div className="mb-6">
            <span className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${
              laudo.status === PORTAL_RELEASE_STATUS
                ? 'bg-teal-100 text-teal-800'
                : laudo.status === 'Finalizado'
                ? 'bg-green-100 text-green-800'
                : laudo.status === 'Rascunho'
                  ? 'bg-gray-100 text-gray-800'
                  : 'bg-blue-100 text-blue-800'
              }`}>
              {laudo.status}
            </span>
          </div>

          {laudoEhEletrocardiograma && (
            <div className="mb-6 rounded-lg border border-teal-100 bg-teal-50 p-4 text-sm text-teal-900">
              <p className="font-semibold">PDF original anexado</p>
              <p className="mt-1">
                Use o botao PDF para baixar o eletrocardiograma enviado. A liberacao para o portal da clinica fica no botao Liberar portal.
              </p>
              <div className="mt-4 rounded-lg border border-teal-200 bg-white/70 p-4">
                <p className="text-sm font-semibold text-slate-900">Trocar arquivo do eletrocardiograma</p>
                <p className="mt-1 text-sm text-slate-600">
                  {laudo.pdf_externo?.nome_original
                    ? `Arquivo atual: ${laudo.pdf_externo.nome_original}`
                    : "Nenhum PDF externo encontrado para este laudo."}
                </p>
                <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-center">
                  <input
                    key={fileInputKey}
                    type="file"
                    accept="application/pdf,.pdf"
                    onChange={(event) => selecionarPdfSubstituto(event.target.files?.[0] || null)}
                    className="block w-full text-sm text-slate-700 file:mr-4 file:rounded-lg file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
                  />
                  <button
                    type="button"
                    onClick={substituirPdfEletrocardiograma}
                    disabled={substituindoPdf || !arquivoSubstituicao}
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {substituindoPdf ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                    {substituindoPdf ? "Substituindo..." : "Trocar PDF"}
                  </button>
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  {isPortalReleased(laudo.status)
                    ? "Como este laudo ja esta no portal, a troca atualiza imediatamente o arquivo disponivel para a clinica parceira."
                    : "A troca atualiza o PDF deste laudo sem criar um novo registro."}
                </p>
              </div>
            </div>
          )}

          {laudoEhPressao && (
            <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
              <p className="font-semibold">Resumo da afericao de pressao arterial</p>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-4">
                <div className="rounded-lg border border-amber-200 bg-white px-3 py-2">
                  <span className="text-xs uppercase tracking-wide text-amber-700">PAS 1</span>
                  <p className="mt-1 font-medium">{laudo.pressao_arterial?.pas_1 ?? "-"} mmHg</p>
                </div>
                <div className="rounded-lg border border-amber-200 bg-white px-3 py-2">
                  <span className="text-xs uppercase tracking-wide text-amber-700">PAS 2</span>
                  <p className="mt-1 font-medium">{laudo.pressao_arterial?.pas_2 ?? "-"} mmHg</p>
                </div>
                <div className="rounded-lg border border-amber-200 bg-white px-3 py-2">
                  <span className="text-xs uppercase tracking-wide text-amber-700">PAS 3</span>
                  <p className="mt-1 font-medium">{laudo.pressao_arterial?.pas_3 ?? "-"} mmHg</p>
                </div>
                <div className="rounded-lg border border-amber-200 bg-white px-3 py-2">
                  <span className="text-xs uppercase tracking-wide text-amber-700">Media</span>
                  <p className="mt-1 font-medium">{laudo.pressao_arterial?.pas_media ?? "-"} mmHg</p>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                <div>
                  <span className="text-xs uppercase tracking-wide text-amber-700">Metodo</span>
                  <p className="mt-1">{laudo.pressao_arterial?.metodo || "Doppler"}</p>
                </div>
                <div>
                  <span className="text-xs uppercase tracking-wide text-amber-700">Manguito</span>
                  <p className="mt-1">{laudo.pressao_arterial?.manguito || "-"}</p>
                </div>
                <div>
                  <span className="text-xs uppercase tracking-wide text-amber-700">Membro / decubito</span>
                  <p className="mt-1">
                    {[laudo.pressao_arterial?.membro, laudo.pressao_arterial?.decubito].filter(Boolean).join(" · ") || "-"}
                  </p>
                </div>
              </div>
              {laudo.pressao_arterial?.obs_extra ? (
                <div className="mt-3 rounded-lg border border-amber-200 bg-white px-3 py-2">
                  <span className="text-xs uppercase tracking-wide text-amber-700">Observacoes da afericao</span>
                  <p className="mt-1 whitespace-pre-wrap">{laudo.pressao_arterial.obs_extra}</p>
                </div>
              ) : null}
            </div>
          )}

          {laudoEhEco && (
            <EchoNarrativeConsistencyNotice
              species={paciente?.especie}
              measurements={medidas}
              qualitative={qualitativa}
              conclusion={laudo.diagnostico || ""}
            />
          )}

          {/* Medidas */}
          {laudoEhEco && gruposMedidas.length > 0 && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">Medidas Ecocardiográficas</h3>
              {ambiguousKeys.size > 0 && (
                <p className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950" role="status">
                  Unidade a confirmar nas medidas indicadas. Confira o exame de origem antes de interpretar essas dimensões; o PDF mantém os valores registrados.
                </p>
              )}
              {alertasCalculo.length > 0 && (
                <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950" role="status">
                  <p className="font-semibold">Conferir cálculo normalizado</p>
                  {alertasCalculo.map((alerta) => (
                    <p key={alerta.key} className="mt-1">
                      {alerta.key === "DIVEd_normalizado_2D" ? "DIVEd normalizado (2D)" : "DIVEd normalizado"}: registro {alerta.recorded.toFixed(2)}; cálculo com o peso atual ({paciente?.peso_kg} kg) {alerta.calculated.toFixed(2)}. O PDF usa o valor recalculado.
                    </p>
                  ))}
                </div>
              )}
              <p className="mb-3 text-xs text-gray-600">
                {carregandoReferencia
                  ? "Consultando faixas de referência por espécie e peso..."
                  : referenciaParaPrevia?.reference_origin === "computed"
                  ? `Referência calculada para ${referenciaParaPrevia.especie}, ${paciente?.peso_kg} kg; confirme a população adulta e o contexto de cada medida.`
                  : referenciaEco
                  ? `Referência selecionada por espécie e peso: cadastro de ${referenciaEco.especie}, ${referenciaEco.peso_kg} kg.`
                  : gruposMedidas.some((grupo) => grupo.rows.some((row) => ["descriptive", "reference_interval"].includes(row.referenceMetadata?.kind ?? "")))
                  ? "Referências específicas da técnica estão indicadas nas medidas abaixo."
                  : "Faixas de referência indisponíveis nesta prévia."}
              </p>
              {referenciaEco?.fs_source && medidasExibidas.DeltaD_FS && medidasExibidas.VE_tecnica_relatorio !== "2d" && (
                <p className="mb-2 text-xs text-gray-600">FS (modo M): {referenciaEco.fs_source}.</p>
              )}
              {medidas.Remodelamento_AD && (
                <p className="mb-3 text-xs text-gray-600">Premissa registrada para estimativa da pressão atrial direita: remodelamento de AD {medidas.Remodelamento_AD}.</p>
              )}
              <div className="space-y-4">
                {gruposMedidas.map((grupo) => (
                  <div key={grupo.title} className="overflow-x-auto rounded-lg bg-gray-50 p-4">
                    <h4 className="mb-2 font-semibold text-gray-800">{grupo.title}</h4>
                    <table className="w-full text-sm">
                      <thead><tr className="border-b border-gray-200">
                        <th className="py-2 text-left font-medium text-gray-700">Parâmetro</th>
                        <th className="py-2 text-left font-medium text-gray-700">Valor</th>
                        <th className="py-2 text-left font-medium text-gray-700">Referência</th>
                      </tr></thead>
                      <tbody>
                        {grupo.rows.map((row) => (
                          <tr key={row.key} className="border-b border-gray-100 last:border-0">
                            <td className="py-2 pr-3 text-gray-700">{row.label}</td>
                            <td className="py-2 pr-3 font-medium whitespace-nowrap">{row.value}</td>
                            <td className={row.referenceMetadata
                              ? "py-2 text-gray-600 whitespace-normal break-words align-top min-w-[14rem] max-w-md"
                              : "py-2 text-gray-600 whitespace-nowrap"}>
                              {row.referenceMetadata ? <p>{row.reference}</p> : row.reference}
                              {row.referenceMetadata?.source && (
                                <p className="mt-1 text-xs leading-relaxed">
                                  {row.referenceMetadata.doi ? (
                                    <a href={`https://doi.org/${row.referenceMetadata.doi}`} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                                      {row.referenceMetadata.source}
                                    </a>
                                  ) : row.referenceMetadata.source}
                                </p>
                              )}
                              {row.referenceMetadata?.note && (
                                <p className="mt-1 text-xs leading-relaxed">{row.referenceMetadata.note}</p>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            </div>
          )}

          {laudoEhEco && laudo.paciente_id && <EchoPreviousExamComparison laudoId={laudo.id} pacienteId={laudo.paciente_id} />}

          {/* Qualitativa */}
          {!laudoEhPressao && Object.values(qualitativa).some((value) => Boolean(value?.trim())) && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">Avaliação Qualitativa</h3>
              <div className="space-y-3">
                {Object.entries(qualitativa).filter(([, valor]) => Boolean(valor?.trim())).map(([chave, valor]) => (
                  <div key={chave} className="bg-gray-50 rounded-lg p-3">
                    <span className="font-medium text-gray-700">{ROTULOS_QUALITATIVOS[chave as keyof QualitativaEcoLegada]}:</span>
                    <p className="text-gray-600 mt-1 whitespace-pre-wrap">{valor}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Conclusão */}
          {laudo.diagnostico && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">Conclusão</h3>
              <div className="bg-gray-50 rounded-lg p-4 whitespace-pre-wrap">
                {laudo.diagnostico}
              </div>
            </div>
          )}

          {/* Observações */}
          {observacoes.clinical && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">Observações clínicas</h3>
              <div className="bg-gray-50 rounded-lg p-4 whitespace-pre-wrap">
                {observacoes.clinical}
              </div>
            </div>
          )}
          {observacoes.operational && (
            <div className="mb-6">
              <h3 className="text-base font-semibold text-gray-700 mb-2">Registro operacional</h3>
              <div className="bg-slate-50 rounded-lg p-4 whitespace-pre-wrap text-sm text-slate-700">
                {observacoes.operational}
              </div>
            </div>
          )}

          {/* Rodapé */}
          <div className="mt-8 pt-4 border-t border-gray-200 text-center text-sm text-gray-500">
            <p>Laudo emitido por {laudo.criado_por_nome || "Médico Veterinário"}</p>
            <p className="mt-1">
              Documento gerado eletronicamente em{' '}
              {formatOperationalDate(laudo.data_laudo)}
            </p>
          </div>
        </article>
      </div>
    </DashboardLayout>
  );
}
