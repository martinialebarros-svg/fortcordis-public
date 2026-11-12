import { AlertTriangle } from "lucide-react";

import { AlertaOperacionalItem } from "../types";

interface AlertasListProps {
  alertas: AlertaOperacionalItem[];
  titulo?: string;
}

export default function AlertasList({ alertas, titulo = "Alertas automáticos" }: AlertasListProps) {
  return (
    <div className="fc-reports-alerts">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-4 h-4 text-amber-600" />
        <h2 className="font-semibold text-gray-900">{titulo}</h2>
      </div>
      <div className="space-y-2">
        {alertas.length === 0 ? (
          <p className="text-sm text-gray-500">Sem alertas para os criterios atuais.</p>
        ) : (
          alertas.map((item) => (
            <div
              key={item.codigo}
              className={`rounded-lg border px-3 py-2 ${
                item.severidade === "alto"
                  ? "bg-red-50 border-red-200"
                  : item.severidade === "medio"
                    ? "bg-amber-50 border-amber-200"
                    : "bg-blue-50 border-blue-200"
              }`}
            >
              <p className="text-sm font-medium text-gray-900">
                [{String(item.severidade || "").toUpperCase()}] {item.titulo}
              </p>
              <p className="text-xs text-gray-700 mt-1">{item.descricao}</p>
              <p className="text-xs text-gray-600 mt-1">Ação: {item.recomendacao}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
