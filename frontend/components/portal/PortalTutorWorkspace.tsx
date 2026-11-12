"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, LockKeyhole, LogOut, MailCheck, RefreshCcw, ShieldCheck } from "lucide-react";

import PortalExamResults from "@/components/portal/PortalExamResults";
import { formatPortalDateTime } from "@/lib/portal-datetime";
import {
  clearPortalSession,
  createPortalExamDownloadUrls,
  downloadPortalAttachment,
  listPortalPetExams,
  loadPortalSession,
  requestTutorPortalChallenge,
  savePortalSession,
  verifyPortalCode,
  type PortalChallengeResponse,
  type PortalExamItem,
  type PortalSessionResponse,
} from "@/lib/portal-api";

export default function PortalTutorWorkspace() {
  const [session, setSession] = useState<PortalSessionResponse | null>(null);
  const [challenge, setChallenge] = useState<PortalChallengeResponse | null>(null);
  const [tutorId, setTutorId] = useState("");
  const [pacienteId, setPacienteId] = useState("");
  const canal = "email" as const;
  const [contato, setContato] = useState("");
  const [codigo, setCodigo] = useState("");
  const [requestLoading, setRequestLoading] = useState(false);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [examsLoading, setExamsLoading] = useState(false);
  const [downloadingAttachmentId, setDownloadingAttachmentId] = useState<number | null>(null);
  const [exams, setExams] = useState<PortalExamItem[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function parsePositiveInteger(value: string, fieldLabel: string): number {
    const parsed = Number.parseInt(value.trim(), 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      throw new Error(`${fieldLabel} precisa ser um número válido.`);
    }
    return parsed;
  }

  async function loadTutorExams(activeSession: PortalSessionResponse) {
    if (!activeSession.paciente_id) {
      setExams([]);
      return;
    }

    setExamsLoading(true);
    setError("");
    try {
      const response = await listPortalPetExams(activeSession.paciente_id, activeSession.access_token);
      setExams(response.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar os exames.");
    } finally {
      setExamsLoading(false);
    }
  }

  useEffect(() => {
    const storedSession = loadPortalSession("tutor");
    if (storedSession) {
      setSession(storedSession);
      void loadTutorExams(storedSession);
    }
  }, []);

  async function handleRequestChallenge(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestLoading(true);
    setError("");
    setMessage("");

    try {
      const response = await requestTutorPortalChallenge({
        tutor_id: parsePositiveInteger(tutorId, "ID do tutor"),
        paciente_id: parsePositiveInteger(pacienteId, "ID do pet"),
        canal,
        contato: contato.trim(),
      });
      setChallenge(response);
      setCodigo(response.debug_code || "");
      setMessage(response.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível solicitar o código.");
    } finally {
      setRequestLoading(false);
    }
  }

  async function handleVerifyCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!challenge) {
      return;
    }

    setVerifyLoading(true);
    setError("");
    setMessage("");

    try {
      const verifiedSession = await verifyPortalCode({
        challenge_id: challenge.challenge_id,
        codigo: codigo.trim(),
      });
      savePortalSession(verifiedSession);
      setSession(verifiedSession);
      setMessage("Sessão do tutor validada com sucesso.");
      await loadTutorExams(verifiedSession);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível validar o código.");
    } finally {
      setVerifyLoading(false);
    }
  }

  function handleLogout() {
    clearPortalSession("tutor");
    setSession(null);
    setChallenge(null);
    setExams([]);
    setCodigo("");
    setMessage("Sessão do portal encerrada neste dispositivo.");
    setError("");
  }

  async function handleDownload(examId: number, attachmentId: number) {
    if (!session) {
      return;
    }

    setDownloadingAttachmentId(attachmentId);
    setError("");
    try {
      const response = await createPortalExamDownloadUrls(examId, session.access_token);
      const item = response.items.find((entry) => entry.anexo_id === attachmentId);
      if (!item) {
        throw new Error("O anexo solicitado não está disponível para download.");
      }
      await downloadPortalAttachment(item);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível baixar o anexo.");
    } finally {
      setDownloadingAttachmentId(null);
    }
  }

  return (
    <aside className="fc-portal-workspace fc-portal-tutor-workspace rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      {!session ? (
        <>
          <div className="flex items-center justify-between border-b border-slate-200 pb-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
                Acesso seguro
              </p>
              <h2 className="mt-2 text-xl font-bold text-slate-950">Entrar como tutor</h2>
            </div>
            <span className="rounded-lg bg-teal-50 px-3 py-2 text-xs font-bold text-teal-800">
              portal real
            </span>
          </div>

          <form className="mt-5 space-y-4" onSubmit={handleRequestChallenge}>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-semibold text-slate-800">
                ID do tutor
                <input
                  required
                  inputMode="numeric"
                  value={tutorId}
                  onChange={(event) => setTutorId(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
                  placeholder="Ex.: 12"
                />
              </label>
              <label className="text-sm font-semibold text-slate-800">
                ID do pet
                <input
                  required
                  inputMode="numeric"
                  value={pacienteId}
                  onChange={(event) => setPacienteId(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
                  placeholder="Ex.: 48"
                />
              </label>
            </div>

            <div className="rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm text-teal-900">
              <span className="inline-flex items-center gap-2 font-bold">
                <MailCheck className="h-4 w-4" />
                Código temporário por e-mail
              </span>
              <p className="mt-2 leading-6">
                WhatsApp será habilitado após a liberação da API da Meta.
              </p>
            </div>

            <div>
              <label className="text-sm font-semibold text-slate-800">
                Email cadastrado
                <input
                  required
                  type="email"
                  value={contato}
                  onChange={(event) => setContato(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
                  placeholder="email@tutor.com"
                />
              </label>
            </div>

            <button
              type="submit"
              disabled={requestLoading}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-teal-600 px-4 py-3 text-sm font-bold text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-teal-300"
            >
              {requestLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <LockKeyhole className="h-4 w-4" />}
              {requestLoading ? "Solicitando..." : "Receber código temporário"}
            </button>
          </form>

          {challenge ? (
            <form className="mt-5 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4" onSubmit={handleVerifyCode}>
              <div className="flex items-start gap-3">
                <CheckCircle2 className="mt-0.5 h-5 w-5 text-teal-700" />
                <div>
                  <p className="text-sm font-bold text-slate-950">Código solicitado</p>
                  <p className="mt-1 text-sm leading-6 text-slate-600">{challenge.message}</p>
                </div>
              </div>

              {challenge.debug_code ? (
                <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                  Código de desenvolvimento: <span className="font-bold">{challenge.debug_code}</span>
                </div>
              ) : null}

              <label className="block text-sm font-semibold text-slate-800">
                Código recebido
                <input
                  required
                  value={codigo}
                  onChange={(event) => setCodigo(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
                  placeholder="Digite o código temporário"
                />
              </label>

              <button
                type="submit"
                disabled={verifyLoading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-3 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {verifyLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                {verifyLoading ? "Validando..." : "Entrar no portal do pet"}
              </button>
            </form>
          ) : null}
        </>
      ) : (
        <div>
          <div className="flex items-center justify-between border-b border-slate-200 pb-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
                Sessão ativa
              </p>
              <h2 className="mt-2 text-xl font-bold text-slate-950">Portal do tutor</h2>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700 transition hover:bg-slate-50"
            >
              <LogOut className="h-4 w-4" />
              Sair
            </button>
          </div>

          <div className="mt-5 rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm text-teal-900">
            <p className="font-bold">Pet autorizado no portal</p>
            <p className="mt-1">ID do pet: {session.paciente_id ?? "-"}</p>
            <p className="mt-1">Sessão válida até {formatPortalDateTime(session.expires_at)}</p>
          </div>

          <div className="mt-5 flex gap-3">
            <button
              type="button"
              onClick={() => void loadTutorExams(session)}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-bold text-slate-800 transition hover:bg-slate-50"
            >
              <RefreshCcw className="h-4 w-4" />
              Atualizar exames
            </button>
          </div>

          <div className="mt-5">
            {examsLoading ? (
              <div className="rounded-lg border border-slate-200 p-5 text-sm text-slate-600">
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Carregando exames liberados...
                </span>
              </div>
            ) : (
              <PortalExamResults
                emptyMessage="Nenhum exame liberado foi encontrado para este pet."
                exams={exams}
                downloadingAttachmentId={downloadingAttachmentId}
                onDownload={(examId, attachmentId) => void handleDownload(examId, attachmentId)}
              />
            )}
          </div>
        </div>
      )}

      {message ? (
        <div className="mt-4 rounded-lg border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">
          {message}
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          {error}
        </div>
      ) : null}
    </aside>
  );
}
