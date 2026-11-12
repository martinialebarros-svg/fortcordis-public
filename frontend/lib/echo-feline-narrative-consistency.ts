import { isEchoNarrativeHypothetical, isPreviousExamUnavailable, withoutPreviousExamAvailabilityModal } from "./echo-previous-exam-availability";
import { isFelineEchoSpecies, normalizeEchoSpecies } from "./echo-species";

export type FelineNarrativeDiscrepancy = {
  key: "feline_transmitral_fusion" | "feline_tissue_fusion";
  message: string;
  section: string;
  excerpt: string;
  suggestion: string;
};

export type EchoWaveNarrativeDiscrepancy = Omit<FelineNarrativeDiscrepancy, "key"> & {
  key: FelineNarrativeDiscrepancy["key"] | "canine_transmitral_fusion" | "canine_tissue_fusion";
};

function normalized(text: string): string {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[′’‘´`]/g, "'").toLowerCase();
}

const SECTION_LABELS: Record<string, string> = {
  valvas: "Valvas", camaras: "Câmaras", funcao: "Função",
  funcao_diastolica: "Função diastólica", funcao_sistolica: "Função sistólica",
  pericardio: "Pericárdio", vasos: "Vasos", ad_vd: "Câmaras direitas",
};

/** Only explicit, current assertions are candidates. Ambiguous/qualified prose
 * is left to the clinician; this is deliberately not a general text classifier. */
function isQualified(text: string): boolean {
  return /\b(?:nao|impossivel|limitad[oa]s?|indeterminad[oa]s?|inconclusiv[oa]s?|fundid[oa]s?|fusionad[oa]s?|sobreposicao|descartad[oa]s?|desconsiderad[oa]s?|invalid[oa]s?|incorret[oa]s?|artefato)\b/.test(text)
    || /\bsem\s+(?:(?:possibilidade|condicoes)\s+de\s+)?(?:mensuracao|interpretacao|separacao|individualizacao|avaliacao)\b/.test(text)
    || /\b(?:historia|historico|historica|historicos|historicas|previamente|anteriormente|importad[oa]s?)\b/.test(text)
    || /\b(?:exame|estudo|avaliacao|laudo)\s+(?:anterior|previo|previa|passado)\b/.test(text)
    || /\b(?:exame|estudo|avaliacao|laudo)\s+(?:de|em)\s+(?:\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}|\d{4})\b/.test(text)
    || /\b(?:caso|quando|when|poderia|poderiam|possivel|possivelmente|hipotese|suspeita)\b/.test(text)
    || /(?:^|[\s(,;:])se\s+/.test(text)
    || /\?\s*$/.test(text)
    || /^(?:[-•]\s*)?(?:avaliar|verificar|confirmar|revisar)\b/.test(text);
}

const E_A = String.raw`(?<![\w'])e\s*\/\s*a(?![\w'])`;
const E_E = String.raw`(?<![\w'])e\s*\/\s*e\s*'(?!\w)`;
const E_TRIV = String.raw`(?<![\w'])e\s*\/\s*(?:triv|ivrt)\b`;
const TDI_RATIO = String.raw`\be\s*'\s*\/\s*a\s*'(?!\w)`;
const NUMERIC = String.raw`(?:\s*(?:de|em|igual\s+a|foi|e|=|:)\s*)?\s*\d+(?:[.,]\d+)?`;
const PREDICATE = String.raw`\s*(?:(?:e|esta|mostra|encontra-se)\s+)?(?:(?:aparentemente|acentuadamente|discretamente|marcadamente)\s+)?(?:normal|invertida|aumentada|elevada|reduzida|preservada)\b`;
const E_A_PAIR = String.raw`(?:e\s*(?:e|\/)\s*a)(?![\w'])`;
const TDI_PAIR = String.raw`(?:e\s*'\s*(?:e|\/)\s*a\s*')`;
// A velocity unit makes a bare E/A label unambiguous. Exclude ratios and
// apostrophes so an isolated transmitral peak never captures a tissue peak.
const TRANSMITRAL_PEAK = String.raw`(?<![\w'/])\b[ea](?![\w'/])${NUMERIC}\s*(?:m\/s|cm\/s)\b`;

function individualTransmitralPeakClaim(text: string): boolean {
  return [...text.matchAll(new RegExp(TRANSMITRAL_PEAK, "g"))]
    .some((match) => !/\/\s*$/.test(text.slice(0, match.index)));
}

function ratioClaim(text: string, ratio: string): boolean {
  return new RegExp(`${ratio}${NUMERIC}`).test(text)
    || new RegExp(`\\brelacao\\s+${ratio}${PREDICATE}`).test(text)
    || new RegExp(`\\b(?:inversao|elevacao|reducao)\\s+da\\s+relacao\\s+${ratio}`).test(text);
}

function separatedClaim(text: string, pair: string): boolean {
  return new RegExp(`\\b(?:ondas|picos)\\s+${pair}\\s+(?:(?:estao|sao|bem)\\s+)?(?:separad[oa]s|individualizad[oa]s|mensuraveis)\\b`).test(text);
}

function transmitralClaim(text: string): boolean {
  return separatedClaim(text, E_A_PAIR)
    || individualTransmitralPeakClaim(text)
    || ratioClaim(text, E_A) || ratioClaim(text, E_E) || ratioClaim(text, E_TRIV)
    || /\bpadrao\s+(?:de\s+enchimento\s+)?[^\n]{0,110}\b(?:normal|adequado|restritivo|pseudonormal)\b[^\n]{0,80}\b(?:doppler|fluxo)\s+transmitral\b/.test(text)
    || /\b(?:doppler|fluxo)\s+transmitral\b[^\n]{0,60}\bpadrao\s+(?:de\s+enchimento\s+)?(?:normal|adequado|restritivo|pseudonormal)\b/.test(text);
}

function tissueClaim(text: string): boolean {
  return separatedClaim(text, TDI_PAIR) || ratioClaim(text, TDI_RATIO) || ratioClaim(text, E_E)
    || /\b[ea]\s*'\s*(?:(?:lateral|septal)\s*)?(?:de|=|:)?\s*\d+(?:[.,]\d+)?\s*(?:m\/s|cm\/s)\b/.test(text);
}

type NarrativeClause = { text: string; boundary: string };

function narrativeClauses(text: string): NarrativeClause[] {
  // Commas inside decimal values belong to the claim. A conjunction starts a
  // new clause only before an explicit subject/claim, never inside "E e A".
  const boundary = /;|,(?!\d)|\s+\b(?:mas|porem|contudo|entretanto|todavia)\b\s+|\s+e\s+(?=(?:(?:a|o|as|os)\s+)?(?:relacao\b|onda\b|pico\b|doppler\b|fluxo\b|padrao\b|nao\b|sem\b)|[ea]\s*(?:'|[=:]|(?:de\s+)?\d))/g;
  const clauses: NarrativeClause[] = [];
  let start = 0;
  let previousBoundary = "";
  for (const match of text.matchAll(boundary)) {
    if (/^\s+e\s+/.test(match[0]) && /\b[ea]\s*'\s*$/.test(text.slice(start, match.index))) continue;
    clauses.push({ text: text.slice(start, match.index).trim(), boundary: previousBoundary });
    start = match.index + match[0].length;
    previousBoundary = match[0];
  }
  clauses.push({ text: text.slice(start).trim(), boundary: previousBoundary });
  return clauses;
}

function isContextHeader(text: string): boolean {
  return isHistoricalContext(text)
    || /\b(?:quando|when|caso|hipotese|suspeita)\b/.test(text)
    || /^(?:[-•]\s*)?(?:se|avaliar|verificar|confirmar|revisar)\b/.test(text);
}

const PREVIOUS_EXAM = /\b(?:exame|estudo|avaliacao|laudo)\s+(?:anterior|previo|previa|passado|(?:de|em)\s+(?:\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}|\d{4}))\b/;

function isHistoricalContext(text: string): boolean {
  // Antecedents qualify their own clause. Persist only an explicit historical
  // heading or previous examination, never the absence of that examination.
  if (/^(?:[-•]\s*)?(?:(?:historia|historico|historicos|historicas)\s*:|(?:previamente|anteriormente)\s*:?\s*$)/.test(text)) return true;
  const previous = PREVIOUS_EXAM.exec(text);
  if (!previous) return false;
  const before = text.slice(0, previous.index);
  const after = text.slice(previous.index + previous[0].length);
  return !isPreviousExamUnavailable(before, after);
}

function isCurrentExamContext(text: string): boolean {
  return /\b(?:atualmente|agora|nest[ea]\s+(?:exame|estudo|laudo|avaliacao)|(?:(?:no|na)\s+)?(?:exame|estudo|laudo|avaliacao)\s+atual|valor\s+atual)\b/.test(text);
}

function isQualificationContinuation(text: string): boolean {
  // A following limitation may qualify the preceding value. An unrelated
  // negative finding (e.g. "não há refluxo") must not qualify that value.
  return /^(?:(?:e|mas|porem|contudo)\s+)?(?:(?:ambos|ambas|todos|todas|valores|picos|medidas|relacoes)\s+)?(?:(?:nao\s+(?:(?:e|sao|esta|estao|foi|foram)\s+)?(?:mensurave(?:l|is)|interpretave(?:l|is)|avaliave(?:l|is)|valid[oa]|individualizad|separad))|impossivel|limitad[oa]|indeterminad[oa]|inconclusiv[oa]|fundid[oa]|fusionad[oa]|sobreposicao|descartad[oa]|desconsiderad[oa]|invalid[oa]|incorret[oa]|artefato|sem\s+(?:(?:possibilidade|condicoes)\s+de\s+)?(?:mensuracao|interpretacao|separacao|individualizacao|avaliacao))/.test(text)
    || (/^(?:(?:registrad|obtid|medid|aferid|calculad|avaliad|importad)[oa]s?|previamente|anteriormente)\b/.test(text) && isQualified(text))
    || (/^(?:com|por|devido\s+a)\s+(?:(?:as|os)\s+)?(?:ondas|picos|medidas|valores|relacoes|fusao|sobreposicao|artefato)\b/.test(text) && isQualified(text));
}

function continuationTargetsClaim(text: string, claim: (text: string) => boolean, preceding: string): boolean {
  // Bind an explicit subject to its own family. Only a subjectless limitation
  // can qualify the preceding value by proximity alone.
  if (/\bfuncao\s+sistolica\b/.test(text)) return false;
  if (new RegExp(E_E).test(text) || ratioClaim(preceding, E_E)) return true; // E/e′ depends on both families.
  const targetsTissue = /\b(?:tecidual|tdi)\b|\b[ea]\s*'/.test(text);
  const targetsTransmitral = /\btransmitral\b/.test(text)
    || new RegExp(`${E_A}|${E_TRIV}|\\b(?:onda|pico)s?\\s+[ea](?![\\w'])`).test(text);
  return claim === transmitralClaim ? !targetsTissue || targetsTransmitral : !targetsTransmitral || targetsTissue;
}

function isPluralQualification(text: string): boolean {
  return /\b(?:ambos|ambas|todos|todas|valores|picos|medidas|relacoes|mensuraveis|interpretaveis|avaliaveis|(?:valid|individualizad|separad|limitad|indeterminad|inconclusiv|fundid|fusionad|descartad|desconsiderad|invalid|incorret)[oa]s)\b/.test(text);
}

function hasUnqualifiedClaim(text: string, claim: (text: string) => boolean): boolean {
  if (/\?\s*$/.test(text)) return false;
  const clauses = narrativeClauses(text);
  const anyClaim = (value: string) => transmitralClaim(value) || tissueClaim(value);
  let inheritedContext = false;
  let historicalContext = false;
  for (const [index, clause] of clauses.entries()) {
    // Punctuation alone does not end a historical exam. Conditional headers
    // apply to their clause group; returning to the current exam is explicit.
    if (clause.boundary.includes(";") || /\b(?:mas|porem|contudo|entretanto|todavia)\b/.test(clause.boundary)) inheritedContext = false;
    const currentExam = isCurrentExamContext(clause.text);
    if (currentExam) {
      inheritedContext = false;
      historicalContext = false;
    }
    const previousExam = PREVIOUS_EXAM.exec(clause.text);
    if (previousExam && isPreviousExamUnavailable(clause.text.slice(0, previousExam.index), clause.text.slice(previousExam.index + previousExam[0].length))) {
      const hypothesis = withoutPreviousExamAvailabilityModal(clause.text.slice(0, previousExam.index)) + clause.text.slice(previousExam.index);
      if (isEchoNarrativeHypothetical(hypothesis)) inheritedContext = true;
      continue;
    }
    if (isHistoricalContext(clause.text)) historicalContext = true;
    if (!anyClaim(clause.text) && isContextHeader(clause.text)) inheritedContext = true;
    const previous = clauses[index - 1];
    // A leading limitation belongs only to the adjacent claim, in its own
    // family. Never turn it into a sentence-wide historical/conditional header.
    const qualifiedBefore = !currentExam && clause.boundary === "," && previous
      && !anyClaim(previous.text) && isQualificationContinuation(previous.text)
      && continuationTargetsClaim(previous.text, claim, clause.text);
    if (historicalContext || inheritedContext || qualifiedBefore || !claim(clause.text) || isQualified(clause.text)) continue;

    let qualifiedAfter = false;
    for (let next = index + 1; next < clauses.length; next++) {
      const following = clauses[next];
      if (/\b(?:mas|porem|contudo|entretanto|todavia)\b/.test(following.boundary)) break;
      if (isQualificationContinuation(following.text) && continuationTargetsClaim(following.text, claim, clause.text)) {
        // "Ambos descartados" also qualifies a preceding list of peaks;
        // singular limitations qualify only the immediately preceding claim.
        qualifiedAfter = next === index + 1 || isPluralQualification(following.text);
        break;
      }
      if (!anyClaim(following.text) || isQualified(following.text) || following.boundary.includes(";")) break;
    }
    if (!qualifiedAfter) return true;
  }
  return false;
}

export function findEchoWaveNarrativeDiscrepancies(
  measurements: Record<string, string>, qualitative: object, conclusion: string, species?: string,
): EchoWaveNarrativeDiscrepancy[] {
  const normalizedSpecies = normalizeEchoSpecies(species);
  if (normalizedSpecies !== "Canina" && normalizedSpecies !== "Felina") return [];
  const prefix = normalizedSpecies === "Canina" ? "canine" : "feline";
  const sources = [
    ...Object.entries(qualitative).filter((entry): entry is [string, string] => typeof entry[1] === "string")
      .map(([key, text]) => ({ section: SECTION_LABELS[key] || key, text })),
    { section: "Conclusão", text: conclusion },
  ];
  const families = [
    { key: `${prefix}_transmitral_fusion` as const, active: measurements.Diastolica_ondas === "fundidas", claim: transmitralClaim,
      message: "Ondas E/A registradas como fundidas: revise a afirmação de picos, relações ou padrão transmitral neste trecho.",
      suggestion: "Ondas E e A fundidas, sem mensuração independente dos picos transmitrais e das relações dependentes. A interpretação diastólica deve considerar os demais parâmetros disponíveis." },
    { key: `${prefix}_tissue_fusion` as const, active: measurements.TDI_ondas === "fundidas", claim: tissueClaim,
      message: "Ondas e′/a′ registradas como fundidas: revise a afirmação de picos ou relações teciduais individuais neste trecho.",
      suggestion: "Ondas e′ e a′ fundidas; picos e relações teciduais dependentes não mensuráveis individualmente. A interpretação diastólica deve considerar os demais parâmetros disponíveis." },
  ];
  const results: EchoWaveNarrativeDiscrepancy[] = [];
  for (const family of families) {
    if (!family.active) continue;
    let found = false;
    for (const source of sources) {
      let historicalPassage = false;
      // Decimal points inside values do not split a sentence. Retain the
      // original text for review rather than printing a normalized paraphrase.
      for (const fragment of source.text.split(/[\r\n]+|(?<=[.!?])\s+/)) {
        const excerpt = fragment.trim();
        const text = normalized(excerpt);
        const currentExam = isCurrentExamContext(text);
        if (currentExam) historicalPassage = false;
        if (isHistoricalContext(text) && !currentExam) historicalPassage = true;
        if (!text || historicalPassage || !hasUnqualifiedClaim(text, family.claim)) continue;
        results.push({ key: family.key, section: source.section, excerpt,
          message: `${source.section}: ${family.message}`, suggestion: family.suggestion });
        found = true;
        break;
      }
      if (found) break; // At most one review item per family; avoid repeated warnings.
    }
  }
  return results;
}

/** Preserve the existing feline-only API and its discrepancy keys. */
export function findFelineNarrativeDiscrepancies(
  measurements: Record<string, string>, qualitative: object, conclusion: string, species?: string,
): FelineNarrativeDiscrepancy[] {
  if (!isFelineEchoSpecies(species)) return [];
  return findEchoWaveNarrativeDiscrepancies(measurements, qualitative, conclusion, species)
    .filter((issue): issue is FelineNarrativeDiscrepancy =>
      issue.key === "feline_transmitral_fusion" || issue.key === "feline_tissue_fusion");
}
