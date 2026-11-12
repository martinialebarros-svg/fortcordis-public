interface Props {
  needsReply?: boolean;
  ownerId?: string | null;
  ownerName?: string | null;
  waitingLabel: string;
  paused?: boolean;
  pausedUntil?: string | null;
  handoffReason?: string | null;
  windowOpen: boolean;
}

const reasons: Record<string, string> = {
  emergencia: "Encaminhada por possível emergência. Confira a mensagem e priorize o contato.",
  pedido_humano: "O cliente pediu atendimento humano.",
  sem_fonte: "O bot não encontrou uma fonte segura para responder.",
  tipo_nao_suportado: "A mensagem precisa de análise pela equipe.",
  modelo_pediu_humano: "O bot solicitou apoio da equipe.",
};

export default function WaitingForTeamNotice({ needsReply, ownerId, ownerName, waitingLabel,
  paused, pausedUntil, handoffReason, windowOpen }: Props) {
  if (!needsReply || (!paused && !ownerId)) return null;
  const assigned = Boolean(ownerId);
  const until = pausedUntil && Number.isFinite(Date.parse(pausedUntil))
    ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Fortaleza" }).format(new Date(pausedUntil)) : null;
  return <section className="mx-4 my-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"
    role="status" aria-label="Resposta pendente da equipe">
    <strong>Cliente aguardando resposta da equipe</strong>
    <p>{waitingLabel}. {ownerId ? `Responsável: ${ownerName || "atendente atribuído"}.` :
      "Conversa sem responsável atribuído."}</p>
    <p>{assigned ? "O bot não responde enquanto o atendimento estiver assumido. Remover apenas a pausa não libera a automação." :
      "O bot está pausado nesta conversa. Assuma o atendimento e responda ao cliente."}</p>
    {paused && until ? <p>Pausa registrada até {until} (Fortaleza).</p> : null}
    {paused && handoffReason && reasons[handoffReason] ? <p>Último encaminhamento registrado: {reasons[handoffReason]}</p> : null}
    <p>{windowOpen ? "Use o campo de resposta abaixo para continuar o atendimento." :
      "A janela de resposta livre está fechada. Confira os modelos e use o fluxo correspondente."}</p>
  </section>;
}
