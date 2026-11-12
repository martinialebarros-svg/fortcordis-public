"use client";

import { useState, useEffect } from "react";
import api from "@/lib/axios";
import { BookOpen, Search, ChevronLeft, ChevronRight } from "lucide-react";

interface Referencia {
  id: number;
  especie: string;
  peso_kg: number;
  lvid_d_min?: number;
  lvid_d_max?: number;
  ivs_d_min?: number;
  ivs_d_max?: number;
  lvpw_d_min?: number;
  lvpw_d_max?: number;
  lvid_s_min?: number;
  lvid_s_max?: number;
  ivs_s_min?: number;
  ivs_s_max?: number;
  lvpw_s_min?: number;
  lvpw_s_max?: number;
  fs_min?: number;
  fs_max?: number;
  ef_min?: number;
  ef_max?: number;
  ao_min?: number;
  ao_max?: number;
  la_min?: number;
  la_max?: number;
  la_ao_min?: number;
  la_ao_max?: number;
  vmax_ao_min?: number;
  vmax_ao_max?: number;
  vmax_pulm_min?: number;
  vmax_pulm_max?: number;
  mv_e_min?: number;
  mv_e_max?: number;
  mv_a_min?: number;
  mv_a_max?: number;
  mv_ea_min?: number;
  mv_ea_max?: number;
}

interface ReferenciasEcoProps {
  especie?: string;
  peso?: number;
}

export default function ReferenciasEco({ especie = "Canina", peso }: ReferenciasEcoProps) {
  const [referencias, setReferencias] = useState<Referencia[]>([]);
  const [loading, setLoading] = useState(true);
  const [especieFiltro, setEspecieFiltro] = useState(especie);
  const [pesoBusca, setPesoBusca] = useState(peso?.toString() || "");

  useEffect(() => {
    carregarReferencias();
  }, [especieFiltro]);

  const carregarReferencias = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/referencias-eco?especie=${especieFiltro}`);
      setReferencias(response.data.items || []);
    } catch (error) {
      console.error("Erro ao carregar referências:", error);
    } finally {
      setLoading(false);
    }
  };

  const buscarPorPeso = async () => {
    if (!pesoBusca) return;
    try {
      setLoading(true);
      const response = await api.get(`/referencias-eco/buscar/${especieFiltro}/${pesoBusca}`);
      // Destaca a referência encontrada
      const refEncontrada = response.data;
      setReferencias([refEncontrada]);
    } catch (error) {
      console.error("Erro ao buscar referência:", error);
      alert("Referência não encontrada para este peso");
    } finally {
      setLoading(false);
    }
  };

  const formatarMedida = (min?: number, max?: number, unidade = "") => {
    if (min === undefined || min === null || max === undefined || max === null) return "-";
    return `${min?.toFixed ? min.toFixed(1) : min} - ${max?.toFixed ? max.toFixed(1) : max}${unidade}`;
  };

  return (
    <div className="space-y-4">
      {/* Header com filtros */}
      <div className="flex flex-wrap gap-4 items-center justify-between bg-white p-4 rounded-lg border">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-teal-600" />
          <h3 className="font-semibold text-gray-900">Referências Ecocardiográficas</h3>
        </div>
        
        <div className="flex flex-wrap gap-3">
          {/* Filtro de espécie */}
          <select
            value={especieFiltro}
            onChange={(e) => setEspecieFiltro(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500"
          >
            <option value="Canina">Canina</option>
            <option value="Felina">Felina</option>
          </select>
          
          {/* Busca por peso */}
          <div className="flex gap-2">
            <input
              type="number"
              step="0.1"
              placeholder="Peso (kg)"
              value={pesoBusca}
              onChange={(e) => setPesoBusca(e.target.value)}
              className="w-28 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500"
            />
            <button
              onClick={buscarPorPeso}
              className="px-3 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 text-sm flex items-center gap-1"
            >
              <Search className="w-4 h-4" />
              Buscar
            </button>
          </div>
          
          <button
            onClick={carregarReferencias}
            className="px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm"
          >
            Ver Todos
          </button>
        </div>
      </div>

      {/* Tabela de referências */}
      {loading ? (
        <div className="text-center py-8 text-gray-500">Carregando...</div>
      ) : referencias.length === 0 ? (
        <div className="text-center py-8 text-gray-500">Nenhuma referência encontrada</div>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">Peso (kg)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">LVIDd (mm)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">IVSd (mm)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">LVPWd (mm)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">FS (%)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">EF (%)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">Ao (mm)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">LA (mm)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 border-b">LA/Ao</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {referencias.map((ref) => (
                <tr key={ref.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-medium">{ref.peso_kg}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.lvid_d_min, ref.lvid_d_max)}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.ivs_d_min, ref.ivs_d_max)}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.lvpw_d_min, ref.lvpw_d_max)}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.fs_min, ref.fs_max)}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.ef_min, ref.ef_max)}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.ao_min, ref.ao_max)}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.la_min, ref.la_max)}</td>
                  <td className="px-3 py-2">{formatarMedida(ref.la_ao_min, ref.la_ao_max)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Legenda */}
      <div className="bg-blue-50 p-4 rounded-lg text-sm text-blue-800">
        <p className="font-medium mb-1">Legenda:</p>
        <ul className="space-y-1 text-xs">
          <li><strong>LVIDd:</strong> Diâmetro do ventrículo esquerdo em diástole</li>
          <li><strong>IVSd:</strong> Septo interventricular em diástole</li>
          <li><strong>LVPWd:</strong> Parede posterior do VE em diástole</li>
          <li><strong>FS:</strong> Fração de encurtamento</li>
          <li><strong>EF:</strong> Fração de ejeção</li>
          <li><strong>Ao:</strong> Aorta</li>
          <li><strong>LA:</strong> Átrio esquerdo</li>
          <li><strong>LA/Ao:</strong> Razão átrio/aorta</li>
        </ul>
      </div>
    </div>
  );
}
