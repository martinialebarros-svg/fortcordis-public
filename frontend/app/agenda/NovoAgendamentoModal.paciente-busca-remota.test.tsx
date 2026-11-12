import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_AGENDA_SEMANAL } from "@/lib/agenda-config";

const { apiGet, apiPut } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
}));

vi.mock("@/lib/axios", () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: vi.fn(),
    put: (...args: unknown[]) => apiPut(...args),
  },
}));

vi.mock("@/components/fortinho/FortinhoProvider", () => ({
  useFortinho: () => ({ notify: vi.fn(), confirm: vi.fn(async () => false) }),
}));

vi.mock("@/lib/stable-catalog-cache", () => ({
  loadStableCatalog: ({ load }: { load: () => Promise<unknown> }) => load(),
}));

vi.mock("@/lib/credito-cliente", () => ({
  consultarSaldoCreditoCliente: vi.fn(async () => 0),
}));

import NovoAgendamentoModal from "./NovoAgendamentoModal";

const TUTOR = { id: 11, nome: "Maria Souza", telefone: "85999999999", georreferenciado: true };
const PACIENTE_REMOTO = {
  id: 1299,
  nome: "Zelda",
  tutor_id: TUTOR.id,
  tutor: TUTOR.nome,
  especie: "Felina",
  raca: "SRD",
};
const CLINICA = { id: 7, nome: "Sarita Vet Care", latitude: -3.7319, longitude: -38.5267 };
const SERVICO = { id: 3, nome: "Ecocardiograma", duracao_minutos: 30 };
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

let pacientesDoTutor = [PACIENTE_REMOTO];
let respostaDetalhe: Promise<{ data: typeof PACIENTE_REMOTO }> | null = null;

const parametrosPaciente = (url: string, config?: { params?: Record<string, unknown> }) => {
  const parsed = new URL(url, "http://localhost");
  return {
    search: String(config?.params?.search ?? parsed.searchParams.get("search") ?? ""),
    limit: Number(config?.params?.limit ?? parsed.searchParams.get("limit") ?? 100),
    skip: Number(config?.params?.skip ?? parsed.searchParams.get("skip") ?? 0),
    tutorId: Number(config?.params?.tutor_id ?? parsed.searchParams.get("tutor_id") ?? 0),
  };
};

