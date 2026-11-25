import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ReferenciaComparison } from "./ReferenciaComparison";
import { compararMedidasComReferencia } from "../hooks/useReferenciaEco";
import type { ReferenciaEco } from "../types/referencia-eco";
import { buildEchoReportGroups, prepareEchoReportMeasurements } from "@/lib/echo-report-presentation";

const buscarReferencia = vi.hoisted(() => vi.fn<(...args: unknown[]) => Promise<ReferenciaEco | null>>(
  async () => ({ id: 1, especie: "Canina", peso_kg: 11 }),
));
const compararMedidas = vi.hoisted(() => vi.fn<typeof import("../hooks/useReferenciaEco").compararMedidasComReferencia>(() => ({})));
const carregandoReferencia = vi.hoisted(() => vi.fn(() => false));

vi.mock("../hooks/useReferenciaEco", async () => ({
  ...await vi.importActual<typeof import("../hooks/useReferenciaEco")>("../hooks/useReferenciaEco"),
  useReferenciaEco: () => ({ buscarReferencia, compararMedidas, loading: carregandoReferencia() }),
}));

describe("identificação da referência ecocardiográfica", () => {
  it("exibe o limite no cartão AE/Ao com método sueco e catálogo legado bloqueado", async () => {
    buscarReferencia.mockResolvedValueOnce({
      id: 1, especie: "Canina", peso_kg: 4, la_ao_min: 0.8, la_ao_max: 1.6,
      range_metadata: { la_ao: { status: "blocked", reason: "Faixa legada sem método de aquisição identificado" } },
    });
    compararMedidas.mockImplementationOnce(compararMedidasComReferencia);
    const medidas = Object.freeze({ AE_Ao: "1.49", LA_Ao: "1.80", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" });
    const change = vi.fn();
    render(<ReferenciaComparison especie="Canina" peso={4.2} medidas={medidas} onMedidaChange={change} />);

    await screen.findByText("Referência selecionada: Canina, cadastro de 4 kg");
    expect(screen.getAllByText("AE/Ao")).toHaveLength(1);
    const card = screen.getByText("AE/Ao").closest("div.border");
    expect(card).toHaveTextContent("Limite clínico orientativo: <1,60 (2D, eixo curto)");
    expect(card).toHaveTextContent("1.49");
    expect(card).toHaveClass("bg-white");
    expect(screen.getByRole("link", { name: "Rishniw (2023)" }))
      .toHaveAttribute("href", "https://doi.org/10.1016/j.jvc.2023.04.003");
    expect(screen.queryByText("1.80")).not.toBeInTheDocument();
    expect(screen.queryByText("Faixa legada sem método de aquisição identificado")).not.toBeInTheDocument();
    expect(change).not.toHaveBeenCalled();
  });

  it("recalcula o limite sem peso ao confirmar ou retirar o método, sem classificar 1,60", async () => {
    const medidas = { AE_Ao: "1,60", LA_Ao: "1.80", AE_Ao_metodo: "" };
    const change = vi.fn();
    const { rerender } = render(<ReferenciaComparison especie=" Cão " medidas={medidas} onMedidaChange={change} />);
    expect(screen.queryByText(/Limite clínico orientativo:/)).not.toBeInTheDocument();

    const confirmado = { ...medidas, AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" };
    rerender(<ReferenciaComparison especie=" Cão " medidas={confirmado} onMedidaChange={change} />);
    const card = (await screen.findByText("AE/Ao")).closest("div.border");
    expect(card).toHaveTextContent("Limite clínico orientativo: <1,60 (2D, eixo curto)");
    expect(card).toHaveTextContent("Interpretar com os demais achados");
    expect(card).toHaveClass("bg-white");
    expect(screen.getByText("1,60")).toBeInTheDocument();

    rerender(<ReferenciaComparison especie=" Cão " medidas={{ ...confirmado, AE_Ao: "" }} onMedidaChange={change} />);
    expect(screen.queryByText(/Limite clínico orientativo:/)).not.toBeInTheDocument();
    rerender(<ReferenciaComparison especie=" Cão " medidas={{ ...confirmado, AE_Ao_metodo: "outro" }} onMedidaChange={change} />);
    expect(screen.queryByText(/Limite clínico orientativo:/)).not.toBeInTheDocument();
  });

  it("mantém o alias isolado no caminho legado, sem anunciar limite ausente da prévia", async () => {
    compararMedidas.mockImplementationOnce(compararMedidasComReferencia);
    const medidas = { LA_Ao: "1.49", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" };
    render(<ReferenciaComparison especie="Canina" peso={11} medidas={medidas} onMedidaChange={vi.fn()} />);
    const card = (await screen.findByText("AE/Ao")).closest("div.border");
    expect(card).toHaveTextContent("1.49");
    expect(screen.queryByText(/Limite clínico orientativo:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/O PDF apresentará AE\/Ao/)).not.toBeInTheDocument();
    expect(screen.queryByText(/O PDF citará Hansson/)).not.toBeInTheDocument();
    const { measurements, ambiguousKeys } = prepareEchoReportMeasurements(medidas, 11, "Canina");
    const preview = buildEchoReportGroups(measurements, null, ambiguousKeys, 11, "Canina");
    expect(preview.flatMap(({ rows }) => rows).find(({ key }) => key === "LA_Ao"))
      .toMatchObject({ value: "1.49", reference: "—" });
  });

  it.each(["Felina", "CaninaXYZ"])("não atribui limite canino pela espécie do catálogo a %s", async (species) => {
    compararMedidas.mockImplementationOnce(compararMedidasComReferencia);
    render(<ReferenciaComparison especie={species} peso={11}
      medidas={{ AE_Ao: "1.49", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" }} onMedidaChange={vi.fn()} />);
    await screen.findByText("Referência selecionada: Canina, cadastro de 11 kg");
    expect(screen.queryByText(/Limite clínico orientativo:/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Rishniw (2023)" })).not.toBeInTheDocument();
  });

  it("mantém a referência clínica durante e após uma busca sem linha no catálogo", async () => {
    let concluirBusca!: (referencia: ReferenciaEco | null) => void;
    buscarReferencia.mockReturnValueOnce(new Promise((resolve) => { concluirBusca = resolve; }));
    carregandoReferencia.mockReturnValueOnce(true);
    render(<ReferenciaComparison especie="Canina" peso={11}
      medidas={{ AE_Ao: "1.80", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" }} onMedidaChange={vi.fn()} />);
    const limite = "Limite clínico orientativo: <1,60 (2D, eixo curto)";
    expect(screen.getByText(limite).closest("div.border")).toHaveClass("bg-white");
    await act(async () => concluirBusca(null));
    expect(screen.getByText(limite).closest("div.border")).toHaveClass("bg-white");
    expect(screen.getByText("1.80")).toBeInTheDocument();
  });

  it.each(["Canina", "Felina"] as const)("mostra um cartão por medida e o valor canônico após mesclar o catálogo de %s", async (species) => {
    buscarReferencia.mockResolvedValueOnce({ id: 1, especie: species, peso_kg: 11 });
    compararMedidas.mockImplementationOnce(compararMedidasComReferencia);
    const measurements = { MV_E: "1.80", Onda_E: "0.70", MV_A: "1.90", Onda_A: "0.50", TDI_e: "0.80", e_doppler: "0.09",
      Diastolica_metodo: species === "Canina" ? "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo" : "felino_adulto_nao_sedado_pw_apical_clique_aortico",
      Diastolica_ondas: "separadas", TDI_metodo: species === "Canina" ? "canino_pw_anel_septal_choi" : "felino_pw_anel_lateral", TDI_ondas: "separadas" };
    const before = { ...measurements };
    render(<ReferenciaComparison especie={species} peso={11} medidas={measurements} onMedidaChange={vi.fn()} />);
    await screen.findByText(`Referência selecionada: ${species}, cadastro de 11 kg`);
    expect(screen.getAllByText("Onda E")).toHaveLength(1);
    expect(screen.getAllByText("Onda A")).toHaveLength(1);
    expect(screen.getAllByText("e' (Doppler tecidual, m/s)")).toHaveLength(1);
    expect(screen.getByText("0.70")).toBeInTheDocument();
    expect(screen.queryByText("1.80")).not.toBeInTheDocument();
    expect(screen.queryByText("1.90")).not.toBeInTheDocument();
    expect(screen.queryByText("0.80")).not.toBeInTheDocument();
    expect(measurements).toEqual(before);
  });

  it.each(["Canina", "Felina"] as const)("não ressuscita o alias no catálogo após limpar a canônica em %s", async (species) => {
    buscarReferencia.mockResolvedValueOnce({ id: 1, especie: species, peso_kg: 11 });
    compararMedidas.mockImplementationOnce(compararMedidasComReferencia);
    render(<ReferenciaComparison especie={species} peso={11} medidas={{ MV_E: "1.80", Onda_E: "",
      Diastolica_ondas: "nao_confirmadas" }} onMedidaChange={vi.fn()} />);
    await screen.findByText(`Referência selecionada: ${species}, cadastro de 11 kg`);
    expect(screen.queryByText("Onda E")).not.toBeInTheDocument();
    expect(screen.queryByText("1.80")).not.toBeInTheDocument();
  });

  it.each(["Gato", "Cat", "Felino", " Feline "])("oferece protocolo e mantém fusões independentes para %s", async (species) => {
    render(<ReferenciaComparison especie={species} medidas={{ Onda_E: "1.08", E_A: "1.13", e_doppler: "0.16",
      Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas",
      TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" }} onMedidaChange={vi.fn()} />);
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("fundidas");
    expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("separadas");
    expect(await screen.findByText("Média ± DP publicada: 0,11 ± 0,03 m/s")).toBeInTheDocument();
    expect(screen.getAllByText("Comparação diastólica: Ondas E/A fundidas").length).toBeGreaterThan(1);
  });

  it("não oferece protocolo felino para espécie não reconhecida", () => {
    render(<ReferenciaComparison especie="Catfish" medidas={{ Onda_E: "1.08" }} onMedidaChange={vi.fn()} />);
    expect(screen.queryByLabelText("Protocolo diastólico felino")).not.toBeInTheDocument();
  });

  it("mostra controles felinos independentes sem peso ou catálogo e não infere separação", async () => {
    const change = vi.fn();
    render(<ReferenciaComparison especie="Felina" medidas={{ Onda_E: "1.08", Onda_A: "0.95", e_doppler: "0.16" }} onMedidaChange={change} />);
    expect(screen.getByLabelText("Aquisição transmitral e TRIV")).toHaveValue("");
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("");
    expect(screen.getByLabelText("Técnica e sítio do Doppler tecidual")).toHaveValue("");
    expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("");
    expect(await screen.findByText(/estudos publicados independentes do cadastro por peso/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: "fundidas" } });
    expect(change).toHaveBeenCalledWith("Diastolica_ondas", "fundidas");
    fireEvent.change(screen.getByLabelText("Ondas teciduais e'/a'"), { target: { value: "separadas" } });
    expect(change).toHaveBeenCalledWith("TDI_ondas", "separadas");
  });

  it("exibe o caso Skar com fusão E/A e e' lateral separada sem cores de normalidade", async () => {
    render(<ReferenciaComparison especie="Felina" medidas={{ Onda_E: "1.08", Onda_A: "0.95", E_A: "1.14", TD: "51", TRIV: "40", e_doppler: "0.16", E_E_linha: "6.75",
      Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", Diastolica_ondas: "fundidas",
      TDI_metodo: "felino_pw_anel_lateral", TDI_ondas: "separadas" }} onMedidaChange={vi.fn()} />);
    expect(await screen.findByText("Média ± DP publicada: 0,11 ± 0,03 m/s")).toBeInTheDocument();
    expect(screen.getByText("Média ± DP publicada: 46,2 ± 7,6 ms")).toBeInTheDocument();
    expect(screen.getAllByText("Comparação diastólica: Ondas E/A fundidas").length).toBeGreaterThan(1);
    expect(screen.getByText("0.16").closest("div.border")).toHaveClass("bg-white");
    expect(screen.queryByText("1.08")).not.toBeInTheDocument();
    expect(screen.getAllByText("Não mensurável")[0].closest("div.border")).toHaveClass("bg-white");
  });
  it("distingue o peso do paciente da linha de cadastro selecionada", async () => {
    render(<ReferenciaComparison especie="Canina" peso={10.8} medidas={{}} onMedidaChange={vi.fn()} />);

    expect(await screen.findByText("Referência selecionada: Canina, cadastro de 11 kg")).toBeInTheDocument();
    expect(screen.getByText(/Peso do paciente: 10,8 kg/)).toBeInTheDocument();
    expect(screen.getByText("Dentro da faixa")).toBeInTheDocument();
    expect(screen.queryByText("Normal")).not.toBeInTheDocument();
  });

  it("exige confirmação da vista antes de pedir comparação das medidas 2D", async () => {
    compararMedidas.mockClear();
    function Example() {
      const [medidas, setMedidas] = useState({ DIVEd_2D: "33.53", DIVES_2D: "22.87" });
      return <ReferenciaComparison especie="Canina" peso={13.6} medidas={medidas}
        onMedidaChange={(key, value) => setMedidas((current) => ({ ...current, [key]: value }))} />;
    }
    render(<Example />);
    const vista = await screen.findByLabelText("Confirme cão adulto e vista 2D do ventrículo esquerdo");
    expect(screen.getByText(/Septo e parede não têm faixa 2D por peso nas fontes adotadas/)).toBeInTheDocument();
    expect(screen.getByText(/Teichholz não são comparados aos intervalos obtidos por Simpson/)).toBeInTheDocument();
    expect(vista).toHaveValue("");
    fireEvent.change(vista, { target: { value: "eixo_curto" } });
    await waitFor(() => expect(compararMedidas).toHaveBeenLastCalledWith(
      expect.objectContaining({ DIVEd_2D: "33.53", DIVES_2D: "22.87" }),
      expect.objectContaining({ especie: "Canina" }),
      "eixo_curto",
      13.6,
    ));
  });

  it("pede método de TAPSE somente quando preenchido e persiste seleção explícita", async () => {
    const change = vi.fn();
    const { rerender } = render(<ReferenciaComparison especie="Canina" peso={10} medidas={{}} onMedidaChange={change} />);
    await screen.findByText(/Referência selecionada/);
    expect(screen.queryByLabelText("Método de obtenção do TAPSE")).not.toBeInTheDocument();
    rerender(<ReferenciaComparison especie="Canina" peso={10} medidas={{ TAPSE: "10" }} onMedidaChange={change} />);
    const method = await screen.findByLabelText("Método de obtenção do TAPSE");
    expect(method).toHaveValue("");
    fireEvent.change(method, { target: { value: "modo_m_apical" } });
    expect(change).toHaveBeenCalledWith("TAPSE_metodo", "modo_m_apical");
  });

  it("exige vista e fase de AE/Ao felino sem assumir método por espécie", async () => {
    buscarReferencia.mockResolvedValueOnce({ id: 2, especie: "Felina", peso_kg: 4 });
    const change = vi.fn();
    render(<ReferenciaComparison especie="Felina" peso={4} medidas={{ AE_Ao: "1.42" }} onMedidaChange={change} />);
    const method = await screen.findByLabelText("Método de obtenção de AE/Ao");
    expect(method).toHaveValue("");
    fireEvent.change(method, { target: { value: "2d_eixo_curto_diastole_inicial" } });
    expect(change).toHaveBeenCalledWith("AE_Ao_metodo", "2d_eixo_curto_diastole_inicial");
  });

  it("confirma método canino sem inferir a vista da técnica ventricular", async () => {
    const change = vi.fn();
    const { rerender } = render(<ReferenciaComparison especie="Canina" peso={3.6}
      medidas={{ AE_Ao: "1.41", VE_tecnica_relatorio: "modo_m" }} onMedidaChange={change} />);
    await screen.findByText(/Referência selecionada/);
    const method = await screen.findByLabelText("Método de obtenção de AE/Ao");
    expect(method).toHaveValue("");
    expect(screen.queryByText(/O PDF apresentará AE\/Ao/)).not.toBeInTheDocument();
    fireEvent.change(method, { target: { value: "2d_eixo_curto_diastole_inicial" } });
    expect(change).toHaveBeenCalledWith("AE_Ao_metodo", "2d_eixo_curto_diastole_inicial");
    rerender(<ReferenciaComparison especie="Canina" peso={3.6}
      medidas={{ AE_Ao: "1.41", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" }} onMedidaChange={change} />);
    expect(screen.getByText(/O PDF apresentará AE\/Ao < 1,60/)).toBeInTheDocument();
    rerender(<ReferenciaComparison especie="Canina" peso={3.6}
      medidas={{ AE_Ao: "1.41", AE_Ao_metodo: "outro" }} onMedidaChange={change} />);
    expect(screen.queryByText(/O PDF apresentará AE\/Ao/)).not.toBeInTheDocument();
  });

  it("permite confirmar o limite clínico canino mesmo sem peso ou linha do catálogo", async () => {
    const change = vi.fn();
    render(<ReferenciaComparison especie="Canina" medidas={{ AE_Ao: "1.41" }} onMedidaChange={change} />);
    expect(screen.getByText("Nenhuma referência encontrada")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Método de obtenção de AE/Ao"),
      { target: { value: "2d_eixo_curto_diastole_inicial" } });
    expect(change).toHaveBeenCalledWith("AE_Ao_metodo", "2d_eixo_curto_diastole_inicial");
  });

  it("registra método sueco somente pela escolha explícita e identifica a fonte da técnica", async () => {
    const change = vi.fn();
    const { rerender } = render(<ReferenciaComparison especie="Canina" peso={4}
      medidas={{ AE_Ao: "1.41", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" }} onMedidaChange={change} />);
    await screen.findByText(/Referência selecionada/);
    const method = await screen.findByLabelText("Método de obtenção de AE/Ao");
    expect(method).toHaveValue("2d_eixo_curto_diastole_inicial");
    expect(screen.queryByText(/O PDF citará Hansson/)).not.toBeInTheDocument();
    fireEvent.change(method, { target: { value: "2d_eixo_curto_diastole_inicial_sueco" } });
    expect(change).toHaveBeenCalledWith("AE_Ao_metodo", "2d_eixo_curto_diastole_inicial_sueco");
    rerender(<ReferenciaComparison especie="Canina" peso={4}
      medidas={{ AE_Ao: "1.41", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial_sueco" }} onMedidaChange={change} />);
    expect(screen.getByText(/O PDF citará Hansson/)).toBeInTheDocument();
    expect(screen.getByText(/O PDF apresentará AE\/Ao < 1,60/)).toBeInTheDocument();
  });

  it("não oferece método canino para razão ausente ou não finita", async () => {
    const { rerender } = render(<ReferenciaComparison especie="Canina" peso={4} medidas={{}} onMedidaChange={vi.fn()} />);
    await screen.findByText(/Referência selecionada/);
    expect(screen.queryByLabelText("Método de obtenção de AE/Ao")).not.toBeInTheDocument();
    rerender(<ReferenciaComparison especie="Canina" peso={4} medidas={{ AE_Ao: "Infinity" }} onMedidaChange={vi.fn()} />);
    expect(screen.queryByLabelText("Método de obtenção de AE/Ao")).not.toBeInTheDocument();
  });

  it("não promete limite no PDF enquanto unidades das origens são ambíguas", async () => {
    const medidas = { DIVEd: "2.5", DIVES: "1.5", Aorta: "1.0", Atrio_esquerdo: "1.4",
      AE_Ao: "1.4", AE_Ao_metodo: "2d_eixo_curto_diastole_inicial" };
    const { rerender } = render(<ReferenciaComparison especie="Canina" peso={4} medidas={medidas} onMedidaChange={vi.fn()} />);
    await screen.findByText(/Referência selecionada/);
    expect(screen.queryByLabelText("Método de obtenção de AE/Ao")).not.toBeInTheDocument();
    expect(screen.queryByText(/O PDF apresentará AE\/Ao/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Limite clínico orientativo:/)).not.toBeInTheDocument();
    rerender(<ReferenciaComparison especie="Canina" peso={4} medidas={{ ...medidas,
      unidade_confirmada_Aorta: "cm", unidade_confirmada_Atrio_esquerdo: "cm" }} onMedidaChange={vi.fn()} />);
    expect(screen.getByLabelText("Método de obtenção de AE/Ao")).toBeInTheDocument();
    expect(screen.getByText(/O PDF apresentará AE\/Ao < 1,60/)).toBeInTheDocument();
    expect(screen.getByText("Limite clínico orientativo: <1,60 (2D, eixo curto)")).toBeInTheDocument();
  });
});
