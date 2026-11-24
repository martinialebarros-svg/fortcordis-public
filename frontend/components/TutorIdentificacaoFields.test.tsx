import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TutorIdentificacaoFields from "./TutorIdentificacaoFields";
import { resetStableCatalogCacheForTests } from "@/lib/stable-catalog-cache";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: { get } }));

function Form({ origem = "" }: { origem?: string }) {
  const [value, setValue] = useState({
    identificacao_pendente: true, origem_cadastro: origem, identificacao_observacoes: "Confirmar contato",
  });
  return <TutorIdentificacaoFields value={value} onChange={setValue} />;
}

function sugestoes() {
  const campo = screen.getByLabelText("Origem do cadastro / clínica informante");
  return document.getElementById(campo.getAttribute("list")!)!;
}

beforeEach(() => {
  get.mockReset();
  resetStableCatalogCacheForTests();
});

describe("origem do tutor com clínicas cadastradas", () => {
  it("consulta ao abrir a origem, inclui a próxima página e preserva a origem já preenchida", async () => {
    const primeiraPagina = Array.from({ length: 500 }, (_, index) => ({ id: index + 1, nome: `Clínica ${index + 1}` }));
    get.mockResolvedValueOnce({ data: { items: primeiraPagina, total: 501 } })
      .mockResolvedValueOnce({ data: { items: [{ id: 501, nome: "Clínica Última" }], total: 501 } });
    render(<Form origem="Origem anterior" />);
    expect(get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Origem e observações (opcional)"));
    await waitFor(() => expect(sugestoes().querySelector('option[value="Clínica Última"]')).not.toBeNull());
    expect(get.mock.calls.map(([, config]) => config.params)).toEqual([{ skip: 0, limit: 500 }, { skip: 500, limit: 500 }]);
    expect(screen.getByLabelText("Origem do cadastro / clínica informante")).toHaveValue("Origem anterior");
    expect(screen.getByLabelText("O que falta confirmar / observações da identificação")).toHaveValue("Confirmar contato");
    expect(screen.getByText("Identificação pendente")).toBeInTheDocument();
  });

  it("aceita o nome sugerido, outra origem e campo vazio sem impor vínculo com a clínica", async () => {
    get.mockResolvedValue({ data: { items: [{ id: 7, nome: "Clínica Alfa" }], total: 1 } });
    render(<Form />);
    const campo = screen.getByLabelText("Origem do cadastro / clínica informante");
    fireEvent.focus(campo);
    await waitFor(() => expect(sugestoes().querySelector('option[value="Clínica Alfa"]')).not.toBeNull());
    for (const origem of ["Clínica Alfa", "Indicação de um amigo", ""]) {
      fireEvent.change(campo, { target: { value: origem } });
      expect(campo).toHaveValue(origem);
      expect(campo).not.toBeRequired();
    }
  });

  it("mantém digitação durante falha e permite recuperar as sugestões sem apagar o texto", async () => {
    get.mockRejectedValueOnce(new Error("rede indisponível"))
      .mockResolvedValueOnce({ data: { items: [{ id: 7, nome: "Clínica Alfa" }], total: 1 } });
    render(<Form />);
    const campo = screen.getByLabelText("Origem do cadastro / clínica informante");
    fireEvent.click(screen.getByText("Origem e observações (opcional)"));
    await screen.findByText("Não foi possível carregar as clínicas. Você pode informar a origem manualmente.");
    expect(campo).not.toBeDisabled();
    fireEvent.change(campo, { target: { value: "Origem digitada" } });
    fireEvent.click(screen.getByRole("button", { name: "Tentar carregar clínicas novamente" }));
    await waitFor(() => expect(sugestoes().querySelector('option[value="Clínica Alfa"]')).not.toBeNull());
    expect(campo).toHaveValue("Origem digitada");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
