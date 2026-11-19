export interface OrderSnapshot {
  id: number;
  status: string;
  valor_final: number;
  valor_recebido?: number;
  valor_em_aberto?: number;
}

const fields = ["id", "status", "valor_final", "valor_recebido", "valor_em_aberto", "paciente_id", "tutor_id", "clinica_id", "servico_id",
  "responsavel_pagamento_tipo", "responsavel_pagamento_id", "responsavel_pagamento_nome",
  "numero_os", "data_atendimento", "origem_atendimento", "destinatario_tipo", "destinatario_nome",
  "destinatario_telefone", "destinatario_email", "paciente", "tutor", "clinica", "servico"];
function fingerprint(value: OrderSnapshot) {
  const record = value as unknown as Record<string, unknown>;
  return JSON.stringify(fields.map((key) => record[key] ?? null));
}

function assertSameOrder(before: OrderSnapshot, current: OrderSnapshot | undefined, status: string): void {
  if (!current || current.status !== status || fingerprint(current) !== fingerprint(before)) {
    throw new Error("Uma OS mudou desde a selecao. Limpe a selecao, atualize a lista e confira novamente.");
  }
}

/** The bulk read must return the entire selected set with unchanged order data. */
export function validateOrderSelectionBatch<T extends OrderSnapshot>(
  ids: number[], snapshots: T[], status: string, currentOrders: T[],
): void {
  if (!ids.length || new Set(ids).size !== ids.length) throw new Error("Selecao de OS invalida.");
  const expected = new Map(snapshots.map((os) => [os.id, os]));
  const current = new Map(currentOrders.map((os) => [os.id, os]));
  if (currentOrders.length !== ids.length || current.size !== ids.length) {
    throw new Error("Uma OS mudou desde a selecao. Limpe a selecao, atualize a lista e confira novamente.");
  }
  for (const id of ids) {
    const before = expected.get(id);
    if (!before || before.status !== status) throw new Error("Selecao de OS mudou. Limpe a selecao e confira novamente.");
    assertSameOrder(before, current.get(id), status);
  }
}

/** Read-only, bounded concurrency. Any missing/changed item invalidates the entire selection. */
export async function validateOrderSelection<T extends OrderSnapshot>(
  ids: number[], snapshots: T[], status: string, read: (id: number) => Promise<T>
): Promise<void> {
  if (!ids.length || new Set(ids).size !== ids.length) throw new Error("Selecao de OS invalida.");
  const expected = new Map(snapshots.map((os) => [os.id, os]));
  for (let start = 0; start < ids.length; start += 5) {
    await Promise.all(ids.slice(start, start + 5).map(async (id) => {
      const before = expected.get(id);
      if (!before || before.status !== status) throw new Error("Selecao de OS mudou. Limpe a selecao e confira novamente.");
      assertSameOrder(before, await read(id), status);
    }));
  }
}
