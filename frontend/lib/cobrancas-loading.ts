export interface BillingGroup {
  chave: string;
  nome_destinatario: string;
  tipo_destinatario: "clinica" | "tutor";
  quantidade_total: number;
  quantidade_os: number;
  total_pendente: number;
}
interface BillingOrder { id: number; status: string; valor_final: number }
interface BillingPage<T> { total: number; items: T[]; resumo: { pendentes: number; valor_pendente: number } }
const cents = (value: number) => Math.round(value * 100);

/** Never expose a partial recipient to receipt/payment/message actions. */
export async function loadCompleteBillingGroup<T extends BillingOrder>(
  group: BillingGroup, read: (skip: number, limit: number) => Promise<BillingPage<T>>, signal: AbortSignal,
): Promise<T[]> {
  if (!Number.isInteger(group.quantidade_total) || group.quantidade_total < 1 || group.quantidade_total > 10000) {
    throw new Error("Restrinja os filtros para abrir um destinatario com ate 10000 OS.");
  }
  const items = new Map<number, T>();
  for (let skip = 0; skip < group.quantidade_total; skip += 100) {
    if (signal.aborted) throw new Error("Carregamento cancelado.");
    const page = await read(skip, 100);
    if (signal.aborted) throw new Error("Carregamento cancelado.");
    if (page.total !== group.quantidade_total || !page.resumo ||
      page.resumo.pendentes !== group.quantidade_os || cents(page.resumo.valor_pendente) !== cents(group.total_pendente) ||
      page.items.length !== Math.min(100, group.quantidade_total - skip)) {
      throw new Error("As cobrancas mudaram durante a leitura. Atualize os destinatarios e tente novamente.");
    }
    for (const item of page.items) {
      if (items.has(item.id) || item.status === "Cancelado" || !Number.isFinite(item.valor_final)) {
        throw new Error("Leitura inconsistente das OS. Atualize os destinatarios e tente novamente.");
      }
      items.set(item.id, item);
    }
  }
  const pending = [...items.values()].filter((os) => os.status === "Pendente");
  if (pending.length !== group.quantidade_os || pending.reduce((sum, os) => sum + cents(os.valor_final), 0) !== cents(group.total_pendente)) {
    throw new Error("Os valores das cobrancas mudaram. Atualize os destinatarios e tente novamente.");
  }
  return [...items.values()];
}
