import { formatPortalDateTime } from "@/lib/portal-datetime";

export function getPortalAdminAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") {
    return {};
  }

  const token = window.localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function buildClinicInviteMessage({
  clinicaNome,
  activationUrl,
  accessMode,
  expiresAt,
  accountEmailMasked,
  senhaTemporaria,
}: {
  clinicaNome: string;
  activationUrl: string;
  accessMode: "activation" | "login" | "temporary_password";
  expiresAt?: string | null;
  accountEmailMasked?: string | null;
  senhaTemporaria?: string | null;
}): string {
  const emailLine = accountEmailMasked
    ? `O email institucional definido para este acesso e ${accountEmailMasked}.`
    : "A clinica usara o email institucional cadastrado no portal.";

  if (accessMode === "login") {
    return [
      `Ola, equipe ${clinicaNome}.`,
      "",
      "A Fort Cordis manteve o acesso seguro da sua clinica ao portal para consulta de exames e laudos liberados.",
      "Use o link abaixo para entrar no portal com o email institucional ja cadastrado:",
      activationUrl,
      "",
      emailLine,
      "Se a senha nao estiver mais com a equipe, use a opcao 'Esqueci minha senha' na tela de entrada para redefinir o acesso.",
      "O portal continua protegendo os dados da unidade e dos pacientes, entao este acesso nao deve ser compartilhado fora da equipe autorizada.",
    ].join("\n");
  }

  if (accessMode === "temporary_password") {
    return [
      `Ola, equipe ${clinicaNome}.`,
      "",
      "A Fort Cordis liberou um acesso seguro para a sua clinica acompanhar exames e laudos dos pets atendidos na unidade.",
      "Use o link abaixo para entrar direto no portal:",
      activationUrl,
      "",
      emailLine,
      `Senha temporaria: ${senhaTemporaria || "(gerada pelo sistema)"}`,
      "No primeiro acesso vamos pedir um codigo extra por email, e o portal vai lembrar a equipe de trocar essa senha por uma so da unidade assim que possivel.",
      "Nao compartilhe este acesso fora da equipe autorizada.",
    ].join("\n");
  }

  const expirationText = expiresAt ? formatPortalDateTime(expiresAt) : "no prazo informado no portal";
  return [
    `Ola, equipe ${clinicaNome}.`,
    "",
    "A Fort Cordis liberou um acesso seguro para a sua clinica acompanhar exames e laudos dos pets atendidos na unidade.",
    "Use o link abaixo para ativar o portal da unidade, criar a senha e comecar a consultar os resultados:",
    activationUrl,
    "",
    emailLine,
    `Este link e individual, expira em ${expirationText} e nao deve ser compartilhado fora da equipe autorizada.`,
    "Depois da ativacao, o acesso passa a ser feito pelo portal com email, senha e confirmacao adicional apenas quando necessario.",
  ].join("\n");
}

export function buildClinicWhatsappLink(target: string, message: string): string {
  const normalizedTarget = String(target || "").replace(/\D+/g, "");
  const baseUrl = normalizedTarget ? `https://wa.me/${normalizedTarget}` : "https://wa.me/";
  return `${baseUrl}?text=${encodeURIComponent(message)}`;
}

export function buildPartnerInviteMessage({
  partnerNome,
  activationUrl,
  accessMode,
  expiresAt,
  accountEmailMasked,
}: {
  partnerNome: string;
  activationUrl: string;
  accessMode: "activation" | "login" | "temporary_password";
  expiresAt?: string | null;
  accountEmailMasked?: string | null;
}): string {
  const emailLine = accountEmailMasked
    ? `O email definido para este acesso e ${accountEmailMasked}.`
    : "O parceiro usara o email cadastrado no portal.";

  if (accessMode === "login") {
    return [
      `Ola, ${partnerNome}.`,
      "",
      "A Fort Cordis manteve seu acesso seguro ao portal para consulta de exames e laudos liberados.",
      "Use o link abaixo para entrar com o email ja cadastrado:",
      activationUrl,
      "",
      emailLine,
      "Se a senha nao estiver mais com voce, use a opcao 'Esqueci minha senha' na tela de entrada para redefinir o acesso.",
      "Este ambiente mostra apenas os casos liberados para você no portal.",
    ].join("\n");
  }

  const expirationText = expiresAt ? formatPortalDateTime(expiresAt) : "no prazo informado no portal";
  return [
    `Ola, ${partnerNome}.`,
    "",
    "A Fort Cordis criou um acesso seguro para voce consultar exames e laudos liberados no portal.",
    "Use o link abaixo para cadastrar sua senha e concluir a ativacao:",
    activationUrl,
    "",
    emailLine,
    `Este link e individual, expira em ${expirationText} e nao deve ser compartilhado.`,
    "Depois da ativacao, o acesso passa a ser feito com email, senha e confirmacao adicional apenas quando necessario.",
  ].join("\n");
}
