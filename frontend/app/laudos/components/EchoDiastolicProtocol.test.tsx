import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { EchoDiastolicProtocol } from "./EchoDiastolicProtocol";
import { ReferenciaComparison } from "./ReferenciaComparison";
import { mergeImportedEchoMeasurements, updateEchoMeasurement } from "@/lib/echo-unit-provenance";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";
import { useEchoMeasurements } from "../hooks/useEchoMeasurements";

vi.mock("@/lib/axios", () => ({ default: { get: vi.fn(async () => ({ data: null })) } }));
const measured = { Onda_E: ".47", Onda_A: ".67", E_A: ".70", TRIV: "85", e_doppler: ".07", a_doppler: ".12", E_E_linha: "6.71", doppler_tecidual_relacao: ".58" };

describe("canine protocol and real evidence comparison", () => {
  it("carrega os padrões no novo exame e preserva a troca explícita de ondas após importação", async () => {
    function NewReport() {
      const { measurements, importMeasurements, setProtocolMeasurement } = useEchoMeasurements({ newReportSpecies: "Canina" });
      return <>
        <ReferenciaComparison especie="Canina" medidas={measurements} onMedidaChange={setProtocolMeasurement} />
        <button onClick={() => importMeasurements(measured)}>Importar medidas sintéticas</button>
      </>;
    }
    render(<NewReport />);
    expect(screen.getByLabelText("Aquisição transmitral e TRIV")).toHaveValue("canino_nao_sedado_pw_apical");
    expect(screen.getByLabelText("Técnica e sítio do Doppler tecidual")).toHaveValue("canino_pw_basal_lateral_wess");
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("separadas");
    expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("separadas");
    fireEvent.click(screen.getByText("Importar medidas sintéticas"));
    expect(await screen.findByText("Intervalo de referência publicado: IR95%: 0,51-1,10 m/s")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: "fundidas" } });
    fireEvent.click(screen.getByText("Importar medidas sintéticas"));
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("fundidas");
    expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("separadas");
    await waitFor(() => expect(screen.queryByText("0.47")).not.toBeInTheDocument());
  });

  it("starts unknown and asks only relevant acquisition domains", () => {
    const change = vi.fn();
    const view = render(<EchoDiastolicProtocol especie="Cão" medidas={{ Onda_E: ".47" }} onMedidaChange={change} />);
    expect(screen.getByLabelText("Aquisição transmitral e TRIV")).toHaveValue("");
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("");
    expect(screen.queryByLabelText("Técnica e sítio do Doppler tecidual")).not.toBeInTheDocument();
    expect(screen.getByText(/Ao selecionar o protocolo/)).toHaveTextContent("55 e 171 bpm");
    expect(screen.getByText(/Ao selecionar o protocolo/)).toHaveTextContent("pontas dos folhetos mitrais");
    expect(change).not.toHaveBeenCalled();
    view.rerender(<EchoDiastolicProtocol especie="Canina" medidas={{ e_doppler: ".07" }} onMedidaChange={change} />);
    expect(screen.queryByLabelText("Aquisição transmitral e TRIV")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Técnica e sítio do Doppler tecidual")).toHaveValue("");
    expect(screen.getByText(/Confirme paciente não sedado/)).toHaveTextContent("amostra de 5 mm");
  });
  it.each(["Dogfish", "Caniniforme", ""])("hides irrelevant or unknown species: %s", (species) => {
    render(<EchoDiastolicProtocol especie={species} medidas={measured} onMedidaChange={vi.fn()} />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });
  it("uses real selectors, survives serialization/reload and keeps fusion domains independent without weight/catalogue", async () => {
    let live: Record<string, string> = {};
    function Example() {
      const [measurements, setMeasurements] = useState<Record<string, string>>(measured);
      live = measurements;
      return <>
        <ReferenciaComparison especie="Cão" medidas={measurements}
          onMedidaChange={(key, value) => setMeasurements((previous) => ({ ...previous, [key]: value }))} />
        <button onClick={() => setMeasurements(parseStoredEchoMeasurements(JSON.parse(JSON.stringify(measurements))))}>Recarregar registro sintético</button>
      </>;
    }
    render(<Example />);
    expect(screen.getByLabelText("Aquisição transmitral e TRIV")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Aquisição transmitral e TRIV"), { target: { value: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo" } });
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: "separadas" } });
    fireEvent.change(screen.getByLabelText("Técnica e sítio do Doppler tecidual"), { target: { value: "canino_pw_anel_septal_choi" } });
    fireEvent.change(screen.getByLabelText("Ondas teciduais e'/a'"), { target: { value: "separadas" } });
    const interval = await screen.findByText("Intervalo de referência publicado: IR95%: 0,51-1,10 m/s");
    expect(interval.closest("div.border")).toHaveClass("bg-blue-50");
    const descriptive = await screen.findByText("Média ± DP publicada: 0,0658 ± 0,0181 m/s");
    expect(descriptive.closest("div.border")).toHaveClass("bg-white");
    expect(screen.getByText("Média ± DP publicada: 80 ± 9 ms")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: "fundidas" } });
    await waitFor(() => expect(screen.queryByText("0.47")).not.toBeInTheDocument());
    expect(await screen.findByText("Média ± DP publicada: 0,0658 ± 0,0181 m/s")).toBeInTheDocument();
    expect(screen.getAllByText("Comparação diastólica: Ondas E/A fundidas").length).toBeGreaterThan(1);
    fireEvent.click(screen.getByText("Recarregar registro sintético"));
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("fundidas");
    expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("separadas");
    expect(screen.getByLabelText("Técnica e sítio do Doppler tecidual")).toHaveValue("canino_pw_anel_septal_choi");
    expect(live).toMatchObject({ ...measured, Diastolica_metodo: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", Diastolica_ondas: "fundidas", TDI_ondas: "separadas" });
    expect(parseStoredEchoMeasurements({ Diastolica_metodo: "canino_inferido", TDI_metodo: "PW_lateral" })).toEqual({});
  });
});


describe("invalidated wave review remains visible", () => {
  it.each(["edit", "import"])("requires reconfirmation in the real selector after %s and reload", async (action) => {
    const original = { ...measured, Diastolica_metodo: "canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo", Diastolica_ondas: "fundidas", TDI_metodo: "canino_pw_anel_septal_choi", TDI_ondas: "separadas" };
    const changed = action === "edit" ? updateEchoMeasurement(original, "Onda_E", "1.10") : mergeImportedEchoMeasurements(original, { Onda_E: "1.10" });
    const change = vi.fn();
    render(<EchoDiastolicProtocol especie="Canina" medidas={parseStoredEchoMeasurements(JSON.parse(JSON.stringify(changed)))} onMedidaChange={change} />);
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("nao_confirmadas");
    expect(screen.getByRole("option", { name: "Separação a reconfirmar" })).toBeInTheDocument();
    expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("separadas");
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: "separadas" } });
    expect(change).toHaveBeenCalledExactlyOnceWith("Diastolica_ondas", "separadas");
  });
});
