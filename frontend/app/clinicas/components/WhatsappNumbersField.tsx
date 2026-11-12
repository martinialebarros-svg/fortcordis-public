"use client";

import { Plus, Trash2 } from "lucide-react";
import { formatarTelefoneVisual } from "@/lib/atendimento-cadastro";

interface WhatsappNumbersFieldProps {
  value: string[];
  onChange: (value: string[]) => void;
}

export default function WhatsappNumbersField({ value, onChange }: WhatsappNumbersFieldProps) {
  const numeros = value.length > 0 ? value : [""];

  const atualizarNumero = (indice: number, numero: string) => {
    const proximos = [...numeros];
    proximos[indice] = formatarTelefoneVisual(numero);
    onChange(proximos);
  };

  const adicionarNumero = () => {
    if (numeros.length >= 10) return;
    onChange([...numeros, ""]);
  };

  const removerNumero = (indice: number) => {
    const proximos = numeros.filter((_, itemIndice) => itemIndice !== indice);
    onChange(proximos.length > 0 ? proximos : [""]);
  };

  return (
    <div className="space-y-2 md:col-span-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700">WhatsApps para mensagens</label>
          <p className="mt-0.5 text-xs text-gray-500">
            Cadastre os números que poderão ser escolhidos ao enviar avisos da agenda.
          </p>
        </div>
        <button
          type="button"
          onClick={adicionarNumero}
          disabled={numeros.length >= 10}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Adicionar número
        </button>
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {numeros.map((numero, indice) => (
          <div key={indice} className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <label htmlFor={`clinica-whatsapp-${indice}`} className="sr-only">
                WhatsApp {indice + 1}
              </label>
              <input
                id={`clinica-whatsapp-${indice}`}
                type="tel"
                value={numero}
                onChange={(event) => atualizarNumero(indice, event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-emerald-500"
                placeholder={`WhatsApp ${indice + 1}: (00) 00000-0000`}
                inputMode="tel"
                autoComplete="tel"
                maxLength={15}
              />
            </div>
            <button
              type="button"
              onClick={() => removerNumero(indice)}
              className="rounded-lg border border-gray-200 p-2 text-gray-500 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
              aria-label={`Remover WhatsApp ${indice + 1}`}
              title="Remover número"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
