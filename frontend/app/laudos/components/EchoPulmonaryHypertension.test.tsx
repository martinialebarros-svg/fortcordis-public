import { useEffect } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EchoPulmonaryHypertension from "./EchoPulmonaryHypertension";
import { useEchoMeasurements } from "../hooks/useEchoMeasurements";

const INITIAL = {
  HP_ativa: "sim", HP_TRV: "", HP_VSVD: "", HP_suporte_automatico: "sim", IT_Vmax: "3.2",
};

function Editor({ initial = INITIAL, species = "Canina" }: { initial?: Record<string, string>; species?: string }) {
  const measurements = useEchoMeasurements({ species });
  useEffect(() => measurements.replaceMeasurements(initial), [initial, measurements.replaceMeasurements]);
  return <EchoPulmonaryHypertension species={species} measurements={measurements.measurements}
    onPatch={(patch) => measurements.setMeasurements((previous) => ({ ...previous, ...patch }))} />;
}

describe("avaliação rápida de probabilidade de HP", () => {
  it("exige inclusão explícita e não transforma campos vazios em sítios normais", () => {
    const onPatch = vi.fn();
    const { rerender } = render(<EchoPulmonaryHypertension species="Canina" measurements={{ IT_Vmax: "3.2" }} onPatch={onPatch} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Incluir avaliação de HP neste laudo"));
    expect(onPatch).toHaveBeenCalledWith({ HP_ativa: "sim", HP_suporte_automatico: "sim" });
    rerender(<EchoPulmonaryHypertension species="Canina" measurements={INITIAL} onPatch={onPatch} />);
    expect(screen.getByLabelText("Sinais em Ventrículos")).toHaveValue("");
    expect(screen.getByLabelText("Sinais em Artéria pulmonar")).toHaveValue("");
    expect(screen.getByLabelText("Sinais em Átrio direito / veia cava caudal")).toHaveValue("");
    expect(screen.getByText("Avaliação de HP pendente")).toBeInTheDocument();
  });

  it("fecha os três sítios em lote e só classifica após qualidade, VSVD e revisão humanas", () => {
    render(<Editor />);
    fireEvent.click(screen.getByRole("button", { name: "Três sítios avaliados sem sinais" }));
    fireEvent.change(screen.getByLabelText("Aquisição da regurgitação tricúspide"), { target: { value: "adequado" } });
    fireEvent.change(screen.getByLabelText("Via de saída do ventrículo direito"), { target: { value: "sem_obstrucao" } });
    expect(screen.getByText("Avaliação de HP pendente")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar avaliação atual" }));
    expect(screen.getByText("Probabilidade intermediária de hipertensão pulmonar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Avaliação confirmada" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Sinais em Ventrículos"), { target: { value: "com_sinais" } });
    expect(screen.getByText("Avaliação de HP pendente")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirmar avaliação atual" })).toBeEnabled();
  });

  it("preserva sinais presentes no atalho e exige aceitar sugestões métricas positivas", () => {
    const initial = { ...INITIAL, HP_TRV: "adequado", HP_VSVD: "sem_obstrucao", IT_Vmax: "3.6",
      HP_ventriculos: "com_sinais", AP_Ao: "1.2", Remodelamento_AD: "moderado" };
    render(<Editor initial={initial} />);
    fireEvent.click(screen.getByRole("button", { name: "Demais sítios avaliados sem sinais" }));
    expect(screen.getByLabelText("Sinais em Ventrículos")).toHaveValue("com_sinais");
    expect(screen.getByLabelText("Sinais em Artéria pulmonar")).toHaveValue("sem_sinais");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar avaliação atual" }));
    expect(screen.getByText("Avaliação de HP pendente")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar sinais sugeridos" }));
    expect(screen.getByLabelText("Sinais em Artéria pulmonar")).toHaveValue("com_sinais");
    expect(screen.getByLabelText("Sinais em Átrio direito / veia cava caudal")).toHaveValue("com_sinais");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar avaliação atual" }));
    expect(screen.getByText("Probabilidade alta de hipertensão pulmonar")).toBeInTheDocument();
  });

  it("mantém felinos descritivos e disponibiliza aquisição específica do pico de IP", () => {
    render(<Editor species="Gato" />);
    expect(screen.getByText(/classificação de probabilidade canina.*não está validada para gatos/)).toBeInTheDocument();
    expect(screen.getByText("Registro descritivo de achados")).toBeInTheDocument();
    expect(screen.queryByText(/^Probabilidade (baixa|intermediária|alta) de hipertensão/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Medidas de apoio e técnica de aquisição (opcionais)"));
    expect(screen.getByLabelText("Pico inicial diastólico da insuficiência pulmonar (m/s)")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("RPAD informado (%)"), { target: { value: "25" } });
    expect(screen.getByLabelText("RPAD informado (%)")).toHaveValue("25");
  });

  it.each(["Felina", "Cat", "Equina"])("não atribui probabilidade canina à espécie %s mesmo com todos os critérios preenchidos", (species) => {
    render(<Editor species={species} initial={{ ...INITIAL, HP_TRV: "adequado", HP_VSVD: "sem_obstrucao", IT_Vmax: "3.6",
      HP_ventriculos: "com_sinais", HP_arteria_pulmonar: "com_sinais", HP_atrio_cava: "com_sinais" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirmar avaliação atual" }));
    expect(screen.getByText("Registro descritivo de achados")).toBeInTheDocument();
    expect(screen.queryByText(/^Probabilidade (baixa|intermediária|alta) de hipertensão/)).not.toBeInTheDocument();
  });

  it("expõe a IT antiga quando a aquisição atual não é mensurável e a PSAP não está revisada", () => {
    render(<Editor initial={{ ...INITIAL, HP_TRV: "nao_mensuravel", PSAP: "45.96" }} />);
    expect(screen.getByText(/Há uma IT Vmax registrada.*não mensurável/)).toBeInTheDocument();
    expect(screen.getByText(/Ainda não validada para esta aquisição/)).toBeInTheDocument();
  });
});
