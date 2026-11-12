export type DiaSemanaKey = "1" | "2" | "3" | "4" | "5" | "6" | "7";

export interface AgendaDiaConfig {
  ativo: boolean;
  inicio: string;
  fim: string;
}

export interface AgendaFeriadoConfig {
  data: string;
  descricao?: string;
  tipo?: "local" | "nacional";
}

export interface AgendaExcecaoConfig {
  data: string;
  ativo: boolean;
  inicio: string;
  fim: string;
  motivo?: string;
}

export type AgendaSemanalConfig = Record<DiaSemanaKey, AgendaDiaConfig>;

export const DIA_SEMANA_KEYS: DiaSemanaKey[] = ["1", "2", "3", "4", "5", "6", "7"];

export const DIAS_SEMANA_LABELS: Array<{ id: DiaSemanaKey; nome: string }> = [
  { id: "1", nome: "Segunda-feira" },
  { id: "2", nome: "Terca-feira" },
  { id: "3", nome: "Quarta-feira" },
  { id: "4", nome: "Quinta-feira" },
  { id: "5", nome: "Sexta-feira" },
  { id: "6", nome: "Sabado" },
  { id: "7", nome: "Domingo" },
];

export const DEFAULT_AGENDA_SEMANAL: AgendaSemanalConfig = {
  "1": { ativo: true, inicio: "08:00", fim: "14:00" },
  "2": { ativo: true, inicio: "08:00", fim: "14:00" },
  "3": { ativo: true, inicio: "08:00", fim: "14:00" },
  "4": { ativo: true, inicio: "08:00", fim: "14:00" },
  "5": { ativo: true, inicio: "08:00", fim: "14:00" },
  "6": { ativo: true, inicio: "09:00", fim: "13:00" },
  "7": { ativo: false, inicio: "09:00", fim: "13:00" },
};

const toDateInput = (date: Date) => {
  const ano = date.getFullYear();
  const mes = String(date.getMonth() + 1).padStart(2, "0");
  const dia = String(date.getDate()).padStart(2, "0");
  return `${ano}-${mes}-${dia}`;
};

export const normalizarHoraHHMM = (valor: unknown, fallback: string): string => {
  if (typeof valor !== "string") return fallback;
  const texto = valor.trim();
  const match = texto.match(/^(\d{2}):(\d{2})$/);
  if (!match) return fallback;
  const hora = Number.parseInt(match[1], 10);
  const minuto = Number.parseInt(match[2], 10);
  if (!Number.isFinite(hora) || !Number.isFinite(minuto) || hora < 0 || hora > 23 || minuto < 0 || minuto > 59) {
    return fallback;
  }
  return `${String(hora).padStart(2, "0")}:${String(minuto).padStart(2, "0")}`;
};

export const horarioParaMinutos = (horario: string): number | null => {
  const match = horario.match(/^(\d{2}):(\d{2})$/);
  if (!match) return null;
  const hora = Number.parseInt(match[1], 10);
  const minuto = Number.parseInt(match[2], 10);
  if (!Number.isFinite(hora) || !Number.isFinite(minuto)) return null;
  if (hora < 0 || hora > 23 || minuto < 0 || minuto > 59) return null;
  return hora * 60 + minuto;
};

export const normalizarAgendaSemanal = (payload: unknown): AgendaSemanalConfig => {
  const source = typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>) : {};
  const agenda = {} as AgendaSemanalConfig;

  for (const dia of DIA_SEMANA_KEYS) {
    const defaultDia = DEFAULT_AGENDA_SEMANAL[dia];
    const rawDia = source[dia];
    const item = typeof rawDia === "object" && rawDia !== null ? (rawDia as Record<string, unknown>) : {};

    const inicio = normalizarHoraHHMM(item.inicio, defaultDia.inicio);
    const fim = normalizarHoraHHMM(item.fim, defaultDia.fim);

    const inicioMin = horarioParaMinutos(inicio) ?? horarioParaMinutos(defaultDia.inicio) ?? 0;
    const fimMin = horarioParaMinutos(fim) ?? horarioParaMinutos(defaultDia.fim) ?? 0;

    agenda[dia] = {
      ativo: typeof item.ativo === "boolean" ? item.ativo : defaultDia.ativo,
      inicio: inicioMin < fimMin ? inicio : defaultDia.inicio,
      fim: inicioMin < fimMin ? fim : defaultDia.fim,
    };
  }

  return agenda;
};

export const normalizarAgendaFeriados = (payload: unknown): AgendaFeriadoConfig[] => {
  if (!Array.isArray(payload)) return [];

  const datas = new Set<string>();
  const itens: AgendaFeriadoConfig[] = [];

  for (const item of payload) {
    let dataRaw = "";
    let descricaoRaw = "";
    let tipoRaw = "local";

    if (typeof item === "string") {
      dataRaw = item.trim();
    } else if (typeof item === "object" && item !== null) {
      const row = item as Record<string, unknown>;
      dataRaw = String(row.data || "").trim();
      descricaoRaw = String(row.descricao || "").trim();
      tipoRaw = String(row.tipo || "local").trim().toLowerCase();
    }

    if (!/^\d{4}-\d{2}-\d{2}$/.test(dataRaw) || datas.has(dataRaw)) {
      continue;
    }

    datas.add(dataRaw);
    itens.push({
      data: dataRaw,
      descricao: descricaoRaw,
      tipo: tipoRaw === "nacional" ? "nacional" : "local",
    });
  }

  itens.sort((a, b) => a.data.localeCompare(b.data));
  return itens;
};

