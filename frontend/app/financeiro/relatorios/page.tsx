"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { operationalTodayDateInput } from "@/lib/calendar-date";
import {
  ArrowDownCircle,
  ArrowUpCircle,
  BarChart3,
  CalendarDays,
  PieChart,
  RefreshCw,
  Scale,
  TrendingUp,
  WalletCards,
} from "lucide-react";

interface RelatorioCategoria {
  categoria: string;
  total: number;
  quantidade: number;
  percentual: number;
}

interface ComparativoMes {
  mes: string;
  ano: number;
  entradas: number;
  saidas: number;
  saldo: number;
  variacao_entrada?: number;
  variacao_saida?: number;
}

const ABAS_RELATORIO = [
  { id: "categorias", nome: "Por categoria", icon: PieChart },
  { id: "comparativo", nome: "Comparativo mensal", icon: TrendingUp },
  { id: "grafico", nome: "Evolução gráfica", icon: BarChart3 },
] as const;

type AbaRelatorio = (typeof ABAS_RELATORIO)[number]["id"];

export default function RelatoriosFinanceirosPage() {
  const [periodoInicio, setPeriodoInicio] = useState("");
  const [periodoFim, setPeriodoFim] = useState("");
  const [loading, setLoading] = useState(false);
  const [relatorioEntradas, setRelatorioEntradas] = useState<RelatorioCategoria[]>([]);
  const [relatorioSaidas, setRelatorioSaidas] = useState<RelatorioCategoria[]>([]);
  const [comparativo, setComparativo] = useState<ComparativoMes[]>([]);
  const [dadosGrafico, setDadosGrafico] = useState<any>(null);
  const [abaAtiva, setAbaAtiva] = useState<AbaRelatorio>("categorias");
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    
    // Definir período padrão (último mês)
    const hoje = operationalTodayDateInput();
    setPeriodoFim(hoje);
    setPeriodoInicio(`${hoje.slice(0, 7)}-01`);
  }, [router]);

  const carregarRelatorios = async () => {
    if (!periodoInicio || !periodoFim) return;
    
    try {
      setLoading(true);
      const [entradas, saidas, comparativoData, grafico] = await Promise.all([
        api.get(`/financeiro/relatorios/categorias?tipo=entrada&data_inicio=${periodoInicio}&data_fim=${periodoFim}`),
        api.get(`/financeiro/relatorios/categorias?tipo=saida&data_inicio=${periodoInicio}&data_fim=${periodoFim}`),
        api.get("/financeiro/relatorios/comparativo-mensal?meses=6"),
        api.get("/financeiro/relatorios/dados-grafico?tipo=mensal&meses=6"),
      ]);
      
      setRelatorioEntradas(entradas.data.categorias || []);
      setRelatorioSaidas(saidas.data.categorias || []);
      setComparativo(comparativoData.data.items || []);
      setDadosGrafico(grafico.data);
    } catch (error) {
      console.error("Erro ao carregar relatórios:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (periodoInicio && periodoFim) {
      carregarRelatorios();
    }
  }, [periodoInicio, periodoFim]);

  const formatarValor = (valor: number) => {
    return valor?.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) || 'R$ 0,00';
  };

  const getCategoriaNome = (categoria: string) => {
    const categorias: Record<string, string> = {
      consulta: "Consulta",
      exame: "Exame",
      cirurgia: "Cirurgia",
      medicamento: "Medicamento",
      banho_tosa: "Banho e Tosa",
      produto: "Produto",
      salario: "Salário",
      aluguel: "Aluguel",
      fornecedor: "Fornecedor",
      imposto: "Imposto",
      manutencao: "Manutenção",
      marketing: "Marketing",
      outros: "Outros",
    };
    return categorias[categoria] || categoria;
  };

  const resumo = useMemo(() => {
    const entradas = relatorioEntradas.reduce((total, item) => total + item.total, 0);
    const saidas = relatorioSaidas.reduce((total, item) => total + item.total, 0);
    const movimentacoes = [...relatorioEntradas, ...relatorioSaidas].reduce(
      (total, item) => total + item.quantidade,
      0,
    );

    return {
      entradas,
      saidas,
      saldo: entradas - saidas,
      movimentacoes,
    };
  }, [relatorioEntradas, relatorioSaidas]);

  const graficoDisponivel = Boolean(dadosGrafico?.labels?.length);

  return (
    <DashboardLayout>
      <div className="fc-finance-reports-page">
        <header className="fc-finance-reports-header">
          <div>
            <span className="fc-finance-reports-kicker">
              <BarChart3 className="h-4 w-4" />
              Inteligência financeira
            </span>
            <h1>Relatórios financeiros</h1>
            <p>Entradas, saídas e evolução mensal em uma leitura consolidada.</p>
          </div>
          <button
            type="button"
            onClick={carregarRelatorios}
            disabled={loading || !periodoInicio || !periodoFim}
            className="fc-finance-reports-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Atualizando..." : "Atualizar dados"}
          </button>
        </header>

        <section className="fc-finance-reports-metrics" aria-label="Resumo financeiro do período">
          <article className="fc-finance-reports-metric fc-finance-reports-metric-income">
            <ArrowUpCircle className="h-5 w-5" />
            <div><span>Entradas</span><strong>{formatarValor(resumo.entradas)}</strong><small>No período selecionado</small></div>
          </article>
          <article className="fc-finance-reports-metric fc-finance-reports-metric-expense">
            <ArrowDownCircle className="h-5 w-5" />
            <div><span>Saídas</span><strong>{formatarValor(resumo.saidas)}</strong><small>No período selecionado</small></div>
          </article>
          <article className="fc-finance-reports-metric fc-finance-reports-metric-balance">
            <Scale className="h-5 w-5" />
            <div><span>Saldo</span><strong>{formatarValor(resumo.saldo)}</strong><small>Balanço do período</small></div>
          </article>
          <article className="fc-finance-reports-metric fc-finance-reports-metric-volume">
            <WalletCards className="h-5 w-5" />
            <div><span>Movimentações</span><strong>{resumo.movimentacoes}</strong><small>Transações agrupadas</small></div>
          </article>
        </section>

        <section className="fc-finance-reports-filters">
          <div className="fc-finance-reports-filter-heading">
            <CalendarDays className="h-5 w-5" />
            <div><h2>Período de análise</h2><p>Defina o intervalo usado nos relatórios por categoria.</p></div>
          </div>
          <div className="fc-finance-reports-filter-controls">
            <div>
              <label htmlFor="relatorio-inicio">Data inicial</label>
              <input
                id="relatorio-inicio"
                type="date"
                value={periodoInicio}
                onChange={(e) => setPeriodoInicio(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="relatorio-fim">Data final</label>
              <input
                id="relatorio-fim"
                type="date"
                value={periodoFim}
                onChange={(e) => setPeriodoFim(e.target.value)}
              />
            </div>
            <button
              type="button"
              onClick={carregarRelatorios}
              disabled={loading || !periodoInicio || !periodoFim}
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              {loading ? "Carregando..." : "Aplicar período"}
            </button>
          </div>
        </section>

        <div className="fc-finance-reports-tabs" role="tablist" aria-label="Visões dos relatórios financeiros">
          {ABAS_RELATORIO.map((aba) => (
            <button
              key={aba.id}
              type="button"
              role="tab"
              aria-selected={abaAtiva === aba.id}
              onClick={() => setAbaAtiva(aba.id)}
              className={`fc-finance-reports-tab ${abaAtiva === aba.id ? "fc-finance-reports-tab-active" : ""}`}
            >
              <aba.icon className="h-4 w-4" />
              {aba.nome}
            </button>
          ))}
        </div>

        <div className="fc-finance-reports-content" aria-busy={loading}>
          {abaAtiva === "categorias" && (
            <div className="fc-finance-reports-grid">
              <section className="fc-finance-reports-panel fc-finance-reports-panel-income">
                <div className="fc-finance-reports-panel-header">
                  <ArrowUpCircle className="h-5 w-5" />
                  <div><h2>Entradas por categoria</h2><p>Composição da receita no período.</p></div>
                </div>
                <div className="fc-finance-reports-panel-body">
                {relatorioEntradas.length === 0 ? (
                    <p className="fc-finance-reports-empty">Nenhuma entrada no período selecionado.</p>
                ) : (
                    <div className="fc-finance-reports-categories">
                    {relatorioEntradas.map((item) => (
                        <div key={item.categoria} className="fc-finance-reports-category">
                          <div className="fc-finance-reports-category-title">
                            <span>{getCategoriaNome(item.categoria)}</span><strong>{formatarValor(item.total)}</strong>
                          </div>
                          <div className="fc-finance-reports-progress"><span style={{ width: `${Math.min(Math.max(item.percentual, 0), 100)}%` }} /></div>
                          <div className="fc-finance-reports-category-meta"><span>{item.quantidade} transações</span><span>{item.percentual}%</span></div>
                        </div>
                    ))}
                  </div>
                )}
                </div>
              </section>

              <section className="fc-finance-reports-panel fc-finance-reports-panel-expense">
                <div className="fc-finance-reports-panel-header">
                  <ArrowDownCircle className="h-5 w-5" />
                  <div><h2>Saídas por categoria</h2><p>Distribuição dos custos no período.</p></div>
                </div>
                <div className="fc-finance-reports-panel-body">
                {relatorioSaidas.length === 0 ? (
                    <p className="fc-finance-reports-empty">Nenhuma saída no período selecionado.</p>
                ) : (
                    <div className="fc-finance-reports-categories">
                    {relatorioSaidas.map((item) => (
                        <div key={item.categoria} className="fc-finance-reports-category">
                          <div className="fc-finance-reports-category-title">
                            <span>{getCategoriaNome(item.categoria)}</span><strong>{formatarValor(item.total)}</strong>
                          </div>
                          <div className="fc-finance-reports-progress"><span style={{ width: `${Math.min(Math.max(item.percentual, 0), 100)}%` }} /></div>
                          <div className="fc-finance-reports-category-meta"><span>{item.quantidade} transações</span><span>{item.percentual}%</span></div>
                        </div>
                    ))}
                  </div>
                )}
                </div>
              </section>
            </div>
          )}

          {abaAtiva === "comparativo" && (
            <section className="fc-finance-reports-panel fc-finance-reports-table-panel">
              <div className="fc-finance-reports-panel-header">
                <TrendingUp className="h-5 w-5" />
                <div><h2>Comparativo dos últimos meses</h2><p>Receita, despesas, variação e saldo mês a mês.</p></div>
              </div>
              <div className="fc-finance-reports-table-scroll">
                <table>
                  <thead>
                  <tr>
                      <th>Período</th><th>Entradas</th><th>Variação</th><th>Saídas</th><th>Variação</th><th>Saldo</th>
                  </tr>
                  </thead>
                  <tbody>
                    {comparativo.length === 0 ? (
                      <tr><td colSpan={6} className="fc-finance-reports-table-empty">Nenhum comparativo disponível.</td></tr>
                    ) : comparativo.map((mes) => (
                      <tr key={`${mes.mes}-${mes.ano}`}>
                        <td>{mes.mes}/{mes.ano}</td>
                        <td className="fc-finance-reports-value-income">{formatarValor(mes.entradas)}</td>
                        <td><span className={mes.variacao_entrada !== undefined && mes.variacao_entrada < 0 ? "fc-negative" : "fc-positive"}>{mes.variacao_entrada !== undefined ? `${mes.variacao_entrada >= 0 ? "+" : ""}${mes.variacao_entrada}%` : "—"}</span></td>
                        <td className="fc-finance-reports-value-expense">{formatarValor(mes.saidas)}</td>
                        <td><span className={mes.variacao_saida !== undefined && mes.variacao_saida > 0 ? "fc-negative" : "fc-positive"}>{mes.variacao_saida !== undefined ? `${mes.variacao_saida >= 0 ? "+" : ""}${mes.variacao_saida}%` : "—"}</span></td>
                        <td><strong className={mes.saldo >= 0 ? "fc-positive" : "fc-negative"}>{formatarValor(mes.saldo)}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {abaAtiva === "grafico" && (
            <section className="fc-finance-reports-panel fc-finance-reports-chart-panel">
              <div className="fc-finance-reports-panel-header">
                <BarChart3 className="h-5 w-5" />
                <div><h2>Evolução mensal</h2><p>Comparação visual entre entradas e saídas.</p></div>
              </div>
              {graficoDisponivel ? (
                <>
                  <div className="fc-finance-reports-chart">
                    {dadosGrafico.labels.map((label: string, index: number) => {
                      const entrada = dadosGrafico.entradas[index] || 0;
                      const saida = dadosGrafico.saidas[index] || 0;
                      const max = Math.max(...dadosGrafico.entradas, ...dadosGrafico.saidas) || 1;
                      return (
                        <div key={label} className="fc-finance-reports-chart-column">
                          <div className="fc-finance-reports-chart-bars">
                            <span className="fc-finance-reports-bar-income" style={{ height: `${(entrada / max) * 100}%` }} title={`Entrada: ${formatarValor(entrada)}`} />
                            <span className="fc-finance-reports-bar-expense" style={{ height: `${(saida / max) * 100}%` }} title={`Saída: ${formatarValor(saida)}`} />
                          </div>
                          <small>{label}</small>
                        </div>
                      );
                    })}
                  </div>
                  <div className="fc-finance-reports-legend"><span><i className="fc-legend-income" />Entradas</span><span><i className="fc-legend-expense" />Saídas</span></div>
                </>
              ) : <p className="fc-finance-reports-empty">Nenhum dado disponível para o gráfico.</p>}
            </section>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
