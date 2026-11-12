import { Building2, DollarSign, Gauge, Landmark, Receipt, Route, TrendingUp, Wallet } from "lucide-react";

import AlertasList from "../AlertasList";
import MetricCard from "../MetricCard";
import { formatarMoeda, formatarNumero } from "../../formatters";
import {
  mediaTicketPeriodo,
  ordenarComparativoMensal,
  somarKmPeriodo,
  totalContasPendentes,
} from "../../services/relatoriosViewModel";
import { FinanceiroContextoResponse, RelatorioControleResponse } from "../../types";

interface RelatoriosVisaoGeralViewProps {
  relatorio: RelatorioControleResponse;
  financeiroContexto: FinanceiroContextoResponse | null;
}

export default function RelatoriosVisaoGeralView({
  relatorio,
  financeiroContexto,
}: RelatoriosVisaoGeralViewProps) {
  const faturamentoPeriodo = relatorio.financeiro.periodo.valor_total_servicos;
  const despesasPeriodo = relatorio.financeiro.periodo.saidas_pagas;
  const taxasPagamentoPeriodo = relatorio.financeiro.periodo.taxas_pagamento || 0;
  const creditosGeradosPeriodo = relatorio.financeiro.periodo.creditos_gerados || 0;
  const lucroLiquido =
    financeiroContexto?.dre?.lucro_liquido ?? faturamentoPeriodo - despesasPeriodo;
  const contasReceberPendentes = totalContasPendentes(financeiroContexto?.contas_receber, [
    "Pendente",
    "Atrasado",
  ]);
  const pendenciasOs = relatorio.insights_avancados.pendencias_recebimento?.valor_total_pendente || 0;
  const contasReceberConsolidado = contasReceberPendentes + pendenciasOs;
  const saldoCaixa = relatorio.financeiro.periodo.saldo;
  const ticketMedio = mediaTicketPeriodo(relatorio);
  const kmPeriodo = somarKmPeriodo(relatorio);
  const retornoPorKm = relatorio.indicadores_extras.retorno_por_km_mes_referencia;
  const comparativo = ordenarComparativoMensal(financeiroContexto?.comparativo_mensal?.items);
  const maxComparativo = Math.max(
    1,
    ...comparativo.map((item) => Math.max(item.entradas || 0, item.saidas || 0))
  );
  const pendenciasRecebimento = relatorio.insights_avancados.pendencias_recebimento;
  const pendenciasItens = pendenciasRecebimento?.itens || [];
  const totalPendenciasRecebimento = pendenciasRecebimento?.valor_total_pendente || 0;
  const dataCortePendencias =
    pendenciasRecebimento?.data_corte || relatorio.periodo.data_referencia;
  const rankingResumo = relatorio.rentabilidade.ranking_clinicas.slice(0, 5);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          titulo="Faturamento do periodo"
          valor={formatarMoeda(faturamentoPeriodo)}
          descricao={`${relatorio.financeiro.periodo.quantidade_servicos} servicos realizados`}
          icon={DollarSign}
          iconColorClass="text-green-600"
        />
        <MetricCard
          titulo="Despesas do periodo"
          valor={formatarMoeda(despesasPeriodo)}
          descricao={`Taxas de pagamento: ${formatarMoeda(taxasPagamentoPeriodo)}`}
          icon={Receipt}
          iconColorClass="text-red-600"
          emphasis="negative"
        />
        <MetricCard
          titulo="Creditos gerados"
          valor={formatarMoeda(creditosGeradosPeriodo)}
          icon={Landmark}
          iconColorClass="text-cyan-600"
        />
        <MetricCard
          titulo="Lucro liquido"
          valor={formatarMoeda(lucroLiquido)}
          icon={TrendingUp}
          iconColorClass="text-emerald-600"
          emphasis={lucroLiquido >= 0 ? "positive" : "negative"}
        />
        <MetricCard
          titulo="Contas a receber"
          valor={formatarMoeda(contasReceberConsolidado)}
          descricao={`Contas: ${formatarMoeda(contasReceberPendentes)} | OS pendentes: ${formatarMoeda(pendenciasOs)}`}
          icon={Landmark}
          iconColorClass="text-amber-600"
        />
        <MetricCard
          titulo="Saldo em caixa"
          valor={formatarMoeda(saldoCaixa)}
          icon={Wallet}
          iconColorClass="text-blue-600"
          emphasis={saldoCaixa >= 0 ? "positive" : "negative"}
        />
        <MetricCard
          titulo="Ticket medio"
          valor={formatarMoeda(ticketMedio)}
          icon={Gauge}
          iconColorClass="text-indigo-600"
        />
        <MetricCard
          titulo="KM rodado no periodo"
          valor={`${formatarNumero(kmPeriodo, 2)} km`}
          icon={Route}
          iconColorClass="text-sky-600"
        />
        <MetricCard
          titulo="Retorno por km"
          valor={retornoPorKm !== null ? formatarMoeda(retornoPorKm) : "N/D"}
          icon={TrendingUp}
          iconColorClass="text-emerald-600"
        />
      </div>

      <AlertasList alertas={relatorio.alertas_operacionais} />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl p-4">
          <h2 className="font-semibold text-gray-900 mb-3">Evolucao mensal</h2>
          {comparativo.length === 0 ? (
            <p className="text-sm text-gray-500">Sem historico mensal suficiente.</p>
          ) : (
            <div>
              <div className="h-48 flex items-end gap-2">
                {comparativo.map((item) => (
                  <div key={`${item.mes}-${item.ano}`} className="flex-1 flex flex-col items-center gap-1">
                    <div className="w-full flex gap-1 items-end h-40">
                      <div
                        className="flex-1 bg-green-500 rounded-t"
                        style={{ height: `${(item.entradas / maxComparativo) * 100}%` }}
                        title={`Entradas ${formatarMoeda(item.entradas)}`}
                      />
                      <div
                        className="flex-1 bg-red-500 rounded-t"
                        style={{ height: `${(item.saidas / maxComparativo) * 100}%` }}
                        title={`Saidas ${formatarMoeda(item.saidas)}`}
                      />
                    </div>
                    <span className="text-[11px] text-gray-500">
                      {item.mes}/{String(item.ano).slice(-2)}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex gap-4 mt-2 text-xs text-gray-600">
                <span className="inline-flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-green-500" />
                  Entradas
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-red-500" />
                  Saidas
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="bg-white border rounded-xl p-4">
          <h2 className="font-semibold text-gray-900 mb-3">Pendencias de recebimento por clinica</h2>
          <div className="space-y-2 text-sm">
            <p className="text-gray-600">
              Base de corte: ate {dataCortePendencias}
            </p>
            <p className="text-gray-900 font-semibold">
              Total pendente em OS: {formatarMoeda(totalPendenciasRecebimento)}
            </p>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-3 py-2">Clinica</th>
                  <th className="text-right px-3 py-2">OS pendentes</th>
                  <th className="text-right px-3 py-2">Valor previsto</th>
                </tr>
              </thead>
              <tbody>
                {pendenciasItens.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-3 py-5 text-center text-gray-500">
                      Nenhuma OS pendente ate a data de corte.
                    </td>
                  </tr>
                ) : (
                  pendenciasItens.map((item) => (
                    <tr key={item.clinica_id} className="border-t">
                      <td className="px-3 py-2">{item.clinica_nome}</td>
                      <td className="px-3 py-2 text-right">{item.ordens_pendentes}</td>
                      <td className="px-3 py-2 text-right">{formatarMoeda(item.valor_pendente)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="bg-white border rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Building2 className="w-4 h-4 text-indigo-600" />
          <h2 className="font-semibold text-gray-900">Ranking resumido de clinicas</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-3 py-2">Clinica</th>
                <th className="text-right px-3 py-2">Indice</th>
                <th className="text-right px-3 py-2">R$/km</th>
                <th className="text-right px-3 py-2">Taxa realizacao</th>
              </tr>
            </thead>
            <tbody>
              {rankingResumo.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-center text-gray-500 px-3 py-5">
                    Sem dados de rentabilidade no periodo.
                  </td>
                </tr>
              ) : (
                rankingResumo.map((item) => (
                  <tr key={item.clinica_id} className="border-t">
                    <td className="px-3 py-2">{item.clinica_nome}</td>
                    <td className="px-3 py-2 text-right">{formatarNumero(item.indice_rentabilidade, 2)}</td>
                    <td className="px-3 py-2 text-right">
                      {item.retorno_por_km !== null ? formatarMoeda(item.retorno_por_km) : "N/D"}
                    </td>
                    <td className="px-3 py-2 text-right">{formatarNumero(item.taxa_realizacao_percent, 2)}%</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-white border rounded-xl p-4">
        <h2 className="font-semibold text-gray-900 mb-3">Sugestoes de novos relatorios</h2>
        <div className="space-y-2">
          {relatorio.sugestoes_relatorios.map((item) => (
            <div key={item.codigo} className="rounded-lg border bg-gray-50 px-3 py-2">
              <p className="text-sm font-medium text-gray-900">{item.titulo}</p>
              <p className="text-xs text-gray-600">{item.descricao}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
