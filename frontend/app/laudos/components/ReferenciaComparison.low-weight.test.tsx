import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReferenciaComparison } from "./ReferenciaComparison";
import type { ReferenciaEco } from "../types/referencia-eco";

const mocks = vi.hoisted(() => ({ buscar: vi.fn<(...args: unknown[]) => Promise<ReferenciaEco | null>>(async () => null) }));
vi.mock("../hooks/useReferenciaEco", async () => {
  const actual = await vi.importActual<typeof import("../hooks/useReferenciaEco")>("../hooks/useReferenciaEco");
  return { ...actual, useReferenciaEco: () => ({ buscarReferencia: mocks.buscar,
    compararMedidas: actual.compararMedidasComReferencia, loading: false }) };
});

const measurements = Object.freeze({ VE_tecnica_relatorio: "modo_m", DIVEd: "20", DIVES: "12",
  SIVd: "5", SIVs: "8", PLVEd: "5", PLVES: "8" });
const labels = ["DIVEd (Diâmetro interno VE diástole)", "DIVÉs (Diâmetro interno VE sístole)",
  "SIVd (Septo interventricular diástole)", "SIVs (Septo interventricular sístole)",
  "PLVEd (Parede livre VE diástole)", "PLVÉs (Parede livre VE sístole)"];
const adult = { idade: "2 anos" };
function card(label: string) {
  const element = screen.getByText(label).closest("div.rounded-lg.border");
  expect(element).not.toBeNull();
  return element as HTMLElement;
}

describe("comparação de baixo peso sem linha cadastrada", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.buscar.mockResolvedValue(null); });

  it.each([{ species: "Canina", source: /Isayama/i }, { species: "Felina", source: /Häggström|Haggstrom/i }])
    ("mostra fonte calculada para as seis dimensões M de adulto $species", async ({ species, source }) => {
      render(<ReferenciaComparison especie={species} peso={2} medidas={measurements} onMedidaChange={vi.fn()} {...adult} />);
      await screen.findByText(/Referência calculada/);
      // O cabecalho precede o efeito que materializa as linhas comparadas.
      await screen.findByText(labels[0]);
      expect(screen.queryByText(/cadastro de/i)).not.toBeInTheDocument();
      for (const label of labels) {
        expect(card(label)).toHaveTextContent(source);
        expect(card(label)).not.toHaveTextContent(/Faixa não cadastrada|Sem referência/);
      }
      expect(measurements).toEqual({ VE_tecnica_relatorio: "modo_m", DIVEd: "20", DIVES: "12",
        SIVd: "5", SIVs: "8", PLVEd: "5", PLVES: "8" });
    });

  it.each(["Canina", "Felina"])("mantém estimativa neutra de adulto %s abaixo de 1,5 kg", async (species) => {
    render(<ReferenciaComparison especie={species} peso={1} medidas={measurements} onMedidaChange={vi.fn()} {...adult} />);
    await screen.findByText(/Referência calculada/);
    await screen.findByText(labels[0]);
    for (const label of labels) {
      const row = card(label);
      expect(row).toHaveTextContent(/estimativ|extrapola/i);
      expect(row).not.toHaveTextContent(/Dentro da faixa|Acima da faixa|Abaixo da faixa|Dentro do intervalo|Acima do intervalo|Abaixo do intervalo/);
      expect(row).not.toHaveClass("bg-green-50", "bg-red-50", "bg-blue-50");
    }
  });

  it("não compara a faixa adulta com filhote de idade conhecida", async () => {
    render(<ReferenciaComparison especie="Canina" peso={2} medidas={measurements} onMedidaChange={vi.fn()} {...{ idade: "7m" }} />);
    await waitFor(() => expect(mocks.buscar).toHaveBeenCalled());
    const row = await screen.findByText(labels[0]);
    const body = row.closest("div.rounded-lg.border")!;
    expect(body).toHaveTextContent(/filhote|juvenil|adult|maturidade/i);
    expect(body).not.toHaveTextContent(/Estimativa:|Dentro da faixa|Acima da faixa|Abaixo da faixa|Dentro do intervalo/);
    expect(body).not.toHaveClass("bg-green-50", "bg-red-50", "bg-blue-50");
  });

  it("idade desconhecida oferece apenas estimativa de adultos a confirmar", async () => {
    render(<ReferenciaComparison especie="Canina" peso={2} medidas={measurements} onMedidaChange={vi.fn()} />);
    await screen.findByText(/Referência calculada/);
    expect(card(labels[0])).toHaveTextContent(/idade|maturidade/i);
    expect(card(labels[0])).toHaveTextContent(/estimativ/i);
    expect(card(labels[0])).not.toHaveClass("bg-green-50", "bg-red-50", "bg-blue-50");
  });

  it("retira o modelo ao mudar o peso para 3 kg", async () => {
    const view = render(<ReferenciaComparison especie="Canina" peso={2} medidas={measurements} onMedidaChange={vi.fn()} {...adult} />);
    await screen.findByText(/Referência calculada/);
    view.rerender(<ReferenciaComparison especie="Canina" peso={3} medidas={measurements} onMedidaChange={vi.fn()} {...adult} />);
    await waitFor(() => expect(screen.queryByText(/Referência calculada/)).not.toBeInTheDocument());
    expect(screen.queryByText(/Isayama/i)).not.toBeInTheDocument();
  });

  it("preserva um cadastro próprio válido em vez de substituí-lo", async () => {
    mocks.buscar.mockResolvedValue({ id: 7, especie: "Canina", peso_kg: 2.5, lvid_d_min: 16, lvid_d_max: 24,
      lvid_s_min: 9, lvid_s_max: 15, ivs_d_min: 3, ivs_d_max: 6, ivs_s_min: 5, ivs_s_max: 9,
      lvpw_d_min: 3, lvpw_d_max: 6, lvpw_s_min: 5, lvpw_s_max: 9 });
    render(<ReferenciaComparison especie="Canina" peso={2.5} medidas={measurements} onMedidaChange={vi.fn()} {...adult} />);
    await screen.findByText(/Referência selecionada/);
    await screen.findByText(labels[0]);
    expect(card(labels[0])).toHaveTextContent(/16\s*-\s*24/);
    expect(screen.queryByText(/Referência calculada/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Isayama/i)).not.toBeInTheDocument();
  });

  it.each([{ weight: 2.7, supported: true }, { weight: 2.5, supported: false }])
    ("mantém a fronteira 2D de Visser em $weight kg", async ({ weight, supported }) => {
      render(<ReferenciaComparison especie="Canina" peso={weight} medidas={{ VE_tecnica_relatorio: "2d", VE_vista_2D: "eixo_curto", DIVEd_2D: "22" }}
        onMedidaChange={vi.fn()} {...adult} />);
      const label = await screen.findByText("DIVEd 2D (Diâmetro interno VE diástole)");
      const row = label.closest<HTMLDivElement>("div.rounded-lg.border")!;
      if (supported) expect(within(row).getByText(/Visser/)).toBeInTheDocument();
      else {
        expect(within(row).queryByText(/Visser/)).not.toBeInTheDocument();
        expect(row).not.toHaveClass("bg-green-50", "bg-red-50", "bg-blue-50");
      }
    });
});
