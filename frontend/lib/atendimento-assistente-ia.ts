import type { ClinicalFieldKey } from "./atendimento-clinical-notes";

// Decimal bytes leave headroom below the provider's documented 25 MB ceiling.
export const ASSISTENTE_AUDIO_MAX_BYTES = 24_000_000;
export const ASSISTENTE_AUDIO_MAX_SECONDS = 30 * 60;
export const ASSISTENTE_AUDIO_ACCEPT = ".mp3,.mp4,.mpeg,.mpga,.m4a,.wav,.webm";
export const ASSISTENTE_FILE_ACCEPT = ".jpg,.jpeg,.png,.webp,.pdf";
export const ASSISTENTE_CAMPO_LABELS: Partial<Record<ClinicalFieldKey, string>> = {
  queixa_principal: "Queixa principal",
  anamnese: "Anamnese",
  exame_fisico: "Exame físico",
  dados_clinicos: "Dados clínicos",
  observacoes: "Observações",
};

export interface AssistenteIAStatus {
  usuario_id?: number;
  habilitado: boolean;
  configurado: boolean;
  modelo: string;
  esforco: string;
  esforco_texto?: string;
  modelo_transcricao: string;
  limites?: { audio_bytes: number; arquivo_bytes: number; total_arquivos_bytes: number; arquivos: number; transcricao_chars: number };
}

export interface AssistenteTranscricaoRevisao {
  estado: "concluida" | "parcial" | "indisponivel";
  trechos_total: number;
  trechos_revisados: number;
  avisos: string[];
  trechos: Array<{
    indice: number;
    // These are bounds of the whole audio chunk, not word-level timestamps.
    inicio_segundos: number;
    fim_segundos: number;
    estado: "concluido" | "indisponivel";
    limitado: boolean;
    divergencias: Array<{ texto_original: string; leitura_alternativa: string }>;
    marcacoes_incerteza: string[];
  }>;
}

export interface AssistenteTranscricaoFonteRevisao {
  arquivo_id?: string;
  nome: string;
  revisao_transcricao: AssistenteTranscricaoRevisao;
}

export interface AssistenteTranscricaoResultado {
  texto: string;
  modelo: string;
  avisos: string[];
  revisao_transcricao?: AssistenteTranscricaoRevisao;
}

export interface AssistenteIAResultado {
  modelo: string;
  esforco: string;
  revisao_obrigatoria: boolean;
  bloqueado_integracao: boolean;
  raca_pendente_revisao?: boolean;
  // Local review marker, retained with the draft after an uncertain mutation.
  revisao_desatualizada?: boolean;
  campos: Array<{ campo: ClinicalFieldKey; texto: string; fonte: string; evidencia: string }>;
  fontes: Array<{ arquivo: string; paciente_nome: string | null; especie: string | null; data_exame: string | null; identidade: "compativel" | "divergente" | "nao_confirmada"; motivo: string; revisao_raca?: { decisao: "mesmo_paciente_raca_pendente"; usuario_id: number; registrado_em: string } }>;
  achados_exames: Array<{ arquivo: string; pagina: number | null; descricao: string; evidencia: string; valor: string | null; unidade: string | null; referencia: string | null; confianca: "alta" | "media" | "baixa"; alertas: string[] }>;
  sugestoes: Array<{ titulo: string; justificativa: string; conduta: string; limitacoes: string[] }>;
  pendencias: string[];
  avisos: string[];
}

export function validarArquivosAssistente(files: File[], limites?: AssistenteIAStatus["limites"]): string | null {
  if (files.length > (limites?.arquivos ?? 5)) return "Selecione no máximo cinco arquivos por análise.";
  const maxArquivo = limites?.arquivo_bytes ?? 10 * 1024 * 1024;
  const maxTotal = limites?.total_arquivos_bytes ?? 20 * 1024 * 1024;
  if (files.some((file) => !/\.(jpe?g|png|webp|pdf)$/i.test(file.name))) return "Use fotografias JPG, PNG, WebP ou documentos PDF.";
  if (files.some((file) => !file.size || file.size > maxArquivo)) return "Cada arquivo precisa ter conteúdo e até 10 MB.";
  if (files.reduce((total, file) => total + file.size, 0) > maxTotal) return "O conjunto de arquivos deve ter até 20 MB.";
  return null;
}

