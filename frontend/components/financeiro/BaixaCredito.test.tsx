import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BaixaCredito from "./BaixaCredito";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: api }));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  api.get.mockResolvedValue({ data: { saldo: 100, pode_baixar: true } });
  api.post.mockResolvedValue({ data: { saldo: 60, movimento_id: 20 } });
});
async function abrir() {
  const onSaldoCliente = vi.fn();
  render(<BaixaCredito pacienteId={1} clinicaId={2} onSaldoCliente={onSaldoCliente} />);
  fireEvent.click(screen.getByText("Baixar credito sem contrapartida"));
  await screen.findByLabelText("Valor do credito a baixar");
  return onSaldoCliente;
}
function preencher() {
  fireEvent.change(screen.getByLabelText("Valor do credito a baixar"), { target: { value: "40" } });
  fireEvent.change(screen.getByLabelText("Motivo da baixa"), { target: { value: "Ajuste solicitado" } });
}
describe("baixa de credito no modal", () => {
  it("exige valor e motivo e registra uma baixa independente do recebimento", async () => {
    const onSaldo = await abrir();
    expect(screen.getByRole("button", { name: /Confirmar baixa de/ })).toBeDisabled();
    preencher();
    fireEvent.click(screen.getByRole("button", { name: /Confirmar baixa de/ }));
    await screen.findByText(/A OS continua aguardando recebimento/);
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/financeiro/creditos/baixar", expect.objectContaining({
      paciente_id: 1, tipo_destino: "cliente", valor: 40, motivo: "Ajuste solicitado",
    }));
    expect(onSaldo).toHaveBeenCalledWith(60);
    fireEvent.click(screen.getByText("Desfazer ultima baixa"));
    await screen.findByText("Baixa desfeita; credito restaurado.");
    expect(api.post).toHaveBeenLastCalledWith("/financeiro/creditos/20/desfazer-baixa");
  });
  it("reutiliza a chave na repeticao apos falha de conexao", async () => {
    await abrir();
    preencher();
    api.post.mockRejectedValueOnce(new Error("timeout"));
    fireEvent.click(screen.getByRole("button", { name: /Confirmar baixa de/ }));
    await screen.findByRole("alert");
    const chave = api.post.mock.calls[0][1].idempotency_key;
    fireEvent.click(screen.getByRole("button", { name: /Confirmar baixa de/ }));
    await screen.findByText(/A OS continua aguardando recebimento/);
    expect(api.post.mock.calls[1][1].idempotency_key).toBe(chave);
  });
  it("nao oferece confirmacao sem permissao administrativa", async () => {
    api.get.mockResolvedValue({ data: { saldo: 100, pode_baixar: false } });
    render(<BaixaCredito pacienteId={1} onSaldoCliente={vi.fn()} />);
    fireEvent.click(screen.getByText("Baixar credito sem contrapartida"));
    await screen.findByText(/Apenas administradores/);
    expect(screen.queryByRole("button", { name: /Confirmar baixa de/ })).toBeNull();
  });
  it("consulta a clinica e nao altera o saldo do cliente ao baixa-la", async () => {
    const onSaldo = await abrir();
    fireEvent.change(screen.getByLabelText("Titular do credito"), { target: { value: "clinica" } });
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/financeiro/creditos/disponivel", {
      params: { tipo_destino: "clinica", paciente_id: 1, clinica_id: 2 },
    }));
    await screen.findByLabelText("Valor do credito a baixar");
    preencher();
    fireEvent.click(screen.getByRole("button", { name: /Confirmar baixa de/ }));
    await screen.findByText(/A OS continua aguardando recebimento/);
    expect(onSaldo).not.toHaveBeenCalled();
  });
});
