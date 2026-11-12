"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import {
  getLaudoEditPath,
  getLaudoViewPath,
  TIPO_LAUDO_ULTRASSOM_ABDOMINAL,
} from "@/lib/laudos";
import { baixarLaudoPdf } from "@/lib/laudo-pdf";
import { formatCalendarDate, formatOperationalDate } from "@/lib/calendar-date";
import {
  getOrgaosVisiveis,
  normalizarSexoPaciente,
} from "@/lib/ultrassonografia-abdominal";
import { ArrowLeft, Download, Edit, Loader2, ScanLine } from "lucide-react";

interface ImagemPreview {
  id: number;
  nome: string;
  dataUrl: string;
}

export default function VisualizarUltrassonografiaAbdominalPage() {
  const router = useRouter();
  const routeParams = useParams<{ id?: string | string[] }>();
  const laudoId = Array.isArray(routeParams.id) ? routeParams.id[0] : routeParams.id;
  const [loading, setLoading] = useState(true);
  const [laudo, setLaudo] = useState<any>(null);
  const [imagens, setImagens] = useState<ImagemPreview[]>([]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    if (!laudoId) return;
    carregarLaudo();
  }, [router, laudoId]);

  const carregarLaudo = async () => {
    if (!laudoId) return;
    try {
      setLoading(true);
      const response = await api.get(`/laudos/${laudoId}`);
      if (response.data.tipo !== TIPO_LAUDO_ULTRASSOM_ABDOMINAL) {
        router.replace(getLaudoViewPath(laudoId, response.data.tipo));
        return;
      }
      setLaudo(response.data);
      await carregarImagens(response.data.imagens || []);
    } catch (error) {
      console.error("Erro ao carregar laudo:", error);
      alert("Nao foi possivel carregar o laudo.");
      router.push("/ultrassonografia-abdominal");
    } finally {
      setLoading(false);
    }
  };

  const carregarImagens = async (imagensApi: Array<any>) => {
    const token = localStorage.getItem("token");
    const previews = await Promise.all(
      imagensApi.map(async (imagem) => {
        try {
          const response = await fetch(`/api/v1${imagem.url}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          });
          if (!response.ok) {
            throw new Error("Falha ao carregar imagem.");
          }
          const blob = await response.blob();
          const dataUrl = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
              if (typeof reader.result === "string") {
                resolve(reader.result);
                return;
              }
              reject(new Error("Falha ao ler imagem."));
            };
            reader.onerror = () => reject(reader.error || new Error("Falha ao ler imagem."));
            reader.readAsDataURL(blob);
          });
          return {
            id: imagem.id,
            nome: imagem.nome,
            dataUrl,
          };
        } catch (error) {
          console.error("Erro ao preparar imagem:", error);
          return null;
        }
      })
    );
    setImagens(previews.filter(Boolean) as ImagemPreview[]);
  };

  const downloadPDF = async () => {
    if (!laudoId) return;
    try {
      await baixarLaudoPdf(Number(laudoId), `ultrassonografia_abdominal_${laudoId}.pdf`);
    } catch (error) {
      console.error("Erro ao baixar PDF:", error);
      alert("Nao foi possivel baixar o PDF.");
    }
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="fc-ultrasound-view-page">
          <div className="fc-ultrasound-loading">
          <Loader2 className="h-6 w-6 animate-spin" />
          Carregando laudo...
          </div>
        </div>
      </DashboardLayout>
    );
  }

  if (!laudo) {
    return null;
  }

  const sexoPaciente = laudo.ultrassonografia_abdominal?.sexo_paciente || laudo.paciente?.sexo || "Macho";
  const orgaos = getOrgaosVisiveis(sexoPaciente);
  const qualitativa = laudo.ultrassonografia_abdominal?.qualitativa || {};
  const observacoes = laudo.ultrassonografia_abdominal?.observacoes_gerais || laudo.observacoes || "";

  return (
    <DashboardLayout>
      <div className="fc-ultrasound-view-page">
        <header className="fc-ultrasound-view-header">
          <div className="fc-ultrasound-form-heading">
            <button
              type="button"
              onClick={() => router.push("/ultrassonografia-abdominal")}
              className="fc-ultrasound-form-back"
              aria-label="Voltar para ultrassonografia abdominal"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-ultrasound-form-kicker">
                <ScanLine className="h-4 w-4" />
                Documento ultrassonográfico
              </span>
              <h1>Ultrassonografia abdominal</h1>
              <p>{laudo.paciente?.nome || "Paciente"}</p>
            </div>
          </div>

          <div className="fc-ultrasound-view-actions">
            <button
              type="button"
              onClick={downloadPDF}
              className="fc-ultrasound-view-pdf"
            >
              <Download className="w-4 h-4" />
              PDF
            </button>
            <button
              type="button"
              onClick={() => router.push(getLaudoEditPath(laudoId || "", laudo.tipo))}
              className="fc-ultrasound-view-edit"
            >
              <Edit className="w-4 h-4" />
              Editar
            </button>
          </div>
        </header>

        <section className="fc-ultrasound-view-card fc-ultrasound-view-summary">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 text-sm">
            <div><span className="text-gray-500">Paciente</span><p className="font-medium">{laudo.paciente?.nome || "N/A"}</p></div>
            <div><span className="text-gray-500">Tutor</span><p className="font-medium">{laudo.paciente?.tutor || "N/A"}</p></div>
            <div><span className="text-gray-500">Especie</span><p className="font-medium">{laudo.paciente?.especie || "N/A"}</p></div>
            <div><span className="text-gray-500">Raca</span><p className="font-medium">{laudo.paciente?.raca || "N/A"}</p></div>
            <div><span className="text-gray-500">Sexo</span><p className="font-medium">{normalizarSexoPaciente(sexoPaciente)}</p></div>
            <div><span className="text-gray-500">Peso</span><p className="font-medium">{laudo.paciente?.peso_kg ? `${laudo.paciente.peso_kg} kg` : "N/A"}</p></div>
            <div><span className="text-gray-500">Idade</span><p className="font-medium">{laudo.paciente?.idade || "N/A"}</p></div>
            <div><span className="text-gray-500">Data</span><p className="font-medium">{laudo.data_exame ? formatCalendarDate(laudo.data_exame) : formatOperationalDate(laudo.data_laudo)}</p></div>
            <div><span className="text-gray-500">Clinica</span><p className="font-medium">{laudo.clinica || "N/A"}</p></div>
            <div><span className="text-gray-500">Veterinario</span><p className="font-medium">{laudo.medico_solicitante || "N/A"}</p></div>
            <div><span className="text-gray-500">Status</span><p className="font-medium">{laudo.status}</p></div>
          </div>
        </section>

        <section className="fc-ultrasound-view-card space-y-5">
          <h2 className="text-lg font-semibold text-gray-900">Avaliacao Qualitativa</h2>
          {orgaos.map((orgao) => {
            const texto = qualitativa[orgao.key];
            if (!texto) {
              return null;
            }
            return (
              <div key={orgao.key} className="border-b last:border-b-0 pb-4 last:pb-0">
                <h3 className="font-semibold text-gray-900 mb-1">{orgao.label}</h3>
                <p className="text-sm text-gray-700 whitespace-pre-wrap">{texto}</p>
              </div>
            );
          })}

          {observacoes && (
            <div className="border-t pt-4">
              <h3 className="font-semibold text-gray-900 mb-1">Observacoes gerais</h3>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{observacoes}</p>
            </div>
          )}
        </section>

        {imagens.length > 0 && (
          <section className="fc-ultrasound-view-card">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Imagens</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {imagens.map((imagem) => (
                <div key={imagem.id} className="border rounded-xl overflow-hidden">
                  <img src={imagem.dataUrl} alt={imagem.nome} className="w-full h-64 object-cover" />
                  <div className="p-3 text-sm text-gray-600">{imagem.nome}</div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </DashboardLayout>
  );
}
