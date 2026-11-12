import { isEchoNarrativeHypothetical, isPreviousExamUnavailable, withoutPreviousExamAvailabilityModal } from "./echo-previous-exam-availability";
import { ambiguousEchoLengthKeys, echoLengthInMm } from "./echo-unit-provenance";

export type EchoNumericNarrativeKey =
  | "FE" | "FEC" | "AE_Ao" | "Aorta" | "Atrio_esquerdo"
  | "DIVEd" | "SIVd" | "PLVEd" | "DIVES" | "SIVs" | "PLVES"
  | "DIVEd_2D" | "SIVd_2D" | "PLVEd_2D" | "DIVES_2D" | "SIVs_2D" | "PLVES_2D"
  | "Vmax_aorta" | "Vmax_pulmonar" | "Vmax_VSVE" | "Vmax_VSVD";

export type EchoNumericNarrativeDiscrepancy = {
  key: EchoNumericNarrativeKey;
  message: string;
  section: string;
  excerpt: string;
  suggestion: string;
};

type Kind = "length" | "velocity" | "ratio" | "percentage";
type Metric = { key: EchoNumericNarrativeKey; measure: string; label: string; pattern: string; kind: Kind };
type Mode = "modo_m" | "2d";
type WrittenMode = Mode | "ambiguous";
const DIMENSIONS = [
  ["DIVEd", "DIVEd", String.raw`\b(?:dived|lvidd)\b`],
  ["SIVd", "SIVd", String.raw`\b(?:sivd|ivsd)\b`],
  ["PLVEd", "PLVEd", String.raw`\b(?:plved|ppved|lvpwd)\b`],
  ["DIVES", "DIVEs", String.raw`\b(?:dives|lvids)\b`],
  ["SIVs", "SIVs", String.raw`\b(?:sivs|ivss)\b`],
  ["PLVES", "PLVEs", String.raw`\b(?:plves|ppves|lvpws)\b`],
] as const;
const SECTIONS: Record<string, string> = {
  valvas: "Valvas", camaras: "Câmaras", funcao: "Função", vasos: "Vasos", pericardio: "Pericárdio",
  ad_vd: "Câmaras direitas", funcao_diastolica: "Função diastólica", funcao_sistolica: "Função sistólica",
  atrio_esquerdo: "Átrio esquerdo", ventriculo_esquerdo: "Ventrículo esquerdo",
};
const NUMBER = String.raw`(?<written>\d+(?:[.,]\d+)?)`;
const LINK = String.raw`\s*(?:(?:de|em|=|:|foi|e|igual\s+a)\s*)?`;
const METHOD = String.raw`(?:\s*\(?\s*(?:2d|(?:em\s+)?modo\s*m)\s*\)?)?`;

