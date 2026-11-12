import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_AGENDA_SEMANAL } from "@/lib/agenda-config";

const { apiGet, apiPost, notify } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), notify: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: { get: apiGet, post: apiPost, put: vi.fn() } }));
vi.mock("@/components/fortinho/FortinhoProvider", () => ({ useFortinho: () => ({ notify, confirm: vi.fn() }) }));
vi.mock("@/lib/stable-catalog-cache", () => ({ loadStableCatalog: ({ load }: { load: () => Promise<unknown> }) => load() }));
vi.mock("@/lib/credito-cliente", () => ({ consultarSaldoCreditoCliente: vi.fn(async () => 0) }));
import NovoAgendamentoModal from "./NovoAgendamentoModal";

const tutor = { id: 184, nome: "Cristiane", identificacao_pendente: true, origem_cadastro: "Clínica Alfa" };
const reserva = { id: 91, status: "Reservado", paciente_id: null, tutor_id: null, clinica_id: 7,
  clinica: "Clínica Alfa", servico_id: 3, servico: "Ecocardiograma", origem_atendimento: "clinica_parceira",
  inicio: "2099-05-25T11:00:00", fim: "2099-05-25T11:30:00" };

beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear();
  apiGet.mockImplementation(async (url: string) => {
    if (url.includes("/panorama")) return { data: { tutor, pets: [], resumo: { total_pets: 0 } } };
    if (url.startsWith("/tutores")) return { data: { items: [tutor] } };
    if (url.startsWith("/clinicas")) return { data: { items: [{ id: 7, nome: "Clínica Alfa", latitude: -3.7, longitude: -38.5 }] } };
    if (url.startsWith("/servicos")) return { data: { items: [{ id: 3, nome: "Ecocardiograma", duracao_minutos: 30 }] } };
    if (url.startsWith("/pacientes")) return { data: { items: [] } };
    return { data: {} };
  });
});

describe("cadastro ágil na Agenda", () => {
  it("salva só nomes, repete com a mesma chave e cria pet usando o ID escolhido", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/tutores") return { data: tutor };
      if (url === "/pacientes") return { data: { id: 210, nome: "Pingo", tutor_id: tutor.id, especie: null, sexo: null } };
      return { data: {} };
    });
    render(<NovoAgendamentoModal isOpen isAdmin agendamento={reserva} onClose={vi.fn()} onSuccess={vi.fn()} agendaSemanal={DEFAULT_AGENDA_SEMANAL} agendaFeriados={[]} agendaExcecoes={[]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Novo tutor" }));
    const dialog = screen.getByRole("dialog", { name: "Cadastrar Tutor" });
    fireEvent.change(within(dialog).getByPlaceholderText("Nome do tutor"), { target: { value: "Cristiane" } });
    expect(within(dialog).getByText("Contato e documento — preencher se disponíveis").closest("details")).not.toHaveAttribute("open");
    apiPost.mockRejectedValueOnce(new Error("resposta perdida"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Criar Tutor" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Criar Tutor" })).not.toBeDisabled());
    fireEvent.click(within(dialog).getByRole("button", { name: "Criar Tutor" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Cadastrar Tutor" })).not.toBeInTheDocument());
    const attempts = apiPost.mock.calls.filter(([url]) => url === "/tutores");
    expect(attempts).toHaveLength(2);
    expect(attempts[0][1]).toMatchObject({ nome: "Cristiane", identificacao_pendente: true, telefone: null, cpf: null });
    expect(attempts[0][1].chave_operacao).toBe(attempts[1][1].chave_operacao);
    fireEvent.click(screen.getByRole("button", { name: "Novo animal" }));
    const animal = screen.getByRole("dialog", { name: "Cadastrar Animal" });
    fireEvent.change(within(animal).getByPlaceholderText("Nome do animal"), { target: { value: "Pingo" } });
    fireEvent.click(within(animal).getByRole("button", { name: "Salvar Animal" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/pacientes", expect.objectContaining({ nome: "Pingo", tutor_id: 184, especie: null, sexo: null, chave_operacao: expect.any(String) })));
    expect(apiPost.mock.calls.find(([url]) => url === "/pacientes")?.[1]).not.toHaveProperty("tutor");
    expect(apiGet.mock.calls.some(([url]) => String(url).includes("duplicidades"))).toBe(false);
  });
});
