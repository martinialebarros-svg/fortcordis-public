import { BarChart3, Gauge, LineChart, Target } from "lucide-react";

import MetricCard from "../MetricCard";
import { formatarMoeda, formatarNumero, formatarPercentual } from "../../formatters";
import { montarRentabilidadeResumo } from "../../services/relatoriosViewModel";
import { RelatorioControleResponse } from "../../types";

interface RelatoriosRentabilidadeViewProps {
  relatorio: RelatorioControleResponse;
}

export default function RelatoriosRentabilidadeView({
  relatorio,
}: RelatoriosRentabilidadeViewProps) {
  const resumo = montarRentabilidadeResumo(relatorio);
  const melhorClinica = resumo.melhores_clinicas[0];
  const metodologia = relatorio.rentabilidade.metodologia || "proxy_operacional";
  const isReal = metodologia === "real";
  const pendencias = relatorio.rentabilidade.pendencias_para_real || [];
  const dadosNecessarios = relatorio.rentabilidade.dados_necessarios_para_real || [];
  const cobertura = relatorio.rentabilidade.cobertura_real;
  const custosFrota = relatorio.rentabilidade.custos_frota;

  const rentabilidadeServicoProxy = relatorio.producao.servicos_mais_solicitados
    .map((item) => ({
      ...item,
      indice_proxy: (item.agendamentos * item.taxa_realizacao_percent) / 100,
    }))
    .sort((a, b) => b.indice_proxy - a.indice_proxy)
    .slice(0, 10);

  return (
    <div className="space-y-4">
      <div
        className={`border rounded-xl p-4 ${
          isReal ? "bg-green-50 border-green-200" : "bg-amber-50 border-amber-200"
        }`}
      >
        <p className="text-sm font-semibold text-gray-900">
          Metodologia ativa: {isReal ? "Rentabilidade real" : "Proxy operacional"}
        </p>
        <p className="text-sm text-gray-700 mt-1">
          {relatorio.rentabilidade.mensagem_metodologia ||
            (isReal
              ? "Calculo real aplicado com base em receita e despesas por clinica."
              : "Sem dados completos para calculo real. O sistema aplicou proxy operacional.")}
        </p>

        {cobertura ? (
          <p className="text-xs text-gray-600 mt-2">
            Cobertura de despesas por clinica: {formatarNumero(cobertura.cobertura_percent, 2)}% (
            {cobertura.clinicas_com_despesa_vinculada}/{cobertura.clinicas_com_receita} clinicas com receita).
          </p>
        ) : null}
        {custosFrota ? (
          <p className="text-xs text-gray-600 mt-1">
            Custos de frota no periodo: {formatarMoeda(custosFrota.total_periodo)} | Nao alocados:{" "}
            {formatarMoeda(custosFrota.nao_alocados)}
          </p>
        ) : null}

        {!isReal ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 mt-3">
            <div className="rounded-lg border border-amber-200 bg-white px-3 py-2">
              <p className="text-xs font-semibold text-gray-900 mb-1">Pendencias atuais</p>
              <ul className="text-xs text-gray-700 list-disc pl-4 space-y-1">
                {pendencias.length === 0 ? (
                  <li>Sem pendencias detalhadas no payload.</li>
                ) : (
                  pendencias.map((item, idx) => <li key={`pendencia-${idx}`}>{item}</li>)
                )}
              </ul>
            </div>
            <div className="rounded-lg border border-blue-200 bg-white px-3 py-2">
              <p className="text-xs font-semibold text-gray-900 mb-1">Dados necessarios para rentabilidade real</p>
              <ul className="text-xs text-gray-700 list-disc pl-4 space-y-1">
                {dadosNecessarios.length === 0 ? (
                  <li>Receita por clinica, despesas por clinica e regra de rateio.</li>
                ) : (
                  dadosNecessarios.map((item, idx) => <li key={`necessario-${idx}`}>{item}</li>)
                )}
              </ul>
            </div>
          </div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          titulo="Retorno medio por km"
          valor={
            resumo.retorno_medio_por_km !== null ? formatarMoeda(resumo.retorno_medio_por_km) : "N/D"
          }
          icon={Gauge}
          iconColorClass="text-emerald-600"
        />
        <MetricCard
          titulo="Ticket medio por clinica"
          valor={formatarMoeda(resumo.ticket_medio_top_clinicas)}
          icon={LineChart}
          iconColorClass="text-indigo-600"
        />
        <MetricCard
          titulo="Ponto de equilibrio"
          valor={`${formatarNumero(resumo.ponto_equilibrio_servicos, 1)} servicos`}
          descricao="Estimado com base em despesas do periodo e ticket medio."
          icon={Target}
          iconColorClass="text-amber-600"
        />
        <MetricCard
          titulo="Clinica lider em retorno"
          valor={melhorClinica ? melhorClinica.clinica_nome : "N/D"}
          descricao={
            melhorClinica
              ? `Indice ${formatarNumero(melhorClinica.indice_rentabilidade, 2)}`
              : "Sem dados no periodo"
          }
          icon={BarChart3}
          iconColorClass="text-blue-600"
        />
      </div>

      <div className="bg-white border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h2 className="font-semibold text-gray-900">
            Rentabilidade por clinica ({isReal ? "real" : "proxy operacional"})
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-2">Clinica</th>
                <th className="text-right px-4 py-2">Indice</th>
                <th className="text-right px-4 py-2">R$/km</th>
                <th className="text-right px-4 py-2">Despesa</th>
                <th className="text-right px-4 py-2">Lucro</th>
                <th className="text-right px-4 py-2">Margem</th>
                <th className="text-right px-4 py-2">Valor total</th>
                <th className="text-right px-4 py-2">Taxa cancel.</th>
              </tr>
            </thead>
            <tbody>
              {resumo.melhores_clinicas.map((item) => (
                <tr key={item.clinica_id} className="border-t">
                  <td className="px-4 py-2">{item.clinica_nome}</td>
                  <td className="px-4 py-2 text-right">{formatarNumero(item.indice_rentabilidade, 2)}</td>
                  <td className="px-4 py-2 text-right">
                    {item.retorno_por_km !== null ? formatarMoeda(item.retorno_por_km) : "N/D"}
                  </td>
                  <td className="px-4 py-2 text-right">{formatarMoeda(item.despesa_total || 0)}</td>
                  <td className="px-4 py-2 text-right">{formatarMoeda(item.lucro_liquido || 0)}</td>
                  <td className="px-4 py-2 text-right">{formatarPercentual(item.margem_percent || 0)}</td>
                  <td className="px-4 py-2 text-right">{formatarMoeda(item.valor_total_servicos)}</td>
                  <td className="px-4 py-2 text-right">{formatarPercentual(item.taxa_cancelamento_percent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Ticket medio por clinica</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Clinica</th>
                  <th className="text-right px-4 py-2">Servicos</th>
                  <th className="text-right px-4 py-2">Ticket medio</th>
                </tr>
              </thead>
              <tbody>
                {relatorio.financeiro.clinicas_maior_faturamento.map((item) => (
                  <tr key={item.clinica_id} className="border-t">
                    <td className="px-4 py-2">{item.clinica_nome}</td>
                    <td className="px-4 py-2 text-right">{item.servicos}</td>
                    <td className="px-4 py-2 text-right">
                      {item.servicos > 0 ? formatarMoeda(item.valor_total / item.servicos) : "N/D"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Rentabilidade por servico (proxy operacional)</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Servico</th>
                  <th className="text-right px-4 py-2">Agendamentos</th>
                  <th className="text-right px-4 py-2">Taxa realizacao</th>
                  <th className="text-right px-4 py-2">Indice proxy</th>
                </tr>
              </thead>
              <tbody>
                {rentabilidadeServicoProxy.map((item) => (
                  <tr key={item.servico_id} className="border-t">
                    <td className="px-4 py-2">{item.servico_nome}</td>
                    <td className="px-4 py-2 text-right">{item.agendamentos}</td>
                    <td className="px-4 py-2 text-right">{formatarPercentual(item.taxa_realizacao_percent)}</td>
                    <td className="px-4 py-2 text-right">{formatarNumero(item.indice_proxy, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="bg-white border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h2 className="font-semibold text-gray-900">Margem por cliente (proxy operacional)</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-2">Clinica</th>
                <th className="text-right px-4 py-2">Taxa realizacao</th>
                <th className="text-right px-4 py-2">Cancelamento</th>
                <th className="text-right px-4 py-2">Faltas</th>
                <th className="text-right px-4 py-2">Margem proxy</th>
              </tr>
            </thead>
            <tbody>
              {resumo.melhores_clinicas.map((item) => {
                const margemProxy =
                  item.taxa_realizacao_percent - item.taxa_cancelamento_percent - item.taxa_falta_percent;
                return (
                  <tr key={`margem-${item.clinica_id}`} className="border-t">
                    <td className="px-4 py-2">{item.clinica_nome}</td>
                    <td className="px-4 py-2 text-right">{formatarPercentual(item.taxa_realizacao_percent)}</td>
                    <td className="px-4 py-2 text-right">{formatarPercentual(item.taxa_cancelamento_percent)}</td>
                    <td className="px-4 py-2 text-right">{formatarPercentual(item.taxa_falta_percent)}</td>
                    <td className="px-4 py-2 text-right">{formatarNumero(margemProxy, 2)} p.p.</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
