import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Modal from "./Modal";

afterEach(() => {
  cleanup();
});

function renderModal(overrides: Partial<React.ComponentProps<typeof Modal>> = {}) {
  const onClose = overrides.onClose ?? vi.fn();
  render(
    <Modal
      titleId="modal-titulo-teste"
      onClose={onClose}
      overlayClassName="fixed inset-0"
      contentClassName="relative"
      {...overrides}
    >
      <h3 id="modal-titulo-teste">Titulo do modal</h3>
      <button type="button">Primeiro botao</button>
      <button type="button">Segundo botao</button>
    </Modal>
  );
  return { onClose };
}

describe("Modal", () => {
  it("declara role=dialog, aria-modal e aria-labelledby apontando para o titulo", () => {
    renderModal();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "modal-titulo-teste");
  });

  it("foca automaticamente o primeiro elemento interativo do conteudo", () => {
    renderModal();
    expect(screen.getByText("Primeiro botao")).toHaveFocus();
  });

  it("fecha ao pressionar Escape", () => {
    const { onClose } = renderModal();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("nao fecha com Escape quando closeOnEscape=false", () => {
    const { onClose } = renderModal({ closeOnEscape: false });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("fecha ao clicar fora (overlay)", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByLabelText("Fechar"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("nao renderiza botao de overlay quando closeOnOverlayClick=false", () => {
    renderModal({ closeOnOverlayClick: false });
    expect(screen.queryByLabelText("Fechar")).not.toBeInTheDocument();
  });
});
