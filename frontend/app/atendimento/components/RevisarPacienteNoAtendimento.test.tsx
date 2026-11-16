import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import RevisarPacienteNoAtendimento from "./RevisarPacienteNoAtendimento";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: mocks }));

function Consulta() {
  const [queixa, setQueixa] = useState("");
  return <>
    <textarea aria-label="Queixa da consulta" value={queixa} onChange={(event) => setQueixa(event.target.value)} />
    <RevisarPacienteNoAtendimento pacienteId="31" nome="Animal de teste" />
  </>;
}

it("compara e guarda a duplicidade no diálogo preservando a consulta sem salvar", async () => {
  // jsdom não abre diálogos na camada modal do navegador.
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true; } },
    close: { configurable: true, value(this: HTMLDialogElement) {
      this.open = false;
      this.dispatchEvent(new Event("close"));
    } },
  });
  mocks.get.mockResolvedValue({ data: { items: [], tem_mais: false } });
  mocks.post.mockResolvedValueOnce({ data: {
    principal: { id: 31, nome: "Animal de teste" },
    secundario: { id: 32, nome: "Outro cadastro" },
    bloqueios: [], registros: {}, vinculos: {}, token_previa: "a".repeat(64),
  } });
  mocks.post.mockResolvedValueOnce({ data: { estado: "pendente" } });

  render(<Consulta />);
  const queixa = screen.getByRole("textbox", { name: "Queixa da consulta" });
  fireEvent.change(queixa, { target: { value: "Texto ainda não salvo" } });
  fireEvent.click(screen.getByRole("button", { name: "Revisar duplicidade" }));
  const dialog = screen.getByRole("dialog", { name: "Revisar duplicidade do paciente" });
  const painel = within(dialog);
  expect(await painel.findByLabelText("Código do cadastro principal")).toHaveValue("31");
  expect(painel.getByLabelText(/Buscar paciente/)).toHaveValue("Animal de teste");
  fireEvent.change(painel.getByLabelText("Código do cadastro secundário"), { target: { value: "32" } });
  fireEvent.click(painel.getByRole("button", { name: "Comparar cadastros" }));
  expect(await painel.findByRole("heading", { name: "Prévia da mesclagem" })).toBeInTheDocument();
  expect(painel.queryByRole("button", { name: "Confirmar mesclagem" })).not.toBeInTheDocument();

  fireEvent.click(painel.getByRole("button", { name: "Guardar para revisar depois" }));
  expect(await painel.findByText(/Revisão guardada/)).toBeInTheDocument();
  expect(mocks.post.mock.calls).toEqual([
    ["/pacientes/mesclagens/previa", { principal_id: 31, secundario_id: 32 }],
    ["/pacientes/mesclagens/adiar", { principal_id: 31, secundario_id: 32 }],
  ]);
  fireEvent.click(painel.getByRole("button", { name: "Voltar ao atendimento" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(queixa).toHaveValue("Texto ainda não salvo");
});
