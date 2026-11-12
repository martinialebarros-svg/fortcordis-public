"use client";

import { useMemo, useState } from "react";
import { AlertCircle, Check, Loader2, MessageCircle, X } from "lucide-react";

import { formatOperationalDate } from "@/lib/calendar-date";
import {
  getDestinosSelecionaveis,
  getSelecaoInicialAviso,
  type LaudoAvisoWhatsApp,
} from "@/lib/laudo-whatsapp-aviso";

interface AvisoWhatsAppDialogProps {
  laudo: LaudoAvisoWhatsApp;
  enviando?: boolean;
  onCancelar: () => void;
  onEnviar: (destinos: string[]) => void;
}

/**
 * Escolhe quem recebe o aviso de laudo disponivel.
 *
 * Abre com quem ainda nao recebeu ja marcado: o caso comum e avisar quem
 * falta, e reenviar para quem ja recebeu passa a ser um ato deliberado - cada
 * clique gera uma mensagem nova no WhatsApp da pessoa.
 */
export default function AvisoWhatsAppDialog({
  laudo,
  enviando = false,
  onCancelar,
  onEnviar,
}: AvisoWhatsAppDialogProps) {
  const destinos = useMemo(() => getDestinosSelecionaveis(laudo), [laudo]);
  const [selecionados, setSelecionados] = useState<string[]>(() => getSelecaoInicialAviso(destinos));

  const alternar = (id: string) => {
    setSelecionados((atual) =>
      atual.includes(id) ? atual.filter((item) => item !== id) : [...atual, id]
    );
  };

  return (
    <div
      className="fc-appointment-submodal-backdrop fixed inset-0 z-[70] flex items-center justify-center p-4"
      onClick={enviando ? undefined : onCancelar}
    >
      <div
        className="fc-appointment-submodal w-full max-w-md"
        role="dialog"
        aria-modal="true"
        aria-labelledby="fc-aviso-whatsapp-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="fc-appointment-submodal-header flex items-center justify-between px-5 py-4">
          <h3 id="fc-aviso-whatsapp-title" className="flex items-center gap-2 text-lg font-semibold pr-8">
            <MessageCircle className="h-5 w-5" />
            Avisar por WhatsApp
          </h3>
          <button
            type="button"
            onClick={onCancelar}
            disabled={enviando}
            className="fc-appointment-submodal-close"
            aria-label="Fechar"
            title="Fechar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="fc-appointment-submodal-body space-y-3 px-5 py-4">
          <p className="text-sm text-gray-600">
            Quem recebe o aviso de laudo disponível? Já marcamos quem ainda não foi avisado.
          </p>
          <ul className="space-y-2">
            {destinos.map((destino) => {
              const ultimo = destino.ultimoEnvio;
              const jaEnviado = ultimo?.status === "enviado";
              return (
                <li key={destino.id}>
                  <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 px-3 py-2 hover:bg-gray-50">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selecionados.includes(destino.id)}
                      onChange={() => alternar(destino.id)}
                      disabled={enviando}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-gray-900">{destino.nome}</span>
                      <span className="block text-xs text-gray-500">
                        {destino.tipo === "clinica" ? "Clínica parceira" : "Veterinário parceiro"}
                      </span>
                      {jaEnviado && (
                        <span className="mt-1 flex items-center gap-1 text-xs text-teal-700">
                          <Check className="h-3 w-3" />
                          Já avisado
                          {ultimo?.em ? ` em ${formatOperationalDate(ultimo.em)}` : ""}
                        </span>
                      )}
                      {ultimo?.status === "falhou" && (
                        <span className="mt-1 flex items-start gap-1 text-xs text-rose-700">
                          <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                          <span className="min-w-0">
                            Último envio falhou{ultimo.erro ? `: ${ultimo.erro}` : "."}
                          </span>
                        </span>
                      )}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="fc-appointment-submodal-footer flex items-center justify-end gap-3 px-5 py-4">
          <button
            type="button"
            onClick={onCancelar}
            disabled={enviando}
            className="fc-appointment-button-secondary"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={() => onEnviar(selecionados)}
            disabled={enviando || selecionados.length === 0}
            className="fc-appointment-button-primary flex items-center gap-2"
          >
            {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageCircle className="h-4 w-4" />}
            {enviando ? "Enviando..." : `Enviar (${selecionados.length})`}
          </button>
        </div>
      </div>
    </div>
  );
}
