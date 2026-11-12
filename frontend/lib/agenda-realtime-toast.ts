"use client";

import type { AgendaRealtimePayload } from "@/lib/useAgendaRealtime";

const obterTexto = (valor: unknown): string => String(valor || "").trim();

const primeiroTextoPreenchido = (...valores: unknown[]): string => {
  for (const valor of valores) {
    const texto = obterTexto(valor);
    if (texto) return texto;
  }
  return "";
};

export interface AgendaRealtimeToastData {
  texto: string;
  classe: string;
}

export function montarToastAgendaRealtime(payload?: AgendaRealtimePayload): AgendaRealtimeToastData | null {
  if (!payload?.action) {
    return null;
  }

  const data = (payload.data || {}) as Record<string, unknown>;
  const idLabel =
    typeof payload.agendamento_id === "number" && Number.isFinite(payload.agendamento_id)
      ? ` #${payload.agendamento_id}`
      : "";

  const paciente = primeiroTextoPreenchido(data.paciente_nome, data.paciente);
  const clinica = primeiroTextoPreenchido(data.clinica_nome, data.clinica);
  const servico = primeiroTextoPreenchido(data.servico_nome, data.servico);
  const usuario = primeiroTextoPreenchido(data.usuario_nome, data.usuario);
  const dataHorario = primeiroTextoPreenchido(data.data, data.hora)
    ? `${obterTexto(data.data)} ${obterTexto(data.hora)}`.trim()
    : "";
  const statusAnterior = primeiroTextoPreenchido(data.status_anterior);
  const statusNovo = primeiroTextoPreenchido(data.status_novo, data.status);

  const detalhes = [paciente && `Paciente: ${paciente}`, clinica && `Clinica: ${clinica}`, servico && `Servico: ${servico}`]
    .filter(Boolean)
    .join(" | ");
  const contexto = [dataHorario && `Horario: ${dataHorario}`, usuario && `Por: ${usuario}`]
    .filter(Boolean)
    .join(" | ");

  if (payload.action === "created") {
    return {
      texto: `Novo agendamento${idLabel}. ${detalhes}${detalhes && contexto ? " | " : ""}${contexto}`.trim(),
      classe: "border-emerald-200 bg-emerald-50 text-emerald-800",
    };
  }

  if (payload.action === "updated") {
    return {
      texto: `Agendamento${idLabel} atualizado. ${detalhes}${detalhes && contexto ? " | " : ""}${contexto}`.trim(),
      classe: "border-blue-200 bg-blue-50 text-blue-800",
    };
  }

  if (payload.action === "status_changed") {
    const statusInfo =
      statusAnterior || statusNovo
        ? `Status: ${statusAnterior || "?"} -> ${statusNovo || "?"}`
        : "Status alterado";
    return {
      texto: `Agendamento${idLabel}. ${statusInfo}. ${detalhes}${detalhes && contexto ? " | " : ""}${contexto}`.trim(),
      classe: "border-amber-200 bg-amber-50 text-amber-800",
    };
  }

  if (payload.action === "cancelled") {
    const statusInfo = statusAnterior || statusNovo ? `Status: ${statusAnterior || "?"} -> ${statusNovo || "Cancelado"}` : "Status: Cancelado";
    return {
      texto: `Agendamento${idLabel} cancelado. ${statusInfo}. ${detalhes}${detalhes && contexto ? " | " : ""}${contexto}`.trim(),
      classe: "border-orange-200 bg-orange-50 text-orange-800",
    };
  }

  if (payload.action === "deleted") {
    return {
      texto: `Agendamento${idLabel} excluido. ${detalhes}${detalhes && contexto ? " | " : ""}${contexto}`.trim(),
      classe: "border-red-200 bg-red-50 text-red-800",
    };
  }

  return {
    texto: `Agenda atualizada${idLabel}. ${detalhes}${detalhes && contexto ? " | " : ""}${contexto}`.trim(),
    classe: "border-slate-200 bg-slate-50 text-slate-800",
  };
}
