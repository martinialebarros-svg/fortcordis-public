import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgendaDayOpportunities from "./AgendaDayOpportunities";

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/axios", () => ({ default: apiMock }));

const catalogo = { data: { total: 2, items: [
  { id: 1, nome: "Ecocardiograma", duracao_minutos: 30, ativo: true },
  { id: 2, nome: "Eletrocardiograma", duracao_minutos: 20, ativo: true },
] } };

function oportunidade(clinica = "Clínica recorrente", id = 1) {
  return {
    clinica_id: id,
    clinica,
    cidade: "Fortaleza",
    bairro: "Centro",
    dias_realizados_60d: 19,
    atendimentos_realizados_60d: 36,
    ultimo_atendimento: "2026-10-21",
    inicio: "2026-10-23 10:30",
    fim: "2026-10-23 11:00",
    tempo_deslocamento_total_min: 42,
    transicao_regional: true,
    fonte_estimativa: "cache",
    estimativa_atualizada_em: "2026-10-21",
  };
}

function resposta(items = [oportunidade()]) {
  return { data: {
    ok: true,
    enabled: true,
    items,
    historico: { inicio: "2026-08-23", fim: "2026-10-21", dias: 60 },
    sem_estimativa: 2,
    total_clinicas_recorrentes: 69,
  } };
}

function pendente<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((aceitar, recusar) => { resolve = aceitar; reject = recusar; });
  return { promise, resolve, reject };
}

async function abrirESelecionarServico() {
  fireEvent.click(screen.getByRole("button", { name: "Completar dia" }));
  await screen.findByRole("option", { name: "Ecocardiograma (30 min)" });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "1" } });
}

