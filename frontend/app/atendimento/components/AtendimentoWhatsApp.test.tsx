import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AtendimentoWhatsApp, { type AtendimentoWhatsAppProps } from "./AtendimentoWhatsApp";

const pdf = () => new File(["%PDF-1.4 synthetic test"], "receita_atendimento_42.pdf", { type: "application/pdf" });
const props = (overrides: Partial<AtendimentoWhatsAppProps> = {}): AtendimentoWhatsAppProps => ({
  atendimentoId: 42,
  phone: "(85) 99999-1234",
  tutorName: "Tutor de teste",
  patientName: "Paciente de teste",
  onPrepareDocument: vi.fn().mockResolvedValue(pdf()),
  ...overrides,
});

beforeEach(() => {
  Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
  Object.defineProperty(navigator, "canShare", { configurable: true, value: undefined });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function confirmRecipient() {
  fireEvent.click(screen.getByRole("checkbox", { name: /Conferi o número/i }));
}

function renderExpanded(input: AtendimentoWhatsAppProps) {
  const result = render(<AtendimentoWhatsApp {...input} />);
  const details = result.container.querySelector("details");
  if (details) details.open = true;
  return result;
}

describe("WhatsApp no atendimento", () => {
  it("começa recolhido para manter o foco no atendimento", () => {
    const { container } = render(<AtendimentoWhatsApp {...props()} />);
    expect(container.querySelector("details")?.open).toBe(false);
    expect(container.querySelector("summary")?.textContent).toContain("WhatsApp do tutor");
  });

  it("exige conferência do destinatário antes de preparar ou abrir a conversa", () => {
    const input = props();
    renderExpanded(input);
    expect(screen.getByRole("button", { name: "Preparar PDF" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: /Abrir conversa/ })).toBeNull();
    expect(input.onPrepareDocument).not.toHaveBeenCalled();
    confirmRecipient();
    expect(screen.getByRole("button", { name: "Preparar PDF" })).not.toBeDisabled();
    expect(screen.getByRole("link", { name: /Abrir conversa/ })).toHaveAttribute("href", expect.stringContaining("https://wa.me/5585999991234?text="));
    expect(screen.getByText(/não envia a mensagem nem anexa/)).toBeTruthy();
  });

  it("orienta editar cadastro sem inventar telefone", () => {
    const edit = vi.fn();
    renderExpanded(props({ phone: "99999-1234", onEditPhone: edit }));
    expect(screen.getByRole("button", { name: "Preparar PDF" })).toBeDisabled();
    expect(screen.queryByRole("link")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Editar cadastro/ }));
    expect(edit).toHaveBeenCalledOnce();
  });

  it("não prepara documento de atendimento sem salvar", () => {
    renderExpanded(props({ atendimentoId: null }));
    confirmRecipient();
    expect(screen.getByRole("button", { name: "Preparar PDF" })).toBeDisabled();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("prepara a seleção com callback existente e orienta anexo manual no desktop", async () => {
    const input = props();
    renderExpanded(input);
    confirmRecipient();
    fireEvent.change(screen.getByLabelText("Documento"), { target: { value: "exames" } });
    fireEvent.click(screen.getByRole("button", { name: "Preparar PDF" }));
    await screen.findByRole("button", { name: /Baixar PDF para conferir/ });
    expect(input.onPrepareDocument).toHaveBeenCalledWith("exames");
    expect(screen.queryByRole("button", { name: "Compartilhar PDF" })).toBeNull();
    expect(screen.getByText(/Baixe o PDF, abra a conversa e anexe/)).toBeTruthy();
  });

  it("apenas compartilha arquivo após novo clique e não afirma entrega no WhatsApp", async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "share", { configurable: true, value: share });
    Object.defineProperty(navigator, "canShare", { configurable: true, value: vi.fn().mockReturnValue(true) });
    renderExpanded(props());
    confirmRecipient();
    fireEvent.click(screen.getByRole("button", { name: "Preparar PDF" }));
    const button = await screen.findByRole("button", { name: "Compartilhar PDF" });
    expect(share).not.toHaveBeenCalled();
    fireEvent.click(button);
    await screen.findByText(/Confira o envio e o destinatário no WhatsApp/);
    expect(share).toHaveBeenCalledWith({ files: [expect.any(File)], title: "Documento Fort Cordis" });
  });

  it("cancelar compartilhamento preserva PDF sem enviar novamente", async () => {
    const share = vi.fn().mockRejectedValue(new DOMException("cancelled", "AbortError"));
    Object.defineProperty(navigator, "share", { configurable: true, value: share });
    Object.defineProperty(navigator, "canShare", { configurable: true, value: vi.fn().mockReturnValue(true) });
    renderExpanded(props());
    confirmRecipient();
    fireEvent.click(screen.getByRole("button", { name: "Preparar PDF" }));
    fireEvent.click(await screen.findByRole("button", { name: "Compartilhar PDF" }));
    await screen.findByText(/Compartilhamento cancelado/);
    expect(screen.getByRole("button", { name: /Baixar PDF para conferir/ })).toBeTruthy();
    expect(share).toHaveBeenCalledOnce();
  });

  it("descarta preparação atrasada ao trocar paciente e exige nova conferência", async () => {
    let resolve!: (file: File) => void;
    const input = props({ onPrepareDocument: vi.fn().mockImplementation(() => new Promise<File>((done) => { resolve = done; })) });
    const { rerender } = renderExpanded(input);
    confirmRecipient();
    fireEvent.click(screen.getByRole("button", { name: "Preparar PDF" }));
    rerender(<AtendimentoWhatsApp {...input} atendimentoId={43} patientName="Outro paciente" />);
    await act(async () => { resolve(pdf()); });
    expect(screen.queryByRole("button", { name: /Baixar PDF para conferir/ })).toBeNull();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Preparar PDF" })).toBeDisabled();
  });

  it("invalida arquivo ao editar os dados que compõem o PDF", async () => {
    const input = props({ documentRevision: "receita 1" });
    const { rerender } = renderExpanded(input);
    confirmRecipient();
    fireEvent.click(screen.getByRole("button", { name: "Preparar PDF" }));
    await screen.findByRole("button", { name: /Baixar PDF para conferir/ });
    rerender(<AtendimentoWhatsApp {...input} documentRevision="receita corrigida" />);
    expect(screen.queryByRole("button", { name: /Baixar PDF para conferir/ })).toBeNull();
  });

  it("recupera falha de preparação e não expõe erro técnico", async () => {
    const callback = vi.fn().mockRejectedValue(new Error("secret-token-internal"));
    renderExpanded(props({ onPrepareDocument: callback }));
    confirmRecipient();
    fireEvent.click(screen.getByRole("button", { name: "Preparar PDF" }));
    await screen.findByText(/Não foi possível preparar o PDF/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Preparar PDF" })).not.toBeDisabled());
    expect(screen.queryByText(/secret-token/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Baixar PDF/ })).toBeNull();
  });
});
