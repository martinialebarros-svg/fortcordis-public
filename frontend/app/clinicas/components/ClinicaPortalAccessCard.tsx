"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Copy,
  Link2,
  Loader2,
  MessageCircle,
  RefreshCcw,
  Send,
  ShieldCheck,
  Trash2,
  UserPlus,
  UserX,
} from "lucide-react";

import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { buildClinicInviteMessage, getPortalAdminAuthHeaders } from "@/lib/portal-clinic-admin";
import { formatPortalDateTime } from "@/lib/portal-datetime";
import type {
  PortalAdminClinicAccessSummaryResponse,
  PortalAdminClinicInviteResponse,
  PortalAdminClinicInviteSnapshot,
} from "@/lib/portal-api";

type ClinicaPortalAccessCardProps = {
  clinicaId: number;
  clinicaNome: string;
  defaultWhatsapp?: string;
  defaultEmail?: string;
};

type InviteRequestParams = {
  deliveryTarget: string;
  inviteEmail: string;
  expiresInHours: string;
  senhaTemporaria: boolean;
  responsavelNome: string;
};

const ACCOUNT_STATUS_LABELS: Record<string, string> = {
  pending_verification: "Cadastro pendente",
  active: "Ativo",
  locked: "Bloqueado",
  revoked: "Revogado",
};

const ACCOUNT_STATUS_CLASSES: Record<string, string> = {
  pending_verification: "border-sky-200 bg-sky-50 text-sky-800",
  active: "border-emerald-200 bg-emerald-50 text-emerald-800",
  locked: "border-amber-200 bg-amber-50 text-amber-800",
  revoked: "border-rose-200 bg-rose-50 text-rose-800",
};

const INVITE_STATUS_LABELS: Record<string, string> = {
  pending: "Pendente",
  used: "Aceito",
  expired: "Expirado",
  revoked: "Revogado",
};

const INVITE_STATUS_CLASSES: Record<string, string> = {
  pending: "border-sky-200 bg-sky-50 text-sky-800",
  used: "border-emerald-200 bg-emerald-50 text-emerald-800",
  expired: "border-slate-200 bg-slate-50 text-slate-700",
  revoked: "border-rose-200 bg-rose-50 text-rose-800",
};

