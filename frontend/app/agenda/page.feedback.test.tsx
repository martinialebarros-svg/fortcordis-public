import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiGet, apiPatch, apiPost, router, fortinho } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  apiPost: vi.fn(),
  router: { push: vi.fn() },
  fortinho: { confirm: vi.fn(async () => false), notify: vi.fn() },
}));

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("../layout-dashboard", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("./NovoAgendamentoModal", () => ({ default: () => null }));
vi.mock("./ClienteInfoModal", () => ({ default: () => null }));
vi.mock("@/lib/axios", () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    patch: (...args: unknown[]) => apiPatch(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}));
vi.mock("@/lib/useAgendaRealtime", () => ({
  useAgendaRealtime: () => ({ conectado: true, ultimoEvento: null }),
}));
vi.mock("@/components/fortinho/FortinhoProvider", () => ({
  useFortinho: () => fortinho,
}));

import AgendaPage from "./page";

const reservaExpirada = {
  id: 91,
  status: "Expirado",
  paciente_id: null,
  tutor_id: null,
  paciente: null,
  tutor: null,
  clinica: "Clinica Teste",
  servico: "Ecocardiograma",
  inicio: "2099-05-25T11:00:00",
  fim: "2099-05-25T11:30:00",
  data: "2099-05-25",
  hora: "11:00",
  observacoes: null,
};
type AgendamentoTeste = Omit<typeof reservaExpirada, "paciente_id" | "tutor_id" | "paciente"> & {
  paciente_id: number | null;
  tutor_id: number | null;
  paciente: string | null;
};
let agendamentos: AgendamentoTeste[] = [reservaExpirada];

describe("avisos da Agenda", () => {
  beforeEach(() => {
    agendamentos = [reservaExpirada];
    window.history.replaceState(null, "", "/agenda?data=2099-05-25");
    localStorage.setItem("token", "test-token");
    apiGet.mockReset();
    apiPatch.mockReset();
    apiPost.mockReset();
    fortinho.confirm.mockClear();
    fortinho.notify.mockClear();
    apiGet.mockImplementation(async (url: string) => {
      if (url.startsWith("/agenda?")) return { data: { items: agendamentos } };
      return { data: {} };
    });
  });

  it("mostra a falha de confirmação tardia na viewport e acima do modal de reabilitação", async () => {
    const erroConsole = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(<AgendaPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Agendar após confirmação tardia" }));

      const aviso = screen.getByRole("alert");
      expect(aviso).toHaveTextContent("Antes de confirmar tardiamente");
      expect(aviso.parentElement).toHaveClass("fixed", "z-[80]");
      expect(screen.getByRole("button", { name: "Fechar aviso de erro" })).toBeInTheDocument();
      expect(apiPatch).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "Reabilitar reserva" }));
      apiPost.mockRejectedValueOnce({ response: { data: { detail: "Horario indisponivel" } } });
      fireEvent.click(screen.getAllByRole("button", { name: "Reabilitar reserva" }).at(-1)!);

      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Horario indisponivel"));
      expect(screen.getByText("Reabilitar reserva", { selector: "h3" })).toBeInTheDocument();
    } finally {
      erroConsole.mockRestore();
    }
  });

  it("remove o erro anterior ao iniciar outra tentativa de agendar", async () => {
    agendamentos = [
      reservaExpirada,
      {
        ...reservaExpirada,
        id: 92,
        paciente_id: 21,
        tutor_id: 11,
        clinica: "Outra Clinica",
      },
    ];
    let concluirAtualizacao: ((value: { data: object }) => void) | undefined;
    apiPatch.mockImplementation(
      () => new Promise((resolve) => { concluirAtualizacao = resolve; })
    );
    render(<AgendaPage />);
    const botoes = await screen.findAllByRole("button", { name: "Agendar após confirmação tardia" });
    fireEvent.click(botoes[0]);
    expect(screen.getByRole("alert")).toHaveTextContent("Antes de confirmar tardiamente");

    fireEvent.click(botoes[1]);
    await waitFor(() => expect(apiPatch).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(async () => { concluirAtualizacao?.({ data: {} }); });
  });

  it("separa o status atual das ações e mantém o destino do botão Cancelar", async () => {
    agendamentos = [{
      ...reservaExpirada,
      id: 93,
      status: "Agendado",
      paciente: "Paciente exemplo",
    }];
    apiPatch.mockResolvedValue({ data: {} });

    render(<AgendaPage />);

    const statusAtual = await screen.findByText("Status atual: Agendado");
    expect(statusAtual.closest("button")).toBeNull();

    const grupo = screen.getByRole("group", { name: "Alterar status do agendamento de Paciente exemplo" });
    expect(within(grupo).getAllByRole("button").map((botao) => botao.textContent?.trim())).toEqual([
      "Reservar", "Confirmar", "Cancelar", "Marcar Falta",
    ]);
    expect(within(grupo).queryByRole("button", { name: "Cancelado" })).not.toBeInTheDocument();

    fireEvent.click(within(grupo).getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(apiPatch).toHaveBeenCalledWith("/agenda/93/status?status=Cancelado"));
  });
});
