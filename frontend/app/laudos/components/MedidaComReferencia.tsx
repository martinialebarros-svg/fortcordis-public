"use client";

import { useReferenciaEcoLegacy as useReferenciaEco, mapeamentoParametros } from "../hooks/useReferenciaEco";

interface MedidaComReferenciaProps {
  label: string;
  parametro: string;
  valor?: number;
  unidade?: string;
  especie: string;
  pesoKg?: number;
}

export default function MedidaComReferencia({
  label,
  parametro,
  valor,
  unidade = "",
  especie,
  pesoKg,
}: MedidaComReferenciaProps) {
  const { getFaixaReferencia, interpretarMedida } = useReferenciaEco(especie, pesoKg);
  
  const campoRef = mapeamentoParametros[parametro];
  const faixa = campoRef ? getFaixaReferencia(campoRef) : "-";
  const interpretacao = campoRef && valor !== undefined 
    ? interpretarMedida(valor, campoRef) 
    : null;

  const getCorStatus = (status?: string) => {
    switch (status) {
      case "normal": return "text-green-600 bg-green-50";
      case "alterado": return "text-red-600 bg-red-50";
      default: return "text-gray-500 bg-gray-50";
    }
  };

  return (
    <div className="border rounded-lg p-3 bg-white">
      <div className="flex justify-between items-start">
        <label className="text-sm font-medium text-gray-700">{label}</label>
        {interpretacao && (
          <span className={`text-xs px-2 py-0.5 rounded-full ${getCorStatus(interpretacao.status)}`}>
            {interpretacao.status === "normal" ? "✓" : interpretacao.status === "alterado" ? "⚠" : "-"}
          </span>
        )}
      </div>
      
      <div className="mt-2 space-y-1">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={valor !== undefined ? valor : ""}
            readOnly
            className="w-20 px-2 py-1 text-sm border rounded bg-gray-50"
          />
          <span className="text-sm text-gray-500">{unidade}</span>
        </div>
        
        {faixa !== "-" && (
          <div className="text-xs text-gray-500">
            Ref: <span className="font-medium">{faixa}</span> {unidade}
          </div>
        )}
        
        {interpretacao && interpretacao.status !== "nao_avaliado" && (
          <div className={`text-xs ${interpretacao.status === "alterado" ? "text-red-600" : "text-green-600"}`}>
            {interpretacao.mensagem}
          </div>
        )}
      </div>
    </div>
  );
}
