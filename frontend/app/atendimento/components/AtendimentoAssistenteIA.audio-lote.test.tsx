import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import api from "@/lib/axios";
import { apagarAudioBackup } from "@/lib/atendimento-audio-backup";
import { guardarAudioAssistenteMemoria, limparRascunhosAssistenteMemoria } from "@/lib/atendimento-assistente-memory";
import AtendimentoAssistenteIA from "./AtendimentoAssistenteIA";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@/lib/atendimento-audio-backup", () => ({
  apagarAudioBackup: vi.fn(),
  lerAudioBackup: vi.fn().mockResolvedValue(null),
  salvarAudioBackup: vi.fn(),
}));

const original = new File(["captura fictícia"], "gravacao-deste-atendimento.webm", { type: "audio/webm" });
const props = {
  atendimentoId: 1,
  pacienteId: 11,
  patientLabel: "Paciente fictício",
  onApplyFields: vi.fn(() => true),
};

beforeEach(() => {
  limparRascunhosAssistenteMemoria();
  guardarAudioAssistenteMemoria({
    atendimentoId: 1, pacienteId: 11, usuarioId: 7,
    blob: original, filename: original.name, seconds: 10,
    copiaDispositivo: true, finalizado: true, atualizadoEm: Date.now(),
  });
  vi.mocked(api.get).mockImplementation(async (url) => ({
    data: String(url).endsWith("/status") ? {
      usuario_id: 7, habilitado: true, configurado: true,
      modelo: "modelo-ficticio", esforco: "max", modelo_transcricao: "transcricao-ficticia",
    } : null,
  }));
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:gravacao-ficticia");
    static revokeObjectURL = vi.fn();
  });
});

afterEach(() => {
  cleanup();
  limparRascunhosAssistenteMemoria();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

async function abrir() {
  const view = render(<AtendimentoAssistenteIA {...props} />);
  view.container.querySelector("details")?.setAttribute("open", "");
  await waitFor(() => expect(screen.getByRole("button", { name: "Usar áudio deste atendimento" })).toBeEnabled());
  return view;
}

describe("gravação do atendimento na análise conjunta", () => {
  it("bloqueia o envio durante o descarte e retira o áudio do lote quando a cópia é apagada", async () => {
    let concluirDescarte!: () => void;
    vi.mocked(apagarAudioBackup).mockImplementationOnce(() => new Promise<void>((resolve) => { concluirDescarte = resolve; }));
    await abrir();
    fireEvent.click(screen.getByLabelText(/Confirmei a autorização do tutor/));
    fireEvent.click(screen.getByRole("button", { name: "Usar áudio deste atendimento" }));
    expect(screen.getByRole("button", { name: "Analisar conjunto" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Descartar áudio" }));
    expect(screen.getByRole("button", { name: "Analisar conjunto" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Apagar áudio" }));
    await waitFor(() => expect(apagarAudioBackup).toHaveBeenCalledWith(7, 1, 11));
    expect(screen.getByRole("button", { name: "Analisar conjunto" })).toBeDisabled();
    await act(async () => concluirDescarte());

    expect(screen.queryByRole("button", { name: `Retirar ${original.name} do conjunto` })).toBeNull();
    expect(screen.getByRole("button", { name: "Analisar conjunto" })).toBeDisabled();
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("ao trocar de paciente, não oferece a gravação nem leva a seleção do contexto anterior", async () => {
    const view = await abrir();
    fireEvent.click(screen.getByRole("button", { name: "Usar áudio deste atendimento" }));
    view.rerender(<AtendimentoAssistenteIA {...props} pacienteId={22} patientLabel="Outro paciente fictício" />);
    view.container.querySelector("details")?.setAttribute("open", "");
    await waitFor(() => expect(screen.getByLabelText("Áudios e PDFs do conjunto")).toBeEnabled());
    expect(screen.queryByRole("button", { name: /áudio do atendimento no conjunto|usar áudio deste atendimento/i })).toBeNull();
    expect(screen.queryByRole("button", { name: `Retirar ${original.name} do conjunto` })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });
});
