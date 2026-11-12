"use client";

import { useEffect, useRef, useState } from "react";
import { BadgeCheck, Loader2, ShieldCheck } from "lucide-react";

import {
  getAgendaFormalizacaoContext,
  submitAgendaFormalizacao,
  type AgendaFormalizacaoContext,
} from "@/lib/agenda-formalizacao-api";

type AgendaFormalizacaoWorkspaceProps = {
  token: string;
};

export default function AgendaFormalizacaoWorkspace({ token }: AgendaFormalizacaoWorkspaceProps) {
  const [contexto, setContexto] = useState<AgendaFormalizacaoContext | null>(null);
  const [loadingContexto, setLoadingContexto] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const [nomePaciente, setNomePaciente] = useState("");
  const [nomeTutor, setNomeTutor] = useState("");
  const [telefoneTutor, setTelefoneTutor] = useState("");
  const [error, setError] = useState("");
  const [concluido, setConcluido] = useState(false);

  async function loadContexto() {
    setLoadingContexto(true);
    setError("");
    try {
      const response = await getAgendaFormalizacaoContext(token);
      setContexto(response);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Não foi possível validar este link. Solicite um novo pela conversa do WhatsApp.",
      );
    } finally {
      setLoadingContexto(false);
    }
  }

  useEffect(() => {
    void loadContexto();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setError("");
    setSubmitting(true);
    try {
      await submitAgendaFormalizacao(token, {
        nome_paciente: nomePaciente,
        nome_tutor: nomeTutor,
        telefone_tutor: telefoneTutor,
      });
      setConcluido(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível enviar os dados informados.");
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  return (
    <div className="fc-portal-auth-card rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      {loadingContexto ? (
        <div className="flex min-h-[240px] items-center justify-center text-sm text-slate-500">
          <span className="inline-flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Carregando dados do agendamento...
          </span>
        </div>
      ) : contexto ? (
        <div>
          <div className="border-b border-slate-200 pb-4">
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-teal-700">
              {contexto.clinica_nome || "Fort Cordis"}
            </p>
            <h2 className="mt-3 text-2xl font-bold text-slate-950">
              {contexto.servico || "Atendimento"}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Reservado para{" "}
              <span className="font-semibold text-slate-950">
                {contexto.data} às {contexto.hora}
              </span>
              .
            </p>
          </div>

          {concluido ? (
            <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-5">
              <BadgeCheck className="h-8 w-8 text-emerald-700" />
              <h3 className="mt-4 text-lg font-bold text-emerald-950">Dados enviados com sucesso</h3>
              <p className="mt-2 text-sm leading-6 text-emerald-900">
                O agendamento foi atualizado. A Fort Cordis já está com os dados do paciente e do tutor.
              </p>
            </div>
          ) : (
            <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
              <p className="text-sm text-slate-600">Pode informar apenas o primeiro nome do tutor e o nome do pet. Os demais dados serão completados no atendimento.</p>
              <label className="block text-sm font-semibold text-slate-900">
                Nome do paciente
                <input
                  required
                  value={nomePaciente}
                  onChange={(event) => setNomePaciente(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
                  placeholder="Nome do animal"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Nome do tutor
                <input
                  required
                  value={nomeTutor}
                  onChange={(event) => setNomeTutor(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
                  placeholder="Nome do tutor responsável"
                />
              </label>

              <label className="block text-sm font-semibold text-slate-900">
                Telefone do tutor (WhatsApp, opcional)
                <input
                  type="tel"
                  value={telefoneTutor}
                  onChange={(event) => setTelefoneTutor(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
                  placeholder="(85) 99999-9999"
                />
              </label>

              <button
                type="submit"
                disabled={submitting}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-3 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                {submitting ? "Enviando..." : "Confirmar dados"}
              </button>
            </form>
          )}
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-950">
          {error}
        </div>
      ) : null}
    </div>
  );
}
