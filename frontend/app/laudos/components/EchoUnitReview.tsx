import { confirmedEchoUnit, echoUnitReviewCandidates } from "@/lib/echo-unit-provenance";

const LABELS: Record<string, string> = {
  DIVEd: "DIVEd", SIVd: "SIVd", PLVEd: "PLVEd", DIVES: "DIVEs", SIVs: "SIVs", PLVES: "PLVEs",
  DIVEd_2D: "DIVEd 2D", SIVd_2D: "SIVd 2D", PLVEd_2D: "PLVEd 2D",
  DIVES_2D: "DIVEs 2D", SIVs_2D: "SIVs 2D", PLVES_2D: "PLVEs 2D",
  Aorta: "Aorta", Atrio_esquerdo: "Átrio esquerdo", Ao_nivel_AP: "Aorta no nível da AP", AP: "Artéria pulmonar",
};

export default function EchoUnitReview({
  measurements,
  onConfirm,
}: {
  measurements: Record<string, string>;
  onConfirm: (key: string, unit: "cm" | "mm" | "") => void;
}) {
  const candidates = echoUnitReviewCandidates(measurements);
  if (!candidates.length) return null;

  return (
    <section className="rounded-lg border border-amber-300 bg-amber-50 p-4" aria-label="Conferência de unidades legadas">
      <h4 className="text-sm font-semibold text-amber-950">Conferir unidade das medidas legadas</h4>
      <p className="mt-1 text-xs text-amber-900">
        Estes números podem estar em cm ou mm. Confira o exame de origem e escolha a unidade de cada medida.
        O valor registrado permanece igual; prévia e PDF apresentam dimensões confirmadas em mm.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {candidates.map((key) => (
          <label key={key} className="flex items-center justify-between gap-2 rounded border border-amber-200 bg-white px-2 py-1.5 text-xs text-slate-800">
            <span>{LABELS[key] || key}: <strong>{measurements[key]}</strong></span>
            <select
              aria-label={`Unidade de ${LABELS[key] || key}`}
              value={confirmedEchoUnit(measurements, key) || ""}
              onChange={(event) => onConfirm(key, event.target.value as "cm" | "mm" | "")}
              className="rounded border border-amber-300 bg-white px-1 py-1"
            >
              <option value="">A confirmar</option>
              <option value="mm">mm</option>
              <option value="cm">cm</option>
            </select>
          </label>
        ))}
      </div>
    </section>
  );
}
