import { Building2, Clock3, Compass, MapPinned, Route, Timer } from "lucide-react";

import MetricCard from "../MetricCard";
import { formatarMoeda, formatarNumero } from "../../formatters";
import { analisarPorRegiao, somarDuracaoPeriodoMin, somarKmPeriodo } from "../../services/relatoriosViewModel";
import { ClinicaOption, RelatorioControleResponse } from "../../types";

interface RelatoriosLogisticaViewProps {
  relatorio: RelatorioControleResponse;
  clinicas: ClinicaOption[];
}

export default function RelatoriosLogisticaView({
  relatorio,
  clinicas,
}: RelatoriosLogisticaViewProps) {
  const kmTotalPeriodo = somarKmPeriodo(relatorio);
  const duracaoTotalMin = somarDuracaoPeriodoMin(relatorio);
  const diasComRota = relatorio.logistica.km_por_mes.reduce(
    (acc, item) => acc + Number(item.dias_com_rota || 0),
    0
  );
  const retornoKm = relatorio.indicadores_extras.retorno_por_km_mes_referencia;
  const analiseRegiao = analisarPorRegiao(relatorio, clinicas).slice(0, 8);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          titulo="KM total no periodo"
          valor={`${formatarNumero(kmTotalPeriodo, 2)} km`}
          icon={Route}
          iconColorClass="text-blue-600"
        />
        <MetricCard
          titulo="Dias com rota"
          valor={formatarNumero(diasComRota, 0)}
          icon={MapPinned}
          iconColorClass="text-indigo-600"
        />
        <MetricCard
          titulo="Tempo de deslocamento"
          valor={`${formatarNumero(duracaoTotalMin / 60, 2)} h`}
          descricao={`${formatarNumero(duracaoTotalMin, 0)} minutos acumulados`}
          icon={Timer}
          iconColorClass="text-amber-600"
        />
        <MetricCard
          titulo="Retorno por km"
          valor={retornoKm !== null ? formatarMoeda(retornoKm) : "N/D"}
          icon={Compass}
          iconColorClass="text-emerald-600"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <Clock3 className="w-4 h-4 text-blue-600" />
            <h2 className="font-semibold text-gray-900">KM por mes</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Mes</th>
                  <th className="text-right px-4 py-2">KM</th>
                  <th className="text-right px-4 py-2">Trechos</th>
                  <th className="text-right px-4 py-2">Dias c/ rota</th>
                  <th className="text-right px-4 py-2">Duracao (h)</th>
                </tr>
              </thead>
              <tbody>
                {relatorio.logistica.km_por_mes.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                      Sem dados no periodo.
                    </td>
                  </tr>
                ) : (
                  relatorio.logistica.km_por_mes.map((item) => (
                    <tr key={item.mes} className="border-t">
                      <td className="px-4 py-2">{item.mes}</td>
                      <td className="px-4 py-2 text-right">{formatarNumero(item.km_total, 2)}</td>
                      <td className="px-4 py-2 text-right">{item.trechos}</td>
                      <td className="px-4 py-2 text-right">{item.dias_com_rota}</td>
                      <td className="px-4 py-2 text-right">{formatarNumero(item.duracao_total_min / 60, 2)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <Route className="w-4 h-4 text-indigo-600" />
            <h2 className="font-semibold text-gray-900">Rotas mais longas</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Rota</th>
                  <th className="text-right px-4 py-2">KM</th>
                  <th className="text-right px-4 py-2">Min</th>
                </tr>
              </thead>
              <tbody>
                {relatorio.logistica.rotas_mais_longas.map((item) => (
                  <tr key={`${item.origem_clinica_id}-${item.destino_clinica_id}`} className="border-t">
                    <td className="px-4 py-2">
                      {item.origem_nome} -&gt; {item.destino_nome}
                    </td>
                    <td className="px-4 py-2 text-right">{formatarNumero(item.distancia_km, 2)}</td>
                    <td className="px-4 py-2 text-right">{item.duracao_min}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <Building2 className="w-4 h-4 text-orange-600" />
            <h2 className="font-semibold text-gray-900">Clinicas mais distantes da base</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Clinica</th>
                  <th className="text-right px-4 py-2">KM</th>
                  <th className="text-right px-4 py-2">Min</th>
                </tr>
              </thead>
              <tbody>
                {relatorio.logistica.clinicas_mais_distantes_base.map((item) => (
                  <tr key={item.clinica_id} className="border-t">
                    <td className="px-4 py-2">{item.clinica_nome}</td>
                    <td className="px-4 py-2 text-right">{formatarNumero(item.distancia_km, 2)}</td>
                    <td className="px-4 py-2 text-right">{item.duracao_min}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Analise por regiao</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Regiao</th>
                  <th className="text-right px-4 py-2">Clinicas</th>
                  <th className="text-right px-4 py-2">Agendamentos</th>
                  <th className="text-right px-4 py-2">Valor</th>
                </tr>
              </thead>
              <tbody>
                {analiseRegiao.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-gray-500">
                      Sem dados de regiao para os filtros atuais.
                    </td>
                  </tr>
                ) : (
                  analiseRegiao.map((item) => (
                    <tr key={item.regiao} className="border-t">
                      <td className="px-4 py-2">{item.regiao}</td>
                      <td className="px-4 py-2 text-right">{item.clinicas}</td>
                      <td className="px-4 py-2 text-right">{item.agendamentos}</td>
                      <td className="px-4 py-2 text-right">{formatarMoeda(item.valor_total)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

