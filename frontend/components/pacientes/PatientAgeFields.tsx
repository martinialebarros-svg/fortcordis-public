"use client";

import { useId } from "react";
import { operationalTodayDateInput } from "@/lib/calendar-date";
import { calcularIdadeComFonte, changePatientAge, exibirNascimento, patientAgeForm, type PatientAgeValue } from "@/lib/paciente-idade";

export function PatientAgeFields({ value, onChange, referenceDate = operationalTodayDateInput() }: {
  value: PatientAgeValue;
  onChange: (patch: ReturnType<typeof patientAgeForm>) => void;
  referenceDate?: string;
}) {
  const id = useId();
  referenceDate = referenceDate || operationalTodayDateInput();
  const declared = value.idade_informada || (!value.idade_fonte ? value.idade || "" : "");
  const resolved = calcularIdadeComFonte(value, referenceDate) ?? value.idade ?? "";
  const source = value.idade_fonte === "idade" ? "idade informada" : value.idade_fonte === "nascimento" ? "nascimento" : "cadastro anterior";
  const inputClass = "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500";
  return <fieldset className="col-span-full rounded-xl border border-slate-200 p-3">
    <legend className="px-1 text-sm font-medium text-slate-700">Nascimento e idade</legend>
    <div className="grid gap-3 sm:grid-cols-2">
      <div>
        <label htmlFor={`${id}-age`} className="mb-1 block text-sm font-medium">Idade informada</label>
        <input id={`${id}-age`} value={declared} onChange={(event) => onChange(changePatientAge(value, "idade", event.target.value, referenceDate))}
          placeholder="Ex.: 12 anos, 8 meses ou 20 dias" className={inputClass} />
        <p className="mt-1 text-xs text-slate-500">Pode informar só a idade. Ela avançará como estimativa.</p>
      </div>
      <div>
        <label htmlFor={`${id}-birth`} className="mb-1 block text-sm font-medium">Data de nascimento ou ano</label>
        <input id={`${id}-birth`} value={exibirNascimento(value.data_nascimento)} onChange={(event) => onChange(changePatientAge(value, "data_nascimento", event.target.value, referenceDate))}
          placeholder="Ex.: 15/04/2014 ou 2014" className={inputClass} />
        <p className="mt-1 text-xs text-slate-500">Opcional. Informe apenas o que o tutor sabe.</p>
      </div>
    </div>
    <p className="mt-3 text-sm text-slate-700" aria-live="polite">Idade considerada: <strong>{resolved || "a confirmar"}</strong> · Fonte: {source}.</p>
    {value.idade_fonte === "idade" && value.idade_referencia && <p className="mt-1 text-xs text-slate-500">Idade informada em {exibirNascimento(value.idade_referencia)}. Nenhuma data de nascimento foi presumida.</p>}
    {!!value.data_nascimento && !!declared && <div className="mt-2 flex flex-wrap gap-3 text-xs">
      <button type="button" className="text-teal-700 underline" onClick={() => {
        const next = value.idade_informada && value.idade_referencia
          ? { ...patientAgeForm(value), idade_fonte: "idade" }
          : changePatientAge(value, "idade", declared, referenceDate);
        onChange({ ...next, idade: calcularIdadeComFonte(next, referenceDate) || next.idade });
      }}>Usar idade informada</button>
      <button type="button" className="text-teal-700 underline" onClick={() => onChange(changePatientAge(value, "data_nascimento", value.data_nascimento || "", referenceDate))}>Usar nascimento</button>
    </div>}
  </fieldset>;
}
