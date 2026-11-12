"use client";

import { useId } from "react";
import { isCanineEchoSpecies, isFelineEchoSpecies } from "@/lib/echo-species";
import {
  evaluatePulmonaryProbability,
  HP_SITE_KEYS,
  makePulmonaryReviewStamp,
  type HPSite,
} from "@/lib/echo-pulmonary-probability";

type Props = {
  species?: string;
  measurements: Record<string, string>;
  onPatch: (patch: Record<string, string>) => void;
};

const SITES: Array<{ site: HPSite; label: string; examples: string }> = [
  {
    site: "ventriculos",
    label: "Ventrículos",
    examples: "Achatamento do septo, especialmente sistólico; hipertrofia ou dilatação do VD; disfunção sistólica do VD. VE pequeno ou hipopreenchido só contribui quando não há cardiopatia esquerda.",
  },
  {
    site: "arteria_pulmonar",
    label: "Artéria pulmonar",
    examples: "Dilatação da artéria pulmonar, distensibilidade reduzida, fluxo pulmonar com aceleração encurtada ou entalhe sistólico, ou pico inicial diastólico da insuficiência pulmonar aumentado. Confirme a aquisição de cada parâmetro.",
  },
  {
    site: "atrio_cava",
    label: "Átrio direito / veia cava caudal",
    examples: "Dilatação do átrio direito e/ou da veia cava caudal. Mais de um sinal neste cartão continua contando como um único sítio anatômico.",
  },
];

const OPTIONAL_METRICS = [
  { key: "HP_RPAD", label: "RPAD informado (%)" },
  { key: "HP_RPA_max", label: "Artéria pulmonar direita: diâmetro máximo sistólico (mm)" },
  { key: "HP_RPA_min", label: "Artéria pulmonar direita: diâmetro mínimo diastólico (mm)" },
  { key: "HP_TA", label: "Tempo de aceleração pulmonar (ms)" },
  { key: "HP_TE", label: "Tempo de ejeção pulmonar (ms)" },
  { key: "HP_IP_inicio", label: "Pico inicial diastólico da insuficiência pulmonar (m/s)" },
] as const;

function metric(value: number | null, unit = ""): string {
  return value === null ? "Não informado" : `${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}${unit}`;
}

/** An opt-in assessment, kept in the same measurement snapshot as the exam.
 * A blank anatomical site is unresolved, never a normal finding. */
