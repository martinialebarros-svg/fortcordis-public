/** A range may include a juvenile without establishing a precise age for a
 * pediatric interval. Keep punctuation: "1–2 meses" must never become 12 months. */
export function felineAgeRangeMayIncludeJuvenile(age: unknown): boolean {
  const text = String(age ?? "").trim().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/\s*\(estimada\)$/, "");
  const range = /^(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*(anos?|years?|a|y|mes(?:es)?|months?|m|dias?|days?|d|semanas?|weeks?|w)$/.exec(text);
  if (!range) return false;
  const lower = Number(range[1].replace(",", "."));
  const unit = range[3];
  const months = lower * (/^(?:a|y)/.test(unit) ? 12 : /^m/.test(unit) ? 1 : /^(?:s|w)/.test(unit) ? 7 / 30.4375 : 1 / 30.4375);
  return Number.isFinite(months) && months < 12;
}
