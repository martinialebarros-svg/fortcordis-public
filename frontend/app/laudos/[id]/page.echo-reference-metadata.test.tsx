import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VisualizarLaudoPage from "./page";
import { montarDescricaoEcocardiograma } from "@/lib/ecocardiograma-estruturado";

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(),
  router: { push: vi.fn(), replace: vi.fn() }, buscarReferencia: vi.fn(),
}));
vi.mock("../../layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "91" }), useRouter: () => mocks.router }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, post: mocks.post, put: mocks.put } }));
vi.mock("../hooks/useReferenciaEco", () => ({ useReferenciaEco: () => ({ buscarReferencia: mocks.buscarReferencia, loading: false }) }));

const stored: Record<string, string> = {
  Onda_E: "1.08", Onda_A: "0.95", E_A: "1.13", TD: "51", TRIV: "40", E_TRIV: "2.66",
  e_doppler: "0.16", a_doppler: "0.06", doppler_tecidual_relacao: "2.60", E_E_linha: "6.95",
};
const expectedValues: Record<string, string> = {
  "Onda E": "1.08 m/s", "Onda A": "0.95 m/s", "Relação E/A": "1.13",
  "Tempo de desaceleração": "51.00 ms", "Tempo de relaxamento isovolumétrico": "40.00 ms",
  "Relação E/TRIV": "2.66", "e' · Doppler tecidual": "0.16 m/s", "a' · Doppler tecidual": "0.06 m/s",
  "Relação e'/a'": "2.60", "Relação E/e'": "6.95",
};

function cells(label: string) {
  const row = screen.getByText(label, { selector: "td" }).closest("tr");
  expect(row).not.toBeNull();
  return within(row as HTMLElement).getAllByRole("cell");
}
function reference(label: string) { return cells(label)[2]; }

describe("referências diastólicas no visualizador do laudo salvo", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.buscarReferencia.mockResolvedValue(null);
    localStorage.setItem("token", "synthetic-local-token");
  });
  afterEach(() => localStorage.clear());

  it("integra comparação opcional sem prender o laudo atual a uma falha do histórico", async () => {
    mocks.get.mockImplementation(async (url: string) => {
      if (url.endsWith("comparacao-anterior")) throw new Error("synthetic timeout");
      return { data: { id: 91, paciente_id: 8, tipo: "ecocardiograma", titulo: "QA COMPARAÇÃO",
        descricao: "## Medidas Ecocardiograficas\n- DIVEd: 30\n- VE_tecnica_relatorio: modo_m",
        medidas: { DIVEd: "30", VE_tecnica_relatorio: "modo_m" }, diagnostico: "Conclusão atual preservada",
        status: "Rascunho", data_exame: "2026-10-27", data_laudo: "2026-10-27T12:00:00",
        paciente: { id: 8, nome: "SINTÉTICO", especie: "Canina", peso_kg: 10 } } };
    });
    const view = render(<VisualizarLaudoPage />);
    await screen.findByRole("heading", { name: "Medidas Ecocardiográficas" });
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith("/laudos/91");
    const details = view.container.querySelector("details")!;
    details.open = true; fireEvent(details, new Event("toggle"));
    await screen.findByRole("button", { name: "Tentar novamente" });
    expect(screen.getByText("Conclusão atual preservada")).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled(); expect(mocks.put).not.toHaveBeenCalled();
  });

  const cases = ["Felina", "Gato"].flatMap((species) =>
    ["separadas", "fundidas", "desconhecidas", "legado"].map((scenario) => ({ species, scenario })));
  it.each(cases)("rehidrata $species/$scenario preservando o registro e ocultando picos fundidos", async ({ species, scenario }) => {
    const measurements: Record<string, string> = {
      ...stored,
      Diastolica_metodo: scenario === "legado"
        ? "felino_adulto_nao_sedado_pw_clique_aortico" : "felino_adulto_nao_sedado_pw_apical_clique_aortico",
      Diastolica_ondas: scenario === "desconhecidas" ? "" : scenario === "fundidas" ? "fundidas" : "separadas",
      TDI_metodo: scenario === "desconhecidas" ? "" : "felino_pw_anel_lateral",
      TDI_ondas: scenario === "desconhecidas" ? "" : "separadas",
    };
    const before = { ...measurements };
    mocks.get.mockResolvedValue({ data: {
      id: 91, tipo: "ecocardiograma", titulo: "Teste sintético de prévia", descricao: "Medidas Ecocardiográficas",
      medidas: measurements, diagnostico: "Interpretação clínica registrada", observacoes: "", status: "Rascunho",
      data_laudo: "2026-10-14T12:00:00", criado_por_nome: "Teste",
      paciente: { id: 8, nome: "TESTE_PREVIA_FELINA", especie: species, peso_kg: 0, raca: "SRD", sexo: "Macho" },
    } });
    render(<VisualizarLaudoPage />);
    await screen.findByRole("heading", { name: "Medidas Ecocardiográficas" });
    const fusedLabels = new Set(["Onda E", "Onda A", "Relação E/A", "Tempo de desaceleração", "Relação E/TRIV", "Relação E/e'"]);
    for (const [label, value] of Object.entries(expectedValues)) {
      if (scenario === "fundidas" && fusedLabels.has(label)) {
        expect(cells(label)[1]).toHaveTextContent(/^Não mensurável$/);
      } else {
        expect(cells(label)[1]).toHaveTextContent(new RegExp(`^${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
      }
    }
    expect(screen.queryByRole("heading", { name: "Outras medidas registradas" })).not.toBeInTheDocument();
    expect(screen.getByText("Interpretação clínica registrada")).toBeInTheDocument();
    expect(screen.getByText("Referências específicas da técnica estão indicadas nas medidas abaixo.")).toBeInTheDocument();
    expect(screen.queryByText("Faixas de referência indisponíveis nesta prévia.")).not.toBeInTheDocument();
    expect(reference("Onda E")).toHaveClass("whitespace-normal", "break-words");
    expect(reference("Onda E")).not.toHaveClass("whitespace-nowrap");

    if (scenario === "separadas") {
      expect(reference("Onda E")).toHaveTextContent("0,70 ± 0,14 m/s");
      expect(within(reference("Onda E")).getByRole("link", { name: "Disatian et al. (2008)" }))
        .toHaveAttribute("href", "https://doi.org/10.1111/j.1939-1676.2008.0066.x");
      expect(reference("Onda E")).toHaveTextContent(/66 gatos saudáveis, não sedados/);
      expect(reference("Onda E")).toHaveTextContent(/vista apical esquerda de 4 câmaras, nas pontas dos folhetos mitrais/);
      expect(reference("Onda E")).toHaveTextContent("Média ± DP da população estudada; não é intervalo individual de normalidade");
      expect(within(reference("Tempo de desaceleração")).getByRole("link", { name: "Soares et al. (2005)" }))
        .toHaveAttribute("href", "https://doi.org/10.1590/S0103-84782005000600020");
      expect(reference("Tempo de desaceleração")).toHaveTextContent(/24 gatos adultos saudáveis, não sedados/);
      expect(reference("Relação E/e'")).toHaveTextContent("7,8 ± 2,92");
    } else {
      expect(within(reference("Onda E")).queryByRole("link")).not.toBeInTheDocument();
      expect(within(reference("Relação E/e'")).queryByRole("link")).not.toBeInTheDocument();
      if (scenario === "fundidas") {
        expect(reference("Onda E")).toHaveTextContent("Ondas E/A fundidas");
        expect(reference("Onda E")).toHaveTextContent("não são separadamente mensuráveis");
        expect(reference("Relação E/e'")).toHaveTextContent("Valores registrados preservados");
      } else {
        expect(reference("Onda E")).toHaveTextContent(/Confirme/);
        expect(reference("Onda E")).not.toHaveTextContent("0,70 ± 0,14");
      }
    }
    expect(reference("Tempo de relaxamento isovolumétrico")).toHaveTextContent("46,2 ± 7,6 ms");
    expect(reference("Tempo de relaxamento isovolumétrico")).toHaveTextContent(/87 gatos saudáveis, não sedados/);
    expect(reference("Tempo de relaxamento isovolumétrico")).toHaveTextContent(/apical esquerdo de 5 câmaras, do início do clique de fechamento aórtico/);
    if (scenario === "desconhecidas") {
      expect(within(reference("e' · Doppler tecidual")).queryByRole("link")).not.toBeInTheDocument();
      expect(reference("e' · Doppler tecidual")).toHaveTextContent(/Confirme/);
    } else {
      expect(within(reference("e' · Doppler tecidual")).getByRole("link", { name: "Kiatsilapanan & Surachetpong (2020)" }))
        .toHaveAttribute("href", "https://doi.org/10.1186/s12917-020-02557-3");
      expect(reference("e' · Doppler tecidual")).toHaveTextContent(/20 gatos saudáveis, não sedados/);
      expect(reference("e' · Doppler tecidual")).toHaveTextContent(/Doppler tecidual pulsado no anel lateral/);
    }
    expect(measurements).toEqual(before);
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith("/laudos/91");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.buscarReferencia).not.toHaveBeenCalled();
  });

  it.each(["septal", "fundidas"])("exibe a fonte específica ou o motivo de bloqueio tecidual: %s", async (scenario) => {
    mocks.get.mockResolvedValue({ data: {
      id: 91, tipo: "ecocardiograma", titulo: "Teste sintético de técnica tecidual", descricao: "Medidas Ecocardiográficas",
      medidas: { ...stored, Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "separadas",
        TDI_metodo: "felino_pw_anel_septal", TDI_ondas: scenario === "fundidas" ? "fundidas" : "separadas" },
      status: "Rascunho", data_laudo: "2026-10-14T12:00:00",
      paciente: { id: 8, nome: "TESTE_PREVIA_TDI", especie: "Gato", peso_kg: 0 },
    } });
    render(<VisualizarLaudoPage />);
    await screen.findByRole("heading", { name: "Medidas Ecocardiográficas" });
    expect(cells("Onda E")[1]).toHaveTextContent(/^1\.08 m\/s$/);
    if (scenario === "fundidas") {
      for (const label of ["e' · Doppler tecidual", "a' · Doppler tecidual", "Relação e'/a'", "Relação E/e'"]) {
        expect(cells(label)[1]).toHaveTextContent(/^Não mensurável$/);
      }
    } else {
      expect(cells("e' · Doppler tecidual")[1]).toHaveTextContent("0.16 m/s");
      expect(cells("Relação e'/a'")[1]).toHaveTextContent("2.60");
      expect(cells("Relação E/e'")[1]).toHaveTextContent("6.95");
    }
    expect(within(reference("Onda E")).getByRole("link", { name: "Disatian et al. (2008)" })).toBeInTheDocument();
    if (scenario === "septal") {
      expect(reference("e' · Doppler tecidual")).toHaveTextContent("0,075 ± 0,026 m/s");
      expect(within(reference("e' · Doppler tecidual")).getByRole("link", { name: "Ward et al. (2012)" }))
        .toHaveAttribute("href", "https://doi.org/10.1177/1098612X12447729");
      expect(reference("e' · Doppler tecidual")).toHaveTextContent(/7 gatos jovens \(1–3 anos\)/);
      expect(reference("e' · Doppler tecidual")).toHaveTextContent(/antes da sedação.*anel septal/);
      expect(reference("Relação E/e'")).toHaveTextContent("8,7 ± 1,7");
      expect(reference("Relação e'/a'")).toHaveTextContent("Sem comparador septal reconciliado");
      expect(reference("Relação e'/a'")).not.toHaveTextContent("0,93 ± 0,20");
      expect(within(reference("Relação e'/a'")).queryByRole("link")).not.toBeInTheDocument();
    } else {
      for (const label of ["e' · Doppler tecidual", "a' · Doppler tecidual", "Relação e'/a'", "Relação E/e'"]) {
        expect(reference(label)).toHaveTextContent("Ondas e'/a' fundidas");
        expect(reference(label)).toHaveTextContent("Valores registrados preservados");
        expect(within(reference(label)).queryByRole("link")).not.toBeInTheDocument();
      }
    }
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("mantém o layout da referência canina sem inserir fontes felinas", async () => {
    mocks.buscarReferencia.mockResolvedValue({ especie: "Canina", peso_kg: 10, lvid_d_min: 20, lvid_d_max: 40 });
    mocks.get.mockResolvedValue({ data: {
      id: 91, tipo: "ecocardiograma", titulo: "Teste sintético canino", descricao: "Medidas Ecocardiográficas",
      medidas: { DIVEd: "30" }, status: "Rascunho", data_laudo: "2026-10-14T12:00:00",
      paciente: { id: 8, nome: "TESTE_PREVIA_CANINA", especie: "Canina", peso_kg: 10 },
    } });
    render(<VisualizarLaudoPage />);
    await screen.findByText("20.00–40.00 mm");
    expect(reference("DIVEd · diâmetro interno do VE em diástole")).toHaveClass("whitespace-nowrap");
    expect(within(reference("DIVEd · diâmetro interno do VE em diástole")).queryByRole("link")).not.toBeInTheDocument();
    expect(cells("DIVEd · diâmetro interno do VE em diástole")[1]).toHaveTextContent("30.00 mm");
    expect(mocks.buscarReferencia).toHaveBeenCalledWith("Canina", 10, undefined);
  });

  it.each([
    { species: "Canina", weight: 2.5, age: "2 anos", expected: "13.83–21.28 mm", kind: "adult" },
    { species: "Felina", weight: 2.25, age: "2 anos", expected: "10.55–16.50 mm", kind: "adult" },
    { species: "Canina", weight: 1, age: "2 anos", expected: "estimativa", kind: "estimated" },
    { species: "Canina", weight: 2.5, age: undefined, expected: "estimativa", kind: "unknown" },
    { species: "Canina", weight: 2.5, age: "7m", expected: "paciente em crescimento", kind: "juvenile" },
  ])("encaminha idade e mantém a referência aplicável na prévia $species/$kind", async ({ species, weight, age, expected, kind }) => {
    const data = {
      id: 91, tipo: "ecocardiograma", titulo: "QA baixo peso salvo", descricao: "Medidas Ecocardiográficas",
      medidas: { DIVEd: "20", VE_tecnica_relatorio: "modo_m" }, status: "Rascunho", data_laudo: "2026-10-27T12:00:00",
      paciente: { id: 8, nome: "QA BAIXO PESO", especie: species, peso_kg: weight, idade: age },
    };
    const before = structuredClone(data);
    mocks.get.mockResolvedValue({ data });
    render(<VisualizarLaudoPage />);
    await screen.findByRole("heading", { name: "Medidas Ecocardiográficas" });
    await waitFor(() => expect(mocks.buscarReferencia).toHaveBeenCalledWith(species, weight, age));
    const cell = reference("DIVEd · diâmetro interno do VE em diástole");
    expect(cell).toHaveTextContent(expected);
    expect(cells("DIVEd · diâmetro interno do VE em diástole")[1]).toHaveTextContent("20.00 mm");
    expect(mocks.buscarReferencia).toHaveBeenCalledWith(species, weight, age);
    if (kind === "juvenile") expect(cell).not.toHaveTextContent("13.83–21.28 mm");
    if (kind === "unknown") expect(cell).toHaveTextContent(/idade\/maturidade a confirmar/);
    expect(data).toEqual(before);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it.each([
    { species: "Cat", waves: "fundidas", expected: true },
    { species: "Felina", waves: "separadas", expected: false },
    { species: "Canina", waves: "fundidas", expected: true },
  ])("confere a narrativa oficial na prévia $species/$waves sem escrever no laudo", async ({ species, waves, expected }) => {
    const text = "Função diastólica preservada, com padrão de enchimento adequado ao Doppler transmitral.";
    const measurements = { ...stored, Diastolica_ondas: waves, TDI_ondas: "separadas" };
    const description = montarDescricaoEcocardiograma(measurements,
      { valvas: "", camaras: "", funcao: text, pericardio: "", vasos: "", ad_vd: "" });
    const data = {
      id: 91, tipo: "ecocardiograma", titulo: "QA CONFERÊNCIA NARRATIVA", descricao: description,
      medidas: measurements, diagnostico: "Conclusão clínica integrada preservada.", status: "Rascunho",
      data_laudo: "2026-10-15T12:00:00",
      paciente: { id: 8, nome: "QA NARRATIVA FELINA", especie: species, peso_kg: 0 },
      ecocardiograma_estruturado: { usar_no_laudo: true,
        textos: { funcao_diastolica: "Ondas fundidas; avaliação limitada aos demais parâmetros disponíveis." } },
    };
    const before = structuredClone(data);
    mocks.get.mockResolvedValue({ data });
    render(<VisualizarLaudoPage />);
    await screen.findByRole("heading", { name: "Medidas Ecocardiográficas" });
    const notice = screen.queryByRole("status", { name: "Conferência de coerência do laudo" });
    if (expected) {
      expect(notice).toHaveAttribute("data-echo-consistency-review");
      expect(notice!.querySelector("blockquote")).toHaveTextContent(text);
      expect(within(notice!).getByText("Sugestão para sua revisão:")).toBeInTheDocument();
      expect(notice).toHaveTextContent(/Função/);
    } else {
      expect(notice).not.toBeInTheDocument();
    }
    expect(screen.getByText("Conclusão clínica integrada preservada.")).toBeInTheDocument();
    expect(data).toEqual(before);
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith("/laudos/91");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  const numericNarrativeCases: Array<{ species: string; measurements: Record<string, string>; official: string; draft: string; expected: boolean }> = [
    { species: "Canina", measurements: { AE_Ao: "1.40" }, official: "Relação AE/Ao de 1,80.", draft: "Relação AE/Ao de 1,40.", expected: true },
    { species: "Felina", measurements: { AE_Ao: "1.40" }, official: "Relação AE/Ao de 1,40.", draft: "Relação AE/Ao de 1,80.", expected: false },
    { species: "Canina", measurements: { VE_tecnica_relatorio: "2d", DIVEd: "30", DIVEd_2D: "40" }, official: "DIVEd 2D de 45 mm.", draft: "DIVEd 2D de 40 mm.", expected: true },
    { species: "Canina", measurements: { Vmax_pulmonar: "0.80" }, official: "Velocidade máxima pulmonar de 120 cm/s.", draft: "Velocidade máxima pulmonar de 80 cm/s.", expected: true },
    { species: "Canina", measurements: { VE_tecnica_relatorio: "modo_m", LVIDd: "20" }, official: "DIVEd de 30 mm.", draft: "", expected: false },
  ];
  it.each(numericNarrativeCases)("visualizador confere somente o texto oficial de $species: $official", async ({ species, measurements, official, draft, expected }) => {
    const data = {
      id: 91, tipo: "ecocardiograma", titulo: "QA CONFERÊNCIA NUMÉRICA",
      medidas: measurements, descricao: montarDescricaoEcocardiograma(measurements,
        { valvas: "", camaras: "", funcao: official, pericardio: "", vasos: "", ad_vd: "" }),
      diagnostico: "Conclusão clínica oficial intacta.", status: "Rascunho", data_laudo: "2026-10-26T12:00:00",
      paciente: { id: 8, nome: "QA NARRATIVA NUMÉRICA", especie: species, peso_kg: 0 },
      ecocardiograma_estruturado: { usar_no_laudo: true, textos: { funcao_diastolica: draft } },
    };
    const before = structuredClone(data);
    mocks.get.mockResolvedValue({ data });
    render(<VisualizarLaudoPage />);
    await screen.findByRole("heading", { name: "Medidas Ecocardiográficas" });
    const notice = screen.queryByRole("status", { name: "Conferência de coerência do laudo" });
    if (expected) {
      expect(notice).toBeInTheDocument();
      expect(notice!.querySelector("blockquote")).toHaveTextContent(official);
      expect(within(notice!).queryByRole("button")).not.toBeInTheDocument();
    } else expect(notice).not.toBeInTheDocument();
    expect(screen.getByText("Conclusão clínica oficial intacta.")).toBeInTheDocument();
    expect(data).toEqual(before);
    expect(mocks.get).toHaveBeenCalledExactlyOnceWith("/laudos/91");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
  });
});
