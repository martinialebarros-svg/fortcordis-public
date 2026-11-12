import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAtendimentoAudio } from "./use-atendimento-audio";
import { apagarAudioBackup, lerAudioBackup, salvarAudioBackup } from "./atendimento-audio-backup";
import { guardarAudioAssistenteMemoria, lerRascunhoAssistenteMemoria, limparRascunhosAssistenteMemoria } from "./atendimento-assistente-memory";

vi.mock("./atendimento-audio-backup", () => ({
  apagarAudioBackup: vi.fn(), lerAudioBackup: vi.fn(), salvarAudioBackup: vi.fn(),
}));

beforeEach(() => {
  limparRascunhosAssistenteMemoria();
  vi.mocked(lerAudioBackup).mockResolvedValue(null);
  vi.mocked(apagarAudioBackup).mockResolvedValue();
  vi.mocked(salvarAudioBackup).mockResolvedValue();
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

describe("recuperação de áudio por atendimento e usuário", () => {
  it("não lê cópias sem identidade autenticada", async () => {
    const { result } = renderHook(() => useAtendimentoAudio(1, null, 1));
    await waitFor(() => expect(result.current.carregandoBackup).toBe(false));
    expect(lerAudioBackup).not.toHaveBeenCalled();
    await act(() => result.current.setManterCopia(true));
    expect(result.current.manterCopia).toBe(false);
  });
  it("permite descartar gravação em memória com IndexedDB indisponível", async () => {
    vi.mocked(lerAudioBackup).mockRejectedValue(new Error("blocked"));
    vi.mocked(apagarAudioBackup).mockRejectedValue(new Error("blocked"));
    const { result } = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(result.current.carregandoBackup).toBe(false));
    act(() => result.current.importar(new File(["audio"], "teste.webm", { type: "audio/webm" })));
    expect(result.current.audio).not.toBeNull();
    await act(() => result.current.descartar());
    expect(result.current.audio).toBeNull();
    expect(apagarAudioBackup).not.toHaveBeenCalled();
  });
  it("recupera somente a chave do usuário e atendimento corretos", async () => {
    vi.mocked(lerAudioBackup).mockResolvedValue({ usuarioId: 7, atendimentoId: 2, pacienteId: 1, blob: new Blob(["audio"], { type: "audio/webm" }), filename: "trecho.webm", seconds: 8, finalizado: false, atualizadoEm: Date.now() });
    const { result } = renderHook(() => useAtendimentoAudio(2, 7, 1));
    await waitFor(() => expect(result.current.audio?.name).toBe("trecho.webm"));
    expect(lerAudioBackup).toHaveBeenCalledWith(7, 2, 1);
    expect(result.current.aviso).toContain("interrompida");
    expect(result.current.manterCopia).toBe(true);
  });
  it("não afirma descarte se a cópia persistida não pôde ser removida", async () => {
    const { result } = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(result.current.carregandoBackup).toBe(false));
    await act(() => result.current.setManterCopia(true));
    act(() => result.current.importar(new File(["audio"], "teste.webm")));
    await waitFor(() => expect(salvarAudioBackup).toHaveBeenCalled());
    vi.mocked(apagarAudioBackup).mockRejectedValue(new Error("blocked"));
    await act(() => result.current.descartar());
    expect(result.current.audio).not.toBeNull();
    expect(result.current.erro).toContain("Não foi possível apagar");
  });
  it("não restaura áudio de outro paciente mesmo dentro do mesmo atendimento", async () => {
    vi.mocked(lerAudioBackup).mockResolvedValue({ usuarioId: 7, atendimentoId: 1, pacienteId: 9, blob: new Blob(["audio"]), filename: "outro.webm", seconds: 8, finalizado: true, atualizadoEm: Date.now() });
    const { result } = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(result.current.carregandoBackup).toBe(false));
    expect(lerAudioBackup).toHaveBeenCalledWith(7, 1, 1);
    expect(result.current.audio).toBeNull();
  });
  it("preserva os fragmentos na ordem e libera o microfone ao terminar", async () => {
    const stop = vi.fn();
    const track = { stop, onended: null as (() => void) | null };
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    class Recorder {
      static current: Recorder;
      static isTypeSupported(mime: string) { return mime === "audio/mp4"; }
      mimeType = "audio/mp4";
      state = "inactive";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() { Recorder.current = this; }
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob(["final"]) });
        this.onstop?.();
      }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    const { result } = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(result.current.carregandoBackup).toBe(false));
    await act(() => result.current.iniciar());
    expect(result.current.gravando).toBe(true);
    act(() => Recorder.current.ondataavailable?.({ data: new Blob(["header"]) }));
    act(() => result.current.parar());
    expect(result.current.gravando).toBe(false);
    expect(result.current.audio?.type).toBe("audio/mp4");
    expect(result.current.audio?.name).toMatch(/\.m4a$/);
    expect(result.current.audio?.size).toBe("headerfinal".length);
    expect(stop).toHaveBeenCalled();
    expect(salvarAudioBackup).not.toHaveBeenCalled();
  });
  it("recupera áudio em memória após navegação e remove ao descartar", async () => {
    const first = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(first.result.current.carregandoBackup).toBe(false));
    const file = new File(["audio"], "consulta.webm");
    act(() => first.result.current.importar(file));
    first.unmount();
    const second = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(second.result.current.audio).toBe(file));
    expect(salvarAudioBackup).not.toHaveBeenCalled();
    await act(() => second.result.current.descartar());
    expect(lerRascunhoAssistenteMemoria({ usuarioId: 7, atendimentoId: 1, pacienteId: 1 })?.audio).toBeUndefined();
  });
  it("atualiza áudio recuperado quando o gravador finaliza após desmontagem", async () => {
    const identity = { usuarioId: 7, atendimentoId: 1, pacienteId: 1 };
    guardarAudioAssistenteMemoria({ ...identity, blob: new Blob(["inicio"]), filename: "consulta.webm", seconds: 10, finalizado: false, atualizadoEm: Date.now() });
    const { result } = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(result.current.audio?.size).toBe(6));
    const final = new File(["iniciofim"], "consulta.webm");
    act(() => guardarAudioAssistenteMemoria({ ...identity, blob: final, filename: "consulta.webm", seconds: 10, finalizado: true, atualizadoEm: Date.now() }));
    expect(result.current.audio).toBe(final);
    expect(result.current.aviso).not.toContain("interrompida");
  });
  it("não expõe cache de áudio a outro usuário ou paciente", async () => {
    guardarAudioAssistenteMemoria({ usuarioId: 7, atendimentoId: 1, pacienteId: 1, blob: new Blob(["audio"]), filename: "consulta.webm", seconds: 10, finalizado: true, atualizadoEm: Date.now() });
    const otherUser = renderHook(() => useAtendimentoAudio(1, 8, 1));
    const otherPatient = renderHook(() => useAtendimentoAudio(1, 7, 2));
    await waitFor(() => expect(otherUser.result.current.carregandoBackup).toBe(false));
    await waitFor(() => expect(otherPatient.result.current.carregandoBackup).toBe(false));
    expect(otherUser.result.current.audio).toBeNull();
    expect(otherPatient.result.current.audio).toBeNull();
  });
  it("guarda a última mídia emitida pelo gravador depois de sair da tela", async () => {
    const track = { stop: vi.fn(), onended: null as (() => void) | null };
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    let finalize!: () => void;
    class Recorder {
      static isTypeSupported() { return true; }
      mimeType = "audio/webm";
      state = "inactive";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: (() => void) | null = null;
      start() { this.state = "recording"; this.ondataavailable?.({ data: new Blob(["header"]) }); }
      stop() {
        this.state = "inactive";
        finalize = () => { this.ondataavailable?.({ data: new Blob(["final"]) }); this.onstop?.(); };
      }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    const first = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(first.result.current.carregandoBackup).toBe(false));
    await act(() => first.result.current.iniciar());
    first.unmount();
    const restored = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(restored.result.current.audio?.size).toBe(6));
    act(() => finalize());
    expect(restored.result.current.audio?.size).toBe(11);
    expect(lerRascunhoAssistenteMemoria({ usuarioId: 7, atendimentoId: 1, pacienteId: 1 })?.audio?.finalizado).toBe(true);
    expect(salvarAudioBackup).not.toHaveBeenCalled();
  });
  it("preserva áudio importado excedente, mas informa que precisa ser dividido", async () => {
    const { result } = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(result.current.carregandoBackup).toBe(false));
    const file = new File(["123456789"], "consulta.webm");
    act(() => result.current.importar(file, 8));
    expect(result.current.audio).toBe(file);
    expect(result.current.erro).toContain("8 bytes");
    expect(result.current.erro).toContain("original foi preservado");
    expect(lerRascunhoAssistenteMemoria({ usuarioId: 7, atendimentoId: 1, pacienteId: 1 })?.audio?.blob).toBe(file);
  });
  it.each([
    { mime: "audio/webm", supported: true, initialSize: 40_000, finalSize: 300_000, expectedExtension: ".webm", expectedError: "300.000 bytes" },
    { mime: "audio/ogg;codecs=opus", supported: false, initialSize: 0, finalSize: 10, expectedExtension: ".ogg", expectedError: "converta uma cópia" },
  ])("mantém original final sem envio quando tamanho ou formato inviável: $mime", async ({ mime, supported, initialSize, finalSize, expectedExtension, expectedError }) => {
    const track = { stop: vi.fn(), onended: null as (() => void) | null };
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    class Recorder {
      static current: Recorder;
      static isTypeSupported() { return supported; }
      mimeType = mime;
      state = "inactive";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() { Recorder.current = this; }
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob([new Uint8Array(finalSize)], { type: mime }) });
        this.onstop?.();
      }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    const { result } = renderHook(() => useAtendimentoAudio(1, 7, 1));
    await waitFor(() => expect(result.current.carregandoBackup).toBe(false));
    await act(() => result.current.iniciar(300_000));
    if (initialSize) act(() => Recorder.current.ondataavailable?.({ data: new Blob([new Uint8Array(initialSize)], { type: mime }) }));
    else act(() => result.current.parar());
    expect(result.current.gravando).toBe(false);
    expect(result.current.audio?.name.endsWith(expectedExtension)).toBe(true);
    expect(result.current.audio?.size).toBe(initialSize + finalSize);
    expect(result.current.erro).toContain(expectedError);
    expect(lerRascunhoAssistenteMemoria({ usuarioId: 7, atendimentoId: 1, pacienteId: 1 })?.audio?.blob.size).toBe(initialSize + finalSize);
  });
});
