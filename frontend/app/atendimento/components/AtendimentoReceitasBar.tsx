"use client";

import { FilePlus2, Loader2 } from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoReceitasBarProps = LooseAtendimentoComponentProps;

/**
 * Seletor das receitas do atendimento.
 *
 * A receita do dia (sequencia 1) e a que o prontuario salva no autosave; as
 * complementares tem endpoint proprio. Receitas emitidas continuam editaveis,
 * com historico de alteracoes e aviso para gerar o PDF atualizado.
 */
export default function AtendimentoReceitasBar(props: AtendimentoReceitasBarProps) {
  const {
    atendimentoConcluido,
    criandoReceita,
    criarReceitaComplementar,
    formatDate,
    receitaAtiva,
    receitas,
    selecionado,
    selecionarReceita,
  } = props;

  if (!selecionado || receitas.length === 0) return null;

  const varias = receitas.length > 1;

  return (
    <section className="rounded-[24px] border border-teal-100 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-700">
            {varias ? `Receitas (${receitas.length})` : "Receita"}
          </span>
          {receitas.map((receita: any) => {
            const ativa = Number(receitaAtiva?.id) === Number(receita.id);
            return (
              <button
                key={receita.id}
                type="button"
                onClick={() => void selecionarReceita(receita.sequencia > 1 ? receita.id : null)}
                className={`inline-flex items-center gap-2 rounded-2xl border px-3 py-1.5 text-xs font-semibold transition ${
                  ativa
                    ? "border-teal-500 bg-teal-50 text-teal-900"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                {receita.sequencia === 1 ? "Receita do dia" : `Complementar ${receita.sequencia}`}
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                    receita.emitida_em ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {receita.emitida_em ? "Emitida" : "Rascunho"}
                </span>
              </button>
            );
          })}
        </div>

        <button
          type="button"
          onClick={() => void criarReceitaComplementar()}
          disabled={criandoReceita}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-2xl border border-teal-300 bg-teal-50 px-4 py-2 text-sm font-semibold text-teal-900 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {criandoReceita ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus2 className="h-4 w-4" />}
          {criandoReceita ? "Criando..." : "Nova receita complementar"}
        </button>
      </div>

      {receitaAtiva?.emitida_em ? (
        <p className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Esta receita foi emitida em {formatDate(receitaAtiva.emitida_em)} e ja pode estar com o tutor.
          Voce pode editar normalmente; as alteracoes ficam no historico. Gere um novo PDF para usar o texto atualizado.
        </p>
      ) : null}

      {receitaAtiva && receitaAtiva.sequencia > 1 ? (
        <p className="mt-2 text-xs text-slate-500">
          Editando uma receita complementar. A receita do dia e o restante do prontuario nao sao alterados por ela.
        </p>
      ) : atendimentoConcluido ? (
        <p className="mt-2 text-xs text-slate-500">
          Atendimento concluido: a receita continua editavel com historico. Se preferir um registro separado, crie uma receita complementar.
        </p>
      ) : null}

    </section>
  );
}
