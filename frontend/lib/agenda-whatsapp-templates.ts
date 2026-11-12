export type AgendaWhatsAppTemplateKey =
  | "reservation"
  | "appointmentReminder"
  | "appointmentReminderService"
  | "appointmentChange"
  | "appointmentCancellation"
  | "appointmentMissingData";

export const AGENDA_WHATSAPP_TEMPLATES: Record<
  AgendaWhatsAppTemplateKey,
  { label: string; body: string }
> = {
  reservation: {
    label: "Reserva de agendamento",
    body:
      "Olá, {{1}}. A Fort Cordis reservou o atendimento de {{2}} para {{3}}, às {{4}}. " +
      "Confirme até {{5}}. Após esse prazo, o horário poderá ser disponibilizado para outros clientes automaticamente.",
  },
  appointmentReminder: {
    label: "Lembrete de agendamento",
    body:
      "Olá, {{1}}. Lembramos que o atendimento de {{2}} está confirmado para {{3}}, às {{4}}. " +
      "Se precisar alterar o horário, use uma das opções abaixo.",
  },
  appointmentReminderService: {
    label: "Lembrete com serviço",
    body:
      "Olá, {{1}}. Lembramos que o atendimento de {{2}} está agendado para {{3}}, às {{4}}. " +
      "Serviço agendado: {{5}}. Confira o serviço e o horário. Se precisar corrigir ou incluir outro serviço, " +
      "toque em Solicitar alteração e envie o que deve ser ajustado.",
  },
  appointmentChange: {
    label: "Alteração de agendamento",
    body:
      "Olá, {{1}}. O atendimento de {{2}} foi alterado para {{3}}, às {{4}}. " +
      "Confirme se o novo horário funciona para você.",
  },
  appointmentCancellation: {
    label: "Cancelamento de agendamento",
    body:
      "Olá, {{1}}. O atendimento de {{2}}, previsto para {{3}}, às {{4}}, foi cancelado. " +
      "Se desejar, solicite um novo horário.",
  },
  appointmentMissingData: {
    label: "Dados pendentes",
    body:
      "Olá, {{1}}. Para concluir o atendimento de {{2}} em {{3}}, às {{4}}, precisamos confirmar os dados " +
      "do tutor e do paciente. Responda a esta mensagem para continuarmos.",
  },
};

export function normalizeAgendaWhatsAppServiceName(value: unknown): string {
  return typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";
}

export function isValidAgendaWhatsAppServiceName(value: unknown): value is string {
  const name = normalizeAgendaWhatsAppServiceName(value);
  return name.length > 0 && name.length <= 300;
}

export function renderAgendaWhatsAppTemplate(
  templateKey: AgendaWhatsAppTemplateKey,
  parameters: readonly string[],
): string {
  const body = AGENDA_WHATSAPP_TEMPLATES[templateKey].body;
  const expected = body.match(/\{\{\d+\}\}/g)?.length ?? 0;
  if (parameters.length !== expected) {
    throw new Error(`O modelo ${templateKey} exige ${expected} variáveis.`);
  }
  if (templateKey === "appointmentReminderService" && !isValidAgendaWhatsAppServiceName(parameters[4])) {
    throw new Error("Confira o serviço salvo no agendamento antes de preparar o lembrete com serviço.");
  }
  return body.replace(/\{\{(\d+)\}\}/g, (_placeholder, rawIndex: string) => {
    if (templateKey === "appointmentReminderService" && Number(rawIndex) === 5) {
      return normalizeAgendaWhatsAppServiceName(parameters[4]);
    }
    return parameters[Number(rawIndex) - 1] || "";
  });
}
