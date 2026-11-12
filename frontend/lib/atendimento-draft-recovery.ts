import type { AtendimentoForm } from "@/app/atendimento/page";
import { restorePersistedAtendimentoDraft } from "./atendimento-form-merge";

export type AtendimentoBackup = {
  form: Partial<AtendimentoForm>;
  base_snapshot?: string;
  updated_at?: string;
  writer_id?: string;
};

type BackupStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** Um undo que volta a base elimina apenas a copia que esta sessao escreveu.
 * Uma copia diferente, escrita por outra aba, nao pode ser apagada por ela. */
export function writePendingAtendimentoBackup(
  storage: BackupStorage,
  key: string,
  form: AtendimentoForm,
  baseSnapshot: string,
  serialize: (form: AtendimentoForm) => string,
  lastWrittenRaw: string | null,
  writerId: string
): string | null {
  if (serialize(form) === baseSnapshot) {
    if (lastWrittenRaw && storage.getItem(key) === lastWrittenRaw) storage.removeItem(key);
    return null;
  }
  const raw = JSON.stringify({ form, base_snapshot: baseSnapshot, writer_id: writerId, updated_at: new Date().toISOString() });
  storage.setItem(key, raw);
  return raw;
}

export type BackupRecovery = {
  mode: "clean" | "automatic" | "review";
  candidate: AtendimentoForm;
};

const canonical = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, canonical(item)]));
  }
  return value;
};

/** Compara conteudo, sem depender de relogio local ou formato/fuso de updated_at.
 * O estado do encerramento e seus metadados nunca sao recuperados do backup. */
function comparableSnapshot(snapshot: string, completed: boolean): string {
  const data = JSON.parse(snapshot) as Record<string, unknown>;
  if (completed) {
    for (const key of ["status", "consulta_concluida", "triagem_concluida", "paciente_id", "agendamento_id", "clinica_id", "data_atendimento"]) delete data[key];
  }
  return JSON.stringify(canonical(data));
}

export function assessAtendimentoBackup(
  persisted: AtendimentoForm,
  backup: AtendimentoBackup,
  serialize: (form: AtendimentoForm) => string
): BackupRecovery {
  const candidate = restorePersistedAtendimentoDraft(persisted, backup.form);
  if (candidate === persisted) return { mode: "review", candidate: persisted };
  const completed = persisted.status === "Concluido";
  const server = comparableSnapshot(serialize(persisted), completed);
  const local = comparableSnapshot(serialize(candidate), completed);
  if (local === server) return { mode: "clean", candidate: persisted };
  if (!backup.base_snapshot) return { mode: "review", candidate };

  try {
    const base = comparableSnapshot(backup.base_snapshot, completed);
    // Uma copia que ja estava salva nao pode desfazer a correcao de outra aba.
    if (local === base) return { mode: "clean", candidate: persisted };
    // Nao mescla partes de receitas/exames de origens divergentes sem revisao.
    if (server !== base) return { mode: "review", candidate };
    return { mode: "automatic", candidate };
  } catch {
    return { mode: "review", candidate };
  }
}

export function atendimentoBackupDifferences(
  server: AtendimentoForm,
  candidate: AtendimentoForm,
  serialize: (form: AtendimentoForm) => string
): Array<{ campo: string; salvo: unknown; local: unknown }> {
  const saved = JSON.parse(serialize(server)) as Record<string, unknown>;
  const local = JSON.parse(serialize(candidate)) as Record<string, unknown>;
  return Object.keys(local)
    .filter((campo) => campo !== "prescricao" && campo !== "_receita_alvo")
    .filter((campo) => JSON.stringify(canonical(saved[campo])) !== JSON.stringify(canonical(local[campo])))
    .map((campo) => ({ campo: campo === "_receita" ? "prescricao" : campo, salvo: saved[campo], local: local[campo] }));
}
