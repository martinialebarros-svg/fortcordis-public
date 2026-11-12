"use client";

import { isFelineEchoSpecies } from "@/lib/echo-species";

type Props = {
  especie?: string;
  medidas: Record<string, string>;
  onMedidaChange: (key: string, value: string) => void;
  onDiscard: (kind: "transmitral" | "tissue") => void;
};

/** The editor keeps imported history available for review. Discarding it is an
 * explicit action; the acquisition protocol remains in the References tab. */
export default function FelineWaveReview({ especie, medidas, onMedidaChange, onDiscard }: Props) {
  if (!isFelineEchoSpecies(especie)) return null;
  return (
    <section aria-label="Revisão de ondas diastólicas felinas" className="space-y-2 rounded-lg border border-blue-100 bg-blue-50 p-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {[
          { key: "Diastolica_ondas", label: "Ondas transmitrais E/A" },
          { key: "TDI_ondas", label: "Ondas teciduais e'/a'" },
        ].map(({ key, label }) => (
          <div key={key} className="min-w-0">
            <label htmlFor={`wave-review-${key}`} className="mb-1 block text-xs font-medium text-blue-900">{label}</label>
            <select id={`wave-review-${key}`} value={medidas[key] || ""}
              onChange={(event) => onMedidaChange(key, event.target.value)}
              className="w-full min-w-0 rounded border border-blue-200 bg-white p-1.5 text-xs text-gray-900">
              <option value="">Não confirmadas</option>
              {medidas[key] === "nao_confirmadas" && <option value="nao_confirmadas">Separação a reconfirmar</option>}
              <option value="separadas">Separadas e mensuráveis</option>
              <option value="fundidas">Fundidas</option>
            </select>
          </div>
        ))}
      </div>
      {medidas.Diastolica_ondas === "fundidas" && (
        <div className="space-y-2 text-xs text-amber-950" role="status">
          <p>Ondas E/A fundidas: os picos individuais e as relações dependentes não serão apresentados como valores mensuráveis no PDF. TRIV e Doppler tecidual são avaliados independentemente.</p>
          <button type="button" onClick={() => onDiscard("transmitral")}
            className="rounded border border-amber-300 bg-white px-2 py-1.5 text-left font-medium hover:bg-amber-50">
            Remover medidas de E/A fundidas
          </button>
          <p>Remove E, A, TD, E/A, E/TRIV e E/e&apos; deste laudo. Preserva TRIV, Doppler tecidual e as confirmações registradas.</p>
        </div>
      )}
      {medidas.TDI_ondas === "fundidas" && (
        <div className="space-y-2 text-xs text-amber-950" role="status">
          <p>Ondas e&apos;/a&apos; fundidas: os picos teciduais e as relações dependentes não serão apresentados como valores mensuráveis no PDF. O fluxo transmitral é avaliado independentemente.</p>
          <button type="button" onClick={() => onDiscard("tissue")}
            className="rounded border border-amber-300 bg-white px-2 py-1.5 text-left font-medium hover:bg-amber-50">
            Remover medidas de TDI fundidas
          </button>
          <p>Remove e&apos;, a&apos;, e&apos;/a&apos; e E/e&apos; deste laudo. Preserva o fluxo transmitral, TRIV e as confirmações registradas.</p>
        </div>
      )}
    </section>
  );
}
