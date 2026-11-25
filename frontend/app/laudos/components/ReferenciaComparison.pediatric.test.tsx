import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReferenciaComparison } from "./ReferenciaComparison";
import type { ReferenciaEco } from "../types/referencia-eco";
import { FELINE_PEDIATRIC_PROTOCOL } from "@/lib/echo-feline-pediatric-reference";

const mocks = vi.hoisted(() => ({ buscar: vi.fn<(...args: unknown[]) => Promise<ReferenciaEco | null>>(async () => null) }));
vi.mock("../hooks/useReferenciaEco", async () => {
  const actual = await vi.importActual<typeof import("../hooks/useReferenciaEco")>("../hooks/useReferenciaEco");
  return { ...actual, useReferenciaEco: () => ({ buscarReferencia: mocks.buscar,
    compararMedidas: actual.compararMedidasComReferencia, loading: false }) };
});

const base = { VE_tecnica_relatorio: "modo_m", DIVEd: "20", SIVd: "5", Pediatria_protocolo: FELINE_PEDIATRIC_PROTOCOL };
function measurementCard() {
  return screen.getByText("DIVEd (Diâmetro interno VE diástole)").closest("div.rounded-lg.border")!;
}

describe("comparação pediátrica felina", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.buscar.mockResolvedValue(null); });

  it("mostra coorte e fonte com neutralidade mesmo fora dos limites e sem catálogo", async () => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={base} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(screen.getByRole("region", { name: "Referências pediátricas felinas" })).toHaveTextContent("88 gatos");
    expect(measurementCard()).toHaveTextContent("8,60–15,30 mm (coorte pediátrica)");
    expect(measurementCard()).toHaveTextContent("não ajustados ao peso");
    expect(measurementCard()).not.toHaveClass("bg-green-50", "bg-red-50", "bg-blue-50");
    expect(screen.getAllByRole("link", { name: /Gunther-Harrington/ })[0]).toHaveAttribute("href", "https://doi.org/10.1177/1098612X20946461");
    expect(screen.queryByText(/Referência calculada:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Häggström/)).not.toBeInTheDocument();
    expect(mocks.buscar).toHaveBeenCalledWith("Felina", 1.2, "3 meses");
  });

  it("confirma protocolo explicitamente, sem gravar ou mudar medidas por conta própria", async () => {
    const change = vi.fn();
    const m = { ...base, Pediatria_protocolo: "" };
    const view = render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={m} onMedidaChange={change} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(measurementCard()).not.toHaveTextContent("8,60–15,30");
    expect(change).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Protocolo de aquisição pediátrico"), { target: { value: FELINE_PEDIATRIC_PROTOCOL } });
    expect(change).toHaveBeenCalledExactlyOnceWith("Pediatria_protocolo", FELINE_PEDIATRIC_PROTOCOL);
    view.rerender(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={base} onMedidaChange={change} />);
    expect(measurementCard()).toHaveTextContent("8,60–15,30");
    expect(m.DIVEd).toBe("20");
  });

  it("oferece vista 2D pediátrica e retira os limites se a vista não corresponde", async () => {
    const change = vi.fn();
    const m = { Pediatria_protocolo: FELINE_PEDIATRIC_PROTOCOL, VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_longo", DIVEd_2D: "12" };
    const view = render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={m} onMedidaChange={change} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(screen.getByLabelText("Vista 2D do ventrículo esquerdo")).toHaveValue("eixo_longo");
    expect(screen.getByText(/Intervalo da coorte pediátrica: 8,30–14,00/)).toBeInTheDocument();
    expect(screen.queryByText(/Confirme cão adulto/)).not.toBeInTheDocument();
    view.rerender(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={{ ...m, VE_vista_2D: "eixo_curto" }} onMedidaChange={change} />);
    expect(screen.queryByText(/8,30–14,00/)).not.toBeInTheDocument();
  });

  it("catálogo adulto não prevalece e a troca de idade dispara nova consulta", async () => {
    mocks.buscar.mockResolvedValue({ id: 1, especie: "Felina", peso_kg: 2, lvid_d_min: 10.2, lvid_d_max: 16 });
    const view = render(<ReferenciaComparison especie="Felina" peso={2} idade="3 meses" medidas={base} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(measurementCard()).toHaveTextContent("8,60–15,30");
    view.rerender(<ReferenciaComparison especie="Felina" peso={2} idade="2 anos" medidas={base} onMedidaChange={vi.fn()} />);
    await waitFor(() => expect(mocks.buscar).toHaveBeenLastCalledWith("Felina", 2, "2 anos"));
    expect(screen.queryByRole("region", { name: "Referências pediátricas felinas" })).not.toBeInTheDocument();
    expect(measurementCard()).not.toHaveTextContent("coorte pediátrica");
  });
});
