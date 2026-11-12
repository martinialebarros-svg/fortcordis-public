import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_AGENDA_SEMANAL } from "@/lib/agenda-config";

const { apiGet, apiPost, apiPut, fortinhoNotify, fortinhoConfirm } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  fortinhoNotify: vi.fn(),
  fortinhoConfirm: vi.fn(async () => false),
}));

vi.mock("@/lib/axios", () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    put: (...args: unknown[]) => apiPut(...args),
  },
}));

vi.mock("@/components/fortinho/FortinhoProvider", () => ({
  useFortinho: () => ({
    notify: fortinhoNotify,
    confirm: fortinhoConfirm,
  }),
}));

vi.mock("@/lib/stable-catalog-cache", () => ({
  loadStableCatalog: ({ load }: { load: () => Promise<unknown> }) => load(),
}));

vi.mock("@/lib/credito-cliente", () => ({
  consultarSaldoCreditoCliente: vi.fn(async () => 0),
}));

import NovoAgendamentoModal from "./NovoAgendamentoModal";

const TUTOR = {
  id: 11,
  nome: "Maria Souza",
  telefone: "85999999999",
  georreferenciado: true,
  pets: [{ id: 21, nome: "Rex" }],
};

const PACIENTE = {
  id: 21,
  nome: "Rex",
  tutor_id: 11,
  tutor: "Maria Souza",
  especie: "Canina",
};

const CLINICA = {
  id: 7,
  nome: "Sarita Vet Care",
  latitude: -3.7319,
  longitude: -38.5267,
};

const SERVICO = {
  id: 3,
  nome: "Ecocardiograma",
  duracao_minutos: 30,
};

const RESERVA_EXPIRADA = {
  id: 91,
  status: "Expirado",
  paciente_id: null,
  tutor_id: null,
  paciente: "Paciente nao informado",
  tutor: "Tutor nao informado",
  clinica_id: CLINICA.id,
  clinica: CLINICA.nome,
  servico_id: SERVICO.id,
  servico: SERVICO.nome,
  origem_atendimento: "clinica_parceira",
  inicio: "2099-05-25T11:00:00",
  fim: "2099-05-25T11:30:00",
  observacoes: "Reserva aguardando confirmacao tardia",
};

const localizarCampo = async (nome: "Tutor" | "Animal") => {
  const label = await waitFor(() => {
    const encontrado = Array.from(document.querySelectorAll("label")).find((item) =>
      item.textContent?.includes(nome)
    );
    if (!encontrado) throw new Error(`Campo ${nome} ainda nao foi renderizado.`);
    return encontrado;
  });
  return label.parentElement as HTMLElement;
};

const renderizarReserva = (onSuccess = vi.fn(), onClose = vi.fn()) =>
  render(
    <NovoAgendamentoModal
      isOpen
      isAdmin
      agendamento={RESERVA_EXPIRADA}
      onClose={onClose}
      onSuccess={onSuccess}
      agendaSemanal={DEFAULT_AGENDA_SEMANAL}
      agendaFeriados={[]}
      agendaExcecoes={[]}
    />
  );

describe("NovoAgendamentoModal - reserva expirada", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    apiPut.mockReset();
    fortinhoNotify.mockReset();
    fortinhoConfirm.mockClear();

    apiGet.mockImplementation(async (url: string) => {
      if (url === `/tutores/${TUTOR.id}/panorama`) {
        return {
          data: {
            tutor: TUTOR,
            pets: [PACIENTE],
            resumo: { total_pets: 1 },
          },
        };
      }
      if (url.startsWith("/pacientes")) return { data: { items: [PACIENTE] } };
      if (url.startsWith("/tutores")) return { data: { items: [TUTOR] } };
      if (url.startsWith("/clinicas")) return { data: { items: [CLINICA] } };
      if (url.startsWith("/servicos")) return { data: { items: [SERVICO] } };
      return { data: {} };
    });
    apiPost.mockResolvedValue({ data: {} });
    apiPut.mockResolvedValue({ data: { ...RESERVA_EXPIRADA } });
  });

  it("explica que a busca nao vincula o cadastro sem escolher um resultado", async () => {
    renderizarReserva();

    expect(
      await screen.findByRole("region", { name: "Como concluir a confirmação tardia" })
    ).toHaveTextContent("Digitar um nome sem escolher o resultado não vincula o cadastro");
    expect(screen.queryByText("Tutor selecionado:")).not.toBeInTheDocument();

    const campoTutor = await localizarCampo("Tutor");
    const seletorTutor = within(campoTutor).getByRole("button", { name: "Selecione..." });
    fireEvent.click(seletorTutor);
    fireEvent.change(screen.getByPlaceholderText("Buscar tutor por nome ou telefone..."), {
      target: { value: "Maria" },
    });

    expect(seletorTutor).toHaveTextContent("Selecione...");
    expect(
      screen.getByText(/O texto digitado sozinho não seleciona o cadastro/)
    ).toBeInTheDocument();
  });

  it("salva os IDs selecionados e orienta a confirmacao tardia como proxima etapa", async () => {
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    renderizarReserva(onSuccess, onClose);

    const campoTutor = await localizarCampo("Tutor");
    fireEvent.click(within(campoTutor).getByRole("button", { name: "Selecione..." }));
    fireEvent.click(await within(campoTutor).findByRole("button", { name: /Maria Souza/ }));

    const campoAnimal = await localizarCampo("Animal");
    fireEvent.click(within(campoAnimal).getByRole("button", { name: "Selecione..." }));
    fireEvent.click(await within(campoAnimal).findByRole("button", { name: /Rex/ }));

    fireEvent.click(screen.getByRole("button", { name: "Salvar dados da reserva" }));

    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledWith(
        `/agenda/${RESERVA_EXPIRADA.id}`,
        expect.objectContaining({
          paciente_id: PACIENTE.id,
          tutor_id: TUTOR.id,
          status: "Expirado",
        })
      );
    });
    expect(onSuccess).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
    expect(fortinhoNotify).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Dados da reserva atualizados",
        message: expect.stringContaining("Agendar após confirmação tardia"),
      })
    );
  });

  it.each(["limite de custo", "cancelamento da consulta"])("mantém o formulário preenchido após %s", async (kind) => {
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    apiPut.mockRejectedValue({
      code: kind === "cancelamento da consulta" ? "ERR_CANCELED" : "GOOGLE_MAPS_ACTION_BLOCKED",
      response: { status: 409, data: { detail: "Consulta de rota suspensa; revise os limites." } },
    });
    renderizarReserva(onSuccess, onClose);
    const campoTutor = await localizarCampo("Tutor");
    fireEvent.click(within(campoTutor).getByRole("button", { name: "Selecione..." }));
    fireEvent.click(await within(campoTutor).findByRole("button", { name: /Maria Souza/ }));
    const campoAnimal = await localizarCampo("Animal");
    fireEvent.click(within(campoAnimal).getByRole("button", { name: "Selecione..." }));
    fireEvent.click(await within(campoAnimal).findByRole("button", { name: /Rex/ }));
    fireEvent.click(screen.getByRole("button", { name: "Salvar dados da reserva" }));
    await waitFor(() => expect(fortinhoNotify).toHaveBeenCalled());
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(within(campoTutor).getByRole("button", { name: /Maria Souza/ })).toBeVisible();
    expect(within(campoAnimal).getByRole("button", { name: /Rex/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "Salvar dados da reserva" })).toBeEnabled();
  });

});
