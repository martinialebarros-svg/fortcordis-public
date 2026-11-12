import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import api from "@/lib/axios";
import AtendimentoHistoricoEdicoes from "./AtendimentoHistoricoEdicoes";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const edicao = {
  id: 1, created_at: "2026-10-10T20:00:00+00:00", usuario_nome: "Dra. Teste",
  entidade: "documento_atendimento", entidade_id: "10", descricao: "Documento atualizado",
  alteracoes: { corpo: { antes: "Texto anterior", depois: "Texto corrigido" } },
};
const resposta = (items = [edicao], total = items.length) => ({ data: { items, total, skip: 0, limit: 20 } });

describe("historico de edicoes", () => {
  it("busca somente ao abrir e mostra autor, horario local e texto antes/depois", async () => {
    vi.mocked(api.get).mockResolvedValue(resposta());
    render(<AtendimentoHistoricoEdicoes atendimentoId={63} />);
    expect(api.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Historico de edicoes" }));
    expect(await screen.findByText("Texto anterior")).toBeInTheDocument();
    expect(screen.getByText("Texto corrigido")).toBeInTheDocument();
    expect(screen.getByText("Dra. Teste")).toBeInTheDocument();
    expect(screen.getByText(/17:00:00/)).toBeInTheDocument();
    expect(screen.getByText("Texto do documento")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/atendimentos/63/historico-edicoes", { params: { skip: 0, limit: 20 } });
  });

  it("filtra pelo documento, pagina e atualiza apos nova versao salva", async () => {
    vi.mocked(api.get).mockResolvedValue(resposta([edicao], 21));
    const { rerender } = render(<AtendimentoHistoricoEdicoes atendimentoId={63} documentoId={10} refreshKey="v1" />);
    fireEvent.click(screen.getByRole("button", { name: /Historico de edicoes deste documento/ }));
    await screen.findByText("Texto corrigido");
    expect(api.get).toHaveBeenLastCalledWith("/atendimentos/63/historico-edicoes", { params: { documento_id: 10, skip: 0, limit: 20 } });
    fireEvent.click(screen.getByRole("button", { name: "Edicoes anteriores" }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith("/atendimentos/63/historico-edicoes", { params: { documento_id: 10, skip: 20, limit: 20 } }));
    rerender(<AtendimentoHistoricoEdicoes atendimentoId={63} documentoId={10} refreshKey="v2" />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
  });

  it("mostra erro recuperavel sem esconder como historico vazio", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Sem conexao")).mockResolvedValueOnce(resposta([]));
    render(<AtendimentoHistoricoEdicoes atendimentoId={63} />);
    fireEvent.click(screen.getByRole("button", { name: "Historico de edicoes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sem conexao");
    expect(screen.queryByText(/Nenhuma edicao/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar historico" }));
    expect(await screen.findByText(/Nenhuma edicao registrada/)).toBeInTheDocument();
  });

  it("descarta resposta atrasada ao mudar o atendimento", async () => {
    let resolverAntigo: (value: unknown) => void = () => {};
    vi.mocked(api.get).mockImplementationOnce(() => new Promise((resolve) => { resolverAntigo = resolve; }));
    vi.mocked(api.get).mockResolvedValueOnce(resposta([]));
    const { rerender } = render(<AtendimentoHistoricoEdicoes atendimentoId={63} />);
    fireEvent.click(screen.getByRole("button", { name: "Historico de edicoes" }));
    rerender(<AtendimentoHistoricoEdicoes atendimentoId={64} />);
    await screen.findByText(/Nenhuma edicao registrada/);
    await act(async () => { resolverAntigo(resposta()); });
    expect(screen.queryByText("Texto anterior")).toBeNull();
  });
});
