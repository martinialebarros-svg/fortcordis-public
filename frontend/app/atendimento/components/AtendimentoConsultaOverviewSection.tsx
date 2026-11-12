"use client";

import { PencilLine, Search, User } from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoConsultaOverviewSectionProps = LooseAtendimentoComponentProps;

export default function AtendimentoConsultaOverviewSection(props: AtendimentoConsultaOverviewSectionProps) {
  const {
    abrirCadastroComplementar,
    clinicas,
    form,
    getBadgeStatusClass,
    pacienteBusca,
    pacienteDropdownAberto,
    pacienteDropdownBlurTimeoutRef,
    pacienteNomeExibicao,
    pacientesFiltrados,
    selecionarPaciente,
    setField,
    setMostrarPacientes,
    setPacienteBusca,
    STATUS_ATENDIMENTO,
    especieRacaExibicao,
    sexoPacienteExibicao,
    tutorNomeExibicao,
  } = props;

  return (
    <>
      <section className="rounded-[26px] border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-teal-50 p-3">
                <User className="h-5 w-5 text-teal-600" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.25em] text-slate-400">Contexto do paciente</p>
                <h2 className="text-lg font-semibold text-slate-900">Cabecalho clinico</h2>
              </div>
            </div>
            <button
              type="button"
              onClick={abrirCadastroComplementar}
              disabled={!form.paciente_id}
              className="inline-flex items-center justify-center gap-2 rounded-2xl border border-teal-200 bg-teal-50 px-4 py-2.5 text-sm font-semibold text-teal-800 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <PencilLine className="h-4 w-4" />
              Editar paciente e tutor
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="relative md:col-span-2">
              <label htmlFor="atendimento-paciente-busca" className="mb-1.5 block text-xs font-medium text-slate-600">
                Paciente ou tutor
              </label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="atendimento-paciente-busca"
                  disabled={form.status === "Concluido"}
                  value={pacienteBusca}
                  onChange={(e) => {
                    setPacienteBusca(e.target.value);
                    const nextValue = e.target.value;
                    setMostrarPacientes(nextValue.trim().length >= 2);
                    if (!nextValue.trim()) {
                      setField("paciente_id", "");
                      setMostrarPacientes(false);
                    }
                  }}
                  onFocus={() => {
                    if (pacienteDropdownBlurTimeoutRef.current) {
                      window.clearTimeout(pacienteDropdownBlurTimeoutRef.current);
                    }
                    if (pacienteBusca.trim().length >= 2) {
                      setMostrarPacientes(true);
                    }
                  }}
                  onBlur={() => {
                    if (pacienteDropdownBlurTimeoutRef.current) {
                      window.clearTimeout(pacienteDropdownBlurTimeoutRef.current);
                    }
                    pacienteDropdownBlurTimeoutRef.current = window.setTimeout(() => {
                      setMostrarPacientes(false);
                    }, 120);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setMostrarPacientes(false);
                    }
                  }}
                  placeholder="Buscar paciente ou tutor..."
                  className="w-full rounded-2xl border border-slate-200 bg-slate-50 py-3 pl-11 pr-3 text-sm text-slate-900"
                />
              </div>
              {pacienteDropdownAberto && form.status !== "Concluido" ? (
                <div className="absolute left-0 top-full z-20 mt-2 max-h-64 w-full overflow-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-2xl">
                  {pacientesFiltrados.map((paciente: any) => (
                    <button
                      key={paciente.id}
                      type="button"
                      onClick={() => selecionarPaciente(paciente)}
                      className={`w-full rounded-2xl px-3 py-3 text-left transition hover:bg-teal-50 ${
                        String(paciente.id) === form.paciente_id ? "bg-teal-50" : ""
                      }`}
                    >
                      <span className="block text-sm font-medium text-slate-900">{paciente.nome}</span>
                      <span className="block text-xs text-slate-500">{paciente.tutor || "Tutor nao informado"}</span>
                    </button>
                  ))}
                </div>
              ) : null}
              <p className="mt-2 text-xs text-slate-500">{form.status === "Concluido" ? "Paciente do encontro original. Os dados clinicos continuam editaveis." : "Digite pelo menos 2 letras para buscar pacientes e tutores."}</p>
            </div>
            <label className="block text-xs font-medium text-slate-600">
              Clínica
              <select
                value={form.clinica_id}
                onChange={(e) => setField("clinica_id", e.target.value)}
                className="mt-1.5 block w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
              >
                <option value="">Selecione a clínica</option>
                {clinicas.map((c: any) => (
                  <option key={c.id} value={c.id}>
                    {c.nome}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-medium text-slate-600">
              Data e hora do atendimento
              <input
                type="datetime-local"
                value={form.data_atendimento}
                onChange={(e) => setField("data_atendimento", e.target.value)}
                className="mt-1.5 block w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
              />
            </label>
            <div>
              <p className="mb-1.5 text-xs font-medium text-slate-600">Agendamento vinculado</p>
              <div
                aria-label={
                  form.agendamento_id
                    ? `Agendamento vinculado numero ${form.agendamento_id}`
                    : "Atendimento sem agendamento vinculado"
                }
                className="rounded-2xl border border-slate-200 bg-slate-100 px-4 py-3 text-sm text-slate-700"
              >
                {form.agendamento_id ? `Agenda #${form.agendamento_id}` : "Sem agendamento"}
              </div>
            </div>
            <label className="block text-xs font-medium text-slate-600">
              Estado do atendimento
              <select
                value={form.status}
                onChange={(e) => setField("status", e.target.value)}
                disabled={form.status === "Concluido"}
                className="mt-1.5 block w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
              >
                {STATUS_ATENDIMENTO.map((status: string) => (
                  <option
                    key={status}
                    value={status}
                    disabled={status === "Concluido" && form.status !== "Concluido"}
                  >
                    {status}
                  </option>
                ))}
              </select>
              <span className="mt-1.5 block text-[11px] font-normal text-slate-500">
                {form.status === "Concluido"
                  ? "Edicoes sao salvas com historico, mantendo este atendimento concluido."
                  : "Para concluir, use a acao Finalizar atendimento."}
              </span>
            </label>
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Paciente</p>
              <p className="mt-2 text-sm font-medium text-slate-900">{pacienteNomeExibicao || "Nao selecionado"}</p>
            </div>
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Tutor</p>
              <p className="mt-2 text-sm font-medium text-slate-900">{tutorNomeExibicao || "Nao informado"}</p>
            </div>
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Especie / raca</p>
              <p className="mt-2 text-sm font-medium text-slate-900">{especieRacaExibicao || "Nao informadas"}</p>
            </div>
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Sexo</p>
              <p className="mt-2 text-sm font-medium text-slate-900">{sexoPacienteExibicao || "Nao informado"}</p>
            </div>
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Status do caso</p>
              <p className="mt-2">
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${getBadgeStatusClass(form.status)}`}>
                  {form.status || "Triagem"}
                </span>
              </p>
            </div>
          </div>
          {form.paciente_id ? (
            <p className="text-xs text-slate-500">
              Alteracoes salvas no cadastro serao usadas ao imprimir ou reimprimir receitas e solicitacoes de exame.
            </p>
          ) : null}
        </div>
      </section>
    </>
  );
}
