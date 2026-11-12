import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EnderecoFiscalCard from "./EnderecoFiscalCard";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: mocks }));

describe("endereço fiscal separado da localização", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.get.mockResolvedValue({ data: { cnpj: "11.222.333/0001-81", cep: "60000-000", latitude: -3, endereco_fiscal: null } });
    mocks.put.mockResolvedValue({ data: {} });
  });

  it("salva somente o endereço fiscal sem usar CEP ou pin operacional", async () => {
    render(<EnderecoFiscalCard clinicaId={1} />);
    expect(await screen.findByLabelText("CNPJ do cartão")).toHaveValue("11.222.333/0001-81");
    expect(screen.getByLabelText("CEP fiscal")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("CEP fiscal"), { target: { value: "60763-730" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar endereço fiscal" }));
    await screen.findByText(/Endereço fiscal salvo/);
    expect(mocks.put).toHaveBeenCalledWith("/clinicas/1/endereco-fiscal", expect.objectContaining({ cep: "60763-730" }));
    expect(mocks.put.mock.calls[0][1]).not.toHaveProperty("latitude");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).toHaveBeenCalledTimes(1);
  });

  it("carrega a fonte e o endereço fiscal previamente conferidos", async () => {
    mocks.get.mockResolvedValue({ data: { cnpj: "cnpj operacional", endereco_fiscal: { cnpj: "11222333000181", cep: "60763730", endereco: "Rua Fiscal", fonte_url: "https://example.test/cnpj" } } });
    render(<EnderecoFiscalCard clinicaId={1} />);
    expect(await screen.findByLabelText("Logradouro fiscal")).toHaveValue("Rua Fiscal");
    expect(screen.getByLabelText("Link da fonte consultada")).toHaveValue("https://example.test/cnpj");
  });

  it("exibe erro de gravação junto ao formulário e permite corrigir", async () => {
    mocks.put.mockRejectedValue({ response: { data: { detail: "CNPJ divergente" } } });
    render(<EnderecoFiscalCard clinicaId={1} />);
    await screen.findByLabelText("CEP fiscal");
    fireEvent.click(screen.getByRole("button", { name: "Salvar endereço fiscal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("CNPJ divergente");
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar endereço fiscal" })).toBeEnabled());
  });
});
