import { normalizeEchoSpecies } from "./echo-species";

/** Routine acquisition explicitly selected by the veterinarian for new canine reports. */
export const NEW_CANINE_REPORT_PROTOCOL = {
  Diastolica_metodo: "canino_nao_sedado_pw_apical",
  Diastolica_ondas: "separadas",
  TDI_metodo: "canino_pw_basal_lateral_wess",
  TDI_ondas: "separadas",
  TAPSE_metodo: "modo_m_apical",
  AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco",
} as const;

export const NEW_REPORT_PROTOCOL_KEYS = Object.keys(NEW_CANINE_REPORT_PROTOCOL);

export function newEchoReportProtocol(species?: string): Record<string, string> {
  return normalizeEchoSpecies(species) === "Canina" ? { ...NEW_CANINE_REPORT_PROTOCOL } : {};
}

/** Keep the new exam's editable acquisition choices separate from numeric edits.
 * Explicit empty choices and fused waves must also survive subsequent imports. */
export function preserveNewReportProtocol(
  next: Record<string, string>, previous: Record<string, string>, species?: string,
): Record<string, string> {
  if (normalizeEchoSpecies(species) !== "Canina") return next;
  const result = { ...next };
  for (const key of NEW_REPORT_PROTOCOL_KEYS) {
    if (Object.hasOwn(previous, key)) result[key] = previous[key];
    else delete result[key];
  }
  return result;
}
