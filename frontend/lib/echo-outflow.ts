/** Acquisition sites remain independent, including in older reports. */
export const ECHO_OUTFLOW_SITES = [
  { velocity: "Vmax_VSVE", gradient: "Grad_VSVE", label: "Via de saída do VE (VSVE/LVOT)" },
  { velocity: "Vmax_aorta", gradient: "Grad_aorta", label: "Fluxo aórtico" },
  { velocity: "Vmax_VSVD", gradient: "Grad_VSVD", label: "Via de saída do VD (VSVD/RVOT)" },
  { velocity: "Vmax_pulmonar", gradient: "Grad_pulmonar", label: "Fluxo pulmonar" },
] as const;

export const ECHO_OUTFLOW_KEYS = new Set<string>(
  ECHO_OUTFLOW_SITES.flatMap(({ velocity, gradient }) => [velocity, gradient]),
);

export function isOutflowMetadataKey(key: string): boolean {
  return [...ECHO_OUTFLOW_KEYS].some((measurement) =>
    key === `${measurement}_origem` || key === `${measurement}_rotulo_origem`,
  );
}

/** Only a missing gradient or a gradient owned by this calculation is derived.
 * A recorded gradient can retain precision unavailable in a rounded velocity. */
export function deriveOutflowGradients(measurements: Record<string, string>): Record<string, string> {
  const derived: Record<string, string> = {};
  for (const { velocity, gradient } of ECHO_OUTFLOW_SITES) {
    const calculated = measurements[`${gradient}_origem`] === "calculado";
    const missing = String(measurements[gradient] ?? "").trim() === "";
    if (!missing && !calculated) continue;
    const speed = Number(String(measurements[velocity] ?? "").replace(",", "."));
    const result = 4 * speed ** 2;
    if (Number.isFinite(speed) && speed > 0 && Number.isFinite(result)) {
      derived[gradient] = String(Number(result.toFixed(2)));
      derived[`${gradient}_origem`] = "calculado";
      derived[`${gradient}_rotulo_origem`] = "";
    } else if (calculated) {
      derived[gradient] = "";
      derived[`${gradient}_origem`] = "";
      derived[`${gradient}_rotulo_origem`] = "";
    }
  }
  return derived;
}

export function outflowMeasurementLabel(key: string, label: string, measurements: Record<string, string>): string {
  if (!ECHO_OUTFLOW_KEYS.has(key)) return label;
  const origin = measurements[`${key}_origem`];
  if (origin === "calculado") return `${label} · calculado (4 × V²)`;
  if (!origin) return `${label} · origem não confirmada`;
  return label;
}

export function formatOutflowValue(value: string): string {
  const text = value.trim().replace(",", ".");
  const decimals = text.match(/^[+-]?\d+\.(\d+)$/)?.[1].length ?? 0;
  return decimals > 2 ? text : Number(text).toFixed(2);
}
