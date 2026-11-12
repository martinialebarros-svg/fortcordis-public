import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EchoUnitReview from "./EchoUnitReview";

describe("conferência de unidade legada", () => {
  it("não adiciona controles aos laudos com medidas usuais em mm", () => {
    const { container } = render(<EchoUnitReview measurements={{ DIVEd: "35", SIVd: "8", PLVEd: "9" }} onConfirm={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("exige escolha individual e permite retirar uma confirmação", () => {
    const onConfirm = vi.fn();
    render(<EchoUnitReview measurements={{ DIVEd: "2.5", SIVd: "3.0", PLVEd: "0.8", unidade_confirmada_DIVEd: "cm" }} onConfirm={onConfirm} />);
    expect(screen.getByRole("combobox", { name: "Unidade de DIVEd" })).toHaveValue("cm");
    fireEvent.change(screen.getByRole("combobox", { name: "Unidade de SIVd" }), { target: { value: "mm" } });
    expect(onConfirm).toHaveBeenCalledWith("SIVd", "mm");
    fireEvent.change(screen.getByRole("combobox", { name: "Unidade de DIVEd" }), { target: { value: "" } });
    expect(onConfirm).toHaveBeenCalledWith("DIVEd", "");
  });
});