function normalized(text: string): string {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}
function positive(value: unknown): number | null {
  const text = String(value ?? "").trim().replace(",", ".");
  if (!/^\+?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text)) return null;
  const valueNumber = Number(text);
  return Number.isFinite(valueNumber) && valueNumber > 0 ? valueNumber : null;
}
function selectedMode(values: Record<string, string>): Mode | null {
  if (values.VE_tecnica_relatorio === "modo_m" || values.VE_tecnica_relatorio === "2d") return values.VE_tecnica_relatorio;
  const has = (suffix: string) => [...DIMENSIONS.map(([key]) => key), "FE_Teicholz", "DeltaD_FS"]
    .some((key) => positive(values[key + suffix]) !== null);
  const m = has("");
  const twoD = has("_2D");
  return m === twoD ? null : twoD ? "2d" : "modo_m";
}
function metricsFor(mode: Mode | null): Metric[] {
  const metrics: Metric[] = [];
  if (mode) {
    const suffix = mode === "2d" ? "_2D" : "";
    metrics.push(
      { key: "FE", measure: `FE_Teicholz${suffix}`, label: "FE", pattern: String.raw`\bfracao\s+de\s+ejecao\b[^\d.%\n+-]{0,50}?`, kind: "percentage" },
      { key: "FEC", measure: `DeltaD_FS${suffix}`, label: "FEC", pattern: String.raw`\bfracao\s+de\s+encurtamento\b[^\d.%\n+-]{0,50}?`, kind: "percentage" },
    );
  }
  metrics.push({ key: "AE_Ao", measure: "AE_Ao", label: "AE/Ao", pattern: String.raw`\bae\s*\/\s*ao(?![a-z])`, kind: "ratio" });
  if (mode) for (const [key, label, pattern] of DIMENSIONS) {
    const measure = `${key}${mode === "2d" ? "_2D" : ""}` as EchoNumericNarrativeKey;
    metrics.push({ key: measure, measure, label, pattern, kind: "length" });
  }
  metrics.push(
    { key: "Aorta", measure: "Aorta", label: "Aorta", pattern: String.raw`\b(?:raiz\s+(?:da\s+)?aorta|aorta)\b`, kind: "length" },
    { key: "Atrio_esquerdo", measure: "Atrio_esquerdo", label: "Átrio esquerdo", pattern: String.raw`\batrio\s+esquerdo\b`, kind: "length" },
    { key: "Vmax_aorta", measure: "Vmax_aorta", label: "Velocidade aórtica", pattern: String.raw`\b(?:vmax\s+(?:aorta|aortic[oa])|velocidade\s+(?:maxima\s+)?(?:aortic[oa]|(?:da\s+)?aorta|(?:do\s+)?fluxo\s+aortico))\b`, kind: "velocity" },
    { key: "Vmax_pulmonar", measure: "Vmax_pulmonar", label: "Velocidade pulmonar", pattern: String.raw`\b(?:vmax\s+(?:da\s+)?(?:arteria\s+)?pulmonar|velocidade\s+(?:maxima\s+)?(?:do\s+fluxo\s+|da\s+arteria\s+)?pulmonar)\b`, kind: "velocity" },
    { key: "Vmax_VSVE", measure: "Vmax_VSVE", label: "Velocidade da via de saída do VE", pattern: String.raw`\b(?:vmax|velocidade(?:\s+maxima)?)\s+(?:da\s+)?(?:via\s+de\s+saida\s+(?:do\s+)?(?:ve|ventriculo\s+esquerdo)|vsve|lvot)\b`, kind: "velocity" },
    { key: "Vmax_VSVD", measure: "Vmax_VSVD", label: "Velocidade da via de saída do VD", pattern: String.raw`\b(?:vmax|velocidade(?:\s+maxima)?)\s+(?:da\s+)?(?:via\s+de\s+saida\s+(?:do\s+)?(?:vd|ventriculo\s+direito)|vsvd|rvot)\b`, kind: "velocity" },
  );
  return metrics;
}
function literalPattern(metric: Metric): RegExp {
  const unit = metric.kind === "length" ? String.raw`\s*(?<unit>mm|cm)\b(?!\s*(?:[\/^²³]|h(?:g|2o)\b))`
    : metric.kind === "velocity" ? String.raw`\s*(?<unit>cm\s*\/\s*s|m\s*\/\s*s)\b`
    : metric.kind === "percentage" ? String.raw`\s*(?<unit>%)`
    : String.raw`(?!\d|[.,]\d|\s*(?:%|(?:mm|cm|m\s*\/\s*s)\b))`;
  return new RegExp(`${metric.pattern}${metric.kind === "length" ? METHOD : ""}${LINK}${NUMBER}${unit}`, "g");
}
const PREVIOUS_EXAM = /\b(?:exame|estudo|laudo|avaliacao)\s+(?:anterior|previo|previa|passado|(?:de|em)\s+\d)/;
function historical(text: string): boolean {
  return /\b(?:historico|historica|historia|previamente|anteriormente)\b/.test(text) || PREVIOUS_EXAM.test(text);
}
function historicalPassage(text: string): boolean {
  // Clinical history qualifies its own clause; only an explicit history header
  // or a previous examination can carry old measurements into later clauses.
  if (/^(?:historico|historia)\s*:/.test(text)) return true;
  const previous = PREVIOUS_EXAM.exec(text);
  if (!previous) return false;
  const before = text.slice(0, previous.index);
  const after = text.slice(previous.index + previous[0].length);
  return !isPreviousExamUnavailable(before, after);
}
function reference(text: string): boolean {
  return /\b(?:referencias?|limites?|faixas?|intervalos?)\b/.test(text);
}
function hypothetical(text: string): boolean {
  return isEchoNarrativeHypothetical(text);
}
function limitation(text: string): boolean {
  return /\b(?:desconsiderad|descartad|invalid|incorret|indeterminad|inconclusiv|limitad)[oa]s?\b|\bartefato\b|\ba\s+confirmar\b/.test(text)
    || /\bnao\s+(?:(?:foi|foram|e|sao|esta|estao|pode|puderam)\s+)?(?:confirmad|mensurad|medid|observad|valid|avaliad|interpretad)[oa]s?\b/.test(text)
    || /\bnao\s+(?:mensurave(?:l|is)|interpretave(?:l|is)|avaliave(?:l|is))\b|\bsem\s+(?:(?:possibilidade|condicoes)\s+de\s+)?(?:mensuracao|confirmacao|avaliacao|interpretacao)\b/.test(text);
}
function isolatedImage(text: string): boolean {
  return /\b(?:imagem|imagens|fotografia|foto)\b|\b(?:ciclo|batimento)\s+(?:isolado|unico|individual)\b/.test(text);
}
function clauses(text: string): string[] {
  // Delimit independent subjects, retaining decimal commas and paired labels.
  return text.split(/;|,(?!\d)|\s+\b(?:mas|porem|contudo|entretanto|todavia)\b\s+|\s+e\s+(?=(?:(?:a|o|as|os)\s+)?(?:ae\s*\/|dived\b|dives\b|siv[ds]\b|plve[ds]\b|aorta\b|atrio\b|vmax\b|velocidade\b|fracao\b|nao\b|sem\b))/)
    .map((clause) => clause.trim()).filter(Boolean);
}
function currentExam(text: string): boolean {
  return /\b(?:atualmente|agora|nest[ea]\s+(?:exame|estudo|laudo|avaliacao)|(?:(?:no|na)\s+)?(?:exame|estudo|laudo|avaliacao)\s+atual|valor\s+atual)\b/.test(text);
}
function relevantLimitation(text: string, metric: Metric): boolean {
  if (!limitation(text)) return false;
  const ownLabel = new RegExp(metric.pattern).test(text)
    || (metric.key === "FE" && /\bfe\b/.test(text)) || (metric.key === "FEC" && /\bfec\b/.test(text));
  // A named limitation of another parameter/domain is not an adjacent limit
  // on this literal. A subjectless limitation can still qualify its neighbour.
  const otherSubject = /\b(?:diastolic[ao]|tecidual|ae\s*\/\s*ao|dived|dives|siv[ds]|plve[ds]|aorta|atrio\s+esquerdo|vmax|velocidade|fracao|fe|fec)\b/.test(text);
  return ownLabel || !otherSubject;
}
function describedMode(text: string): WrittenMode | null {
  const twoD = /\b2d\b/.test(text);
  const m = /\bmodo\s+m\b/.test(text);
  return twoD && m ? "ambiguous" : twoD ? "2d" : m ? "modo_m" : null;
}
function unqualifiedMatches(fragment: string, metric: Metric, headerMode: WrittenMode | null = null): RegExpMatchArray[] {
  const parts = clauses(fragment);
  const matches: RegExpMatchArray[] = [];
  let inheritedContext = false;
  let narrativeMode = headerMode;
  for (const [index, part] of parts.entries()) {
    const declaredMode = describedMode(part);
    if (declaredMode) narrativeMode = declaredMode;
    if (currentExam(part)) inheritedContext = false;
    // A failed acquisition of the prior exam qualifies only this clause;
    // "possível" here must not become an inherited hypothetical header.
    const previous = PREVIOUS_EXAM.exec(part);
    if (previous && isPreviousExamUnavailable(part.slice(0, previous.index), part.slice(previous.index + previous[0].length))) {
      const hypothesis = withoutPreviousExamAvailabilityModal(part.slice(0, previous.index)) + part.slice(previous.index);
      if (hypothetical(hypothesis)) inheritedContext = true;
      continue;
    }
    if (historicalPassage(part) || reference(part) || hypothetical(part)) inheritedContext = true;
    if (inheritedContext || historical(part) || relevantLimitation(part, metric)) continue;
    // The selected M/2D family still stores Teicholz EF. An explicitly named
    // Simpson EF is a different calculation, including uni/biplanar variants.
    if (metric.key === "FE" && /\bsimpson\b/.test(part)) continue;
    for (const match of part.matchAll(literalPattern(metric))) {
      const suffix = part.slice((match.index || 0) + match[0].length);
      if (/^\s*(?:(?:a|ate|[-–—])\s*[+-]?\d|(?:±|\+\s*\/\s*-)\s*\d)/.test(suffix)) continue;
      // A stated percentage bound is not a point measurement. Only the
      // established aortic-velocity path below evaluates an explicit inequality.
      if (metric.kind === "percentage" && (
        /[<>≤≥]|\b(?:superior|inferior|maior|menor|acima|abaixo|ate)\b|\b(?:pelo|ao)\s+menos\b|\bno\s+(?:minimo|maximo)\b/.test(match[0])
        || /^\s*(?:ou\s+(?:mais|menos)|(?:e\s+)?(?:acima|abaixo))\b/.test(suffix)
      )) continue;
      const prefix = part.slice(0, match.index);
      if (metric.kind === "length" && /\b(?:velocidade|vmax|fluxo)\b/.test(prefix)) continue;
      // A negative independent finding cannot negate this explicit value.
      if (/\bnao\b/.test(prefix) && !/\bnao\s+(?:(?:ha|apresenta|mostra|existe)\s+)?(?:evidencia\s+de\s+)?(?:refluxo|derrame|obstrucao|comunicacao)\b/.test(prefix)) continue;
      const before = parts[index - 1] || "";
      const after = parts[index + 1] || "";
      if ((relevantLimitation(before, metric) && !/\d/.test(before))
          || (relevantLimitation(after, metric) && /^(?:(?:o|a|os|as)\s+)?(?:(?:valor|valores|medida|medidas|ambos|ambas)\s+)?(?:nao|sem|descartad|desconsiderad|invalid|incorret|limitad|indeterminad|inconclusiv|registrad|obtid|medid|aferid)/.test(after))
          || (/^(?:registrad|obtid|medid|aferid)[oa]s?\b/.test(after) && historical(after))) continue;
      const ventricularMetric = /^(?:DIV|SIV|PLVE|FE_Teicholz|DeltaD_FS)/.test(metric.measure);
      if (ventricularMetric && narrativeMode
          && narrativeMode !== (metric.measure.endsWith("_2D") ? "2d" : "modo_m")) continue;
      matches.push(match);
    }
  }
  return matches;
}
function format(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6))).replace(".", ",");
}

