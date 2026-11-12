/** Availability grammar only. The caller owns previous-exam detection,
 * historical headings and current-exam transitions; no clinical finding is
 * interpreted here. Each phrase must end immediately before, or start just
 * after, the matched previous-exam label. */
const ARTICLE = String.raw`(?:os|as|o|a|uns|umas|um|uma|nenhuns|nenhumas|nenhum|nenhuma)`;
const DE = String.raw`d(?:e|[oa]s?)`;
const LINK = String.raw`(?:${DE}|a|ao|aos|as)`;
const RESOURCE_NOUN = String.raw`(?:acessos?|registros?|copias?|informac(?:ao|oes)|dados?|historico|historia)`;
const RESOURCE = String.raw`(?:${ARTICLE}\s+)?${RESOURCE_NOUN}\s+${LINK}(?:\s+${ARTICLE})?`;
const ACQUIRE = String.raw`(?:obter|acessar|consultar|localizar|recuperar|encontrar|visualizar)`;
const ACTION = String.raw`${ACQUIRE}(?:\s+(?:${RESOURCE}|${ARTICLE}))?`;
const POSSIBILITY = String.raw`(?:${ARTICLE}\s+)?(?:possibilidades?|condic(?:ao|oes))\s+${DE}\s+(?:${RESOURCE}|${ACTION})`;
const OBJECT = String.raw`(?:${RESOURCE}|${POSSIBILITY}|${ARTICLE})`;
const OBJECT_SUFFIX = String.raw`(?:\s+${DE})?(?:\s+${OBJECT})?`;
const POSSESSION = String.raw`(?:tenho|tem|temos|tinha|tinhamos|tinham|tive|teve|tivemos|disponho|dispoe|dispomos|possuo|possui|possuimos|possuem)`;
const EXISTENCE = String.raw`(?:ha|houve|havia|existe|existem|consta|constam)`;
const ABILITY = String.raw`(?:consigo|consegue|conseguimos|conseguem|conseguiu|conseguiram|pude|pudemos|pode|podemos)`;
const COPULA = String.raw`(?:e|esta|estao|foi|foram|era|eram|estava|estavam|sera|serao|seria|seriam)`;
const PARTICIPLE = String.raw`(?:realizad|apresentad|disponibilizad|localizad|fornecid|obtid|encontrad|acessad)[oa]s?`;
const ACCESSIBLE = String.raw`(?:disponive(?:l|is)|acessive(?:l|is))`;
const BEFORE = new RegExp(String.raw`\b(?:sem(?:\s+${OBJECT})?|nao\s+(?:(?:${POSSESSION}|${EXISTENCE})${OBJECT_SUFFIX}|${ABILITY}\s+(?:${ACTION}|${RESOURCE})|${COPULA}\s+possivel\s+(?:${ACTION}|${RESOURCE})|(?:${COPULA}\s+)?(?:${PARTICIPLE}|${ACCESSIBLE})${OBJECT_SUFFIX}))\s*$`);
const AFTER_PURPOSE = String.raw`para\s+(?:comparacao|consulta|revisao)`;
const AFTER_TIME = String.raw`(?:ate\s+(?:o\s+)?momento|no\s+momento|atualmente)`;
const AFTER_COMPLEMENT = String.raw`(?:\s+(?:${AFTER_PURPOSE}(?:\s+${AFTER_TIME})?|${AFTER_TIME}(?:\s+${AFTER_PURPOSE})?))?`;
// A participle prefix may introduce a negated measurement, not an absent exam.
// Accept only a complete availability predicate at a clause/sentence boundary.
const AFTER = new RegExp(String.raw`^\s*(?:(?::|[-–—])\s*)?(?:indisponive(?:l|is)|ausentes?|nao(?:\s+${COPULA})?\s+(?:${ACCESSIBLE}|${PARTICIPLE}))\b${AFTER_COMPLEMENT}\s*(?=$|[.,;!?\r\n])`);

function normalized(text: string): string {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

/** Pure bounded language check; never modifies text, measurements or context. */
export function isPreviousExamUnavailable(before: string, after: string): boolean {
  return BEFORE.test(normalized(before)) || AFTER.test(normalized(after));
}


/** Analysis-only copy: keep hypotheses outside the parsed availability phrase. */
export function withoutPreviousExamAvailabilityModal(before: string): string {
  const text = normalized(before);
  const match = BEFORE.exec(text);
  if (!match) return text;
  return text.slice(0, match.index) + match[0].replace(/\bpossivel\b/g, "")
    + text.slice(match.index + match[0].length);
}


/** Exact original numeric detector; callers supply normalized analysis text. */
export function isEchoNarrativeHypothetical(text: string): boolean {
  return /\b(?:hipotese|suspeita|possivel|possivelmente|poderia|poderiam|caso|quando|when)\b|(?:^|[\s(:,])se\s+/.test(text);
}