function statusBadge(label: string, classes: string) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${classes}`}>
      {label}
    </span>
  );
}

function invitesWithoutMatchingAccount(invites: PortalAdminClinicInviteSnapshot[]): PortalAdminClinicInviteSnapshot[] {
  // Convites "aceitos" ja aparecem como conta em "Gestores com acesso"; listar aqui so o que ainda precisa de acao ou historico.
  return invites.filter((invite) => invite.status !== "used");
}

export default function ClinicaPortalAccessCard({
  clinicaId,
  clinicaNome,
  defaultWhatsapp = "",
  defaultEmail = "",
}: ClinicaPortalAccessCardProps) {
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [actionKey, setActionKey] = useState("");
  const [summary, setSummary] = useState<PortalAdminClinicAccessSummaryResponse | null>(null);
  const [deliveryTarget, setDeliveryTarget] = useState(defaultWhatsapp);
  const [inviteEmail, setInviteEmail] = useState(defaultEmail);
  const [expiresInHours, setExpiresInHours] = useState("72");
  const [senhaTemporaria, setSenhaTemporaria] = useState(false);
  const [responsavelNome, setResponsavelNome] = useState("");
  const [lastInvite, setLastInvite] = useState<PortalAdminClinicInviteResponse | null>(null);
  const [lastInviteRequest, setLastInviteRequest] = useState<InviteRequestParams | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const accounts = summary?.accounts || [];
  const invites = summary?.invites || [];
  const pendingInvitesWithoutAccount = useMemo(() => invitesWithoutMatchingAccount(invites), [invites]);
  const activeManagerCount = useMemo(
    () => accounts.filter((account) => account.status !== "revoked").length,
    [accounts],
  );

  const inviteMessage = useMemo(() => {
    if (!lastInvite?.activation_url) {
      return "";
    }
    return buildClinicInviteMessage({
      clinicaNome,
      activationUrl: lastInvite.activation_url,
      accessMode: lastInvite.access_mode,
      expiresAt: lastInvite.expires_at,
      accountEmailMasked: lastInvite.account_email_masked,
      senhaTemporaria: lastInvite.senha_temporaria,
    });
  }, [
    clinicaNome,
    lastInvite?.access_mode,
    lastInvite?.account_email_masked,
    lastInvite?.activation_url,
    lastInvite?.expires_at,
    lastInvite?.senha_temporaria,
  ]);

  async function loadSummary() {
    setLoading(true);
    setError("");
    try {
      const response = await api.get<PortalAdminClinicAccessSummaryResponse>(
        `/portal/admin/clinicas/${clinicaId}/acesso`,
        { headers: getPortalAdminAuthHeaders() },
      );
      setSummary(response.data);
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel carregar o acesso da clinica."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSummary();
  }, [clinicaId]);

  async function handleGenerateInvite(overrides?: InviteRequestParams) {
    const requestParams: InviteRequestParams = {
      deliveryTarget: (overrides?.deliveryTarget ?? deliveryTarget).trim(),
      inviteEmail: (overrides?.inviteEmail ?? inviteEmail).trim(),
      expiresInHours: overrides?.expiresInHours ?? expiresInHours,
      senhaTemporaria: overrides?.senhaTemporaria ?? senhaTemporaria,
      responsavelNome: (overrides?.responsavelNome ?? responsavelNome).trim(),
    };

    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      const response = await api.post<PortalAdminClinicInviteResponse>(
        `/portal/admin/clinicas/${clinicaId}/convites`,
        {
          delivery_channel: "whatsapp",
          delivery_target: requestParams.deliveryTarget,
          account_email: requestParams.inviteEmail,
          expires_in_hours: Number.parseInt(requestParams.expiresInHours, 10) || 72,
          allow_manual_copy: true,
          senha_temporaria: requestParams.senhaTemporaria,
          responsavel_nome: requestParams.senhaTemporaria ? requestParams.responsavelNome : undefined,
        },
        { headers: getPortalAdminAuthHeaders() },
      );
      setLastInvite(response.data);
      setLastInviteRequest(requestParams);
      setMessage(
        response.data.access_mode === "login"
          ? response.data.delivery_status === "sent"
            ? "Este email ja tinha acesso ativo: reenviamos o acesso em vez de criar um novo convite."
            : "Este email ja tinha acesso ativo. Copie a mensagem e encaminhe pelo WhatsApp institucional."
          : response.data.access_mode === "temporary_password"
            ? "Conta criada com senha temporaria. Copie a senha agora - ela nao aparece de novo."
            : response.data.delivery_status === "sent"
              ? "Convite enviado com sucesso para o novo gestor."
              : "Convite gerado. Copie a mensagem e encaminhe pelo WhatsApp institucional.",
      );
      if (response.data.access_mode === "activation" || response.data.access_mode === "temporary_password") {
        setInviteEmail("");
        setResponsavelNome("");
      }
      await loadSummary();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel gerar o convite da clinica."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopyLink() {
    if (!lastInvite?.activation_url) {
      return;
    }
    try {
      await navigator.clipboard.writeText(lastInvite.activation_url);
      setMessage(lastInvite.access_mode === "login" ? "Link de acesso copiado." : "Link de ativacao copiado.");
    } catch {
      setError("Nao foi possivel copiar o link automaticamente.");
    }
  }

  async function handleCopySenhaTemporaria() {
    if (!lastInvite?.senha_temporaria) {
      return;
    }
    try {
      await navigator.clipboard.writeText(lastInvite.senha_temporaria);
      setMessage("Senha temporaria copiada.");
    } catch {
      setError("Nao foi possivel copiar a senha automaticamente.");
    }
  }

  async function handleCopyInviteMessage() {
    if (!inviteMessage) {
      return;
    }
    try {
      await navigator.clipboard.writeText(inviteMessage);
      setMessage("Mensagem com link de ativacao copiada.");
    } catch {
      setError("Nao foi possivel copiar a mensagem automaticamente.");
    }
  }

  async function handleResendWhatsapp() {
    if (!lastInviteRequest) {
      return;
    }
    await handleGenerateInvite(lastInviteRequest);
  }

  async function handleRevokeInvite(inviteId: number) {
    setActionKey(`invite-${inviteId}`);
    setError("");
    setMessage("");
    try {
      await api.post(
        `/portal/admin/clinicas/${clinicaId}/convites/${inviteId}/revogar`,
        { reason: "convite revogado pela operacao" },
        { headers: getPortalAdminAuthHeaders() },
      );
      setMessage("Convite pendente revogado.");
      await loadSummary();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel revogar o convite."));
    } finally {
      setActionKey("");
    }
  }

  async function handleRevokeAccount(accountId: number) {
    setActionKey(`account-${accountId}`);
    setError("");
    setMessage("");
    try {
      await api.post(
        `/portal/admin/clinica-accounts/${accountId}/revogar`,
        {
          reason: "conta revogada pela operacao",
          revoke_sessions: true,
        },
        { headers: getPortalAdminAuthHeaders() },
      );
      setMessage("Acesso do gestor revogado e sessoes encerradas.");
      await loadSummary();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel revogar o acesso deste gestor."));
    } finally {
      setActionKey("");
    }
  }

  async function handleRevokeSessions() {
    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      const response = await api.post<{ revoked_count: number }>(
        "/portal/admin/clinica-sessions/revogar",
        {
          clinica_id: clinicaId,
          reason: "sessoes revogadas pela operacao",
        },
        { headers: getPortalAdminAuthHeaders() },
      );
      setMessage(`Sessoes encerradas: ${response.data.revoked_count}.`);
      await loadSummary();
    } catch (err) {
      setError(extractApiErrorMessageSync(err, "Nao foi possivel revogar as sessoes da clinica."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="fc-clinic-form-card fc-clinic-form-card-portal">
      <div className="flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-teal-700" />
            Acesso da clinica ao portal
          </h2>
          <p className="text-sm text-gray-500 mt-2">
            Convide um ou mais gestores da unidade, acompanhe o estado de cada cadastro e revogue acessos quando necessario.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void loadSummary()}
          disabled={loading || submitting}
          className="inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCcw className="w-4 h-4" />}
          Atualizar
        </button>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-4">
          <div className="rounded-lg border border-gray-200 p-4">
            <p className="text-sm font-semibold text-gray-900">
              {activeManagerCount > 0 ? `Convidar mais um gestor de ${clinicaNome}` : `Convidar gestor de ${clinicaNome}`}
            </p>
            <p className="mt-1 text-xs text-gray-500">
              Cada email institucional recebe um convite individual e passa a ter login proprio no portal. Se o email
              informado ja tiver acesso ativo, reenviamos o acesso em vez de criar um novo convite.
            </p>
            <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1fr_120px]">
              <label className="block text-sm font-medium text-gray-700">
                WhatsApp do gestor
                <input
                  value={deliveryTarget}
                  onChange={(event) => setDeliveryTarget(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-teal-600"
                  placeholder="85999990000"
                />
              </label>

              <label className="block text-sm font-medium text-gray-700">
                Email institucional do gestor
                <input
                  required
                  type="email"
                  value={inviteEmail}
                  onChange={(event) => setInviteEmail(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-teal-600"
                  placeholder="gestor@clinica.com"
                />
              </label>

              <label className="block text-sm font-medium text-gray-700">
                Expira em
                <input
                  value={expiresInHours}
                  onChange={(event) => setExpiresInHours(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-teal-600"
                  placeholder="72"
                />
              </label>
            </div>

            <label className="mt-4 flex items-start gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={senhaTemporaria}
                onChange={(event) => setSenhaTemporaria(event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-teal-700 focus:ring-teal-600"
              />
              <span>
                Gerar senha temporaria (recomendado para quem tem menos familiaridade com sistemas) - a conta ja
                nasce ativa, sem a clinica precisar criar a propria senha.
              </span>
            </label>

            {senhaTemporaria ? (
              <label className="mt-3 block text-sm font-medium text-gray-700">
                Nome do responsavel na clinica
                <input
                  value={responsavelNome}
                  onChange={(event) => setResponsavelNome(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-teal-600"
                  placeholder="Nome de quem vai usar o portal"
                />
              </label>
            ) : null}

            <button
              type="button"
              onClick={() => void handleGenerateInvite()}
              disabled={
                submitting ||
                !deliveryTarget.trim() ||
                !inviteEmail.trim() ||
                (senhaTemporaria && !responsavelNome.trim())
              }
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-teal-700 px-4 py-3 text-sm font-bold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-teal-300"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
              Convidar gestor
            </button>

            {lastInvite ? (
              <div className="mt-4 rounded-lg border border-teal-200 bg-teal-50 p-4">
                <p className="text-sm font-semibold text-teal-950">
                  {lastInvite.access_mode === "login"
                    ? "Ultimo link de acesso gerado nesta sessao"
                    : lastInvite.access_mode === "temporary_password"
                      ? "Conta criada com senha temporaria nesta sessao"
                      : "Ultimo link de ativacao gerado nesta sessao"}
                </p>
                <p className="mt-2 break-all text-sm text-teal-900">{lastInvite.activation_url}</p>
                {lastInvite.access_mode === "temporary_password" && lastInvite.senha_temporaria ? (
                  <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
                    <p className="text-xs font-bold uppercase tracking-wide text-amber-800">
                      Senha temporaria - so aparece agora, anote ou copie antes de sair desta tela
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      <code className="rounded bg-white px-2 py-1 font-mono text-base text-amber-950">
                        {lastInvite.senha_temporaria}
                      </code>
                      <button
                        type="button"
                        onClick={() => void handleCopySenhaTemporaria()}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-bold text-amber-900 hover:bg-amber-100"
                      >
                        <Copy className="w-3.5 h-3.5" />
                        Copiar senha
                      </button>
                    </div>
                  </div>
                ) : null}
                <label className="mt-4 block text-sm font-semibold text-teal-950">
                  {lastInvite.access_mode === "login"
                    ? "Mensagem sugerida para reenvio de acesso"
                    : "Mensagem sugerida para WhatsApp"}
                  <textarea
                    readOnly
                    value={inviteMessage}
                    rows={8}
                    className="mt-2 min-h-44 w-full resize-y rounded-lg border border-teal-200 bg-white px-3 py-2 text-sm leading-6 text-teal-950 outline-none"
                    aria-label="Mensagem sugerida para envio do convite da clinica"
                  />
                </label>
                <div className="mt-3 flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => void handleCopyInviteMessage()}
                    className="inline-flex items-center gap-2 rounded-lg border border-teal-300 px-3 py-2 text-sm font-medium text-teal-900 hover:bg-white"
                  >
                    <MessageCircle className="w-4 h-4" />
                    Copiar mensagem
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleResendWhatsapp()}
                    disabled={submitting || !lastInviteRequest}
                    className="inline-flex items-center gap-2 rounded-lg bg-teal-700 px-3 py-2 text-sm font-bold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-teal-300"
                  >
                    {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                    Reenviar pelo WhatsApp
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleCopyLink()}
                    className="inline-flex items-center gap-2 rounded-lg border border-teal-300 px-3 py-2 text-sm font-medium text-teal-900 hover:bg-white"
                  >
                    <Copy className="w-4 h-4" />
                    {lastInvite.access_mode === "login" ? "Copiar acesso" : "Copiar link"}
                  </button>
                  <a
                    href={lastInvite.activation_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 rounded-lg border border-teal-300 px-3 py-2 text-sm font-medium text-teal-900 hover:bg-white"
                  >
                    <Link2 className="w-4 h-4" />
                    Abrir pagina
                  </a>
                </div>
              </div>
            ) : null}
          </div>

          <div className="rounded-lg border border-gray-200 p-4">
            <p className="text-sm font-semibold text-gray-900">Encerrar sessoes</p>
            <p className="mt-1 text-xs text-gray-500">Encerra de uma vez as sessoes ativas de todos os gestores da unidade.</p>
            <button
              type="button"
              onClick={() => void handleRevokeSessions()}
              disabled={submitting || !summary?.active_session_count}
              className="mt-3 inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-2 text-sm font-medium text-rose-900 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCcw className="w-4 h-4" />
              Encerrar sessoes ativas ({summary?.active_session_count || 0})
            </button>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border border-gray-200 p-4">
            <p className="text-sm font-semibold text-gray-900">
              Gestores com acesso {accounts.length ? `(${activeManagerCount} de ${accounts.length})` : ""}
            </p>
            {loading ? (
              <div className="mt-4 text-sm text-gray-500">Carregando resumo do acesso...</div>
            ) : accounts.length ? (
              <div className="mt-3 space-y-3">
                {accounts.map((account) => (
                  <div key={account.id} className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-gray-900">{account.email_masked || "-"}</p>
                      {statusBadge(
                        ACCOUNT_STATUS_LABELS[account.status] || account.status,
                        ACCOUNT_STATUS_CLASSES[account.status] || "border-slate-200 bg-slate-50 text-slate-700",
                      )}
                    </div>
                    <p className="mt-1">Responsavel: {account.responsavel_nome}</p>
                    <p>Ultimo login: {formatPortalDateTime(account.last_login_at)}</p>
                    {account.status !== "revoked" ? (
                      <button
                        type="button"
                        onClick={() => void handleRevokeAccount(account.id)}
                        disabled={actionKey === `account-${account.id}`}
                        className="mt-2 inline-flex items-center gap-2 rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-900 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {actionKey === `account-${account.id}` ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <UserX className="w-3.5 h-3.5" />
                        )}
                        Revogar acesso deste gestor
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-sm text-gray-500">Nenhum gestor ativou o cadastro ainda.</p>
            )}

            {pendingInvitesWithoutAccount.length ? (
              <div className="mt-4 border-t pt-4">
                <p className="text-sm font-medium text-gray-900">Convites</p>
                <div className="mt-3 space-y-3">
                  {pendingInvitesWithoutAccount.map((invite) => (
                    <div key={invite.id} className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-medium text-gray-900">Destino: {invite.delivery_target_masked || "-"}</p>
                        {statusBadge(
                          INVITE_STATUS_LABELS[invite.status] || invite.status,
                          INVITE_STATUS_CLASSES[invite.status] || "border-slate-200 bg-slate-50 text-slate-700",
                        )}
                      </div>
                      <p className="mt-1">Expira em: {formatPortalDateTime(invite.expires_at)}</p>
                      {invite.status === "pending" ? (
                        <button
                          type="button"
                          onClick={() => void handleRevokeInvite(invite.id)}
                          disabled={actionKey === `invite-${invite.id}`}
                          className="mt-2 inline-flex items-center gap-2 rounded-lg border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {actionKey === `invite-${invite.id}` ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="w-3.5 h-3.5" />
                          )}
                          Revogar convite pendente
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="rounded-lg border border-gray-200 p-4">
            <p className="text-sm font-semibold text-gray-900">Sessoes ativas</p>
            <p className="mt-2 text-sm text-gray-700">
              Total em aberto: <span className="font-semibold">{summary?.active_session_count || 0}</span>
            </p>
            {summary?.active_sessions?.length ? (
              <div className="mt-3 space-y-2">
                {summary.active_sessions.map((session) => {
                  const account = accounts.find((item) => item.id === session.account_id);
                  return (
                    <div key={session.id} className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
                      <p className="font-medium text-gray-900">{account?.email_masked || `Sessao #${session.id}`}</p>
                      <p>Valida ate: {formatPortalDateTime(session.trusted_until)}</p>
                      <p>Ultima atividade: {formatPortalDateTime(session.last_seen_at)}</p>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        </div>
      </div>

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
    </section>
  );
}
