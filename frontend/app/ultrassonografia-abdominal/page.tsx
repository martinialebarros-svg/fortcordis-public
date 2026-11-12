"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import {
  getLaudoEditPath,
  getLaudoViewPath,
  TIPO_LAUDO_ULTRASSOM_ABDOMINAL,
} from "@/lib/laudos";
import { baixarLaudoPdf } from "@/lib/laudo-pdf";
import { formatCalendarDate, formatOperationalDate } from "@/lib/calendar-date";
import { Calendar, Download, Eye, Edit, Plus, Search, Trash2, ScanLine } from "lucide-react";

interface LaudoLista {
  id: number;
  paciente_nome?: string;
  paciente_tutor?: string;
  clinica?: string;
  tipo: string;
  status: string;
  data_laudo: string;
  data_exame?: string;
}

function getStatusColor(status: string) {
  const cores: Record<string, string> = {
    Rascunho: "bg-gray-100 text-gray-800",
    Finalizado: "bg-green-100 text-green-800",
    Arquivado: "bg-blue-100 text-blue-800",
  };
  return cores[status] || "bg-gray-100 text-gray-800";
}

export default function UltrassonografiaAbdominalPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [busca, setBusca] = useState("");
  const [laudos, setLaudos] = useState<LaudoLista[]>([]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarLaudos();
  }, [router]);

  const carregarLaudos = async () => {
    try {
      setLoading(true);
      const response = await api.get("/laudos", {
        params: { tipo: TIPO_LAUDO_ULTRASSOM_ABDOMINAL },
      });
      setLaudos(response.data.items || []);
    } catch (error) {
      console.error("Erro ao carregar laudos:", error);
      setLaudos([]);
    } finally {
      setLoading(false);
    }
  };

  const laudosFiltrados = laudos.filter((laudo) => {
    const termo = busca.trim().toLowerCase();
    if (!termo) {
      return true;
    }
    return (
      (laudo.paciente_nome || "").toLowerCase().includes(termo) ||
      (laudo.paciente_tutor || "").toLowerCase().includes(termo) ||
      (laudo.clinica || "").toLowerCase().includes(termo) ||
      (laudo.status || "").toLowerCase().includes(termo)
    );
  });

  const downloadPDF = async (laudoId: number) => {
    try {
      await baixarLaudoPdf(laudoId, `ultrassonografia_abdominal_${laudoId}.pdf`);
    } catch (error) {
      console.error("Erro ao baixar PDF:", error);
      alert("Nao foi possivel baixar o PDF.");
    }
  };

  const excluirLaudo = async (laudoId: number) => {
    if (!confirm("Deseja excluir este laudo?")) {
      return;
    }
    try {
      await api.delete(`/laudos/${laudoId}`);
      setLaudos((prev) => prev.filter((laudo) => laudo.id !== laudoId));
    } catch (error) {
      console.error("Erro ao excluir laudo:", error);
      alert("Nao foi possivel excluir o laudo.");
    }
  };

  return (
    <DashboardLayout>
      <div className="fc-ultrasound-page">
        <header className="fc-ultrasound-header">
          <div>
            <span className="fc-ultrasound-kicker">
              <ScanLine className="h-4 w-4" />
              Diagnóstico por imagem
            </span>
            <h1>Ultrassonografia abdominal</h1>
            <p>Cadastre, revise e acompanhe os laudos ultrassonográficos.</p>
          </div>
          <button
            type="button"
            onClick={() => router.push("/ultrassonografia-abdominal/novo")}
            className="fc-ultrasound-primary"
          >
            <Plus className="w-4 h-4" />
            Novo laudo
          </button>
        </header>

        <section className="fc-ultrasound-metrics" aria-label="Resumo dos laudos de ultrassonografia">
          <div><strong>{laudos.length}</strong><span>Total de laudos</span></div>
          <div><strong>{laudosFiltrados.length}</strong><span>Resultados visíveis</span></div>
        </section>

        <div className="fc-ultrasound-search">
          <div className="relative">
            <Search className="w-5 h-5 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-teal-500"
              placeholder="Buscar por paciente, tutor, clinica ou status"
            />
          </div>
        </div>

        <section className="fc-ultrasound-list">
          {loading ? (
            <div className="p-10 text-center text-gray-500">Carregando laudos...</div>
          ) : laudosFiltrados.length === 0 ? (
            <div className="p-10 text-center text-gray-500">Nenhum laudo de ultrassonografia abdominal encontrado.</div>
          ) : (
            <div className="divide-y">
              {laudosFiltrados.map((laudo) => (
                <article key={laudo.id} className="fc-ultrasound-item">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="space-y-1">
                      <h2 className="font-semibold text-gray-900">{laudo.paciente_nome || `Paciente #${laudo.id}`}</h2>
                      <div className="flex flex-wrap gap-4 text-sm text-gray-500">
                        <span>{laudo.paciente_tutor || "Sem tutor"}</span>
                        {laudo.clinica && <span>{laudo.clinica}</span>}
                        <span className="inline-flex items-center gap-1">
                          <Calendar className="w-3 h-3" />
                          {laudo.data_exame
                            ? formatCalendarDate(laudo.data_exame)
                            : formatOperationalDate(laudo.data_laudo)}
                        </span>
                      </div>
                    </div>

                    <div className="fc-ultrasound-item-actions">
                      <span className={`px-2 py-1 rounded-full text-xs ${getStatusColor(laudo.status)}`}>
                        {laudo.status}
                      </span>
                      <button
                        type="button"
                        onClick={() => router.push(getLaudoViewPath(laudo.id, laudo.tipo))}
                        className="p-2 rounded-lg text-gray-600 hover:bg-teal-50 hover:text-teal-700"
                        title="Visualizar"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => router.push(getLaudoEditPath(laudo.id, laudo.tipo))}
                        className="p-2 rounded-lg text-gray-600 hover:bg-blue-50 hover:text-blue-700"
                        title="Editar"
                      >
                        <Edit className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => downloadPDF(laudo.id)}
                        className="p-2 rounded-lg text-gray-600 hover:bg-red-50 hover:text-red-700"
                        title="Baixar PDF"
                      >
                        <Download className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => excluirLaudo(laudo.id)}
                        className="p-2 rounded-lg text-gray-600 hover:bg-red-100 hover:text-red-700"
                        title="Excluir"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
