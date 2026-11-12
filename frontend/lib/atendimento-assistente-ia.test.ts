import { describe, expect, it } from "vitest";
import { ASSISTENTE_AUDIO_MAX_BYTES, escolherMimeGravacao, extensaoAudio, podeIncorporarAchado, podeIncorporarCampo, validarArquivosAssistente, validarAudioParaTranscricao, type AssistenteIAResultado } from "./atendimento-assistente-ia";

describe("assistência IA do atendimento", () => {
  it("escolhe MP4 para navegadores que não suportam WebM", () => {
    expect(escolherMimeGravacao((mime) => mime === "audio/mp4")).toBe("audio/mp4");
    expect(escolherMimeGravacao(() => false)).toBeUndefined();
    expect(escolherMimeGravacao((mime) => mime.includes("ogg"))).toBeUndefined();
  });
  it("aceita até 24 MB decimais e recusa o antigo teto de 24 MiB", () => {
    expect(ASSISTENTE_AUDIO_MAX_BYTES).toBe(24_000_000);
    expect(validarAudioParaTranscricao({ name: "consulta.webm", size: 24_000_000 })).toBeNull();
    expect(validarAudioParaTranscricao({ name: "consulta.webm", size: 24_000_001 })).toContain("24.000.000 bytes");
    expect(validarAudioParaTranscricao({ name: "consulta.webm", size: 24 * 1024 * 1024 }, 24 * 1024 * 1024)).toContain("não pode ser enviado");
    expect(validarAudioParaTranscricao({ name: "consulta.webm", size: 9 }, 8)).toContain("8 bytes");
  });
  it("envia somente formatos documentados sem renomear gravações desconhecidas", () => {
    for (const extension of ["mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"]) {
      expect(validarAudioParaTranscricao({ name: `consulta.${extension}`, size: 10 })).toBeNull();
    }
    for (const extension of ["ogg", "flac", "bin"]) {
      expect(validarAudioParaTranscricao({ name: `consulta.${extension}`, size: 10 })).toContain("converta uma cópia");
    }
    expect(extensaoAudio("audio/ogg;codecs=opus")).toBe("ogg");
    expect(extensaoAudio("audio/flac")).toBe("flac");
    expect(extensaoAudio("application/octet-stream")).toBe("bin");
  });
  it("bloqueia arquivos incompatíveis, vazios ou em quantidade excessiva", () => {
    expect(validarArquivosAssistente([new File(["ok"], "exame.pdf")])).toBeNull();
    expect(validarArquivosAssistente([new File(["ok"], "exame.html")])).toContain("PDF");
    expect(validarArquivosAssistente([new File([], "exame.pdf")])).toContain("conteúdo");
    expect(validarArquivosAssistente(Array.from({ length: 6 }, () => new File(["ok"], "exame.pdf")))).toContain("cinco");
  });
  it("rejeita lote acima do limite somado mesmo que cada arquivo seja permitido", () => {
    const files = [new File(["123456"], "a.pdf"), new File(["123456"], "b.pdf")];
    expect(validarArquivosAssistente(files, { arquivos: 5, arquivo_bytes: 10, total_arquivos_bytes: 10, audio_bytes: 100, transcricao_chars: 100 })).toContain("conjunto");
  });
  it("exige fonte, evidência, revisão e campo permitido, mesmo para resposta inesperada", () => {
    const resultado = { bloqueado_integracao: false, revisao_obrigatoria: true } as AssistenteIAResultado;
    const campo = { campo: "anamnese" as const, texto: "Relato", fonte: "transcricao", evidencia: "relato original" };
    expect(podeIncorporarCampo(resultado, campo)).toBe(true);
    expect(podeIncorporarCampo({ ...resultado, bloqueado_integracao: true }, campo)).toBe(false);
    expect(podeIncorporarCampo({ ...resultado, revisao_desatualizada: true }, campo)).toBe(false);
    expect(podeIncorporarCampo(resultado, { ...campo, evidencia: "" })).toBe(false);
    expect(podeIncorporarCampo(resultado, { ...campo, campo: "plano_terapeutico" })).toBe(false);
  });
  it("aceita achado de raça pendente apenas com decisão veterinária explícita e preserva os outros bloqueios", () => {
    const fonte: AssistenteIAResultado["fontes"][number] = {
      arquivo: "exame.pdf", paciente_nome: "Paciente Teste", especie: "canino", data_exame: "2026-11-08", identidade: "divergente", motivo: "Raça diferente",
      revisao_raca: { decisao: "mesmo_paciente_raca_pendente", usuario_id: 7, registrado_em: "2026-11-09T12:00:00Z" },
    };
    const resultado = { bloqueado_integracao: false, revisao_obrigatoria: true, raca_pendente_revisao: true, fontes: [fonte] } as AssistenteIAResultado;
    const achado: AssistenteIAResultado["achados_exames"][number] = { arquivo: "exame.pdf", pagina: 2, descricao: "Creatinina", evidencia: "Creatinina 1,2 mg/dL", valor: "1,2", unidade: "mg/dL", referencia: "0,5–1,5", confianca: "alta", alertas: [] };
    expect(podeIncorporarAchado(resultado, achado)).toBe(true);
    expect(podeIncorporarAchado({ ...resultado, raca_pendente_revisao: false }, achado)).toBe(false);
    expect(podeIncorporarAchado({ ...resultado, bloqueado_integracao: true }, achado)).toBe(false);
    expect(podeIncorporarAchado({ ...resultado, revisao_desatualizada: true }, achado)).toBe(false);
    expect(podeIncorporarAchado({ ...resultado, fontes: [{ ...fonte, revisao_raca: undefined }] }, achado)).toBe(false);
    expect(podeIncorporarAchado({ ...resultado, fontes: [{ ...fonte, revisao_raca: { ...fonte.revisao_raca!, registrado_em: "inválido" } }] }, achado)).toBe(false);
    expect(podeIncorporarAchado(resultado, { ...achado, evidencia: "" })).toBe(false);
    expect(podeIncorporarAchado(resultado, { ...achado, confianca: "baixa" })).toBe(false);
    expect(podeIncorporarAchado(resultado, { ...achado, arquivo: "outro.pdf" })).toBe(false);
  });
});
