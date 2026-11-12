export const formatarMoeda = (valor: number | null | undefined): string =>
  Number(valor || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const formatarNumero = (valor: number | null | undefined, casas = 2): string =>
  Number(valor || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });

export const formatarPercentual = (valor: number | null | undefined): string =>
  `${formatarNumero(valor || 0, 2)}%`;

export const formatarDataPtBr = (valor: string | null | undefined): string => {
  return formatCalendarDate(valor);
};

export const dateToIsoLocal = (value: Date): string => {
  const ano = value.getFullYear();
  const mes = `${value.getMonth() + 1}`.padStart(2, "0");
  const dia = `${value.getDate()}`.padStart(2, "0");
  return `${ano}-${mes}-${dia}`;
};
import { formatCalendarDate } from "@/lib/calendar-date";

