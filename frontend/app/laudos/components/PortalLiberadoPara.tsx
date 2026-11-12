"use client";

import { Building2, Check, Clock, Loader2, ShieldOff, Stethoscope } from "lucide-react";

import {
  getClinicaDoLaudo,
  getRotuloOrigemVeterinario,
  getVeterinariosDoLaudo,
  temDestinosNoPortal,
} from "@/lib/laudo-portal-destinos";
import type { LaudoAvisoWhatsApp } from "@/lib/laudo-whatsapp-aviso";

interface PortalLiberadoParaProps {
  laudo: LaudoAvisoWhatsApp;
  revogandoPartnerId?: number | null;
  onRevogar: (partnerId: number, nome: string) => void;
}

/**
 * Quem enxerga este laudo no portal, e o caminho de volta.
 *
 * Liberar era mao unica: depois do clique em "No portal" nao havia como saber
 * quem ficou com acesso, nem como tirar. Esta lista responde as duas coisas.
 * A clinica nao tem botao aqui de proposito - quem revoga a clinica e a
 * revogacao do exame, em outro fluxo.
 */
export default function PortalLiberadoPara({
  laudo,
  revogandoPartnerId = null,
  onRevogar,
}: PortalLiberadoParaProps) {
  if (!temDestinosNoPortal(laudo)) {
    return null;
  }

  const clinica = getClinicaDoLaudo(laudo);
  const veterinarios = getVeterinariosDoLaudo(laudo);

  return (
    <section className="fc-report-view-portal-access print:hidden" aria-labelledby="fc-portal-access-title">
      <h2 id="fc-portal-access-title" className="text-sm font-semibold text-gray-700">
        Liberado no portal para
      </h2>
      <ul className="mt-2 space-y-2">
        {clinica && (
          <li className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 px-3 py-2">
            <Building2 className="h-4 w-4 shrink-0 text-gray-500" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-gray-900">{clinica.nome}</span>
              <span className="block text-xs text-gray-500">Clínica parceira</span>
            </span>
            <EstadoAcesso liberado={clinica.liberada} />
          </li>
        )}
        {veterinarios.map((veterinario) => (
          <li
            key={veterinario.partner_id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 px-3 py-2"
          >
            <Stethoscope className="h-4 w-4 shrink-0 text-gray-500" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-gray-900">{veterinario.nome}</span>
              <span className="block text-xs text-gray-500">
                {getRotuloOrigemVeterinario(veterinario.origem)}
              </span>
            </span>
            <EstadoAcesso liberado={veterinario.liberado} />
            {veterinario.liberado && (
              <button
                type="button"
                onClick={() => onRevogar(veterinario.partner_id, veterinario.nome)}
                disabled={revogandoPartnerId === veterinario.partner_id}
                className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-2 py-1 text-xs text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                title={`Tirar o acesso de ${veterinario.nome} a este laudo`}
                aria-label={`Revogar acesso de ${veterinario.nome} ao laudo no portal`}
              >
                {revogandoPartnerId === veterinario.partner_id ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <ShieldOff className="h-3 w-3" />
                )}
                {revogandoPartnerId === veterinario.partner_id ? "Revogando..." : "Revogar"}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function EstadoAcesso({ liberado }: { liberado: boolean }) {
  if (liberado) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-2 py-0.5 text-xs text-teal-800">
        <Check className="h-3 w-3" />
        Com acesso
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
      <Clock className="h-3 w-3" />
      Sem acesso
    </span>
  );
}
