import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FelineWaveReview from "./FelineWaveReview";

describe("revisão compacta das ondas felinas", () => {
  it("mantém estados desconhecidos e não descarta números ao escolher uma separação", () => {
    const onMedidaChange = vi.fn();
    const onDiscard = vi.fn();
    render(<FelineWaveReview especie="Gato" medidas={{ E_A: "1.14" }} onMedidaChange={onMedidaChange} onDiscard={onDiscard} />);
    expect(screen.getByLabelText("Ondas transmitrais E/A")).toHaveValue("");
    expect(screen.getByLabelText("Ondas teciduais e'/a'")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: "fundidas" } });
    expect(onMedidaChange).toHaveBeenCalledExactlyOnceWith("Diastolica_ondas", "fundidas");
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it.each([
    { key: "Diastolica_ondas", kind: "transmitral", button: "Remover medidas de E/A fundidas" },
    { key: "TDI_ondas", kind: "tissue", button: "Remover medidas de TDI fundidas" },
  ])("descarta somente por ação explícita: $kind", ({ key, kind, button }) => {
    const onDiscard = vi.fn();
    render(<FelineWaveReview especie="Cat" medidas={{ [key]: "fundidas" }} onMedidaChange={vi.fn()} onDiscard={onDiscard} />);
    expect(screen.getByRole("status")).toHaveTextContent(/não serão apresentados como valores mensuráveis no PDF/);
    expect(onDiscard).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(onDiscard).toHaveBeenCalledExactlyOnceWith(kind);
  });

  it("não oferece descarte felino no paciente canino", () => {
    render(<FelineWaveReview especie="Canina" medidas={{ Diastolica_ondas: "fundidas" }} onMedidaChange={vi.fn()} onDiscard={vi.fn()} />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
