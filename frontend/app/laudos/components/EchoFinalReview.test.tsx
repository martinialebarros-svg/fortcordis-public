import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import EchoFinalReview from "./EchoFinalReview";

vi.mock("./EchoPdfPages", () => ({ default: ({ blob }: { blob: Blob }) => <section title="Prévia do laudo em PDF — rascunho" data-pdf-bytes={blob.size} /> }));

const pdf = () => new Blob(["%PDF-1.4\nSYNTHETIC"], { type: "application/pdf" });
const base = (): ComponentProps<typeof EchoFinalReview> => ({
  snapshotKey: "snapshot:1", scopeKey: "owner:1/echo:44", disabled: false, imageCount: 2,
  issues: [{ key: "waves", title: "Ondas E/A", message: "Confirme as ondas.", kind: "attention", target: "diastolic" },
    { key: "fusion", title: "Fusão tecidual", message: "Picos omitidos no PDF.", kind: "info", target: "diastolic" }],
  requestPreview: vi.fn(async (_signal: AbortSignal) => pdf()), onNavigate: vi.fn(),
});
beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL: vi.fn(() => "blob:synthetic-preview"), revokeObjectURL: vi.fn() }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("painel compacto de conferência e prévia real", () => {
  it("exibe avisos com ação direta e mantém a emissão fora deste painel", () => {
    const props = base(); render(<EchoFinalReview {...props} />);
    expect(screen.getByRole("region", { name: "Conferência final e prévia do PDF" })).toBeInTheDocument();
    expect(screen.getByText("1 ponto(s) para conferir · 1 observação(ões)")).toBeInTheDocument();
    expect(screen.getByText(/2 imagem/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/1 ponto/));
    fireEvent.click(screen.getByRole("button", { name: "Revisar Ondas E/A" }));
    expect(props.onNavigate).toHaveBeenCalledWith("diastolic"); expect(props.requestPreview).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Emitir|Atualizar laudo|Salvar laudo/ })).not.toBeInTheDocument();
  });
  it("sem avisos não afirma normalidade nem revisão clínica concluída", () => {
    render(<EchoFinalReview {...base()} issues={[]} />);
    expect(screen.getByText("Nenhuma pendência detectada pelos avisos automáticos")).toBeInTheDocument();
    expect(screen.queryByText(/normalidade|exame normal|aprovado|tudo certo/i)).not.toBeInTheDocument();
  });
  it("gera por ação explícita, abre PDF de rascunho e fecha para revisar o campo", async () => {
    const props = base(); render(<EchoFinalReview {...props} />);
    expect(props.requestPreview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Conferir e ver PDF" }));
    await waitFor(() => expect(screen.getByTitle("Prévia do laudo em PDF — rascunho")).toHaveAttribute("data-pdf-bytes", String(pdf().size)));
    expect(screen.getByRole("link", { name: "Abrir prévia em outra aba" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/não emite nem substitui/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/1 ponto/)); fireEvent.click(screen.getByRole("button", { name: "Revisar Ondas E/A" }));
    expect(props.onNavigate).toHaveBeenCalledWith("diastolic");
    expect(screen.queryByTitle("Prévia do laudo em PDF — rascunho")).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-preview");
  });
  it("editar imagem/texto/medida retira PDF obsoleto e permite gerar a versão atual", async () => {
    const props = base(); const { rerender } = render(<EchoFinalReview {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Conferir e ver PDF" }));
    await waitFor(() => expect(screen.getByTitle("Prévia do laudo em PDF — rascunho")).toBeInTheDocument());
    rerender(<EchoFinalReview {...props} snapshotKey="snapshot:2-caption" />);
    expect(screen.queryByTitle("Prévia do laudo em PDF — rascunho")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("O conteúdo mudou");
    fireEvent.click(screen.getByRole("button", { name: "Conferir e ver PDF" }));
    await waitFor(() => expect(screen.getByTitle("Prévia do laudo em PDF — rascunho")).toBeInTheDocument());
    expect(props.requestPreview).toHaveBeenCalledTimes(2);
    rerender(<EchoFinalReview {...props} scopeKey="owner:2/echo:44" />);
    expect(screen.queryByTitle("Prévia do laudo em PDF — rascunho")).not.toBeInTheDocument();
  });
  it("falhas locais permitem repetir e estado desabilitado impede requisição", async () => {
    const props = { ...base(), requestPreview: vi.fn(async () => { throw new Error("server detail"); }) };
    const { rerender } = render(<EchoFinalReview {...props} disabled />);
    expect(screen.getByRole("button", { name: "Conferir e ver PDF" })).toBeDisabled();
    rerender(<EchoFinalReview {...props} />); fireEvent.click(screen.getByRole("button", { name: "Conferir e ver PDF" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/rascunho continua preservado/));
    expect(screen.getByRole("button", { name: "Conferir e ver PDF" })).toBeEnabled();
    fireEvent.click(screen.getByText(/1 ponto/)); expect(screen.getByRole("button", { name: "Revisar Ondas E/A" })).toBeEnabled();
  });
});
