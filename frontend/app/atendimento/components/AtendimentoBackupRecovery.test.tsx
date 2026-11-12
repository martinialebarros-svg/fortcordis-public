import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AtendimentoBackupRecovery from "./AtendimentoBackupRecovery";
afterEach(cleanup);

it("preserva servidor ate escolha explicita depois de mostrar comparacao legivel", () => {
  const recover = vi.fn();
  render(<AtendimentoBackupRecovery canRecover onRecover={recover} differences={[{ campo: "anamnese", salvo: "Texto da sessao B", local: "Texto nao salvo da A" }]} />);
  expect(recover).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Recuperar copia no editor" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Comparar copia local" }));
  expect(screen.getByText("Anamnese")).toBeInTheDocument();
  expect(screen.getByText("Texto da sessao B")).toBeInTheDocument();
  expect(screen.getByText("Texto nao salvo da A")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Manter conteudo salvo" }));
  expect(recover).not.toHaveBeenCalled();
  expect(screen.getByText(/copia local segue disponivel/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Comparar copia local" }));
  fireEvent.click(screen.getByRole("button", { name: "Recuperar copia no editor" }));
  expect(recover).toHaveBeenCalledOnce();
});

it("impede aplicar copia de outro contexto", () => {
  render(<AtendimentoBackupRecovery canRecover={false} onRecover={vi.fn()} differences={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Comparar copia local" }));
  expect(screen.getByRole("button", { name: "Recuperar copia no editor" })).toBeDisabled();
  expect(screen.getByText(/outro contexto de paciente ou receita/)).toBeInTheDocument();
});
