import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FelineDiastolicProtocol } from "./FelineDiastolicProtocol";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";

const measurements = { Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", E_A: "1.13", e_doppler: "0.16",
  Diastolica_ondas: "separadas", TDI_ondas: "separadas", TDI_metodo: "felino_pw_anel_lateral" };

describe("full feline transmitral acquisition confirmation", () => {
  it.each(["felino_adulto_nao_sedado_pw_apical_clique_aortico", "felino_adulto_nao_sedado_pw_apical_fim_fluxo"])
    ("explicitly confirms the apical pulsed-wave protocol: %s", (method) => {
      const change = vi.fn();
      render(<FelineDiastolicProtocol especie="Gato" medidas={measurements} onMedidaChange={change} />);
      const select = screen.getByLabelText("Aquisição transmitral e TRIV");
      const option = Array.from((select as HTMLSelectElement).options).find((item) => item.value === method)!;
      expect(option.text).toContain("Adulto não sedado");
      expect(option.text).toContain("PW apical esquerdo 4 câmaras");
      expect(screen.getByText(/Ao selecionar o protocolo/)).toHaveTextContent("vista apical esquerda de 4 câmaras");
      expect(screen.getByText(/Ao selecionar o protocolo/)).toHaveTextContent("vista apical esquerda de 5 câmaras");
      expect(screen.getByText(/Ao selecionar o protocolo/)).toHaveTextContent("pontas dos folhetos mitrais");
      fireEvent.change(select, { target: { value: method } });
      expect(change).toHaveBeenCalledWith("Diastolica_metodo", method);
      expect(parseStoredEchoMeasurements({ ...measurements, Diastolica_metodo: method }).Diastolica_metodo).toBe(method);
      expect(measurements.E_A).toBe("1.13");
    });

  it.each(["felino_adulto_nao_sedado_pw_clique_aortico", "felino_adulto_nao_sedado_pw_fim_fluxo"])
    ("keeps old confirmation visible without silently upgrading it: %s", (method) => {
      const change = vi.fn();
      render(<FelineDiastolicProtocol especie="Cat" medidas={{ ...measurements, Diastolica_metodo: method }} onMedidaChange={change} />);
      expect(screen.getByLabelText("Aquisição transmitral e TRIV")).toHaveValue(method);
      expect(screen.getByRole("option", { name: /Protocolo anterior/ })).toBeDisabled();
      expect(screen.getByText(/Reconfirme a vista apical esquerda de 4 câmaras/)).toBeInTheDocument();
      expect(change).not.toHaveBeenCalled();
      expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("separadas");
    });
});
