import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReferenciaComparison } from "./ReferenciaComparison";
import type { ReferenciaEco } from "../types/referencia-eco";

const mocks = vi.hoisted(() => ({ buscar: vi.fn<(...args: unknown[]) => Promise<ReferenciaEco | null>>() }));
vi.mock("../hooks/useReferenciaEco", async () => {
  const actual = await vi.importActual<typeof import("../hooks/useReferenciaEco")>("../hooks/useReferenciaEco");
  return { ...actual, useReferenciaEco: () => ({ buscarReferencia: mocks.buscar,
    compararMedidas: actual.compararMedidasComReferencia, loading: false }) };
});

const aliases = ["Canina", "canino", "CANINOS", "Canine", " Cão ", "cães", "cachorro", "cachorros", "Dog", "DOGS"];
const original = Object.freeze({ AE_Ao: "1.41", AE_Ao_metodo: "", TAPSE: "12", TAPSE_metodo: "",
  DIVEd_2D: "30", DIVES_2D: "18", VE_tecnica_relatorio: "2d", VE_vista_2D: "" });

describe("controles de referência canina por alias exato", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each(aliases)("oferece os controles existentes sem confirmar ou regravar o paciente %s", async (species) => {
    mocks.buscar.mockResolvedValue({ id: 1, especie: species, peso_kg: 10 } as ReferenciaEco);
    const onChange = vi.fn();
    render(<ReferenciaComparison especie={species} peso={10} idade="2 anos" medidas={original} onMedidaChange={onChange} />);
    await screen.findByText(/Referência selecionada/);
    expect(screen.getByLabelText("Método de obtenção de AE/Ao")).toHaveValue("");
    expect(screen.getByLabelText("Método de obtenção do TAPSE")).toHaveValue("");
    expect(screen.getByLabelText("Confirme cão adulto e vista 2D do ventrículo esquerdo")).toHaveValue("");
    expect(mocks.buscar).toHaveBeenCalledWith(species, 10, "2 anos");
    expect(onChange).not.toHaveBeenCalled();
    expect(original).toMatchObject({ AE_Ao_metodo: "", TAPSE_metodo: "", VE_vista_2D: "" });
  });

  it.each(["CaninaXYZ", "caniniforme", "canino/gato", "caninos extras", "Dogfish", "Equina"])
    ("não oferece confirmação canina por prefixo em %s", async (species) => {
      mocks.buscar.mockResolvedValue({ id: 1, especie: species, peso_kg: 10 } as ReferenciaEco);
      const onChange = vi.fn();
      render(<ReferenciaComparison especie={species} peso={10} idade="2 anos" medidas={original} onMedidaChange={onChange} />);
      await waitFor(() => expect(mocks.buscar).toHaveBeenCalledWith(species, 10, "2 anos"));
      await screen.findByText(/Referência selecionada/);
      expect(screen.queryByLabelText("Método de obtenção de AE/Ao")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Método de obtenção do TAPSE")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Confirme cão adulto e vista 2D do ventrículo esquerdo")).not.toBeInTheDocument();
      expect(onChange).not.toHaveBeenCalled();
    });
});
