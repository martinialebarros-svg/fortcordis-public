export type ReservaManualDestinatario = "clinica" | "tutor";
export type MensagemAgendaManualTipo = "reserva" | "agendamento";

export interface MensagemAgendaManualInput {
  tipo: MensagemAgendaManualTipo;
  data: string;
  hora: string;
  prazoConfirmacao?: string;
  servicoNome?: string | null;
  pacienteId?: number | null;
  pacienteNome?: string | null;
  tutorNome?: string | null;
  clinicaNome?: string | null;
  medicoVeterinario?: string | null;
  especialista?: string | null;
}

const formatarParteDataHora = (value: number): string => String(value).padStart(2, "0");

export const formatarDateTimeLocalInput = (date: Date): string => {
  if (Number.isNaN(date.getTime())) return "";
  return [
    date.getFullYear(),
    "-",
    formatarParteDataHora(date.getMonth() + 1),
    "-",
    formatarParteDataHora(date.getDate()),
    "T",
    formatarParteDataHora(date.getHours()),
    ":",
    formatarParteDataHora(date.getMinutes()),
  ].join("");
};

export const criarPrazoReservaPorHoras = (horas: number, agora = new Date()): string => {
  const horasValidas = Number.isFinite(horas) && horas > 0 ? horas : 3;
  const prazo = new Date(agora.getTime() + horasValidas * 60 * 60 * 1000);
  prazo.setSeconds(0, 0);
  return formatarDateTimeLocalInput(prazo);
};

export const criarPrazoPadraoReserva = (agora = new Date()): string =>
  criarPrazoReservaPorHoras(3, agora);

export const formatarDataReserva = (isoDate: string): string => {
  const match = String(isoDate || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return String(isoDate || "").trim();
  const [, ano, mes, dia] = match;
  return `${dia}/${mes}/${ano}`;
};

export const formatarPrazoReserva = (dateTimeLocal: string): string => {
  const match = String(dateTimeLocal || "")
    .trim()
    .match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return String(dateTimeLocal || "").trim();
  const [, ano, mes, dia, hora, minuto] = match;
  return `${dia}/${mes}/${ano} às ${hora}:${minuto}`;
};

export const normalizarTelefoneWhatsApp = (telefone?: string | null): string => {
  let digitos = String(telefone || "").replace(/\D/g, "");
  while (digitos.startsWith("0")) {
    digitos = digitos.slice(1);
  }
  if (!digitos) return "";
  if (digitos.startsWith("55")) return digitos;
  if (digitos.length >= 10 && digitos.length <= 11) return `55${digitos}`;
  return digitos;
};

export const montarMensagemAgendaManual = ({
  tipo,
  data,
  hora,
  prazoConfirmacao,
  servicoNome,
  pacienteId,
  pacienteNome,
  tutorNome,
  clinicaNome,
  medicoVeterinario = "Dr Martiniano",
  especialista = "Cardiologista",
}: MensagemAgendaManualInput): string => {
  const nomePaciente = String(pacienteNome || "").trim();
  const paciente = nomePaciente
    ? `${nomePaciente}${pacienteId ? ` (${pacienteId})` : ""}`
    : "Pendente";
  const tutor = String(tutorNome || "").trim() || "Pendente";
  const clinica = String(clinicaNome || "").trim() || "Pendente";
  const atendimento = String(servicoNome || "").trim() || "Pendente";
  const titulo = tipo === "reserva" ? "*RESERVA DE HORÁRIO* 🐶 🐱" : "*AGENDAMENTO* 🐶 🐱";

  const detalhes = [
    medicoVeterinario ? `*Médico Veterinário:* ${String(medicoVeterinario).trim()}` : "",
    `*Atendimento:* ${atendimento}`,
    `*Data:* ${formatarDataReserva(data)}`,
    `*Horário:* ${String(hora || "").slice(0, 5)}`,
    `*Paciente:* ${paciente}`,
    `*Tutor:* ${tutor}`,
    especialista ? `*Especialista:* ${String(especialista).trim()}` : "",
    `*Clínica:* ${clinica}`,
  ].filter((linha) => linha !== "");
  const linhas = [titulo, "", ...detalhes, ""];

  if (tipo === "reserva") {
    linhas.push(
      `⚠️ *ATENÇÃO:* Confirme esta reserva até ${formatarPrazoReserva(String(prazoConfirmacao || ""))}.`,
      "Sem confirmação até esse prazo, o horário voltará a ficar disponível para outros clientes.",
    );
  } else {
    linhas.push("✅ *CONFIRMAÇÃO:* O horário solicitado foi agendado.");
  }

  return linhas.join("\n");
};

export const montarLinkWhatsAppReserva = (
  telefone: string | null | undefined,
  mensagem: string,
): string => {
  const numero = normalizarTelefoneWhatsApp(telefone);
  const destino = numero ? `https://wa.me/${numero}` : "https://wa.me/";
  return `${destino}?text=${encodeURIComponent(mensagem)}`;
};
