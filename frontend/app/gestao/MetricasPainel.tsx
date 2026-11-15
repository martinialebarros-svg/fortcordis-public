import { useState, type ReactNode } from "react";
import { formatCalendarDate } from "@/lib/calendar-date";
import type { MetricasGestao, LinhaCaixa } from "./types";

export const moeda = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? "Não disponível" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
export const numero = (value: number | null | undefined, suffix = "") => value == null || !Number.isFinite(value) ? "Não disponível" : `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(value)}${suffix}`;
const fontesCaixa: Record<string, string> = { pagamento_os: "Pagamento de OS", saldo_os: "Saldo pendente de OS", conta_receber: "Conta a receber", conta_pagar: "Conta a pagar", transacao: "Transação financeira", premissa: "Premissa informada" };
const minutos = (value: number | null | undefined) => value == null ? "Não disponível" : numero(value / 60, " h");

function Tabela<T>({ caption, rows, columns }: { caption: string; rows: T[]; columns: Array<{ title: string; render: (row: T) => ReactNode }> }) {
  const [page, setPage] = useState(0);
  const pages = Math.ceil(rows.length / 25);
  const current = Math.min(page, Math.max(0, pages - 1));
  if (!rows.length) return <p className="py-3 text-sm text-slate-500">{caption}: nenhum registro neste recorte.</p>;
  return <div className="mt-3 overflow-x-auto">
    <table className="w-full text-left text-sm"><caption className="mb-2 text-left font-semibold text-slate-800">{caption} · {rows.length} registros</caption>
      <thead><tr className="border-b border-slate-200 bg-slate-50">{columns.map((column) => <th key={column.title} scope="col" className="whitespace-nowrap px-3 py-2 font-medium text-slate-600">{column.title}</th>)}</tr></thead>
      <tbody>{rows.slice(current * 25, (current + 1) * 25).map((row, index) => <tr key={index} className="border-b border-slate-100">{columns.map((column) => <td key={column.title} className="px-3 py-3 align-top text-slate-800">{column.render(row)}</td>)}</tr>)}</tbody>
    </table>
    {pages > 1 && <div className="mt-3 flex items-center gap-3 text-sm"><button type="button" disabled={current === 0} onClick={() => setPage(current - 1)} className="rounded border px-3 py-1 disabled:opacity-40">Anterior</button><span>Página {current + 1} de {pages}</span><button type="button" disabled={current >= pages - 1} onClick={() => setPage(current + 1)} className="rounded border px-3 py-1 disabled:opacity-40">Próxima</button></div>}
  </div>;
}

