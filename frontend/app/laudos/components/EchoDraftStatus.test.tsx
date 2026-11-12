import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EchoDraftStatus from "./EchoDraftStatus";
import { criarEcocardiogramaEstruturadoInicial } from "@/lib/ecocardiograma-estruturado";
import type { EchoEditorDraftResponse } from "@/lib/echo-editor-draft";

const state = () => ({
  status: "saved" as const, lastSavedAt: "2026-11-01T12:04:00Z", error: null,
  pendingImages: 0, recovery: null, resumeRecovered: vi.fn(async () => {}), continueFresh: vi.fn(), retry: vi.fn(async () => {}),
});

describe("status honesto do rascunho", () => {
  it("distingue cópia do rascunho de emissão e mostra hora operacional", () => {
    render(<EchoDraftStatus draft={state()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Rascunho salvo às 09:04");
    expect(screen.queryByText(/laudo emitido/i)).not.toBeInTheDocument();
  });
  it("recuperação exige uma escolha explícita sem aplicar dados ao renderizar", () => {
    const draft = { ...state(), status: "recovery" as const };
    render(<EchoDraftStatus draft={draft} />);
    expect(draft.resumeRecovered).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retomar rascunho" }));
    expect(draft.resumeRecovered).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Continuar com preenchimento atual" }));
    expect(draft.continueFresh).toHaveBeenCalledOnce();
  });
  it("não apresenta arquivo ainda não enviado como recuperado", () => {
    render(<EchoDraftStatus draft={{ ...state(), pendingImages: 2 }} />);
    expect(screen.getByText(/2 imagens precisam de envio ou reenvio/)).toBeInTheDocument();
    expect(screen.getByText(/arquivos ainda não enviados precisam ser selecionados novamente/)).toBeInTheDocument();
  });
  it.each(["pending", "confirmed"] as const)("não oferece descarte da prova de emissão %s", (status) => {
    const recovery: EchoEditorDraftResponse = { draft_id: "id", context_key: "ctx", revision: 2,
      updated_at: "2026-11-01T12:00:00Z", snapshot: { schema_version: 1, editor: "new-echo",
        paciente: {}, measurementState: { measurements: {}, aeAoDerived: false }, qualitativa: {}, conteudo: {},
        ecocardiogramaCabecalho: { ritmo: "", estado: "", fc: "" },
        ecocardiogramaEstruturado: criarEcocardiogramaEstruturadoInicial(), pressaoArterial: {},
        clinicaId: "", clinicaNome: "", veterinario: "", agendamentoVinculadoId: null, sessionId: "x",
        draftLaudoId: null, imagens: [], submission: { status, laudoId: status === "confirmed" ? 99 : null } } };
    render(<EchoDraftStatus draft={{ ...state(), status: "recovery", recovery }} />);
    expect(screen.queryByRole("button", { name: "Continuar com preenchimento atual" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retomar rascunho" })).toBeInTheDocument();
    expect(screen.getByText(/Há uma tentativa de salvamento registrada/)).toBeInTheDocument();
  });
  it("erro oferece retry e conflito exige revisão, sem sobrescrita automática", () => {
    const draft = { ...state(), status: "error" as const, error: "Conexão indisponível." };
    const view = render(<EchoDraftStatus draft={draft} />);
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(draft.retry).toHaveBeenCalledOnce();
    view.rerender(<EchoDraftStatus draft={{ ...draft, status: "conflict" }} />);
    expect(screen.queryByRole("button", { name: "Tentar novamente" })).not.toBeInTheDocument();
  });
});
