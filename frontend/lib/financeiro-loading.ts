export type FinanceiroSectionLoadStatus = "success" | "failed" | "cancelled";

export type FinanceiroActiveTab = "transacoes" | "cobrancas" | "ordens";

export interface FinanceiroLoadingPlan {
  transacoes: boolean;
  ordens: boolean;
  catalogosOrdens: boolean;
}

export interface FinanceiroSectionLoadResult {
  section: string;
  status: FinanceiroSectionLoadStatus;
  error?: unknown;
}

interface LoadFinanceiroSectionOptions<T> {
  section: string;
  request: Promise<T>;
  signal: AbortSignal;
  onSuccess: (value: T) => void;
  onSettled?: () => void;
}

/**
 * De onde partiu a carga. `efeito` e a reacao a mudanca de aba, filtro, busca ou
 * pagina; `manual` e recarga explicita ou pos-mutacao, quando o dinheiro pode
 * ter mudado.
 */
export type FinanceiroLoadOrigin = "efeito" | "manual";

interface DeveRecarregarResumoOptions {
  origem: FinanceiroLoadOrigin;
  periodoAtual: string;
  /** Periodo do ultimo resumo aplicado com sucesso; null antes da primeira carga. */
  periodoCarregado: string | null;
}

/**
 * O resumo monetario depende so de `periodo` - a URL e
 * `/financeiro/resumo?periodo=...`. Refaze-lo a cada troca de pagina ou filtro e
 * requisicao desperdicada. Recarga manual sempre refaz, porque pode vir depois
 * de receber pagamento.
 */
export function deveRecarregarResumo({
  origem,
  periodoAtual,
  periodoCarregado,
}: DeveRecarregarResumoOptions): boolean {
  if (origem === "manual") return true;
  return periodoCarregado !== periodoAtual;
}

export function getFinanceiroLoadingPlan(activeTab: FinanceiroActiveTab): FinanceiroLoadingPlan {
  const shouldLoadOrders = activeTab === "cobrancas" || activeTab === "ordens";

  return {
    transacoes: activeTab === "transacoes",
    ordens: shouldLoadOrders,
    catalogosOrdens: shouldLoadOrders,
  };
}

export async function loadFinanceiroSection<T>({
  section,
  request,
  signal,
  onSuccess,
  onSettled,
}: LoadFinanceiroSectionOptions<T>): Promise<FinanceiroSectionLoadResult> {
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
  } finally {
    if (!signal.aborted) {
      onSettled?.();
    }
  }
}

export function appendUniqueLoadFailure(current: string[], section: string): string[] {
  return current.includes(section) ? current : [...current, section];
}

export function removeLoadFailure(current: string[], section: string): string[] {
  return current.filter((item) => item !== section);
}
