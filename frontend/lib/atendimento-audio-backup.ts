export interface AtendimentoAudioBackup {
  atendimentoId: number;
  usuarioId: number;
  pacienteId: number;
  blob: Blob;
  filename: string;
  seconds: number;
  finalizado: boolean;
  atualizadoEm: number;
  copiaDispositivo?: boolean;
}

const DATABASE = "fortcordis-atendimento-audio-v3";
const STORE = "gravacoes";
// Automatic expiry limits the lifetime of an explicitly enabled device copy.
const RETENTION_MS = 24 * 60 * 60 * 1000;

async function abrirBanco(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") return reject(new Error("Cópia local indisponível neste navegador."));
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: ["usuarioId", "atendimentoId", "pacienteId"] });
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Feche outras abas para habilitar a cópia local."));
    request.onsuccess = () => resolve(request.result);
  });
}

export async function salvarAudioBackup(backup: AtendimentoAudioBackup): Promise<void> {
  const db = await abrirBanco();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(backup);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}

export async function apagarAudioBackup(usuarioId: number, atendimentoId: number, pacienteId: number): Promise<void> {
  const db = await abrirBanco();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).delete([usuarioId, atendimentoId, pacienteId]);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}

export async function lerAudioBackup(usuarioId: number, atendimentoId: number, pacienteId: number): Promise<AtendimentoAudioBackup | null> {
  const db = await abrirBanco();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      const store = tx.objectStore(STORE);
      let found: AtendimentoAudioBackup | null = null;
      const request = store.openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return;
        const value = cursor.value as AtendimentoAudioBackup;
        if (Date.now() - value.atualizadoEm > RETENTION_MS) cursor.delete();
        else if (value.usuarioId === usuarioId && value.atendimentoId === atendimentoId && value.pacienteId === pacienteId) found = value;
        cursor.continue();
      };
      tx.oncomplete = () => resolve(found);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}
