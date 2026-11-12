export const ATENDIMENTO_PATIENT_SEARCH_LIMIT = 8;
export const ATENDIMENTO_LIBRARY_PAGE_SIZE = 100;

type QueryValue = string | number | boolean | null | undefined;

function buildQuery(path: string, values: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function buildPatientSearchPath(search: string): string {
  return buildQuery("/pacientes", {
    search: search.trim(),
    limit: ATENDIMENTO_PATIENT_SEARCH_LIMIT,
  });
}

export function buildMedicationLibraryPath(options: { search?: string; skip?: number } = {}): string {
  return buildQuery("/atendimentos/medicamentos/banco", {
    search: options.search?.trim(),
    skip: options.skip || 0,
    limit: ATENDIMENTO_LIBRARY_PAGE_SIZE,
  });
}

export function buildClinicalPhraseLibraryPath(options: {
  secao?: string;
  search?: string;
  includeInactive?: boolean;
  skip?: number;
} = {}): string {
  return buildQuery("/atendimentos/frases-clinicas", {
    secao: options.secao?.trim(),
    search: options.search?.trim(),
    include_inactive: options.includeInactive ? 1 : undefined,
    skip: options.skip || 0,
    limit: ATENDIMENTO_LIBRARY_PAGE_SIZE,
  });
}

export function mergeRecordsById<T extends { id: number }>(current: T[], incoming: T[]): T[] {
  const byId = new Map<number, T>();
  current.forEach((item) => byId.set(item.id, item));
  incoming.forEach((item) => byId.set(item.id, item));
  return Array.from(byId.values());
}
