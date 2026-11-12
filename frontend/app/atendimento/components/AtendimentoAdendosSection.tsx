"use client";

import { useRef } from "react";
import {
  CalendarClock,
  FilePlus2,
  FileUp,
  Loader2,
  Paperclip,
  Plus,
  Stethoscope,
  X,
} from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoAdendosSectionProps = LooseAtendimentoComponentProps;

const TIPO_BADGE_CLASS: Record<string, string> = {
  resultado_exame: "bg-sky-100 text-sky-800",
  receita_complementar: "bg-teal-100 text-teal-800",
  orientacao: "bg-violet-100 text-violet-800",
  evolucao: "bg-slate-100 text-slate-600",
};

/**
 * Continuidade pos-alta: o que chega depois do encontro (exame que o tutor
 * mandou dias depois, receita complementar, orientacao) entra aqui, no mesmo
 * atendimento, sem abrir uma consulta nova e sem alterar o registro fechado.
 */
export default function AtendimentoAdendosSection(props: AtendimentoAdendosSectionProps) {
  const {
    ADENDO_TIPO_OPCOES,
    ATENDIMENTO_ATTACHMENT_ACCEPT,
    abrirAnexo,
    adendoForm,
    adendoFormAberto,
    adendos,
    anexarArquivoNoAdendo,
    atendimentoConcluido,
    cancelarUploadAnexo,
    criandoAdendo,
    criandoReceita,
    criarAdendo,
    criarReceitaComplementar,
    exameDoAdendo,
    examesAguardandoArquivo,
    formatDate,
    selecionado,
    setAdendoForm,
    setAdendoFormAberto,
    setExameDoAdendo,
    uploadProgressByKey,
    uploadingAttachmentKey,
  } = props;

  const inputsAnexo = useRef<Record<number, HTMLInputElement | null>>({});
  const tipoSelecionado = ADENDO_TIPO_OPCOES.find(
    (opcao: { value: string }) => opcao.value === adendoForm.tipo
  );

  return (
    <section className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
            Continuidade do atendimento
          </p>
          <h3 className="mt-1 text-lg font-semibold text-slate-900">Adendos</h3>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
            {atendimentoConcluido
              ? "Este atendimento ja foi concluido e continua editavel. Use um adendo opcional quando quiser registrar um acrescimo com data propria."
              : "Use um adendo opcional para registrar um acrescimo com data propria. O atendimento e os documentos continuam editaveis depois da conclusao."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdendoFormAberto(!adendoFormAberto)}
          disabled={!selecionado}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-2xl bg-slate-800 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {adendoFormAberto ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {adendoFormAberto ? "Cancelar" : "Registrar adendo"}
        </button>
      </div>

      {!selecionado ? (
        <p className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          Salve o atendimento para poder registrar adendos.
        </p>
      ) : null}

      {adendoFormAberto && selecionado ? (
        <div className="mt-4 space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Tipo</span>
              <select
                value={adendoForm.tipo}
                onChange={(event) =>
                  setAdendoForm({ ...adendoForm, tipo: event.target.value })
                }
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-500"
              >
                {ADENDO_TIPO_OPCOES.map((opcao: { value: string; label: string }) => (
                  <option key={opcao.value} value={opcao.value}>
                    {opcao.label}
                  </option>
                ))}
              </select>
              {tipoSelecionado ? (
                <span className="mt-1 block text-xs text-slate-500">{tipoSelecionado.ajuda}</span>
              ) : null}
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Titulo (opcional)</span>
              <input
                value={adendoForm.titulo}
                onChange={(event) => setAdendoForm({ ...adendoForm, titulo: event.target.value })}
                placeholder="Ex.: Ecocardiograma enviado pelo tutor"
                maxLength={255}
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-500"
              />
            </label>
          </div>
          <label className="block text-sm">
            <span className="font-medium text-slate-700">O que esta sendo acrescentado</span>
            <textarea
              value={adendoForm.descricao}
              onChange={(event) => setAdendoForm({ ...adendoForm, descricao: event.target.value })}
              rows={3}
              placeholder="Descreva o que chegou e a conduta, se houver."
              className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-500"
            />
          </label>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => void criarAdendo()}
              disabled={criandoAdendo || adendoForm.descricao.trim().length < 2}
              className="inline-flex items-center gap-2 rounded-2xl bg-slate-800 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {criandoAdendo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {criandoAdendo ? "Registrando..." : "Registrar adendo"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        {adendos.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
            Nenhum adendo neste atendimento.
          </p>
        ) : null}

        {adendos.map((adendo: any) => {
          const uploadKey = `adendo-${adendo.id}`;
          const enviando = uploadingAttachmentKey === uploadKey;
          const progresso = uploadProgressByKey?.[uploadKey];
          return (
            <article key={adendo.id} className="rounded-2xl border border-slate-200 bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                    TIPO_BADGE_CLASS[adendo.tipo] || TIPO_BADGE_CLASS.evolucao
                  }`}
                >
                  {adendo.titulo}
                </span>
                {adendo.pos_conclusao ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                    <CalendarClock className="h-3 w-3" />
                    Apos a conclusao
                  </span>
                ) : null}
                <span className="text-xs text-slate-500">{formatDate(adendo.data_evolucao)}</span>
                {adendo.responsavel_nome ? (
                  <span className="text-xs text-slate-500">- {adendo.responsavel_nome}</span>
                ) : null}
              </div>

              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{adendo.descricao}</p>

              {adendo.anexos?.length ? (
                <ul className="mt-3 space-y-1">
                  {adendo.anexos.map((anexo: any) => (
                    <li key={anexo.id}>
                      <button
                        type="button"
                        onClick={() => abrirAnexo(anexo)}
                        className="inline-flex items-center gap-2 rounded-lg px-2 py-1 text-sm text-teal-700 transition hover:bg-teal-50"
                      >
                        <Paperclip className="h-3.5 w-3.5" />
                        {anexo.nome_original || "Arquivo"}
                        {anexo.exame_id ? (
                          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                            <Stethoscope className="h-3 w-3" />
                            vinculado ao exame
                          </span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}

              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                {examesAguardandoArquivo.length > 0 ? (
                  <label className="text-xs text-slate-600">
                    Vincular ao exame
                    <select
                      value={exameDoAdendo[adendo.id] || ""}
                      onChange={(event) =>
                        setExameDoAdendo({ ...exameDoAdendo, [adendo.id]: event.target.value })
                      }
                      className="ml-2 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-900 outline-none focus:border-slate-500"
                    >
                      <option value="">Nenhum</option>
                      {examesAguardandoArquivo.map((exame: any) => (
                        <option key={exame.id} value={String(exame.id)}>
                          {exame.tipo_exame}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}

                <input
                  ref={(element) => {
                    inputsAnexo.current[adendo.id] = element;
                  }}
                  type="file"
                  multiple
                  accept={ATENDIMENTO_ATTACHMENT_ACCEPT}
                  className="hidden"
                  onChange={(event) => {
                    const arquivos = Array.from(event.target.files || []);
                    event.target.value = "";
                    if (arquivos.length > 0) {
                      void anexarArquivoNoAdendo(adendo, arquivos);
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={() => inputsAnexo.current[adendo.id]?.click()}
                  disabled={enviando}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {enviando ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileUp className="h-3.5 w-3.5" />}
                  {enviando ? "Enviando..." : "Anexar arquivo"}
                </button>

                {adendo.tipo === "receita_complementar" && !adendo.prescricao_id ? (
                  <button
                    type="button"
                    onClick={() => void criarReceitaComplementar(adendo.id)}
                    disabled={criandoReceita}
                    className="inline-flex items-center gap-2 rounded-xl border border-teal-300 bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-900 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {criandoReceita ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <FilePlus2 className="h-3.5 w-3.5" />
                    )}
                    Emitir receita deste adendo
                  </button>
                ) : null}

                {adendo.prescricao_id ? (
                  <span className="inline-flex items-center gap-1 rounded-xl bg-teal-50 px-3 py-1.5 text-xs font-medium text-teal-800">
                    <FilePlus2 className="h-3.5 w-3.5" />
                    Receita vinculada
                  </span>
                ) : null}

                {enviando ? (
                  <>
                    <span className="text-xs text-slate-500">
                      {typeof progresso === "number" ? `${progresso}%` : "processando..."}
                    </span>
                    <button
                      type="button"
                      onClick={() => cancelarUploadAnexo(uploadKey)}
                      className="text-xs font-semibold text-rose-600 transition hover:text-rose-700"
                    >
                      Cancelar
                    </button>
                  </>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
