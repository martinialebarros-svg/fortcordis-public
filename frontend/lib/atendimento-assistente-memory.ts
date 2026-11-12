import type { AssistenteIAResultado, AssistenteTranscricaoFonteRevisao } from "./atendimento-assistente-ia";
import type { AtendimentoAudioBackup } from "./atendimento-audio-backup";

export interface AssistenteMemoryIdentity {
  usuarioId: number;
  atendimentoId: number;
  pacienteId: number;
}

export interface AssistenteMemoryReview {
  texto: string;
  arquivos: File[];
  resultado: AssistenteIAResultado | null;
  edicoes: Record<number, string>;
  revisados: Record<number, boolean>;
  aplicados: Record<number, boolean>;
  achadosEditados: Record<number, string>;
  achadosRevisados: Record<number, boolean>;
  achadosAplicados: Record<number, boolean>;
  audioTranscrito: string | null;
  anexados: boolean;
  resultadoLoteId?: string | null;
  revisoesTranscricao?: AssistenteTranscricaoFonteRevisao[];
  transcricaoEditadaDesdeRevisao?: boolean;
}

interface MemoryDraft {
  audio?: AtendimentoAudioBackup;
  review?: AssistenteMemoryReview;
}

// This cache lives only in the current JavaScript page. It survives SPA navigation,
// never writes browser storage, and disappears on reload or tab closure.
const drafts = new Map<string, MemoryDraft>();
const audioListeners = new Map<string, Set<(audio: AtendimentoAudioBackup | null) => void>>();
const key = ({ usuarioId, atendimentoId, pacienteId }: AssistenteMemoryIdentity) =>
  JSON.stringify([usuarioId, atendimentoId, pacienteId]);

export function lerRascunhoAssistenteMemoria(identity: AssistenteMemoryIdentity): MemoryDraft | null {
  return drafts.get(key(identity)) || null;
}

export function guardarRevisaoAssistenteMemoria(identity: AssistenteMemoryIdentity, review: AssistenteMemoryReview): void {
  const id = key(identity);
  drafts.set(id, { ...drafts.get(id), review });
}

export function guardarAudioAssistenteMemoria(audio: AtendimentoAudioBackup): void {
  const id = key(audio);
  drafts.set(id, { ...drafts.get(id), audio });
  audioListeners.get(id)?.forEach((listener) => listener(audio));
}

export function apagarAudioAssistenteMemoria(identity: AssistenteMemoryIdentity): void {
  const id = key(identity);
  const draft = drafts.get(id);
  if (!draft) return;
  if (draft.review) drafts.set(id, { review: draft.review });
  else drafts.delete(id);
  audioListeners.get(id)?.forEach((listener) => listener(null));
}

export function observarAudioAssistenteMemoria(identity: AssistenteMemoryIdentity, listener: (audio: AtendimentoAudioBackup | null) => void): () => void {
  const id = key(identity);
  const listeners = audioListeners.get(id) || new Set();
  listeners.add(listener);
  audioListeners.set(id, listeners);
  return () => {
    listeners.delete(listener);
    if (!listeners.size) audioListeners.delete(id);
  };
}

export function limparRascunhosAssistenteMemoria(): void {
  drafts.clear();
}