/** Literal current text/table check only; never diagnoses or changes its inputs. */
export function findEchoNumericNarrativeDiscrepancies(
  measurements: Record<string, string>, qualitative: object, conclusion: string,
): EchoNumericNarrativeDiscrepancy[] {
  // Only canonical fields actually presented by the table are numeric sources.
  // Raw legacy aliases stay historical; a cleared canonical never falls back.
  const values = measurements;
  const ambiguous = ambiguousEchoLengthKeys(values);
  const metrics = metricsFor(selectedMode(values));
  const sources = [...Object.entries(qualitative).filter((entry): entry is [string, string] => typeof entry[1] === "string")
    .map(([key, text]) => ({ section: SECTIONS[key] || key, text })), { section: "Conclusão", text: conclusion }];
  const results: EchoNumericNarrativeDiscrepancy[] = [];
  for (const metric of metrics) {
    if (metric.kind === "length" && ambiguous.has(metric.measure)) continue;
    const measured = metric.kind === "length" ? echoLengthInMm(values, metric.measure) : positive(values[metric.measure]);
    if (measured === null) continue;
    let found = false;
    for (const source of sources) {
      let contextualHeader = false;
      let headerMode: WrittenMode | null = null;
      for (const original of source.text.split(/[\r\n]+|(?<=[.!?])\s+/)) {
        const excerpt = original.trim();
        const text = normalized(excerpt);
        if (currentExam(text)) { contextualHeader = false; headerMode = null; }
        if (/^(?:em\s+)?(?:modo\s*)?(?:2d|m)\s*[:.]?$/.test(text)) headerMode = describedMode(text);
        if ((historicalPassage(text) && !currentExam(text)) || /^(?:historico|historia|referencias?|hipotese)\s*:\s*$/.test(text)) contextualHeader = true;
        if (!text || contextualHeader || isolatedImage(text) || /\?\s*$/.test(text)) continue;
        for (const match of unqualifiedMatches(text, metric, headerMode)) {
          if (!match?.groups) continue;
          const written = positive(match.groups.written);
          if (written === null) continue;
          const unit = (match.groups.unit || "").replace(/\s+/g, "");
          const factor = unit === "cm" ? 10 : unit === "cm/s" ? 0.01 : 1;
          const decimals = match.groups.written.split(/[.,]/)[1]?.length || 0;
          const tolerance = metric.kind === "percentage" ? 1 : 0.5 * 10 ** -decimals * factor;
          const difference = Math.abs(written * factor - measured);
          if (difference <= tolerance + Number.EPSILON * Math.max(1, measured) * 8) continue;
          const suffix = metric.kind === "length" ? " mm" : metric.kind === "velocity" ? " m/s" : metric.kind === "percentage" ? "%" : "";
          results.push({ key: metric.key, section: source.section, excerpt,
            message: `${metric.label}: o texto cita ${format(written * factor)}${suffix}, enquanto a tabela selecionada mostra ${format(measured)}${suffix}.`,
            suggestion: "Confira o valor e o método descritos neste trecho com a medida selecionada na tabela. Revise manualmente o texto ou a medida, se necessário." });
          found = true;
          break;
        }
        if (found) break;
      }
      if (found) break;
    }
  }
  // Retain the established explicit aortic upper-claim check, with the same
  // local qualification rules and its own acquisition site.
  if (!results.some((item) => item.key === "Vmax_aorta")) {
    const measured = positive(values.Vmax_aorta);
    const upper: Metric = { key: "Vmax_aorta", measure: "Vmax_aorta", label: "Velocidade aórtica", kind: "velocity",
      pattern: String.raw`\bvelocidade\s+(?:maxima\s+)?aortica\b[^.\n\d]{0,50}?\b(?:superior|acima)\s+a` };
    if (measured !== null) for (const source of sources) {
      let found = false;
      let historicalHeader = false;
      for (const original of source.text.split(/[\r\n]+|(?<=[.!?])\s+/)) {
        const excerpt = original.trim(); const text = normalized(excerpt);
        if (currentExam(text)) historicalHeader = false;
        if ((historicalPassage(text) && !currentExam(text)) || /^(?:historico|historia|referencias?|hipotese)\s*:\s*$/.test(text)) historicalHeader = true;
        if (historicalHeader || isolatedImage(text) || /\?\s*$/.test(text)) continue;
        for (const claim of unqualifiedMatches(text, upper)) {
          const threshold = positive(claim.groups?.written);
          if (threshold === null || measured > threshold || claim.groups?.unit.replace(/\s+/g, "") !== "m/s") continue;
          results.push({ key: "Vmax_aorta", section: source.section, excerpt,
            message: `O texto cita velocidade aórtica acima de ${format(threshold)} m/s; a tabela mostra Vmax aorta de ${format(measured)} m/s. Confirme o local da medida e documente-o se for distinto.`,
            suggestion: "Confirme o local de aquisição da velocidade aórtica e revise manualmente a afirmação numérica deste trecho." });
          found = true; break;
        }
        if (found) break;
      }
      if (found) break;
    }
  }
  return results;
}
