"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Pill,
  Printer,
  Save,
} from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoPrescricaoAsideProps = LooseAtendimentoComponentProps;

export default function AtendimentoPrescricaoAside(props: AtendimentoPrescricaoAsideProps) {
  const {
    baixarPdfAtendimento,
    classificarAlertaPrescricao,
    form,
    gerandoPdfTipo,
    getAlertaPrescricaoClass,
    hasPrescriptionItems,
    imprimirPrescricao,
    itensPrescricaoAtivos,
    prescricaoErrosCount,
    prescricaoModoFoco,
    prescricaoSupport,
    salvando,
    saveAtendimento,
    setPrescricaoModoFoco,
  } = props;

  return (
    <div className="space-y-4">
      <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-teal-50 p-3">
            <FileText className="h-5 w-5 text-teal-600" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Salvar e conferir</p>
            <h2 className="text-lg font-semibold text-slate-950">Saida da prescricao</h2>
          </div>
        </div>

        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => void saveAtendimento()}
            disabled={salvando}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {salvando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {salvando ? "Salvando..." : "Salvar atendimento"}
          </button>
          <button
            type="button"
            onClick={imprimirPrescricao}
            className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            <Printer className="h-4 w-4" />
            Imprimir
          </button>
          <button
            type="button"
            onClick={() => baixarPdfAtendimento("prescricao")}
            disabled={!hasPrescriptionItems || salvando || Boolean(gerandoPdfTipo)}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-teal-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {gerandoPdfTipo === "prescricao" ? "Gerando PDF..." : "Baixar PDF"}
          </button>
          <button
            type="button"
            onClick={() => setPrescricaoModoFoco((prev: boolean) => !prev)}
            className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            <CheckCircle2 className="h-4 w-4" />
            {prescricaoModoFoco ? "Desocupar lateral" : "Modo revisao"}
          </button>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Itens prontos</p>
            <p className="mt-1 text-lg font-semibold text-slate-950">{itensPrescricaoAtivos.length}</p>
          </div>
          <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Pendencias</p>
            <p className={`mt-1 text-lg font-semibold ${prescricaoErrosCount > 0 ? "text-rose-700" : "text-emerald-700"}`}>
              {prescricaoErrosCount}
            </p>
          </div>
          <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Alertas gerais</p>
            <p className="mt-1 text-lg font-semibold text-slate-950">{prescricaoSupport.alertasGerais.length}</p>
          </div>
          <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Retorno</p>
            <p className="mt-1 text-lg font-semibold text-slate-950">{form.prescricao_retorno_dias || "Em aberto"}</p>
          </div>
        </div>
      </section>

      <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-slate-100 p-3">
            <Pill className="h-5 w-5 text-slate-700" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Resumo para o documento</p>
            <h3 className="text-lg font-semibold text-slate-950">Conferencia rapida</h3>
          </div>
        </div>

        <div className="mt-5 space-y-3">
          {itensPrescricaoAtivos.length > 0 ? (
            itensPrescricaoAtivos.map((item: any, idx: number) => (
              <div key={`${idx}-${item.id || item.medicamento_nome}`} className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-950">{item.medicamento_nome || `Item ${idx + 1}`}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {item.apresentacao_selecionada ||
                        (/(formula manipulada)/i.test(item.medicamento_nome || "") ? "Formula manipulada" : "Apresentacao em aberto")}
                    </p>
                  </div>
                  <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600">
                    {item.via || "Via em aberto"}
                  </span>
                </div>
                <div className="mt-3 space-y-1 text-sm text-slate-600">
                  <p>{item.dose || "Dose em aberto"}</p>
                  <p>{item.frequencia || "Frequencia em aberto"}</p>
                  <p>{item.duracao || "Duracao livre"}</p>
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-[24px] border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
              Os itens ativos aparecerao aqui conforme forem configurados na coluna principal.
            </div>
          )}
        </div>

        <div className="mt-5 rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Orientacoes gerais</p>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            {form.prescricao_orientacoes.trim() || "Nenhuma orientacao geral adicionada ainda."}
          </p>
        </div>
      </section>

      {prescricaoSupport.alertasGerais.length > 0 ? (
        <section className="rounded-[28px] border border-amber-200 bg-amber-50 p-5 shadow-sm">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-700" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Atencao antes do PDF</p>
              <h3 className="text-sm font-semibold text-amber-950">Interacoes e observacoes gerais</h3>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            {prescricaoSupport.alertasGerais.map((alerta: string) => (
              <p
                key={alerta}
                className={`rounded-2xl border px-3 py-2 text-sm ${getAlertaPrescricaoClass(classificarAlertaPrescricao(alerta))}`}
              >
                {alerta}
              </p>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