describe("AgendaDayOpportunities", () => {
  beforeEach(() => {
    apiMock.get.mockReset().mockResolvedValue(catalogo);
    apiMock.post.mockReset();
  });

  it("consulta somente após escolha e clique e preserva a ordem e recorrência recebidas", async () => {
    const primeira = oportunidade("Mais dias de atendimento", 1);
    const segunda = { ...oportunidade("Maior volume em poucos dias", 2), dias_realizados_60d: 2, atendimentos_realizados_60d: 40 };
    apiMock.post.mockResolvedValue(resposta([primeira, segunda]));
    render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);

    expect(apiMock.get).not.toHaveBeenCalled();
    expect(apiMock.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Completar dia" }));
    expect(screen.getByRole("button", { name: "Consultar oportunidades" })).toBeDisabled();
    await screen.findByRole("option", { name: "Ecocardiograma (30 min)" });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "1" } });
    expect(apiMock.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));

    await screen.findByText("Mais dias de atendimento");
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    expect(apiMock.post).toHaveBeenCalledWith("/agenda/oportunidades-dia", { data: "2026-10-23", servico_id: 1, limite: null }, expect.objectContaining({ signal: expect.any(AbortSignal), timeout: 45_000 }));
    const items = screen.getAllByRole("listitem");
    expect(within(items[0]).getByText("Mais dias de atendimento")).toBeInTheDocument();
    expect(within(items[1]).getByText("Maior volume em poucos dias")).toBeInTheDocument();
    expect(within(items[0]).getByText(/19 dias com atendimentos · 36 atendimentos realizados/)).toBeInTheDocument();
    expect(within(items[1]).getByText(/2 dias com atendimentos · 40 atendimentos realizados/)).toBeInTheDocument();
    expect(within(items[0]).getByText(/42 min estimados · estimativa de 21\/10\/2026/)).toBeInTheDocument();
    expect(within(items[0]).getByText(/viagem de até 50 min e margem total de pelo menos 15 min/)).toBeInTheDocument();
    expect(screen.getByText(/2 clínicas ficaram sem avaliação/)).toBeInTheDocument();
    expect(screen.getByText(/Os horários são sugestões, sem reserva/)).toBeInTheDocument();
  });

  it.each([31, 61])("exibe todas as %i clínicas com seus horários, na ordem recebida e sem reservar", async (total) => {
    const oportunidades = Array.from({ length: total }, (_, index) => ({
      ...oportunidade(`Clínica ${index + 1}`, index + 1),
      inicio: index === total - 1 ? "2026-10-23 15:00" : "2026-10-23 12:15",
      fim: index === total - 1 ? "2026-10-23 15:30" : "2026-10-23 12:45",
    }));
    apiMock.post.mockResolvedValue(resposta(oportunidades));
    render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);
    await abrirESelecionarServico();
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));

    expect(await screen.findByText(`${total} clínicas com horários disponíveis.`)).toBeInTheDocument();
    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(total);
    oportunidades.forEach((item, index) => {
      expect(within(cards[index]).getByText(item.clinica)).toBeInTheDocument();
      expect(within(cards[index]).getByText(index === total - 1 ? "15:00–15:30" : "12:15–12:45")).toBeInTheDocument();
    });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.post).toHaveBeenCalledWith("/agenda/oportunidades-dia", { data: "2026-10-23", servico_id: 1, limite: null }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(within(screen.getByRole("region", { name: "Oportunidades para completar o dia" })).getAllByRole("button")).toHaveLength(2);
    expect(screen.getByText(/Os horários são sugestões, sem reserva/)).toBeInTheDocument();
  });

  it("aborta e ignora uma resposta da data anterior mesmo quando o transporte resolve depois", async () => {
    const antiga = pendente<ReturnType<typeof resposta>>();
    const atual = pendente<ReturnType<typeof resposta>>();
    apiMock.post.mockReturnValueOnce(antiga.promise).mockReturnValueOnce(atual.promise);
    const { rerender } = render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);
    await abrirESelecionarServico();
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));
    const sinalAntigo = apiMock.post.mock.calls[0][2].signal as AbortSignal;

    rerender(<AgendaDayOpportunities data="2026-10-24" identityKey="usuario-1" />);
    expect(sinalAntigo.aborted).toBe(true);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));
    await act(async () => { atual.resolve(resposta([oportunidade("Resultado do dia atual")])); });
    await act(async () => { antiga.resolve(resposta([oportunidade("Resultado atrasado")])); });

    expect(screen.getByText("Resultado do dia atual")).toBeInTheDocument();
    expect(screen.queryByText("Resultado atrasado")).not.toBeInTheDocument();
    expect(apiMock.post.mock.calls[1][1].data).toBe("2026-10-24");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("limpa sugestões e cancela a consulta ao trocar o serviço, sem consultar automaticamente", async () => {
    const antiga = pendente<ReturnType<typeof resposta>>();
    apiMock.post.mockReturnValue(antiga.promise);
    render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);
    await abrirESelecionarServico();
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));
    const sinal = apiMock.post.mock.calls[0][2].signal as AbortSignal;
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2" } });
    await act(async () => { antiga.resolve(resposta([oportunidade("Serviço anterior")])); });

    expect(sinal.aborted).toBe(true);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Serviço anterior")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Consultar oportunidades" })).toBeEnabled();
  });

  it("descarta catálogo e consulta ao mudar a identidade", async () => {
    const antiga = pendente<ReturnType<typeof resposta>>();
    apiMock.post.mockReturnValue(antiga.promise);
    const { rerender } = render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);
    await abrirESelecionarServico();
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));
    const sinal = apiMock.post.mock.calls[0][2].signal as AbortSignal;
    rerender(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-2" />);
    await act(async () => { antiga.resolve(resposta([oportunidade("Resultado de outra sessão")])); });

    expect(sinal.aborted).toBe(true);
    expect(screen.queryByText("Resultado de outra sessão")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    await abrirESelecionarServico();
    expect(apiMock.get).toHaveBeenCalledTimes(2);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
  });

  it("permite repetir somente a consulta que falhou, mantendo data e serviço", async () => {
    apiMock.post.mockRejectedValueOnce(new Error("indisponível")).mockResolvedValueOnce(resposta());
    render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);
    await abrirESelecionarServico();
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível consultar as oportunidades deste dia.");
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("combobox")).toHaveValue("1");
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await screen.findByText("Clínica recorrente");

    expect(apiMock.post).toHaveBeenCalledTimes(2);
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    expect(apiMock.post.mock.calls[0][1]).toEqual(apiMock.post.mock.calls[1][1]);
  });

  it("permite repetir a leitura do catálogo sem disparar consulta de oportunidades", async () => {
    apiMock.get.mockRejectedValueOnce(new Error("indisponível")).mockResolvedValueOnce(catalogo);
    render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Completar dia" }));
    await screen.findByText("Não foi possível carregar os serviços.");
    fireEvent.click(screen.getByRole("button", { name: "Tentar carregar serviços novamente" }));
    await screen.findByRole("option", { name: "Ecocardiograma (30 min)" });

    expect(apiMock.get).toHaveBeenCalledTimes(2);
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("aborta a consulta ao desmontar", async () => {
    const consulta = pendente<ReturnType<typeof resposta>>();
    apiMock.post.mockReturnValue(consulta.promise);
    const { unmount } = render(<AgendaDayOpportunities data="2026-10-23" identityKey="usuario-1" />);
    await abrirESelecionarServico();
    fireEvent.click(screen.getByRole("button", { name: "Consultar oportunidades" }));
    const sinal = apiMock.post.mock.calls[0][2].signal as AbortSignal;
    unmount();
    expect(sinal.aborted).toBe(true);
    await act(async () => { consulta.resolve(resposta()); });
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
  });
});