function Lacunas({ items }: { items: string[] }) {
  return items.length > 0 ? <div className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-950"><p className="font-semibold">Limites e informações pendentes</p><ul className="mt-1 list-disc space-y-1 pl-5">{Array.from(new Set(items)).map((item) => <li key={item}>{item}</li>)}</ul></div> : null;
}
function LimiteDetalhes({ total, limitado }: { total?: number; limitado?: boolean }) {
  return limitado ? <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">O cálculo usa todos os {total} registros; a lista abaixo é limitada. Reduza o período ou aplique filtros para conferir um recorte menor.</p> : null;
}
function Medidas({ items }: { items: Array<[string, string]> }) {
  return <dl className="grid gap-4 py-4 sm:grid-cols-2 lg:grid-cols-4">{items.map(([label, value]) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-semibold text-slate-900">{value}</dd></div>)}</dl>;
}
function Secao({ id, title, children, badge }: { id: string; title: string; children: ReactNode; badge?: string }) {
  return <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-2"><h2 id={`${id}-title`} className="text-lg font-semibold text-slate-950">{title}</h2>{badge && <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-900">{badge}</span>}</div>{children}</section>;
}
function Detalhes({ title, children }: { title: string; children: ReactNode }) {
  return <details className="mt-4 border-t border-slate-100 pt-4"><summary className="cursor-pointer text-sm font-semibold text-teal-900">{title}</summary>{children}</details>;
}
function Formula({ base, formula }: { base?: string; formula?: string }) {
  return <div className="mt-3 space-y-1 text-sm text-slate-600">{base && <p>{base}</p>}{formula && <p><span className="font-medium">Cálculo: </span>{formula}</p>}</div>;
}
function CaixaTabela({ title, rows }: { title: string; rows: LinhaCaixa[] }) {
  return <Tabela caption={title} rows={rows} columns={[
    { title: "Período", render: (row) => `${formatCalendarDate(row.inicio)} a ${formatCalendarDate(row.fim)}` },
    { title: "Entradas confirmadas", render: (row) => moeda(row.entradas_confirmadas) },
    { title: "Entradas previstas", render: (row) => moeda(row.entradas_previstas) },
    { title: "Entradas por premissa", render: (row) => moeda(row.entradas_premissas) },
    { title: "Saídas confirmadas", render: (row) => moeda(row.saidas_confirmadas) },
    { title: "Saídas previstas", render: (row) => moeda(row.saidas_previstas) },
    { title: "Saídas por premissa", render: (row) => moeda(row.saidas_premissas) },
    { title: "Saldo projetado", render: (row) => moeda(row.saldo_final) },
  ]} />;
}

export default function MetricasPainel({ atual, anterior }: { atual: MetricasGestao; anterior: MetricasGestao }) {
  const { contribuicao: co, recebimento: re, concentracao: cn, caixa: cx, ocupacao: oc, cancelamentos: ca } = atual;
  const cards = [
    { id: "contribuicao", title: "Contribuição por hora", value: moeda(co.por_hora), before: moeda(anterior.contribuicao.por_hora), detail: co.estimado ? "Com premissas informadas" : "Base por competência" },
    { id: "ocupacao", title: "Ocupação agendada", value: numero(oc.taxa_agendada_pct, "%"), before: numero(anterior.ocupacao.taxa_agendada_pct, "%"), detail: `${minutos(oc.livres_minutos)} livres na jornada global` },
    { id: "cancelamentos", title: "Cancelamentos", value: numero(ca.taxa_pct, "%"), before: numero(anterior.cancelamentos.taxa_pct, "%"), detail: `${ca.total_cancelados} de ${ca.total_agendamentos} agendamentos` },
    { id: "recebimento", title: "Prazo de recebimento", value: numero(re.prazo_medio_dias, " dias"), before: numero(anterior.recebimento.prazo_medio_dias, " dias"), detail: "Prazo efetivo ponderado pelo valor" },
    { id: "concentracao", title: "Maior concentração", value: numero(cn.top1_pct, "%"), before: numero(anterior.concentracao.top1_pct, "%"), detail: "Participação da maior clínica" },
    { id: "caixa", title: "Caixa projetado", value: moeda(cx.saldo_final), before: moeda(anterior.caixa.saldo_final), detail: cx.parcial ? "Projeção parcial" : "Cenário informado pelo administrador" },
  ];
  return <div className="space-y-5">
    <nav aria-label="Indicadores de gestão" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{cards.map((card) => <a key={card.id} href={`#${card.id}`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-teal-600"><h2 className="text-sm font-medium text-slate-600">{card.title}</h2><p className="mt-3 text-2xl font-semibold tracking-tight text-slate-950">{card.value}</p><p className="mt-2 text-xs text-slate-500">Anterior: {card.before}</p><p className="mt-1 text-xs font-medium text-teal-800">{card.detail}</p></a>)}</nav>
    <Secao id="contribuicao" title="Contribuição por hora" badge={co.lacunas.length ? "Informação parcial" : co.estimado ? "Estimativa" : undefined}>
      <p className="mt-2 text-sm text-slate-600">Receita atribuída à prestação dos serviços. A contribuição ainda não desconta custos fixos nem remuneração do proprietário; não representa lucro.</p>
      <Formula formula={co.formula} />{co.taxas_fonte && <p className="mt-2 text-sm text-slate-600">Fonte das taxas: {co.taxas_fonte}. Taxas observadas em pagamentos: {moeda(co.taxas_observadas)}.</p>}
      <Medidas items={[[co.receita_parcial ? "Receita conhecida (parcial)" : "Receita por competência", moeda(co.receita_competencia)], ["Tributos", moeda(co.tributos)], ["Taxas", moeda(co.taxas)], ["Repasses", moeda(co.repasses)], ["Outros custos variáveis", moeda(co.custos_variaveis)], ["Contribuição", moeda(co.valor)], ["Horas totais atribuídas", numero(co.horas_totais, " h")], ["Contribuição por hora", moeda(co.por_hora)]]} />
      <Lacunas items={co.lacunas} />
      <Detalhes title="Ver OS que formam a receita"><LimiteDetalhes total={co.total_registros} limitado={co.detalhes_limitados} /><Tabela caption="Receita dos serviços" rows={co.detalhes} columns={[{ title: "OS", render: (r) => r.numero_os || `#${r.os_id}` }, { title: "Prestação", render: (r) => formatCalendarDate(r.data_atendimento) }, { title: "Clínica", render: (r) => r.clinica_nome }, { title: "Região", render: (r) => r.regiao || "Não informada" }, { title: "Estado atual", render: (r) => r.status || "Não informado" }, { title: "Receita", render: (r) => moeda(r.valor) }]} /></Detalhes>
    </Secao>
    <Secao id="ocupacao" title="Ocupação e capacidade disponível" badge={oc.parcial ? "Informação parcial" : undefined}>
      <Formula base={oc.base} formula={oc.formula} />
      <Medidas items={[["Capacidade da jornada global", minutos(oc.capacidade_minutos)], ["Agendado no recorte", minutos(oc.agendados_minutos)], ["Realizado no recorte", minutos(oc.realizados_minutos)], ["Livre na jornada global", minutos(oc.livres_minutos)], ["Ocupação agendada", numero(oc.taxa_agendada_pct, "%")], ["Ocupação realizada", numero(oc.taxa_realizada_pct, "%")]]} />
      <p className="text-sm text-slate-600">A capacidade é compartilhada entre clínicas e regiões. As janelas livres consideram todos os agendamentos, inclusive fora do filtro. Disponibilidade de horário não confirma a viabilidade de uma rota.</p>
      <Lacunas items={[...oc.lacunas, ...oc.limites]} />
      <Detalhes title="Ver capacidade por dia e região"><Tabela caption="Jornada e janelas livres" rows={oc.dias} columns={[{ title: "Dia", render: (r) => formatCalendarDate(r.data) }, { title: "Capacidade", render: (r) => minutos(r.capacidade_minutos) }, { title: "Bloqueios", render: (r) => minutos(r.bloqueados_minutos) }, { title: "Agendado no recorte", render: (r) => minutos(r.agendados_minutos) }, { title: "Realizado no recorte", render: (r) => minutos(r.realizados_minutos) }, { title: "Livre global", render: (r) => minutos(r.livres_minutos) }, { title: "Janelas livres", render: (r) => r.motivo_fechado || r.janelas_livres.map((j) => `${j.inicio}–${j.fim}`).join(" · ") || "Sem janela identificada" }, { title: "Regiões presentes", render: (r) => r.regioes_presentes.join(", ") || "Não informada" }]} /><Tabela caption="Uso por região" rows={oc.por_regiao} columns={[{ title: "Região", render: (r) => r.regiao }, { title: "Agendado", render: (r) => minutos(r.agendados_minutos) }, { title: "Realizado", render: (r) => minutos(r.realizados_minutos) }]} /></Detalhes>
      <Detalhes title="Ver registros da Agenda"><Tabela caption="Agendamentos do recorte" rows={oc.registros} columns={[{ title: "Registro", render: (r) => `#${r.agendamento_id}` }, { title: "Dia", render: (r) => formatCalendarDate(r.data) }, { title: "Clínica", render: (r) => r.clinica_nome }, { title: "Região", render: (r) => r.regiao || "Não informada" }, { title: "Estado atual", render: (r) => r.status }, { title: "Duração", render: (r) => minutos(r.duracao_minutos) }, { title: "População de cancelamentos", render: (r) => r.incluido_populacao_cancelamentos === false ? "Início fora do período" : "Início no período" }]} /></Detalhes>
    </Secao>
    <Secao id="cancelamentos" title="Cancelamentos e estados da Agenda" badge={ca.parcial ? "Informação parcial" : undefined}>
      <Formula base={ca.base} formula={ca.formula} />
      <Medidas items={[["Agendamentos na população", numero(ca.total_agendamentos)], ["Cancelados atuais", numero(ca.total_cancelados)], ["Taxa de cancelamento", numero(ca.taxa_pct, "%")], ["Reativações identificadas", numero(ca.reativados_identificados)], ["Reagendamentos identificados", numero(ca.reagendados_identificados)]]} />
      <Lacunas items={ca.lacunas} />
      <Detalhes title="Ver estados, clínicas, regiões e motivos"><Tabela caption="Estados atuais, sem somar eventos novamente" rows={ca.por_status} columns={[{ title: "Estado", render: (r) => r.status }, { title: "Quantidade", render: (r) => numero(r.quantidade) }]} /><Tabela caption="Cancelamentos por clínica" rows={ca.por_clinica} columns={[{ title: "Clínica", render: (r) => r.clinica_nome }, { title: "População", render: (r) => numero(r.total_agendamentos) }, { title: "Cancelados", render: (r) => numero(r.total_cancelados) }, { title: "Taxa", render: (r) => numero(r.taxa_pct, "%") }]} /><Tabela caption="Cancelamentos por região" rows={ca.por_regiao} columns={[{ title: "Região", render: (r) => r.regiao }, { title: "População", render: (r) => numero(r.total_agendamentos) }, { title: "Cancelados", render: (r) => numero(r.total_cancelados) }, { title: "Taxa", render: (r) => numero(r.taxa_pct, "%") }]} /><p className="mt-3 text-sm text-slate-600">Motivos: {ca.motivos.length ? ca.motivos.join(" · ") : "sem motivos estruturados disponíveis."}</p></Detalhes>
    </Secao>
    <Secao id="recebimento" title="Prazo de recebimento e contas em aberto" badge={re.saldo_parcial ? "Saldo parcial" : undefined}>
      <Formula formula={re.formula} />{re.data_referencia && <p className="mt-2 text-sm text-slate-600">Saldos e vencimentos na data de referência: {formatCalendarDate(re.data_referencia)}.</p>}
      <Medidas items={[["Prazo efetivo ponderado", numero(re.prazo_medio_dias, " dias")], ["Recebimentos registrados", moeda(re.valor_recebido_bruto)], ["Créditos utilizados", moeda(re.credito_utilizado)], [re.saldo_parcial ? "Saldo em aberto conhecido (parcial)" : "Saldo em aberto", moeda(re.saldo_aberto)], ["OS vencidas do período", moeda(re.vencido)], ["Aberto sem vencimento", moeda(re.sem_vencimento)], ["OS pagas sem comprovante rastreável", numero(re.os_pagas_sem_comprovante)]]} />
      <Lacunas items={re.lacunas} />
      <Detalhes title="Ver recebimentos e saldos por OS"><LimiteDetalhes total={re.total_registros} limitado={re.detalhes_limitados} /><Tabela caption="OS e recebimentos efetivos" rows={re.detalhes} columns={[{ title: "OS", render: (r) => r.numero_os || `#${r.os_id}` }, { title: "Clínica", render: (r) => r.clinica_nome }, { title: "Prestação", render: (r) => formatCalendarDate(r.data_atendimento) }, { title: "Valor", render: (r) => moeda(r.valor) }, { title: "Recebido", render: (r) => moeda(r.recebido) }, { title: "Crédito", render: (r) => moeda(r.credito) }, { title: "Aberto", render: (r) => moeda(r.saldo_aberto) }, { title: "Prazo", render: (r) => numero(r.prazo_medio_dias, " dias") }, { title: "Vencimento", render: (r) => r.vencimento ? formatCalendarDate(r.vencimento) : "Não informado" }, { title: "Evidência", render: (r) => r.legacy ? "Histórico sem comprovante" : "Registros rastreáveis" }]} /></Detalhes>
    </Secao>
    <Secao id="concentracao" title="Concentração da receita por clínica" badge={cn.parcial ? "Receita parcial" : undefined}>
      <Formula base={cn.base} />
      <Medidas items={[["Receita da base", moeda(cn.receita_total)], ["Top 1", numero(cn.top1_pct, "%")], ["Top 3", numero(cn.top3_pct, "%")], ["Top 5", numero(cn.top5_pct, "%")]]} />
      <p className="text-sm text-slate-600">Os percentuais descrevem a distribuição da receita no recorte, sem classificação automática de risco. Um filtro por clínica restringe também esta base. Top 3 e Top 5 dependem de haver clínicas suficientes.</p>
      <Lacunas items={cn.lacunas} />
      <Tabela caption="Participação dos parceiros" rows={cn.clinicas} columns={[{ title: "Clínica", render: (r) => <span>{r.clinica_nome}{r.ativa === false ? " (inativa)" : ""}</span> }, { title: "Região", render: (r) => r.regiao || "Não informada" }, { title: "OS", render: (r) => numero(r.quantidade_os) }, { title: "Receita", render: (r) => moeda(r.receita) }, { title: "Participação", render: (r) => <div className="min-w-24"><span>{numero(r.participacao_pct, "%")}</span>{r.participacao_pct != null && <div aria-hidden="true" className="mt-1 h-1.5 rounded bg-slate-100"><div className="h-full rounded bg-teal-700" style={{ width: `${Math.max(0, Math.min(100, r.participacao_pct))}%` }} /></div>}</div> }]} />
      <Detalhes title="Ver evolução mensal"><Tabela caption="Receita e participação por mês" rows={cn.evolucao} columns={[{ title: "Mês", render: (r) => r.mes.split("-").reverse().join("/") }, { title: "Clínica", render: (r) => r.clinica_nome }, { title: "Receita", render: (r) => moeda(r.receita) }, { title: "Participação", render: (r) => numero(r.participacao_pct, "%") }]} /></Detalhes>
    </Secao>
    <Secao id="caixa" title="Caixa projetado" badge={cx.parcial ? "Projeção parcial" : "Cenário-base informado"}>
      <Formula formula={cx.formula} />
      <p className="mt-2 text-sm text-slate-600">Movimentos confirmados, previstos e premissas aparecem separados. A projeção não representa saldo bancário verificado. Sem saldo inicial, o saldo projetado permanece indisponível.</p>
      <Medidas items={[["Saldo inicial informado", moeda(cx.saldo_inicial)], ["Entradas confirmadas", moeda(cx.entradas_confirmadas)], ["Entradas previstas", moeda(cx.entradas_previstas)], ["Saídas confirmadas", moeda(cx.saidas_confirmadas)], ["Saídas previstas", moeda(cx.saidas_previstas)], ["Entradas por premissa", moeda(cx.entradas_premissas)], ["Saídas por premissa", moeda(cx.saidas_premissas)], ["Pendências sem data", moeda(cx.pendencias_sem_data)], ["Saldo final projetado", moeda(cx.saldo_final)]]} />
      <Lacunas items={cx.lacunas} />
      <CaixaTabela title="Projeção semanal" rows={cx.semanas} />
      <Detalhes title="Ver projeção mensal"><CaixaTabela title="Projeção mensal" rows={cx.meses} /></Detalhes>
      <Detalhes title="Ver movimentos que formam a projeção"><LimiteDetalhes total={cx.total_registros} limitado={cx.detalhes_limitados} /><Tabela caption="Movimentos por origem" rows={cx.detalhes} columns={[{ title: "Data", render: (r) => formatCalendarDate(r.data) }, { title: "Descrição", render: (r) => r.descricao?.trim() || "Não informada" }, { title: "Origem", render: (r) => `${fontesCaixa[r.fonte] || "Registro financeiro"} #${r.id}` }, { title: "Tipo", render: (r) => r.tipo === "entrada" ? "Entrada" : "Saída" }, { title: "Natureza", render: (r) => ({ confirmado: "Confirmado", previsto: "Previsto", premissa: "Premissa" })[r.natureza] }, { title: "Valor", render: (r) => moeda(r.valor) }]} /></Detalhes>
    </Secao>
  </div>;
}
