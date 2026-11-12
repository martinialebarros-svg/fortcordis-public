export interface PreferenciaAgenda {
  data_inicio?: string;
  data_fim?: string;
  turno: "qualquer" | "manha" | "tarde";
  hora_inicio?: string;
  hora_fim?: string;
}

export interface FiltrosPreferenciaAgenda {
  quando: "sem_preferencia" | "data" | "esta_semana" | "proxima_semana" | "intervalo";
  dataInicio: string;
  dataFim: string;
  turno: PreferenciaAgenda["turno"] | "a_partir_de" | "personalizado";
  horaInicio: string;
  horaFim: string;
}

export const FILTROS_PREFERENCIA_VAZIOS: FiltrosPreferenciaAgenda = {
  quando: "sem_preferencia", dataInicio: "", dataFim: "", turno: "qualquer", horaInicio: "", horaFim: "",
};

export function dataFortaleza(agora = new Date()): string {
  const partes = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Fortaleza", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(agora);
  const valor = Object.fromEntries(partes.map((parte) => [parte.type, parte.value]));
  return `${valor.year}-${valor.month}-${valor.day}`;
}

function dataCivil(valor: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(valor)) return null;
  const data = new Date(`${valor}T00:00:00Z`);
  return Number.isFinite(data.getTime()) && data.toISOString().slice(0, 10) === valor ? data : null;
}

export function resolverPreferenciaAgenda(
  filtros: FiltrosPreferenciaAgenda,
  referencia: string,
): { preferencia?: PreferenciaAgenda; erro?: string } {
  const preferencia: PreferenciaAgenda = {
    turno: filtros.turno === "personalizado" || filtros.turno === "a_partir_de" ? "qualquer" : filtros.turno,
  };
  if (filtros.quando === "esta_semana" || filtros.quando === "proxima_semana") {
    const data = dataCivil(referencia);
    if (!data) return { erro: "Não foi possível determinar a semana da solicitação." };
    const diasDesdeSegunda = (data.getUTCDay() + 6) % 7;
    data.setUTCDate(data.getUTCDate() - diasDesdeSegunda + (filtros.quando === "proxima_semana" ? 7 : 0));
    preferencia.data_inicio = data.toISOString().slice(0, 10);
    data.setUTCDate(data.getUTCDate() + 6);
    preferencia.data_fim = data.toISOString().slice(0, 10);
  } else if (filtros.quando !== "sem_preferencia") {
    preferencia.data_inicio = filtros.dataInicio;
    preferencia.data_fim = filtros.quando === "data" ? filtros.dataInicio : filtros.dataFim;
    const inicio = dataCivil(preferencia.data_inicio);
    const fim = dataCivil(preferencia.data_fim);
    if (!inicio || !fim) return { erro: "Informe as datas do período desejado." };
    const dias = (fim.getTime() - inicio.getTime()) / 86_400_000;
    if (dias < 0) return { erro: "A data final deve ser igual ou posterior à inicial." };
    if (dias > 30) return { erro: "Escolha um período de até 31 dias." };
  }
  if (filtros.turno === "a_partir_de") {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(filtros.horaInicio)) return { erro: "Informe o horário a partir do qual o atendimento pode começar." };
    preferencia.hora_inicio = filtros.horaInicio;
  } else if (filtros.turno === "personalizado") {
    const horaValida = (hora: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(hora);
    if (!horaValida(filtros.horaInicio) || !horaValida(filtros.horaFim)) return { erro: "Informe o início e o fim da faixa de horários." };
    if (filtros.horaFim <= filtros.horaInicio) return { erro: "O horário final deve ser posterior ao inicial." };
    preferencia.hora_inicio = filtros.horaInicio;
    preferencia.hora_fim = filtros.horaFim;
  }
  return preferencia.data_inicio || preferencia.turno !== "qualquer" || preferencia.hora_inicio ? { preferencia } : {};
}

export function filtrosDePreferencia(preferencia?: PreferenciaAgenda | null): FiltrosPreferenciaAgenda {
  if (!preferencia) return { ...FILTROS_PREFERENCIA_VAZIOS };
  let horaInicio = preferencia.hora_inicio || "";
  let horaFim = preferencia.hora_fim || "";
  // Um turno importado impõe também um limite final: mostrá-lo como faixa evita ampliar a busca.
  if ((horaInicio || horaFim) && preferencia.turno !== "qualquer") {
    const [inicioTurno, fimTurno] = preferencia.turno === "manha" ? ["00:00", "12:00"] : ["12:00", "18:00"];
    horaInicio = horaInicio > inicioTurno ? horaInicio : inicioTurno;
    horaFim = horaFim && horaFim < fimTurno ? horaFim : fimTurno;
  }
  return {
    quando: preferencia.data_inicio || preferencia.data_fim
      ? preferencia.data_inicio === preferencia.data_fim ? "data" : "intervalo"
      : "sem_preferencia",
    dataInicio: preferencia.data_inicio || "",
    dataFim: preferencia.data_fim || "",
    turno: horaInicio && !horaFim ? "a_partir_de" : horaInicio || horaFim ? "personalizado" : preferencia.turno,
    horaInicio,
    horaFim,
  };
}

export function resumoPreferenciaAgenda(preferencia?: PreferenciaAgenda): string {
  if (!preferencia) return "Sem restrição de período. A agenda buscará as melhores opções disponíveis.";
  const formatar = (data: string) => data.split("-").reverse().join("/");
  const datas = preferencia.data_inicio && preferencia.data_fim
    ? preferencia.data_inicio === preferencia.data_fim ? formatar(preferencia.data_inicio)
      : `${formatar(preferencia.data_inicio)} a ${formatar(preferencia.data_fim)}`
    : "Qualquer data disponível";
  const turno = preferencia.hora_inicio && preferencia.hora_fim ? `${preferencia.hora_inicio} a ${preferencia.hora_fim}`
    : preferencia.hora_inicio ? `a partir de ${preferencia.hora_inicio}`
    : preferencia.turno === "manha" ? "manhã (término até 12h)"
      : preferencia.turno === "tarde" ? "tarde (12h às 18h)" : "qualquer turno";
  return `${datas}, ${turno}. Serão sugeridos apenas atendimentos inteiros dentro desse período, no horário de Fortaleza.`;
}
