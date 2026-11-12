import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MesclagensPacientesPage from "./page";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../../layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("@/lib/axios", () => ({ default: mocks }));

const rota = "/pacientes/mesclagens";
const par = { principal_id: 10, secundario_id: 20 };
const previa = {
  principal: { id: 10, nome: "Pet antigo", tutor: "Tutor de teste" },
  secundario: { id: 20, nome: "Pet novo", tutor: "Tutor de teste" },
  bloqueios: [],
  token_previa: "a".repeat(64),
  vinculos: {
    exames: { principal: 0, secundario: 1 }, laudos: { principal: 0, secundario: 1 },
    atendimentos_clinicos: { principal: 0, secundario: 1 },
  },
  registros: {
    exames: [{ id: 31, paciente_id: 20, tipo_exame: "Ecocardiograma", status: "Concluído", data_solicitacao: "2026-11-07T02:30:00Z" }],
    laudos: [{ id: 32, paciente_id: 20, titulo: "Laudo de teste", status: "Finalizado", data_exame: "2026-11-06 00:00:00" }],
    atendimentos_clinicos: [{ id: 33, paciente_id: 20, status: "Concluído" }],
  },
};
const registro = { ...par, id: 8, estado: "pendente", criado_por: "Admin teste", criado_em: "2026-11-06T10:00:00Z" };

async function escolherSecundario() {
  const input = await screen.findByLabelText("Código do cadastro secundário");
  expect(screen.getByLabelText("Código do cadastro principal")).toHaveValue("10");
  fireEvent.change(input, { target: { value: "20" } });
}

describe("Revisão de duplicidade de pacientes", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.history.replaceState({}, "", "/pacientes/mesclagens?paciente=10");
    mocks.get.mockResolvedValue({ data: { items: [], tem_mais: false } });
    mocks.post.mockResolvedValue({ data: previa });
  });

  it("abre com o paciente do Atendimento e guarda a dupla sem confirmar nem gerar prévia", async () => {
    render(<MesclagensPacientesPage />);
    await escolherSecundario();
    expect(mocks.post).not.toHaveBeenCalled();
    mocks.post.mockResolvedValue({ data: registro });
    fireEvent.click(screen.getByRole("button", { name: "Guardar para revisar depois" }));
    expect(await screen.findByText(/Revisão guardada/)).toBeInTheDocument();
    expect(mocks.post.mock.calls).toEqual([[`${rota}/adiar`, par]]);
  });

  it("retoma a revisão, lista exames, laudos e consultas, e confirma só com motivo e aceite", async () => {
    mocks.get.mockImplementation((_url, config) => Promise.resolve({ data: { items: [
      config.params.estado === "historico" ? { ...registro, estado: "concluida", motivo: "Conferido com o tutor",
        confirmado_por: "Admin teste", confirmado_em: "2026-11-06T10:30:00Z",
        evidencia: { principal: previa.principal, secundario: previa.secundario, movidos: { exames: [31] } } } : registro,
    ], tem_mais: false } }));
    render(<MesclagensPacientesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retomar revisão #8" }));
    const panel = await screen.findByRole("region", { name: "Prévia da mesclagem de pacientes" });
    expect(within(panel).getByText("#31 Ecocardiograma")).toBeInTheDocument();
    expect(within(panel).getByText("#32 Laudo de teste")).toBeInTheDocument();
    expect(within(panel).getByText("#33")).toBeInTheDocument();
    expect(within(panel).getByText(/Solicitação: 06\/11\/2026/)).toBeInTheDocument();
    expect(within(panel).getByText(/Exame: 06\/11\/2026/)).toBeInTheDocument();
    const confirmar = screen.getByRole("button", { name: "Confirmar mesclagem" });
    expect(confirmar).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Motivo da mesclagem"), { target: { value: "Conferido com o tutor" } });
    expect(confirmar).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Confirmei que é o mesmo animal/ }));
    fireEvent.click(confirmar);
    await waitFor(() => expect(mocks.post).toHaveBeenLastCalledWith(`${rota}/confirmar`, {
      ...par, token_previa: previa.token_previa, motivo: "Conferido com o tutor", confirmar: true,
    }));
    expect(await screen.findByText("Motivo: Conferido com o tutor")).toBeInTheDocument();
    expect(screen.getByText("Exames: #31")).toBeInTheDocument();
  });

  it("permite guardar a revisão mesmo quando uma consulta em aberto bloqueia a mesclagem", async () => {
    mocks.post.mockResolvedValue({ data: { ...previa, bloqueios: ["Há atendimento em aberto."] } });
    render(<MesclagensPacientesPage />);
    await escolherSecundario();
    fireEvent.click(screen.getByRole("button", { name: "Comparar cadastros" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("atendimento em aberto");
    expect(screen.getByRole("button", { name: "Confirmar mesclagem" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Guardar para revisar depois" })).toBeEnabled();
  });

  it("não exibe controles nem registros quando o servidor recusa acesso", async () => {
    mocks.get.mockRejectedValue({ response: { status: 403 } });
    render(<MesclagensPacientesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Somente administradores");
    expect(screen.queryByRole("button", { name: "Comparar cadastros" })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
