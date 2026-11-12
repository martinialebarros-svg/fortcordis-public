export interface OrderSnapshot { id: number; status: string; valor_final: number }

const fields = ["id", "status", "valor_final", "paciente_id", "tutor_id", "clinica_id", "servico_id",
  "numero_os", "data_atendimento", "origem_atendimento", "destinatario_tipo", "destinatario_nome",
  "destinatario_telefone", "destinatario_email", "paciente", "tutor", "clinica", "servico"];
function fingerprint(value: OrderSnapshot) {
  const record = value as unknown as Record<string, unknown>;
  return JSON.stringify(fields.map((key) => record[key] ?? null));
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
      const current = await read(id);
      if (current.status !== status || fingerprint(current) !== fingerprint(before)) {
        throw new Error("Uma OS mudou desde a selecao. Limpe a selecao, atualize a lista e confira novamente.");
      }
    }));
  }
}
