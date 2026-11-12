import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { PatientAgeFields } from "./PatientAgeFields";
import { patientAgeForm } from "@/lib/paciente-idade";

function Form() {
  const [value, setValue] = useState(patientAgeForm({ data_nascimento: "2020-05-03", idade_fonte: "nascimento", idade_informada: "12 anos", idade_referencia: "2025-01-31" }));
  return <PatientAgeFields value={value} referenceDate="2026-11-04" onChange={setValue} />;
}
describe("campos independentes", () => {
  it("alterna origem sem apagar alternativa nem mover a data da idade original", () => {
    render(<Form />);
    expect(screen.getByLabelText("Data de nascimento ou ano")).toHaveValue("03/05/2020");
    fireEvent.click(screen.getByRole("button", { name: "Usar idade informada" }));
    expect(screen.getByText(/Idade informada em 31\/01\/2025/)).toBeInTheDocument();
    expect(screen.getByText("13a 9m (estimada)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Idade informada"), { target: { value: "8 meses" } });
    expect(screen.getByText("8m (estimada)")).toBeInTheDocument();
    expect(screen.getByLabelText("Data de nascimento ou ano")).toHaveValue("03/05/2020");
    expect(screen.getByText(/Idade informada em 04\/11\/2026/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Data de nascimento ou ano"), { target: { value: "2014" } });
    expect(screen.getByText("11–12 anos (estimada pelo ano)")).toBeInTheDocument();
    expect(screen.getByLabelText("Idade informada")).toHaveValue("8 meses");
  });
});
