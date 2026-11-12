import { Activity, CalendarClock, Clock3, Stethoscope, UserRoundCheck, Users } from "lucide-react";

import MetricCard from "../MetricCard";
import { formatarNumero, formatarPercentual } from "../../formatters";
import { RelatorioControleResponse } from "../../types";

interface RelatoriosOperacaoViewProps {
  relatorio: RelatorioControleResponse;
}

export default function RelatoriosOperacaoView({ relatorio }: RelatoriosOperacaoViewProps) {
  const antecedencia = relatorio.insights_avancados.antecedencia_agendamento;
  const pontualidade = relatorio.insights_avancados.pontualidade_atrasos;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          titulo="Taxa de realizacao"
          valor={formatarPercentual(relatorio.producao.taxa_realizacao_percent)}
          icon={UserRoundCheck}
          iconColorClass="text-emerald-600"
        />
        <MetricCard
          titulo="Taxa de cancelamento"
          valor={formatarPercentual(relatorio.producao.taxa_cancelamento_percent)}
          icon={Activity}
          iconColorClass="text-red-600"
          emphasis="negative"
        />
        <MetricCard
          titulo="Taxa de falta"
          valor={formatarPercentual(relatorio.producao.taxa_falta_percent)}
          icon={CalendarClock}
          iconColorClass="text-amber-600"
        />
        <MetricCard
          titulo="Antecedencia media"
          valor={
            antecedencia.media_dias !== null ? `${formatarNumero(antecedencia.media_dias, 2)} dias` : "N/D"
          }
          descricao={`Mediana ${antecedencia.mediana_dias !== null ? formatarNumero(antecedencia.mediana_dias, 2) : "N/D"} dias`}
          icon={Clock3}
          iconColorClass="text-blue-600"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <Users className="w-4 h-4 text-emerald-600" />
            <h2 className="font-semibold text-gray-900">Clinicas que mais agendam</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Clinica</th>
                  <th className="text-right px-4 py-2">Ags</th>
                  <th className="text-right px-4 py-2">Real.</th>
                  <th className="text-right px-4 py-2">Cancel.</th>
                  <th className="text-right px-4 py-2">Taxa</th>
                </tr>
              </thead>
              <tbody>
                {relatorio.producao.clinicas_mais_agendam.map((item) => (
                  <tr key={item.clinica_id} className="border-t">
                    <td className="px-4 py-2">{item.clinica_nome}</td>
                    <td className="px-4 py-2 text-right">{item.agendamentos}</td>
                    <td className="px-4 py-2 text-right">{item.realizados}</td>
                    <td className="px-4 py-2 text-right">{item.cancelados}</td>
                    <td className="px-4 py-2 text-right">
                      {formatarPercentual(item.taxa_realizacao_percent)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <Stethoscope className="w-4 h-4 text-blue-600" />
            <h2 className="font-semibold text-gray-900">Servicos mais solicitados</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Servico</th>
                  <th className="text-right px-4 py-2">Ags</th>
                  <th className="text-right px-4 py-2">Real.</th>
                  <th className="text-right px-4 py-2">Taxa</th>
                </tr>
              </thead>
              <tbody>
                {relatorio.producao.servicos_mais_solicitados.map((item) => (
                  <tr key={item.servico_id} className="border-t">
                    <td className="px-4 py-2">{item.servico_nome}</td>
                    <td className="px-4 py-2 text-right">{item.agendamentos}</td>
                    <td className="px-4 py-2 text-right">{item.realizados}</td>
                    <td className="px-4 py-2 text-right">
                      {formatarPercentual(item.taxa_realizacao_percent)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Ociosidade por janela de horario</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Janela</th>
                  <th className="text-right px-4 py-2">Ags</th>
                  <th className="text-right px-4 py-2">Media/dia</th>
                  <th className="text-right px-4 py-2">Ociosidade</th>
                </tr>
              </thead>
              <tbody>
                {relatorio.insights_avancados.ociosidade_janela_horario.slice(0, 8).map((item) => (
                  <tr key={`${item.hora_inicio}-${item.hora_fim}`} className="border-t">
                    <td className="px-4 py-2">
                      {item.hora_inicio} - {item.hora_fim}
                    </td>
                    <td className="px-4 py-2 text-right">{item.agendamentos_total}</td>
                    <td className="px-4 py-2 text-right">{formatarNumero(item.media_agendamentos_dia, 2)}</td>
                    <td className="px-4 py-2 text-right">{formatarPercentual(item.indice_ociosidade_percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Pontualidade e atrasos</h2>
          </div>
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm">
              <div className="rounded-lg border bg-gray-50 px-3 py-2">
                <p className="text-gray-600">Transicoes</p>
                <p className="font-semibold text-gray-900">{pontualidade.total_transicoes}</p>
              </div>
              <div className="rounded-lg border bg-gray-50 px-3 py-2">
                <p className="text-gray-600">Com risco</p>
                <p className="font-semibold text-gray-900">{pontualidade.transicoes_com_risco}</p>
              </div>
              <div className="rounded-lg border bg-gray-50 px-3 py-2">
                <p className="text-gray-600">Taxa de risco</p>
                <p className="font-semibold text-gray-900">{formatarPercentual(pontualidade.taxa_risco_percent)}</p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th className="text-left px-3 py-2">Data</th>
                    <th className="text-left px-3 py-2">Rota</th>
                    <th className="text-right px-3 py-2">Deficit (min)</th>
                  </tr>
                </thead>
                <tbody>
                  {pontualidade.transicoes_criticas.slice(0, 6).map((item, idx) => (
                    <tr key={`${item.data}-${item.origem_clinica_id}-${item.destino_clinica_id}-${idx}`} className="border-t">
                      <td className="px-3 py-2">{item.data}</td>
                      <td className="px-3 py-2">
                        {item.origem_nome} -&gt; {item.destino_nome}
                      </td>
                      <td className="px-3 py-2 text-right">{item.deficit_min}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h2 className="font-semibold text-gray-900">Mix de servicos por clinica</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-2">Clinica</th>
                <th className="text-left px-4 py-2">Servico principal</th>
                <th className="text-right px-4 py-2">Participacao</th>
                <th className="text-right px-4 py-2">Servicos distintos</th>
              </tr>
            </thead>
            <tbody>
              {relatorio.insights_avancados.mix_servicos_por_clinica.slice(0, 10).map((item) => (
                <tr key={item.clinica_id} className="border-t">
                  <td className="px-4 py-2">{item.clinica_nome}</td>
                  <td className="px-4 py-2">{item.servico_principal_nome}</td>
                  <td className="px-4 py-2 text-right">
                    {formatarPercentual(item.servico_principal_participacao_percent)}
                  </td>
                  <td className="px-4 py-2 text-right">{item.servicos_distintos}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

