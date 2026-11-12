export interface AgendaIdCandidate {
  id?: unknown;
}

export interface AgendaFiltroOption {
  id: number;
  nome: string;
}

interface AgendaCatalogLoaderOptions<T> {
  request: () => Promise<T>;
  onSuccess: (value: T) => void;
  onLoadingChange?: (loading: boolean) => void;
  onError?: (error: unknown) => void;
}

export interface AgendaCatalogLoader {
  load: () => Promise<boolean>;
  isLoaded: () => boolean;
}

export type AgendaAuxiliaryLoad = () => Promise<unknown>;

export function executarCargasAuxiliaresAgenda(
  tasks: readonly AgendaAuxiliaryLoad[]
): Promise<PromiseSettledResult<unknown>[]> {
  return Promise.allSettled(tasks.map(async (task) => task()));
}

export function extrairIdsAgendamentosVisiveis(
  items: AgendaIdCandidate[],
  limit = 100
): number[] {
  const ids: number[] = [];
  const vistos = new Set<number>();

  for (const item of items) {
    const id = Number(item?.id);
    if (!Number.isInteger(id) || id <= 0 || vistos.has(id)) continue;
    vistos.add(id);
    ids.push(id);
    if (ids.length >= limit) break;
  }

  return ids;
}

export function agruparIdsAgendamentosVisiveis(
  items: AgendaIdCandidate[],
  batchSize = 100
): number[][] {
  const tamanho = Number.isInteger(batchSize) && batchSize > 0 ? batchSize : 100;
  const ids = extrairIdsAgendamentosVisiveis(items, Number.MAX_SAFE_INTEGER);
  const lotes: number[][] = [];
  for (let inicio = 0; inicio < ids.length; inicio += tamanho) {
    lotes.push(ids.slice(inicio, inicio + tamanho));
  }
  return lotes;
}

export function normalizarOpcoesFiltroAgenda(payload: unknown): AgendaFiltroOption[] {
  const data = payload as { items?: unknown } | null | undefined;
  const items = Array.isArray(data?.items) ? data.items : [];

  return items
    .map((raw) => {
      const item = raw as { id?: unknown; nome?: unknown };
      return {
        id: Number(item?.id),
        nome: String(item?.nome || "").trim(),
      };
    })
    .filter((item) => Number.isInteger(item.id) && item.id > 0 && item.nome.length > 0)
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
}

export function createAgendaCatalogLoader<T>({
  request,
  onSuccess,
  onLoadingChange,
  onError,
}: AgendaCatalogLoaderOptions<T>): AgendaCatalogLoader {
  let loaded = false;
  let inFlight: Promise<boolean> | null = null;

  return {
    load(): Promise<boolean> {
      if (loaded) return Promise.resolve(true);
      if (inFlight) return inFlight;

      onLoadingChange?.(true);
      inFlight = request()
        .then((value) => {
          onSuccess(value);
          loaded = true;
          return true;
        })
        .catch((error: unknown) => {
          onError?.(error);
          return false;
        })
        .finally(() => {
          inFlight = null;
          onLoadingChange?.(false);
        });
      return inFlight;
    },
    isLoaded(): boolean {
      return loaded;
    },
  };
}