describe("NovoAgendamentoModal - busca remota de animal", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPut.mockReset();
    pacientesDoTutor = [PACIENTE_REMOTO];
    respostaDetalhe = null;

    apiGet.mockImplementation(async (url: string, config?: { params?: Record<string, unknown> }) => {
      if (url === `/pacientes/${PACIENTE_REMOTO.id}`) {
        return respostaDetalhe ?? { data: PACIENTE_REMOTO };
      }
      if (url.startsWith("/pacientes")) {
        const { search, tutorId } = parametrosPaciente(url, config);
        if (search === "Zelda") {
          return { data: { total: 1, total_ativos: 1299, items: [PACIENTE_REMOTO] } };
        }
        if (search === "Inexistente") {
          return { data: { total: 0, total_ativos: 1299, items: [] } };
        }
        if (tutorId === TUTOR.id) {
          return { data: { total: pacientesDoTutor.length, total_ativos: 1299, items: pacientesDoTutor } };
        }
        return {
          data: {
            total: 1299,
            total_ativos: 1299,
            items: Array.from({ length: 1000 }, (_, index) => ({
              id: index + 1,
              nome: `Animal ${index + 1}`,
              tutor_id: 1,
              tutor: "Outro tutor",
              especie: "Canina",
            })),
          },
        };
      }
      if (url === `/tutores/${TUTOR.id}/panorama`) {
        return { data: { tutor: TUTOR, pets: [PACIENTE_REMOTO], resumo: { total_pets: 1 } } };
      }
      if (url.startsWith("/tutores")) return { data: { items: [TUTOR] } };
      if (url.startsWith("/clinicas")) return { data: { items: [CLINICA] } };
      if (url.startsWith("/servicos")) return { data: { items: [SERVICO] } };
      return { data: {} };
    });
    apiPut.mockResolvedValue({ data: RESERVA_EXPIRADA });
  });

  it("encontra e vincula o paciente fora dos primeiros 1000 registros", async () => {
    pacientesDoTutor = [];
    render(
      <NovoAgendamentoModal
        isOpen
        isAdmin
        agendamento={RESERVA_EXPIRADA}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        agendaSemanal={DEFAULT_AGENDA_SEMANAL}
        agendaFeriados={[]}
        agendaExcecoes={[]}
      />
    );

    const labelAnimal = await waitFor(() => {
      const label = Array.from(document.querySelectorAll("label")).find((item) =>
        item.textContent?.includes("Animal")
      );
      if (!label) throw new Error("Campo Animal ainda nao foi renderizado.");
      return label;
    });
    const campoAnimal = labelAnimal.parentElement as HTMLElement;
    fireEvent.click(within(campoAnimal).getByRole("button", { name: "Selecione..." }));
    expect(await within(campoAnimal).findByRole("button", { name: /Animal 1000/ })).toBeInTheDocument();
    const observacoes = screen.getByPlaceholderText("Observações sobre o agendamento...");
    fireEvent.change(observacoes, { target: { value: "Detalhe mantido durante busca" } });
    fireEvent.change(within(campoAnimal).getByPlaceholderText("Buscar animal ou tutor..."), {
      target: { value: "Zelda" },
    });

    await waitFor(() => {
      const buscas = apiGet.mock.calls
        .map(([url, config]) => [url, parametrosPaciente(url, config)] as const)
        .filter(([url, params]) => url.startsWith("/pacientes") && params.search === "Zelda");
      expect(buscas).toHaveLength(1);
      expect(buscas[0][1].limit).toBeLessThanOrEqual(100);
    });

    fireEvent.click(await within(campoAnimal).findByRole("button", { name: /Zelda/ }));
    const gatilhoAnimal = within(campoAnimal).getByRole("button", { name: /Zelda/ });
    expect(gatilhoAnimal).toBeInTheDocument();
    expect(observacoes).toHaveValue("Detalhe mantido durante busca");

    fireEvent.click(gatilhoAnimal);
    fireEvent.change(within(campoAnimal).getByPlaceholderText("Buscar animal ou tutor..."), {
      target: { value: "Inexistente" },
    });
    await waitFor(() => {
      expect(apiGet.mock.calls.some(([url, config]) =>
        url.startsWith("/pacientes") && parametrosPaciente(url, config).search === "Inexistente"
      )).toBe(true);
    });
    expect(await within(campoAnimal).findByText("Nenhum animal encontrado para este tutor.")).toBeInTheDocument();
    fireEvent.click(gatilhoAnimal);
    expect(gatilhoAnimal).toHaveTextContent("Zelda");

    fireEvent.click(screen.getByRole("button", { name: "Salvar dados da reserva" }));
    await waitFor(() => {
      expect(apiPut).toHaveBeenCalledWith(
        `/agenda/${RESERVA_EXPIRADA.id}`,
        expect.objectContaining({
          paciente_id: PACIENTE_REMOTO.id,
          tutor_id: TUTOR.id,
          observacoes: expect.stringContaining("Detalhe mantido durante busca"),
        })
      );
    });
  }, 20_000);

  it("mostra animal fora do lote inicial ao selecionar o tutor, sem digitar", async () => {
    render(
      <NovoAgendamentoModal
        isOpen
        isAdmin
        agendamento={RESERVA_EXPIRADA}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        agendaSemanal={DEFAULT_AGENDA_SEMANAL}
        agendaFeriados={[]}
        agendaExcecoes={[]}
      />
    );

    const campoTutor = await waitFor(() => {
      const label = Array.from(document.querySelectorAll("label")).find((item) =>
        item.textContent?.includes("Tutor")
      );
      if (!label) throw new Error("Campo Tutor ainda nao foi renderizado.");
      return label.parentElement as HTMLElement;
    });
    fireEvent.click(within(campoTutor).getByRole("button", { name: "Selecione..." }));
    fireEvent.click(await within(campoTutor).findByRole("button", { name: /Maria Souza/ }));

    await waitFor(() => {
      const buscas = apiGet.mock.calls
        .map(([url, config]) => [url, parametrosPaciente(url, config)] as const)
        .filter(([url, params]) => url.startsWith("/pacientes") && params.tutorId === TUTOR.id);
      expect(buscas).toHaveLength(1);
      expect(buscas[0][1]).toMatchObject({ skip: 0, limit: 100 });
    });

    const campoAnimal = await waitFor(() => {
      const label = Array.from(document.querySelectorAll("label")).find((item) =>
        item.textContent?.includes("Animal")
      );
      if (!label) throw new Error("Campo Animal ainda nao foi renderizado.");
      return label.parentElement as HTMLElement;
    });
    fireEvent.click(within(campoAnimal).getByRole("button", { name: "Selecione..." }));
    fireEvent.click(await within(campoAnimal).findByRole("button", { name: /Zelda/ }));
    expect(within(campoAnimal).getByRole("button", { name: /Zelda/ })).toBeInTheDocument();
  });

  it("hidrata o animal da edicao fora do lote sem apagar observacoes alteradas", async () => {
    pacientesDoTutor = [];
    let completarDetalhe!: (response: { data: typeof PACIENTE_REMOTO }) => void;
    respostaDetalhe = new Promise((resolve) => { completarDetalhe = resolve; });
    render(
      <NovoAgendamentoModal
        isOpen
        isAdmin
        agendamento={{
          ...RESERVA_EXPIRADA,
          status: "Agendado",
          paciente_id: PACIENTE_REMOTO.id,
          observacoes: "Nota original",
        }}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
        agendaSemanal={DEFAULT_AGENDA_SEMANAL}
        agendaFeriados={[]}
        agendaExcecoes={[]}
      />
    );

    const campoAnimal = await waitFor(() => {
      const label = Array.from(document.querySelectorAll("label")).find((item) =>
        item.textContent?.includes("Animal")
      );
      if (!label) throw new Error("Campo Animal ainda nao foi renderizado.");
      return label.parentElement as HTMLElement;
    });
    const gatilhoAnimal = within(campoAnimal).getByRole("button", { name: "Selecione..." });
    fireEvent.click(gatilhoAnimal);
    expect(await within(campoAnimal).findByRole("button", { name: /Animal 1000/ })).toBeInTheDocument();
    fireEvent.click(gatilhoAnimal);

    const observacoes = screen.getByPlaceholderText("Observações sobre o agendamento...");
    fireEvent.change(observacoes, { target: { value: "Nota editada antes da resposta" } });
    completarDetalhe({ data: PACIENTE_REMOTO });

    await waitFor(() => expect(gatilhoAnimal).toHaveTextContent("Zelda"));
    const campoTutor = Array.from(document.querySelectorAll("label")).find((item) =>
      item.textContent?.includes("Tutor")
    )?.parentElement as HTMLElement;
    expect(within(campoTutor).getByRole("button", { name: /Maria Souza/ })).toBeInTheDocument();
    expect(observacoes).toHaveValue("Nota editada antes da resposta");
  }, 20_000);
});
