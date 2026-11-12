"use client";

import Link from "next/link";
import { useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";

import { resetClinicPassword } from "@/lib/portal-api";
import { PORTAL_PASSWORD_MIN_LENGTH, validatePortalPasswordConfirmation } from "@/lib/portal-password";

type PortalClinicResetPasswordWorkspaceProps = {
  resetToken: string;
};

export default function PortalClinicResetPasswordWorkspace({
  resetToken,
}: PortalClinicResetPasswordWorkspaceProps) {
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setMessage("");

    const passwordError = validatePortalPasswordConfirmation(password, passwordConfirmation);
    if (passwordError) {
      setError(passwordError);
      setSubmitting(false);
      return;
    }

    try {
      const response = await resetClinicPassword({
        reset_token: resetToken,
        password,
        password_confirmation: passwordConfirmation,
      });
      setDone(true);
      setMessage(response.message);
      setPassword("");
      setPasswordConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível redefinir a senha.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!resetToken) {
    return (
      <div className="fc-portal-auth-card rounded-lg border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950">
        O link de redefinição está incompleto. Solicite um novo e-mail de acesso pelo portal da clínica.
      </div>
    );
  }

  return (
    <div className="fc-portal-auth-card rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      {done ? (
        <div>
          <ShieldCheck className="h-8 w-8 text-emerald-700" />
          <h2 className="mt-5 text-2xl font-bold text-slate-950">Senha atualizada</h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            Sua senha foi redefinida. No próximo login, o portal pode pedir um código extra para confirmar que o acesso voltou para a unidade correta.
          </p>
          <Link
            href="/clinica-parceira"
            className="mt-5 inline-flex rounded-lg bg-slate-950 px-4 py-3 text-sm font-bold text-white transition hover:bg-slate-800"
          >
            Voltar para o login da clínica
          </Link>
        </div>
      ) : (
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-teal-700">
              Redefinir senha
            </p>
            <h2 className="mt-3 text-2xl font-bold text-slate-950">
              Escolha uma nova senha para a unidade
            </h2>
          </div>

          <label className="block text-sm font-semibold text-slate-900">
            Nova senha
            <input
              required
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
              placeholder={`Mínimo de ${PORTAL_PASSWORD_MIN_LENGTH} caracteres`}
            />
          </label>

          <label className="block text-sm font-semibold text-slate-900">
            Confirmação de senha
            <input
              required
              type="password"
              autoComplete="new-password"
              value={passwordConfirmation}
              onChange={(event) => setPasswordConfirmation(event.target.value)}
              className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-teal-600"
              placeholder="Repita a nova senha"
            />
          </label>

          <button
            type="submit"
            disabled={submitting}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-3 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
            {submitting ? "Salvando..." : "Salvar nova senha"}
          </button>
        </form>
      )}

      {message ? (
        <div className="mt-4 rounded-lg border border-teal-200 bg-teal-50 p-3 text-sm text-teal-950">
          {message}
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
