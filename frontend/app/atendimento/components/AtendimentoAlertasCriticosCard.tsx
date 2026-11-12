"use client";

import { AlertTriangle } from "lucide-react";
import type { LooseAtendimentoComponentProps } from "./component-props";

type AtendimentoAlertasCriticosCardProps = LooseAtendimentoComponentProps;

const GRAVIDADES_COMPACTAS = new Set(["critica", "alta"]);

export default function AtendimentoAlertasCriticosCard(props: AtendimentoAlertasCriticosCardProps) {
  const { alertasAtivos, getGravidadeClass } = props;

  const alertasCriticos = (alertasAtivos || []).filter((alerta: any) =>
    GRAVIDADES_COMPACTAS.has((alerta.gravidade || "").toLowerCase())
  );

  if (alertasCriticos.length === 0) return null;

  return (
    <section className="rounded-[26px] border border-red-200 bg-red-50/60 p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="rounded-2xl bg-red-100 p-3">
          <AlertTriangle className="h-5 w-5 text-red-700" />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-red-700">Atencao ao prescrever/solicitar</p>
          <h2 className="text-lg font-semibold text-slate-900">
            {alertasCriticos.length} alerta{alertasCriticos.length > 1 ? "s" : ""} de gravidade alta/critica
          </h2>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {alertasCriticos.map((alerta: any) => (
          <div key={alerta.id} className={`rounded-[20px] border px-4 py-3 ${getGravidadeClass(alerta.gravidade)}`}>
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold">{alerta.titulo}</p>
              <span className="rounded-full bg-white/70 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.2em]">
                {alerta.gravidade}
              </span>
            </div>
            <p className="mt-2 text-sm">{alerta.descricao}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
