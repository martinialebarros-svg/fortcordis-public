import { formatarPrazoReserva, formatarDateTimeLocalInput } from "./agenda-reserva-manual";

// Espelha as constantes do backend (app/api/v1/endpoints/agenda.py):
// reabilitar uma reserva expirada devolve o horario ao status "Reservado"
// com um novo prazo de confirmacao.
export const PRAZO_REABILITACAO_HORAS_PADRAO = 3;
export const PRAZO_REABILITACAO_HORAS_MIN = 0.5;
export const PRAZO_REABILITACAO_HORAS_MAX = 72;
export const MARGEM_MINIMA_PRAZO_RESERVA_MIN = 5;

export interface PrazoReabilitacaoPreview {
  /** Prazo resolvido no formato datetime-local (vazio quando nao ha prazo possivel). */
  prazo: string;
  /** Mesmo prazo formatado para leitura (dd/mm/aaaa as hh:mm). */
  prazoLegivel: string;
  /** O prazo pedido nao cabia antes do horario reservado e foi encurtado. */
  encurtado: boolean;
  /** O horario reservado esta proximo demais (ou passou) para uma nova reserva. */
  indisponivel: boolean;
}

export const podeReabilitarReserva = (status?: string | null): boolean =>
  String(status || "").trim() === "Expirado";

export const normalizarPrazoReabilitacaoHoras = (valor: string | number): number | null => {
  const horas = typeof valor === "number" ? valor : Number(String(valor || "").replace(",", "."));
  if (!Number.isFinite(horas)) return null;
  if (horas < PRAZO_REABILITACAO_HORAS_MIN || horas > PRAZO_REABILITACAO_HORAS_MAX) return null;
  return horas;
};

/**
 * Converte "2099-05-25 11:00:00" / "2099-05-25T11:00:00" (horario local, como a
 * API da agenda devolve) em Date. Retorna null quando nao da para interpretar.
 */
export const parseDataHoraAgenda = (valor?: string | null): Date | null => {
  const bruto = String(valor || "").trim();
  if (!bruto) return null;
  const match = bruto.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return null;
  const [, ano, mes, dia, hora, minuto, segundo] = match;
  const data = new Date(
    Number(ano),
    Number(mes) - 1,
    Number(dia),
    Number(hora),
    Number(minuto),
    Number(segundo || "0"),
  );
  return Number.isNaN(data.getTime()) ? null : data;
};

/**
 * Resolve o prazo que o backend vai aplicar ao reabilitar a reserva: horas
 * contadas de agora, encurtadas quando nao cabem antes do horario reservado.
 */
export const calcularPrazoReabilitacao = (
  horas: number,
  inicioAgendamento?: string | null,
  agora: Date = new Date(),
): PrazoReabilitacaoPreview => {
  const agoraTruncado = new Date(agora.getTime());
  agoraTruncado.setSeconds(0, 0);

  const prazoPedido = new Date(agoraTruncado.getTime() + horas * 60 * 60 * 1000);
  prazoPedido.setSeconds(0, 0);

  const inicio = parseDataHoraAgenda(inicioAgendamento);
  if (inicio === null) {
    return {
      prazo: formatarDateTimeLocalInput(prazoPedido),
      prazoLegivel: formatarPrazoReserva(formatarDateTimeLocalInput(prazoPedido)),
      encurtado: false,
      indisponivel: false,
    };
  }

  const limite = new Date(inicio.getTime() - MARGEM_MINIMA_PRAZO_RESERVA_MIN * 60 * 1000);
  limite.setSeconds(0, 0);

  if (limite.getTime() <= agoraTruncado.getTime()) {
    return { prazo: "", prazoLegivel: "", encurtado: false, indisponivel: true };
  }

  const prazoFinal = prazoPedido.getTime() <= limite.getTime() ? prazoPedido : limite;
  const prazoInput = formatarDateTimeLocalInput(prazoFinal);
  return {
    prazo: prazoInput,
    prazoLegivel: formatarPrazoReserva(prazoInput),
    encurtado: prazoFinal.getTime() !== prazoPedido.getTime(),
    indisponivel: false,
  };
};
