import { BarChart3, Landmark, Receipt, Wallet } from "lucide-react";

import MetricCard from "../MetricCard";
import { formatarMoeda, formatarNumero, formatarPercentual } from "../../formatters";
import {
  calcularInadimplenciaPercent,
  montarComparativoCompetenciaCaixa,
  montarProjecaoFluxo30d,
  totalContasPendentes,
} from "../../services/relatoriosViewModel";
import { FinanceiroContextoResponse, RelatorioControleResponse } from "../../types";

interface RelatoriosFinanceiroViewProps {
  relatorio: RelatorioControleResponse;
  financeiroContexto: FinanceiroContextoResponse | null;
}

export default function RelatoriosFinanceiroView({
  relatorio,
  financeiroContexto,
}: RelatoriosFinanceiroViewProps) {
  const dre = financeiroContexto?.dre;
  const fluxo = financeiroContexto?.fluxo_caixa;
  const despesasCategoria = financeiroContexto?.despesas_por_categoria?.categorias || [];
  const contasReceber = financeiroContexto?.contas_receber?.items || [];
  const contasPagar = financeiroContexto?.contas_pagar?.items || [];
  const inadimplencia = calcularInadimplenciaPercent(financeiroContexto?.contas_receber || null);
  const comp = montarComparativoCompetenciaCaixa(relatorio);
  const projecao = montarProjecaoFluxo30d(
    financeiroContexto,
    relatorio.periodo.data_referencia
  );
  const aReceber = totalContasPendentes(financeiroContexto?.contas_receber, ["Pendente", "Atrasado"]);
  const pendenciasOs = relatorio.insights_avancados.pendencias_recebimento?.valor_total_pendente || 0;
  const aReceberConsolidado = aReceber + pendenciasOs;
  const aPagar = totalContasPendentes(financeiroContexto?.contas_pagar, ["Pendente", "Atrasado"]);
  const taxasPagamentoPeriodo = relatorio.financeiro.periodo.taxas_pagamento || 0;
  const creditosGeradosPeriodo = relatorio.financeiro.periodo.creditos_gerados || 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          titulo="DRE - lucro liquido"
          valor={formatarMoeda(dre?.lucro_liquido ?? relatorio.financeiro.periodo.saldo)}
          descricao={
            dre ? `Margem liquida ${formatarPercentual(dre.margem_liquida)}` : "Sem DRE detalhada para o periodo."
          }
          icon={BarChart3}
          iconColorClass="text-indigo-600"
          emphasis={(dre?.lucro_liquido ?? relatorio.financeiro.periodo.saldo) >= 0 ? "positive" : "negative"}
        />
        <MetricCard
          titulo="Fluxo de caixa realizado"
          valor={formatarMoeda(fluxo?.saldo_final ?? relatorio.financeiro.periodo.saldo)}
          descricao={fluxo ? `${fluxo.items.length} dias analisados` : "Usando saldo consolidado"}
          icon={Wallet}
          iconColorClass="text-green-600"
        />
        <MetricCard
          titulo="Contas a receber"
          valor={formatarMoeda(aReceberConsolidado)}
          descricao={`Contas: ${formatarMoeda(aReceber)} | OS pendentes: ${formatarMoeda(pendenciasOs)}`}
          icon={Landmark}
          iconColorClass="text-blue-600"
        />
        <MetricCard
          titulo="Contas a pagar"
          valor={formatarMoeda(aPagar)}
          icon={Receipt}
          iconColorClass="text-red-600"
          emphasis="negative"
        />
        <MetricCard
          titulo="Taxas de pagamento"
          valor={formatarMoeda(taxasPagamentoPeriodo)}
          descricao="Desconto operacional por meio de pagamento"
          icon={Wallet}
          iconColorClass="text-amber-600"
          emphasis="negative"
        />
        <MetricCard
          titulo="Creditos gerados"
          valor={formatarMoeda(creditosGeradosPeriodo)}
          descricao="Valor excedente convertido em credito"
          icon={Landmark}
          iconColorClass="text-cyan-600"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl p-4">
          <h2 className="font-semibold text-gray-900 mb-3">DRE gerencial</h2>
          {dre ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span>Receita liquida</span>
                <strong>{formatarMoeda(dre.receita_liquida)}</strong>
              </div>
              <div className="flex justify-between">
                <span>Total de custos</span>
                <strong>{formatarMoeda(dre.total_custos)}</strong>
              </div>
              <div className="flex justify-between">
                <span>Total despesas operacionais</span>
                <strong>{formatarMoeda(dre.total_despesas_operacionais)}</strong>
              </div>
              <div className="flex justify-between">
                <span>Outras despesas</span>
                <strong>{formatarMoeda(dre.total_outras_despesas)}</strong>
              </div>
              <div className="border-t pt-2 flex justify-between text-base">
                <span className="font-semibold">Lucro liquido</span>
                <strong className={dre.lucro_liquido >= 0 ? "text-green-700" : "text-red-700"}>
                  {formatarMoeda(dre.lucro_liquido)}
                </strong>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">Nao foi possivel carregar DRE para este periodo.</p>
          )}
        </div>

        <div className="bg-white border rounded-xl p-4">
          <h2 className="font-semibold text-gray-900 mb-3">Fluxo de caixa projetado (30 dias)</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span>Entradas previstas</span>
              <strong>{formatarMoeda(projecao.entradas_previstas)}</strong>
            </div>
            <div className="flex justify-between">
              <span>Saidas previstas</span>
              <strong>{formatarMoeda(projecao.saidas_previstas)}</strong>
            </div>
            <div className="border-t pt-2 flex justify-between text-base">
              <span className="font-semibold">Saldo projetado</span>
              <strong className={projecao.saldo_previsto >= 0 ? "text-green-700" : "text-red-700"}>
                {formatarMoeda(projecao.saldo_previsto)}
              </strong>
            </div>
            <div className="pt-2 text-xs text-gray-500">
              Inadimplencia atual: <strong>{formatarPercentual(inadimplencia)}</strong>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Despesas por categoria</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Categoria</th>
                  <th className="text-right px-4 py-2">Total</th>
                  <th className="text-right px-4 py-2">%</th>
                </tr>
              </thead>
              <tbody>
                {despesasCategoria.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                      Sem dados de despesas por categoria.
                    </td>
                  </tr>
                ) : (
                  despesasCategoria.slice(0, 10).map((item) => (
                    <tr key={item.categoria} className="border-t">
                      <td className="px-4 py-2">{item.categoria}</td>
                      <td className="px-4 py-2 text-right">{formatarMoeda(item.total)}</td>
                      <td className="px-4 py-2 text-right">{formatarNumero(item.percentual, 2)}%</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Competencia x caixa</h2>
          </div>
          <div className="p-4 space-y-3 text-sm">
            <div className="flex justify-between">
              <span>Receita por competencia</span>
              <strong>{formatarMoeda(comp.receita_competencia)}</strong>
            </div>
            <div className="flex justify-between">
              <span>Receita por caixa</span>
              <strong>{formatarMoeda(comp.receita_caixa)}</strong>
            </div>
            <div className="flex justify-between border-t pt-2">
              <span>Gap caixa x competencia</span>
              <strong className={comp.gap_percent >= 0 ? "text-green-700" : "text-red-700"}>
                {formatarNumero(comp.gap_percent, 2)}%
              </strong>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Contas a receber</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Descricao</th>
                  <th className="text-right px-4 py-2">Valor</th>
                  <th className="text-right px-4 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {contasReceber.slice(0, 10).map((item) => (
                  <tr key={item.id} className="border-t">
                    <td className="px-4 py-2">{item.descricao || `Conta #${item.id}`}</td>
                    <td className="px-4 py-2 text-right">{formatarMoeda(item.valor)}</td>
                    <td className="px-4 py-2 text-right">{item.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="font-semibold text-gray-900">Contas a pagar</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-2">Descricao</th>
                  <th className="text-right px-4 py-2">Valor</th>
                  <th className="text-right px-4 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {contasPagar.slice(0, 10).map((item) => (
                  <tr key={item.id} className="border-t">
                    <td className="px-4 py-2">{item.descricao || `Conta #${item.id}`}</td>
                    <td className="px-4 py-2 text-right">{formatarMoeda(item.valor)}</td>
                    <td className="px-4 py-2 text-right">{item.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