export default function EchoPulmonaryHypertension({ species, measurements, onPatch }: Props) {
  const id = useId();
  const assessment = evaluatePulmonaryProbability(measurements, species || "");
  const active = measurements.HP_ativa === "sim";
  const canine = isCanineEchoSpecies(species);
  const feline = isFelineEchoSpecies(species);
  const hasPositiveSite = SITES.some(({ site }) => measurements[HP_SITE_KEYS[site]] === "com_sinais");
  const hasUnassessedSite = SITES.some(({ site }) => !["sem_sinais", "com_sinais"].includes(measurements[HP_SITE_KEYS[site]]));
  const supportEnabled = measurements.HP_suporte_automatico !== "nao";
  const probabilityLabel = assessment.probability === "intermediaria" ? "intermediária" : assessment.probability;
  const trvText = String(measurements.IT_Vmax || "").trim().replace(/,/g, ".");
  const rawTrv = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(trvText) ? Number(trvText) : Number.NaN;
  const recordedTrv = Number.isFinite(rawTrv) && rawTrv > 0 ? rawTrv : null;

  const markRemainingWithoutSigns = () => {
    onPatch(Object.fromEntries(SITES
      .filter(({ site }) => measurements[HP_SITE_KEYS[site]] !== "com_sinais")
      .map(({ site }) => [HP_SITE_KEYS[site], "sem_sinais"])));
  };
  const applySuggestions = () => {
    onPatch(Object.fromEntries(assessment.suggestions.map(({ site }) => [HP_SITE_KEYS[site], "com_sinais"])));
  };

  return (
    <section aria-labelledby={`${id}-title`} className="space-y-4 rounded-xl border border-teal-200 bg-teal-50/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 id={`${id}-title`} className="text-sm font-semibold text-gray-900">Probabilidade de hipertensão pulmonar</h4>
          <p className="mt-1 max-w-3xl text-xs text-gray-600">Avaliação integrada da regurgitação tricúspide e de três sítios anatômicos. A PSAP estimada é complementar.</p>
        </div>
        <label className="flex items-center gap-2 text-sm font-medium text-teal-900">
          <input type="checkbox" checked={active}
            onChange={(event) => onPatch({ HP_ativa: event.target.checked ? "sim" : "", ...(event.target.checked
              ? { HP_suporte_automatico: measurements.HP_suporte_automatico || "sim" } : {}) })}
            className="h-4 w-4 rounded border-teal-300 accent-teal-700" />
          Incluir avaliação de HP neste laudo
        </label>
      </div>

      {active && <>
        {!canine && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950">
          {feline ? "Em felinos, esta seção registra os achados de forma descritiva. A classificação de probabilidade canina do consenso ACVIM não está validada para gatos."
            : "A classificação de probabilidade do consenso ACVIM foi estabelecida para cães. Para esta espécie, registre os achados de forma descritiva."}
        </p>}

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label htmlFor={`${id}-trv`} className="block text-xs font-medium text-gray-700">Aquisição da regurgitação tricúspide</label>
            <select id={`${id}-trv`} value={measurements.HP_TRV || ""} onChange={(event) => onPatch({ HP_TRV: event.target.value })}
              className="w-full rounded-md border border-gray-300 bg-white p-2 text-sm text-gray-900">
              <option value="">Não confirmada</option>
              <option value="adequado">Envelope CW adequado e mensurável</option>
              <option value="nao_mensuravel">Não mensurável</option>
            </select>
            <p className="text-xs text-gray-600">IT Vmax registrada em Regurgitações: <strong>{metric(recordedTrv, " m/s")}</strong>. Confirme alinhamento e envelope completo.</p>
          </div>
          <div className="space-y-1">
            <label htmlFor={`${id}-rvot`} className="block text-xs font-medium text-gray-700">Via de saída do ventrículo direito</label>
            <select id={`${id}-rvot`} value={measurements.HP_VSVD || ""} onChange={(event) => onPatch({ HP_VSVD: event.target.value })}
              className="w-full rounded-md border border-gray-300 bg-white p-2 text-sm text-gray-900">
              <option value="">Obstrução não avaliada</option>
              <option value="sem_obstrucao">Ausência de obstrução confirmada</option>
              <option value="obstrucao">Obstrução presente</option>
            </select>
            <p className="text-xs text-gray-600">A velocidade da IT não deve ser atribuída à pressão pulmonar quando há obstrução da via de saída do VD.</p>
          </div>
        </div>

        {measurements.HP_TRV === "nao_mensuravel" && recordedTrv !== null && <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-950">
          Há uma IT Vmax registrada, mas a aquisição atual foi marcada como não mensurável. Esse valor histórico/importado não será usado para classificar a probabilidade nem validar a PSAP.
        </p>}

        <div className="grid gap-3 lg:grid-cols-3">
          {SITES.map(({ site, label, examples }) => {
            const key = HP_SITE_KEYS[site];
            const suggestions = assessment.suggestions.filter((suggestion) => suggestion.site === site);
            return <fieldset key={site} className="min-w-0 space-y-2 rounded-lg border border-gray-200 bg-white p-3">
              <legend className="px-1 text-xs font-semibold text-gray-900">{label}</legend>
              <label htmlFor={`${id}-${site}`} className="sr-only">Sinais em {label}</label>
              <select id={`${id}-${site}`} value={measurements[key] || ""} onChange={(event) => onPatch({ [key]: event.target.value })}
                className="w-full rounded-md border border-gray-300 bg-white p-2 text-sm text-gray-900">
                <option value="">Não avaliado</option>
                <option value="sem_sinais">Avaliado, sem sinais</option>
                <option value="com_sinais">Avaliado, com sinais</option>
              </select>
              {suggestions.length > 0 && <div className="rounded bg-blue-50 p-2 text-xs text-blue-950">
                <p className="font-medium">Sugestão pelas medidas registradas:</p>
                <ul className="mt-1 list-disc space-y-1 pl-4">{suggestions.flatMap((suggestion) => suggestion.reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul>
              </div>}
              <details className="text-xs text-gray-600"><summary className="cursor-pointer font-medium">Quais sinais considerar?</summary><p className="mt-1">{examples}</p></details>
            </fieldset>;
          })}
        </div>

        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={markRemainingWithoutSigns} disabled={!hasUnassessedSite}
            className="rounded-md border border-teal-300 bg-white px-3 py-2 text-xs font-medium text-teal-900 hover:bg-teal-50 disabled:opacity-50">
            {hasPositiveSite ? "Demais sítios avaliados sem sinais" : "Três sítios avaliados sem sinais"}
          </button>
          {supportEnabled && assessment.suggestions.length > 0 && <button type="button" onClick={applySuggestions}
            className="rounded-md border border-blue-300 bg-white px-3 py-2 text-xs font-medium text-blue-900 hover:bg-blue-50">
            Aplicar sinais sugeridos
          </button>}
        </div>
        <p className="text-xs text-gray-600">Use a ação em lote somente após avaliar os sítios. Sinais presentes são preservados; um campo não avaliado permanece pendente.</p>

        <details className="rounded-lg border border-gray-200 bg-white p-3">
          <summary className="cursor-pointer text-xs font-semibold text-gray-800">Medidas de apoio e técnica de aquisição (opcionais)</summary>
          <div className="mt-3 space-y-3">
            <label className="flex items-start gap-2 text-xs text-gray-800">
              <input type="checkbox" checked={supportEnabled} onChange={(event) => onPatch({ HP_suporte_automatico: event.target.checked ? "sim" : "nao" })}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 accent-teal-700" />
              Usar sugestões métricas: aquisição e técnica compatíveis com os critérios
            </label>
            {!supportEnabled && <p className="text-xs text-amber-950">Métricas excluídas por técnica incompatível. A avaliação dos sítios é manual.</p>}
            <p className="text-xs text-gray-600">AP/Ao: {metric(assessment.metrics.ap_ao)}. Remodelamento do AD: {measurements.Remodelamento_AD || "não informado"}. Esses dados são reutilizados dos campos existentes e sugerem apenas sinais positivos para confirmação.</p>
            <p className="text-xs text-gray-600">Para calcular o RPAD, use o diâmetro máximo sistólico e o mínimo diastólico da artéria pulmonar direita, no mesmo local e ciclo. TA e TE devem ser obtidos no mesmo traçado Doppler pulmonar.</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {OPTIONAL_METRICS.map(({ key, label }) => <div key={key} className="space-y-1">
                <label htmlFor={`${id}-${key}`} className="block text-xs text-gray-700">{label}</label>
                <input id={`${id}-${key}`} type="text" inputMode="decimal" value={measurements[key] || ""} placeholder="0,00"
                  onChange={(event) => onPatch({ [key]: event.target.value })}
                  className="w-full rounded-md border border-gray-300 bg-white p-2 text-sm text-gray-900" />
              </div>)}
            </div>
            <p className="text-xs text-gray-600">RPAD utilizado: {metric(assessment.metrics.rpad, "%")}. TA/TE: {metric(assessment.metrics.at_et)}. O pico inicial diastólico deve ser medido nessa fase; o campo genérico de insuficiência pulmonar não é reutilizado.</p>
          </div>
        </details>

        <div role="status" aria-live="polite" className={`space-y-2 rounded-lg border p-3 text-xs ${assessment.status === "classified" ? "border-teal-300 bg-teal-50 text-teal-950" : "border-amber-200 bg-amber-50 text-amber-950"}`}>
          <p className="text-sm font-semibold">{assessment.status === "classified" ? `Probabilidade ${probabilityLabel} de hipertensão pulmonar`
            : assessment.status === "unsupported" ? "Registro descritivo de achados" : "Avaliação de HP pendente"}</p>
          <p>{assessment.summary}</p>
          {assessment.missing.length > 0 && <ul className="list-disc space-y-1 pl-4">{assessment.missing.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
          {assessment.notes.length > 0 && <ul className="space-y-1">{assessment.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
          {measurements.PSAP && <p>PSAP calculada no formulário: <strong>{measurements.PSAP} mmHg</strong>. Estimativa complementar, não usada para graduar a probabilidade.
            {!assessment.psap_usable && " Ainda não validada para esta aquisição; não será apresentada como estimativa válida no PDF."}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={assessment.review_valid} onClick={() => onPatch({ HP_revisao: makePulmonaryReviewStamp(measurements, species || "") })}
            className="rounded-md bg-teal-700 px-3 py-2 text-xs font-semibold text-white hover:bg-teal-800 disabled:bg-teal-100 disabled:text-teal-900">
            {assessment.review_valid ? "Avaliação confirmada" : "Confirmar avaliação atual"}
          </button>
          <p className="text-xs text-gray-600">Alterações nas medidas, critérios ou espécie e novas importações exigem reconfirmação.</p>
        </div>
        <div className="space-y-1">
          <label htmlFor={`${id}-notes`} className="block text-xs font-medium text-gray-700">Observações da avaliação de HP (opcional)</label>
          <textarea id={`${id}-notes`} rows={2} value={measurements.HP_observacoes || ""} onChange={(event) => onPatch({ HP_observacoes: event.target.value })}
            className="w-full rounded-md border border-gray-300 bg-white p-2 text-sm text-gray-900" />
        </div>
        <p className="text-xs text-gray-600">A síntese será apresentada em seção própria do PDF. A análise qualitativa e a conclusão permanecem sob sua revisão.
          {canine && <> Critérios: <a href="https://doi.org/10.1111/jvim.15725" target="_blank" rel="noreferrer" className="underline">Reinero et al., consenso ACVIM (2020), Tabelas 2 e 3</a>.</>}</p>
      </>}
    </section>
  );
}
