import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
function measurementCard(name = "DIVEd (Diâmetro interno VE diástole)") {
  return screen.getByText(name).closest<HTMLDivElement>("div.rounded-lg.border")!;
}

describe("comparação pediátrica felina", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.buscar.mockResolvedValue(null); });

  it("destaca medido e referência e sinaliza posição na coorte sem catálogo", async () => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={base} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(screen.getByRole("region", { name: "Referências pediátricas felinas" })).toHaveTextContent("88 gatos");
    expect(measurementCard()).toHaveTextContent("8,60–15,30 mm");
    expect(within(measurementCard()).getByText("Valor medido")).toBeInTheDocument();
    expect(within(measurementCard()).getByText("Referência")).toBeInTheDocument();
    expect(within(measurementCard()).getByText("20 mm")).toBeInTheDocument();
    expect(measurementCard()).toHaveTextContent("Acima da faixa da coorte");
    expect(measurementCard()).toHaveClass("bg-red-50");
    expect(screen.getByText(/As cores indicam apenas a posição/)).toHaveTextContent("não são ajustados ao peso");
    expect(screen.getByText(/As cores indicam apenas a posição/)).toHaveTextContent("não determinam normalidade, doença ou diagnóstico");
    expect(screen.queryByText(/sem classificação automática/)).not.toBeInTheDocument();
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
    expect(measurementCard()).toHaveTextContent("Não disponível");
    expect(measurementCard()).toHaveTextContent("Confirme ausência de sedação");
    expect(measurementCard()).not.toHaveClass("bg-green-50", "bg-red-50", "bg-blue-50");
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
    expect(screen.getByText("8,30–14,00 mm")).toBeInTheDocument();
    expect(measurementCard("DIVEd 2D (Diâmetro interno VE diástole)")).toHaveClass("bg-green-50");
    expect(screen.queryByText(/Confirme cão adulto/)).not.toBeInTheDocument();
    view.rerender(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={{ ...m, VE_vista_2D: "eixo_curto" }} onMedidaChange={change} />);
    expect(screen.queryByText(/8,30–14,00/)).not.toBeInTheDocument();
    expect(measurementCard("DIVEd 2D (Diâmetro interno VE diástole)")).toHaveTextContent("Selecione técnica 2D e vista de eixo longo");
    expect(measurementCard("DIVEd 2D (Diâmetro interno VE diástole)")).toHaveClass("bg-white");
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

  it.each([
    ["8.59", "Abaixo da faixa da coorte", "bg-blue-50"],
    ["8.6", "Dentro da faixa da coorte", "bg-green-50"],
    ["12", "Dentro da faixa da coorte", "bg-green-50"],
    ["15.3", "Dentro da faixa da coorte", "bg-green-50"],
    ["15.31", "Acima da faixa da coorte", "bg-red-50"],
  ])("mostra %s na posição correta incluindo os limites", async (value, text, color) => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={{ ...base, DIVEd: value }} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(measurementCard()).toHaveTextContent(text);
    expect(measurementCard()).toHaveClass(color);
  });

  it.each(["0", "-1", "12abc", "Infinity", "0x10", "0b10"])("não atribui cor ao valor inválido %s", async (value) => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={{ ...base, DIVEd: value }} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(measurementCard()).toHaveClass("bg-white");
    expect(measurementCard()).not.toHaveTextContent(/Dentro da faixa da coorte|Acima da faixa da coorte|Abaixo da faixa da coorte/);
    expect(measurementCard()).toHaveTextContent("Informe um valor medido positivo e finito");
  });

  it.each(["5 semanas", "17 semanas", "1–2 meses"])("não colore fora da idade elegível: %s", async (age) => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade={age} medidas={base} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(measurementCard()).toHaveClass("bg-white");
    expect(measurementCard()).toHaveTextContent("Não disponível");
    expect(measurementCard()).toHaveTextContent(/Idade fora da coorte|Informe idade precisa/);
    expect(measurementCard()).not.toHaveTextContent("8,60–15,30");
  });

  it("usa mm após converter cm e mantém igualdade dos limites dentro da faixa", async () => {
    const medidas = { ...base, DIVEd: "0.86", unidade_confirmada_DIVEd: "cm" };
    const view = render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={medidas} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(measurementCard()).toHaveTextContent("8.6 mm");
    expect(measurementCard()).toHaveClass("bg-green-50");
    view.rerender(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={{ ...medidas, DIVEd: "1.53" }} onMedidaChange={vi.fn()} />);
    expect(measurementCard()).toHaveTextContent("15.3 mm");
    expect(measurementCard()).toHaveClass("bg-green-50");
    expect(medidas.DIVEd).toBe("0.86");
  });

  it("apresenta unidades de porcentagem e velocidade e mantém AE/Ao adimensional", async () => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={{ ...base,
      DeltaD_FS: "50", Vmax_aorta: "1.1", AE_Ao: "1.3", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" }} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    expect(measurementCard("Delta D / %FS (Encurtamento)")).toHaveTextContent("50 %");
    expect(measurementCard("Vmax Aorta")).toHaveTextContent("1.1 m/s");
    expect(within(measurementCard("AE/Ao")).getByText("1.3")).toBeInTheDocument();
    expect(measurementCard("AE/Ao")).not.toHaveTextContent(/mm|m\/s|%/);
  });

  it.each<Record<string, string>>([
    { DIVEd: "1.2", DIVES: "6", unidade_confirmada_DIVEd: "cm" },
    { DIVEd: "12", DIVES: "0.6", unidade_confirmada_DIVES: "cm" },
  ])("deriva FS de unidades mistas uma única vez: %j", async (dimensions) => {
    const measurements = Object.freeze({ ...base, ...dimensions });
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={measurements} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    const fs = measurementCard("Delta D / %FS (Encurtamento)");
    expect(within(fs).getByText("50 %")).toBeInTheDocument();
    expect(fs).toHaveClass("bg-green-50");
    expect(measurements).toEqual({ ...base, ...dimensions });
    expect(measurements).not.toHaveProperty("DeltaD_FS");
  });

  it.each([
    { DIVES: "3.78", display: "68,5 %", color: "bg-green-50", position: "Dentro da faixa da coorte" },
    { DIVES: "7.62", display: "36,5 %", color: "bg-blue-50", position: "Abaixo da faixa da coorte" },
  ])("não arredonda FS antes de escolher a cor: %j", async ({ DIVES, display, color, position }) => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses" medidas={{ ...base, DIVEd: "12", DIVES }} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    const fs = measurementCard("Delta D / %FS (Encurtamento)");
    expect(within(fs).getByText(display)).toBeInTheDocument();
    expect(fs).toHaveClass(color);
    expect(fs).toHaveTextContent(position);
  });

  it("não colore origem hexadecimal convertida para mm nem FS derivado dessa origem", async () => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses"
      medidas={{ ...base, DIVEd: "0x1", unidade_confirmada_DIVEd: "cm", DIVES: "5" }} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    for (const label of ["DIVEd (Diâmetro interno VE diástole)", "Delta D / %FS (Encurtamento)"]) {
      expect(measurementCard(label)).toHaveClass("bg-white");
      expect(measurementCard(label)).not.toHaveTextContent(/Dentro da faixa da coorte|Acima da faixa da coorte|Abaixo da faixa da coorte/);
    }
  });

  it("mantém FS informado e não troca sua posição pelo valor derivável", async () => {
    render(<ReferenciaComparison especie="Felina" peso={1.2} idade="3 meses"
      medidas={{ ...base, DIVEd: "12", DIVES: "7.62", DeltaD_FS: "55.2" }} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência pediátrica: consulta da coorte publicada");
    const fs = measurementCard("Delta D / %FS (Encurtamento)");
    expect(fs).toHaveTextContent("55.2 %");
    expect(fs).toHaveClass("bg-green-50");
  });
});
