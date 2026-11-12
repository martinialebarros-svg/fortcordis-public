"use client";

import { useId } from "react";
import { Minus, Plus } from "lucide-react";
import { ECHO_OUTFLOW_SITES } from "@/lib/echo-outflow";

interface Props {
  measurements: Record<string, string>;
  onChange: (key: string, value: string) => void;
}

function measurementOrigin(measurements: Record<string, string>, key: string): string | null {
  if (!measurements[key]?.trim()) return null;
  const origin = measurements[`${key}_origem`];
  if (origin === "calculado") return "Calculado: 4 × V².";
  if (origin === "importado") return "Importado do exame.";
  if (origin === "informado") return "Informado no formulário.";
  return "Origem não confirmada; valor mantido como registrado.";
}

/** Acquisition sites are independently editable for every species. */
export default function EchoOutflowMeasurements({ measurements, onChange }: Props) {
  const prefix = useId();
  const stepValue = (key: string, step: number) => {
    const current = Number(String(measurements[key] || "0").replace(",", "."));
    if (!Number.isFinite(current) || (step < 0 && current <= 0)) return;
    onChange(key, Math.max(0, current + step).toFixed(2));
  };

  return (
    <section className="border-t pt-6 mt-6" aria-label="Doppler — locais de aquisição">
      <h4 className="font-semibold text-gray-900 text-sm mb-4">Doppler — locais de aquisição</h4>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {ECHO_OUTFLOW_SITES.map(({ velocity, gradient, label }) => (
          <fieldset key={velocity} className="min-w-0 rounded-lg border border-gray-200 p-3">
            <legend className="px-1 text-sm font-medium text-gray-900">{label}</legend>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {[[velocity, "Vmax (m/s)"], [gradient, "Gradiente (mmHg)"]].map(([key, fieldLabel]) => {
                const id = `${prefix}-${key}`;
                const origin = measurementOrigin(measurements, key);
                const sourceLabel = measurements[`${key}_rotulo_origem`];
                return (
                  <div key={key} className="space-y-1">
                    <label htmlFor={id} className="block text-xs text-gray-600">{fieldLabel}</label>
                    <div className="flex items-center gap-1">
                      <input
                        id={id}
                        type="text"
                        inputMode="decimal"
                        value={measurements[key] ?? ""}
                        onChange={(event) => onChange(key, event.target.value)}
                        aria-describedby={origin || sourceLabel ? `${id}-source` : undefined}
                        className="min-w-0 flex-1 px-2 py-1.5 bg-blue-50 border-0 rounded text-sm text-gray-700 focus:ring-1 focus:ring-teal-500"
                      />
                      <button type="button" onClick={() => stepValue(key, -0.01)}
                        aria-label={`Diminuir ${fieldLabel} — ${label}`}
                        className="p-1 text-gray-500 hover:text-teal-600"><Minus size={14} /></button>
                      <button type="button" onClick={() => stepValue(key, 0.01)}
                        aria-label={`Aumentar ${fieldLabel} — ${label}`}
                        className="p-1 text-gray-500 hover:text-teal-600"><Plus size={14} /></button>
                    </div>
                    {origin || sourceLabel ? (
                      <p id={`${id}-source`} className="text-[11px] text-gray-500 break-words">
                        {origin}{sourceLabel ? ` Rótulo de origem: ${sourceLabel}` : ""}
                      </p>
                    ) : null}
                  </div>
                );
              })}
            </div>
            {velocity === "Vmax_pulmonar" && [velocity, gradient].some((key) =>
              measurements[key]?.trim() && !measurements[`${key}_origem`]
            ) ? (
              <p className="mt-2 text-xs text-amber-800">
                Registro legado com local de aquisição não confirmado: confira a fonte para distinguir fluxo pulmonar de VSVD/RVOT.
              </p>
            ) : null}
          </fieldset>
        ))}
      </div>
    </section>
  );
}
