import {
  validarArquivosAssistente, validarAudioParaTranscricao,
  type AssistenteIAResultado, type AssistenteTranscricaoFonteRevisao,
} from "./atendimento-assistente-ia";

export type TipoFonteLote = "audio" | "exame";
export interface FonteLote {
  id: string;
  nome: string;
  tipo: TipoFonteLote;
  tamanho: number;
  mime?: string;
  status: "pending" | "uploaded" | "processing" | "failed" | "completed";
  erro: string | null;
}

export interface AssistenteLote {
  id: string;
  atendimento_id: number;
  paciente_id: number;
  status: "uploading" | "queued" | "processing" | "failed" | "completed";
  erro: string | null;
  arquivos: FonteLote[];
  resultado: AssistenteIAResultado | null;
  transcricao: string | null;
  revisoes_transcricao?: AssistenteTranscricaoFonteRevisao[];
  revisao_raca?: {
    token: string;
    pode_revisar: boolean;
    raca_cadastrada: string | null;
    fontes: Array<{
      arquivo_id: string;
      nome: string;
      paciente_nome: string | null;
      especie: string | null;
      identidade: "compativel" | "divergente" | "nao_confirmada";
      motivo: string;
      elegivel: boolean;
      impedimento: string | null;
      confirmada: boolean;
      registrado_em: string | null;
    }>;
  };
}

export interface ArquivoLoteLocal {
  id: string;
  file: File;
  tipo: TipoFonteLote;
}

export function tipoArquivoLote(file: File): TipoFonteLote {
  return /\.(mp3|mp4|mpeg|mpga|m4a|wav|webm)$/i.test(file.name) ? "audio" : "exame";
}

export function validarArquivosLote(files: File[]): string | null {
  const audios = files.filter((file) => tipoArquivoLote(file) === "audio");
  const exames = files.filter((file) => tipoArquivoLote(file) === "exame");
  if (audios.length > 5) return "Selecione até cinco áudios por conjunto.";
  for (const audio of audios) {
    const error = validarAudioParaTranscricao(audio);
    if (error) return `${audio.name}: ${error}`;
  }
  return validarArquivosAssistente(exames);
}

export const STATUS_FONTE_LOTE: Record<FonteLote["status"], string> = {
  pending: "Aguardando envio",
  uploaded: "Recebido",
  processing: "Processando",
  failed: "Falhou — aguarda retomada",
  completed: "Concluído",
};
