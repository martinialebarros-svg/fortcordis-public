import type { FelinePediatricRange } from "../types/referencia-eco";

export function pediatricDisplayNumber(value: string): number | null {
  const text = value.trim();
  if (!/^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:e[+-]?\d+)?$/i.test(text)) return null;
  const number = Number(text.replace(",", "."));
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function pediatricCohortIntervalText(range?: FelinePediatricRange): string | null {
  if (!range || range.status !== "descriptive"
    || range.statistic !== "published_cohort_reference_interval"
    || typeof range.lower !== "number" || !Number.isFinite(range.lower)
    || typeof range.upper !== "number" || !Number.isFinite(range.upper)
    || range.lower >= range.upper) return null;
  const format = (value: number) => value.toFixed(2).replace(".", ",");
  return `${format(range.lower)}–${format(range.upper)}${range.unit ? ` ${range.unit}` : ""}`;
}

/** Display-only position in the published cohort; never an individual diagnosis
 * or a replacement for the neutral comparison stored in the report model. */
export function pediatricComparisonPosition(value: string, range?: FelinePediatricRange) {
  const measured = pediatricDisplayNumber(value);
  if (measured === null || !pediatricCohortIntervalText(range)) return null;
  const lower = range!.lower!;
  const upper = range!.upper!;

  // A cm-to-mm conversion can differ from an equal published boundary by an
  // IEEE-754 rounding step. This tolerance is not a clinical margin.
  const tolerance = Number.EPSILON * Math.max(1, measured, Math.abs(lower), Math.abs(upper)) * 8;
  if (measured < lower - tolerance) {
    return { status: "diminuido", text: "Abaixo da faixa da coorte" } as const;
  }
  if (measured > upper + tolerance) {
    return { status: "aumentado", text: "Acima da faixa da coorte" } as const;
  }
  return { status: "normal", text: "Dentro da faixa da coorte" } as const;
}

export const PEDIATRIC_COMPARISON_COLOR_NOTE = "As cores indicam apenas a posição do valor medido na faixa publicada da coorte pediátrica: verde dentro, vermelho acima e azul abaixo. Os intervalos não são ajustados ao peso e as cores não determinam normalidade, doença ou diagnóstico. Interpretar com a técnica, a morfologia e os demais achados.";
