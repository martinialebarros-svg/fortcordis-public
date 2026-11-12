import { RefreshCw, SlidersHorizontal } from "lucide-react";

import { PERFIS_DESLOCAMENTO } from "../constants";
import { ClinicaOption, PerfilDeslocamento, ProfissionalOption, ServicoOption } from "../types";

interface RelatoriosFiltrosGlobaisProps {
  periodoInicio: string;
  setPeriodoInicio: (value: string) => void;
  periodoFim: string;
  setPeriodoFim: (value: string) => void;
  dataReferencia: string;
  setDataReferencia: (value: string) => void;
  perfilDeslocamento: PerfilDeslocamento;
  setPerfilDeslocamento: (value: PerfilDeslocamento) => void;
  clinicaBaseId: string;
  setClinicaBaseId: (value: string) => void;
  clinicaId: string;
  setClinicaId: (value: string) => void;
  servicoId: string;
  setServicoId: (value: string) => void;
  profissionalId: string;
  setProfissionalId: (value: string) => void;
  regiao: string;
  setRegiao: (value: string) => void;
  clinicas: ClinicaOption[];
  servicos: ServicoOption[];
  profissionais: ProfissionalOption[];
  regioes: string[];
  loading: boolean;
  onAtualizar: () => void;
}

export default function RelatoriosFiltrosGlobais({
  periodoInicio,
  setPeriodoInicio,
  periodoFim,
  setPeriodoFim,
  dataReferencia,
  setDataReferencia,
  perfilDeslocamento,
  setPerfilDeslocamento,
  clinicaBaseId,
  setClinicaBaseId,
  clinicaId,
  setClinicaId,
  servicoId,
  setServicoId,
  profissionalId,
  setProfissionalId,
  regiao,
  setRegiao,
  clinicas,
  servicos,
  profissionais,
  regioes,
  loading,
  onAtualizar,
}: RelatoriosFiltrosGlobaisProps) {
  return (
    <div className="fc-reports-filters">
      <div className="fc-reports-panel-title"><SlidersHorizontal className="h-5 w-5" /><div><span>Período e escopo</span><h2>Filtros globais</h2></div></div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
        <div>
          <label className="block text-xs text-gray-600 mb-1">Data inicial</label>
          <input
            type="date"
            value={periodoInicio}
            onChange={(e) => setPeriodoInicio(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Data final</label>
          <input
            type="date"
            value={periodoFim}
            onChange={(e) => setPeriodoFim(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Data de referência</label>
          <input
            type="date"
            value={dataReferencia}
            onChange={(e) => setDataReferencia(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Perfil de rota</label>
          <select
            value={perfilDeslocamento}
            onChange={(e) => setPerfilDeslocamento(e.target.value as PerfilDeslocamento)}
            className="w-full px-3 py-2 border rounded-lg"
          >
            {PERFIS_DESLOCAMENTO.map((perfil) => (
              <option key={perfil} value={perfil}>
                {perfil}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Clínica base</label>
          <select
            value={clinicaBaseId}
            onChange={(e) => setClinicaBaseId(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          >
            <option value="">Seleção automática</option>
            {clinicas.map((clinica) => (
              <option key={clinica.id} value={String(clinica.id)}>
                {clinica.nome}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Clínica</label>
          <select
            value={clinicaId}
            onChange={(e) => setClinicaId(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          >
            <option value="">Todas</option>
            {clinicas.map((clinica) => (
              <option key={clinica.id} value={String(clinica.id)}>
                {clinica.nome}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Serviço</label>
          <select
            value={servicoId}
            onChange={(e) => setServicoId(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          >
            <option value="">Todos</option>
            {servicos.map((servico) => (
              <option key={servico.id} value={String(servico.id)}>
                {servico.nome}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Profissional</label>
          <select
            value={profissionalId}
            onChange={(e) => setProfissionalId(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          >
            <option value="">Todos</option>
            {profissionais.map((profissional) => (
              <option key={profissional.id} value={String(profissional.id)}>
                {profissional.nome}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-600 mb-1">Região</label>
          <select
            value={regiao}
            onChange={(e) => setRegiao(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg"
          >
            <option value="">Todas</option>
            {regioes.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-end">
          <button
            type="button"
            onClick={onAtualizar}
            disabled={loading}
            className="fc-reports-primary"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            Atualizar
          </button>
        </div>
      </div>
    </div>
  );
}