export const normalizarAgendaExcecoes = (payload: unknown): AgendaExcecaoConfig[] => {
  if (!Array.isArray(payload)) return [];

  const mapa = new Map<string, AgendaExcecaoConfig>();

  for (const item of payload) {
    if (typeof item !== "object" || item === null) continue;
    const row = item as Record<string, unknown>;

    const dataRaw = String(row.data || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dataRaw)) {
      continue;
    }

    const ativo = typeof row.ativo === "boolean" ? row.ativo : true;
    const inicio = normalizarHoraHHMM(row.inicio, "08:00");
    const fim = normalizarHoraHHMM(row.fim, "18:00");
    const inicioMin = horarioParaMinutos(inicio) ?? 8 * 60;
    const fimMin = horarioParaMinutos(fim) ?? 18 * 60;
    const motivo = String(row.motivo || "").trim();

    mapa.set(dataRaw, {
      data: dataRaw,
      ativo,
      inicio: inicioMin < fimMin ? inicio : "08:00",
      fim: inicioMin < fimMin ? fim : "18:00",
      motivo,
    });
  }

  const itens = Array.from(mapa.values());
  itens.sort((a, b) => a.data.localeCompare(b.data));
  return itens;
};

export const obterExcecaoData = (
  dataIso: string,
  agendaExcecoes: AgendaExcecaoConfig[]
) => agendaExcecoes.find((item) => item.data === dataIso);

export const obterJornadaDia = (
  dataIso: string,
  agendaSemanal: AgendaSemanalConfig,
  agendaFeriados: AgendaFeriadoConfig[],
  agendaExcecoes: AgendaExcecaoConfig[] = []
): { fechado: boolean; inicio: string; fim: string; motivo: string } => {
  const excecao = obterExcecaoData(dataIso, agendaExcecoes);
  if (excecao) {
    if (!excecao.ativo) {
      return {
        fechado: true,
        inicio: excecao.inicio,
        fim: excecao.fim,
        motivo: excecao.motivo || "Agenda fechada por excecao",
      };
    }
    return {
      fechado: false,
      inicio: excecao.inicio,
      fim: excecao.fim,
      motivo: excecao.motivo ? `Excecao: ${excecao.motivo}` : "Horario especial desta data",
    };
  }

  const feriado = agendaFeriados.find((item) => item.data === dataIso);
  if (feriado) {
    const descricao = (feriado.descricao || "").trim();
    return {
      fechado: true,
      inicio: "00:00",
      fim: "00:00",
      motivo: descricao ? `Feriado: ${descricao}` : "Feriado",
    };
  }

  const data = new Date(`${dataIso}T00:00:00`);
  const diaSemanaJs = data.getDay(); // 0=Dom, 1=Seg...
  const diaKey: DiaSemanaKey = (diaSemanaJs === 0 ? "7" : String(diaSemanaJs)) as DiaSemanaKey;
  const cfg = agendaSemanal[diaKey] || DEFAULT_AGENDA_SEMANAL[diaKey];

  if (!cfg.ativo) {
    return {
      fechado: true,
      inicio: cfg.inicio,
      fim: cfg.fim,
      motivo: "Agenda fechada",
    };
  }

  return {
    fechado: false,
    inicio: cfg.inicio,
    fim: cfg.fim,
    motivo: "",
  };
};

export const slotDentroDaJornada = (
  hora: string,
  jornada: { fechado: boolean; inicio: string; fim: string }
) => {
  if (jornada.fechado) return false;
  const horaMin = horarioParaMinutos(hora);
  const inicioMin = horarioParaMinutos(jornada.inicio);
  const fimMin = horarioParaMinutos(jornada.fim);
  if (horaMin === null || inicioMin === null || fimMin === null) return false;
  return horaMin >= inicioMin && horaMin < fimMin;
};

export const validarHorarioAgendamento = (
  inicio: Date,
  fim: Date,
  agendaSemanal: AgendaSemanalConfig,
  agendaFeriados: AgendaFeriadoConfig[],
  agendaExcecoes: AgendaExcecaoConfig[] = []
): { valido: boolean; motivo: string } => {
  if (Number.isNaN(inicio.getTime()) || Number.isNaN(fim.getTime())) {
    return { valido: false, motivo: "Data ou hora invalida." };
  }
  if (fim.getTime() <= inicio.getTime()) {
    return { valido: false, motivo: "O horario final deve ser maior que o inicial." };
  }

  const dataInicio = toDateInput(inicio);
  const dataFim = toDateInput(fim);
  if (dataInicio !== dataFim) {
    return { valido: false, motivo: "O agendamento deve iniciar e terminar no mesmo dia." };
  }

  const jornada = obterJornadaDia(dataInicio, agendaSemanal, agendaFeriados, agendaExcecoes);
  if (jornada.fechado) {
    return { valido: false, motivo: jornada.motivo || "Agenda fechada neste dia." };
  }

  const inicioMin = inicio.getHours() * 60 + inicio.getMinutes();
  const fimMin = fim.getHours() * 60 + fim.getMinutes();
  const inicioJornadaMin = horarioParaMinutos(jornada.inicio);
  const fimJornadaMin = horarioParaMinutos(jornada.fim);

  if (inicioJornadaMin === null || fimJornadaMin === null) {
    return { valido: false, motivo: "Horario de funcionamento invalido nas configuracoes." };
  }

  if (inicioMin < inicioJornadaMin || fimMin > fimJornadaMin) {
    return {
      valido: false,
      motivo: `Horario fora do funcionamento da agenda (${jornada.inicio} as ${jornada.fim}).`,
    };
  }

  return { valido: true, motivo: "" };
};