export function escolherMimeGravacao(isSupported: (mime: string) => boolean): string | undefined {
  return ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find(isSupported);
}

export function extensaoAudio(mime: string): string {
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("webm")) return "webm";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("flac")) return "flac";
  if (mime.includes("wav")) return "wav";
  if (mime.includes("mpeg")) return "mp3";
  // Preserve an unknown recording for download without relabeling it as WebM.
  return "bin";
}

export function limiteAudioAssistente(maxBytes = ASSISTENTE_AUDIO_MAX_BYTES): number {
  return Number.isFinite(maxBytes) && maxBytes > 0 ? Math.min(maxBytes, ASSISTENTE_AUDIO_MAX_BYTES) : ASSISTENTE_AUDIO_MAX_BYTES;
}

export function validarAudioParaTranscricao(file: Pick<File, "name" | "size">, maxBytes = ASSISTENTE_AUDIO_MAX_BYTES): string | null {
  const limit = limiteAudioAssistente(maxBytes);
  if (!file.size) return "O áudio está vazio. Grave novamente ou selecione outro arquivo.";
  if (file.size > limit) {
    return `O áudio excede ${new Intl.NumberFormat("pt-BR").format(limit)} bytes e não pode ser enviado para transcrição. O original foi preservado: baixe-o, divida em trechos menores e carregue um trecho por vez.`;
  }
  if (!/\.(mp3|mp4|mpeg|mpga|m4a|wav|webm)$/i.test(file.name)) {
    return "Este formato de áudio não pode ser enviado para transcrição. O original foi preservado para ouvir ou baixar; converta uma cópia para MP3, MP4/M4A, MPEG/MPGA, WAV ou WebM e carregue essa cópia.";
  }
  return null;
}

export function podeIncorporarCampo(resultado: AssistenteIAResultado, campo: AssistenteIAResultado["campos"][number]): boolean {
  return resultado.revisao_desatualizada !== true && resultado.bloqueado_integracao === false && resultado.revisao_obrigatoria === true &&
    Object.prototype.hasOwnProperty.call(ASSISTENTE_CAMPO_LABELS, campo.campo) &&
    Boolean(campo.evidencia?.trim()) && Boolean(campo.fonte?.trim());
}

export function temRevisaoRacaConfirmada(fonte: AssistenteIAResultado["fontes"][number]): boolean {
  const revisao = fonte.revisao_raca;
  return revisao?.decisao === "mesmo_paciente_raca_pendente" && Number.isInteger(revisao.usuario_id) &&
    revisao.usuario_id > 0 && Boolean(revisao.registrado_em) && Number.isFinite(Date.parse(revisao.registrado_em));
}

export function podeIncorporarAchado(resultado: AssistenteIAResultado, achado: AssistenteIAResultado["achados_exames"][number]): boolean {
  return resultado.revisao_desatualizada !== true && resultado.bloqueado_integracao === false && resultado.revisao_obrigatoria === true && achado.confianca === "alta" &&
    Boolean(achado.evidencia?.trim()) && resultado.fontes.some((fonte) => fonte.arquivo === achado.arquivo &&
      (fonte.identidade === "compativel" || (resultado.raca_pendente_revisao === true && temRevisaoRacaConfirmada(fonte))));
}

export function textoAchadoParaRevisao(resultado: AssistenteIAResultado, achado: AssistenteIAResultado["achados_exames"][number]): string {
  const fonte = resultado.fontes.find((item) => item.arquivo === achado.arquivo);
  const origem = `${achado.arquivo}${achado.pagina ? `, página ${achado.pagina}` : ""}${fonte?.data_exame ? `, exame de ${fonte.data_exame}` : ""}`;
  const valor = achado.valor ? `: ${achado.valor}${achado.unidade ? ` ${achado.unidade}` : " (unidade não informada)"}` : "";
  return `[Exame: ${origem}] ${achado.descricao}${valor}.${achado.referencia ? ` Referência descrita no exame: ${achado.referencia}.` : ""}${achado.alertas.length ? ` Pendências: ${achado.alertas.join("; ")}.` : ""}`;
}
