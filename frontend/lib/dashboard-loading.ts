export const DASHBOARD_SECTIONS = ["agenda", "pacientes", "clinicas", "servicos"] as const;

export type DashboardSection = (typeof DASHBOARD_SECTIONS)[number];
export type DashboardSectionLoadStatus = "success" | "failed" | "cancelled";

export interface DashboardSectionLoadResult {
  section: DashboardSection;
  status: DashboardSectionLoadStatus;
  error?: unknown;
}

interface LoadDashboardSectionOptions<T> {
  section: DashboardSection;
  request: Promise<T>;
  signal: AbortSignal;
  onSuccess: (value: T) => void;
}

/**
 * Mantem a falha de uma leitura isolada das demais e nunca publica uma
 * resposta que tenha chegado apos o cancelamento da carga atual.
 */
export async function loadDashboardSection<T>({
  section,
  request,
  signal,
  onSuccess,
}: LoadDashboardSectionOptions<T>): Promise<DashboardSectionLoadResult> {
  try {
    const value = await request;
    if (signal.aborted) {
      return { section, status: "cancelled" };
    }

    onSuccess(value);
    return { section, status: "success" };
  } catch (error) {
    if (signal.aborted) {
      return { section, status: "cancelled" };
    }

    return { section, status: "failed", error };
  }
}
