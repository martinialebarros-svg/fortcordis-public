import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_AGENDA_SEMANAL } from "@/lib/agenda-config";
import type { PedidoAgenda } from "@/lib/whatsapp-pedido-agenda";

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/lib/axios", () => ({ default: { get: (...args: unknown[]) => apiGet(...args), post: (...args: unknown[]) => apiPost(...args), put: vi.fn() } }));
vi.mock("@/components/fortinho/FortinhoProvider", () => ({ useFortinho: () => ({ notify: vi.fn(), confirm: vi.fn(async () => false) }) }));
vi.mock("@/lib/stable-catalog-cache", () => ({ loadStableCatalog: ({ load }: { load: () => Promise<unknown> }) => load() }));
vi.mock("@/lib/credito-cliente", () => ({ consultarSaldoCreditoCliente: vi.fn(async () => 0) }));

import NovoAgendamentoModal from "./NovoAgendamentoModal";

const PEDIDO: PedidoAgenda = {
  pedido_id: 9, versao: 1, clinica_id: 7, resumo: "Solicitação de teste",
  paciente: null, tutor: null, servico_id: 3, avisos: [],
};
const OFERTA = {
  inicio: "2026-10-05 14:00", fim: "2026-10-05 14:40", score: 0, risco: 0,
  tempo_deslocamento_total_min: 0,
  tempo_deslocamento_base_min: 22,
  fonte_deslocamento_base: "google_maps",
  inicio_minimo_primeira_saida: "2026-10-05 08:52",
  origem_primeira_saida: "base_operacional",
  anterior: null, proximo: null,
};
const resposta = () => ({ data: { panorama_ofertas: { items: [OFERTA] } } });

function formulario(pedido = PEDIDO, isOpen = true, agendamento?: { id: number; clinica_id: number; servico_id: number; inicio: string; status: string }) {
  return <NovoAgendamentoModal isOpen={isOpen} isAdmin pedidoWhatsApp={pedido} agendamento={agendamento} onClose={vi.fn()} onSuccess={vi.fn()}
    defaultDate="2026-10-04" defaultTime="09:00" intervaloSlotMinutos={60}
    agendaSemanal={DEFAULT_AGENDA_SEMANAL} agendaFeriados={[]} agendaExcecoes={[]} />;
}

function montar(pedido = PEDIDO) {
  return render(formulario(pedido));
}

async function botaoGerar() {
  const botao = screen.getByRole("button", { name: "Gerar melhor oferta" });
  await waitFor(() => expect(botao).toBeEnabled());
  return botao;
}

describe("preferências antes das ofertas", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-05T01:00:00Z"));
    apiGet.mockReset(); apiPost.mockReset();
    apiGet.mockImplementation(async (url: string) => {
      if (url.startsWith("/clinicas")) return { data: { items: [{ id: 7, nome: "Clínica teste", latitude: -3.73, longitude: -38.52 }] } };
      if (url.startsWith("/servicos")) return { data: { items: [{ id: 3, nome: "Ecocardiograma", duracao_minutos: 40 }] } };
      return { data: { items: [] } };
    });
    apiPost.mockImplementation(async (url: string) =>
      url === "/agenda/assistente/validar-oferta"
        ? { data: { ok: true, valido: true } }
        : resposta()
    );
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("envia próxima semana à tarde antes de calcular, usando Fortaleza e passo independente da grade", async () => {
    montar();
    await botaoGerar();
    expect(apiPost).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Quando deseja o atendimento"), { target: { value: "proxima_semana" } });
    fireEvent.change(screen.getByLabelText("Turno desejado"), { target: { value: "tarde" } });
    expect(screen.getByText(/05\/10\/2026 a 11\/10\/2026/)).toBeInTheDocument();
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/assistente/ofertas", expect.objectContaining({
      intervalo_minutos: 15, duracao_minutos: 40, data_contato: "2026-10-04",
      preferencia: { data_inicio: "2026-10-05", data_fim: "2026-10-11", turno: "tarde" },
    })));
  });

  it("envia 16/10 após 09:00 antes de sugerir e invalida o aceite ao alterar ou limpar a preferência", async () => {
    apiPost.mockImplementation(async (url: string) =>
      url === "/agenda/assistente/validar-oferta"
        ? { data: { ok: true, valido: true } }
        : { data: { panorama_ofertas: { items: [
          { ...OFERTA, inicio: "2026-10-16 10:00", fim: "2026-10-16 10:40" },
        ] } } }
    );
    montar();
    await botaoGerar();
    fireEvent.change(screen.getByLabelText("Quando deseja o atendimento"), { target: { value: "data" } });
    fireEvent.change(screen.getByLabelText("Data desejada"), { target: { value: "2026-10-16" } });
    fireEvent.change(screen.getByLabelText("Turno desejado"), { target: { value: "a_partir_de" } });
    expect(screen.getByLabelText("A partir de")).toBeInTheDocument();
    expect(screen.queryByLabelText("Terminar até")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerar melhor oferta" })).toBeDisabled();
    expect(apiPost).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("A partir de"), { target: { value: "09:00" } });
    expect(screen.getByText(/16\/10\/2026, a partir de 09:00/)).toBeInTheDocument();
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/assistente/ofertas", expect.objectContaining({
      preferencia: { data_inicio: "2026-10-16", data_fim: "2026-10-16", turno: "qualquer", hora_inicio: "09:00" },
    })));
    fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/assistente/validar-oferta", expect.objectContaining({
      inicio: "2026-10-16 10:00",
    })));
    expect(await screen.findByText(/Aceite do cliente registrado/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("A partir de"), { target: { value: "10:00" } });
    expect(screen.queryByText(/Aceite do cliente registrado/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cliente aceitou esta oferta" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Limpar preferências e ampliar busca" }));
    expect(screen.getByLabelText("Turno desejado")).toHaveValue("qualquer");
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenLastCalledWith("/agenda/assistente/ofertas", expect.objectContaining({ preferencia: undefined })));
  });

  it("traz preferência estruturada do pedido e permite ampliar somente por ação explícita", async () => {
    montar({ ...PEDIDO, dados_coletados: { preferencia_agenda: { data_inicio: "2026-10-08", data_fim: "2026-10-08", turno: "manha" } } });
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/assistente/ofertas", expect.objectContaining({
      preferencia: { data_inicio: "2026-10-08", data_fim: "2026-10-08", turno: "manha" },
    })));
    fireEvent.click(screen.getByRole("button", { name: "Limpar preferências e ampliar busca" }));
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenLastCalledWith("/agenda/assistente/ofertas", expect.objectContaining({ preferencia: undefined })));
  });

  it("importa horário inicial isolado do pedido sem exigir fim", async () => {
    montar({ ...PEDIDO, dados_coletados: { preferencia_agenda: {
      data_inicio: "2026-10-16", data_fim: "2026-10-16", turno: "qualquer", hora_inicio: "09:00",
    } } });
    expect(screen.getByLabelText("Turno desejado")).toHaveValue("a_partir_de");
    expect(screen.getByLabelText("A partir de")).toHaveValue("09:00");
    expect(screen.queryByLabelText("Terminar até")).not.toBeInTheDocument();
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/assistente/ofertas", expect.objectContaining({
      preferencia: { data_inicio: "2026-10-16", data_fim: "2026-10-16", turno: "qualquer", hora_inicio: "09:00" },
    })));
  });

  it("descarta resposta antiga ao mudar o turno e invalida uma oferta já aceita", async () => {
    let concluir!: (value: ReturnType<typeof resposta>) => void;
    apiPost.mockImplementationOnce(() => new Promise((resolve) => { concluir = resolve; }));
    const { container } = montar();
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Turno desejado"), { target: { value: "tarde" } });
    await act(async () => { concluir(resposta()); });
    expect(screen.queryByRole("button", { name: "Cliente aceitou esta oferta" })).not.toBeInTheDocument();
    fireEvent.click(await botaoGerar());
    fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/assistente/validar-oferta", expect.objectContaining({
      inicio: OFERTA.inicio,
      clinica_id: 7,
      servico_id: 3,
    })));
    await waitFor(() => expect(container.querySelector<HTMLInputElement>('input[type="time"]')?.value).toBe("14:00"));
    fireEvent.change(screen.getByLabelText("Turno desejado"), { target: { value: "manha" } });
    expect(screen.queryByText(/Aceite do cliente registrado/)).not.toBeInTheDocument();
    expect(container.querySelector<HTMLInputElement>('input[type="time"]')?.value).toBe("");
    expect(screen.queryByRole("button", { name: "Cliente aceitou esta oferta" })).not.toBeInTheDocument();
  });

  it("separa o trajeto desde casa do deslocamento entre atendimentos", async () => {
    montar();
    fireEvent.click(await botaoGerar());
    expect(await screen.findByText(/Trajeto estimado casa → primeiro atendimento: 22 min/)).toBeInTheDocument();
    expect(screen.getByText(/Entre atendimentos: 0 min/)).toBeInTheDocument();
    expect(screen.getByText(/Primeiro inicio estimado com saida da base: 05\/10\/2026 as 08:52/)).toBeInTheDocument();
  });

  it("descarta oferta vencida quando a API reprova o horario exato no aceite", async () => {
    apiPost.mockImplementation(async (url: string) =>
      url === "/agenda/assistente/validar-oferta"
        ? { data: { ok: true, valido: false, codigo: "PRIMEIRA_SAIDA_INVIAVEL", mensagem: "Nao ha tempo para chegar." } }
        : resposta()
    );
    montar();
    fireEvent.click(await botaoGerar());
    fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nao ha tempo para chegar. Gere novas ofertas");
    expect(screen.queryByText(/Oferta 1:/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar Agendamento" })).toBeDisabled();
  });

  it("ignora revalidacao tardia quando a preferencia muda durante o aceite", async () => {
    let concluirValidacao!: (value: { data: { ok: boolean; valido: boolean } }) => void;
    apiPost.mockImplementation((url: string) =>
      url === "/agenda/assistente/validar-oferta"
        ? new Promise((resolve) => { concluirValidacao = resolve; })
        : Promise.resolve(resposta())
    );
    const { container } = montar();
    fireEvent.click(await botaoGerar());
    fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
    await waitFor(() => expect(concluirValidacao).toBeTypeOf("function"));
    fireEvent.change(screen.getByLabelText("Turno desejado"), { target: { value: "manha" } });
    await act(async () => { concluirValidacao({ data: { ok: true, valido: true } }); });
    expect(screen.queryByText(/Aceite do cliente registrado/)).not.toBeInTheDocument();
    expect(container.querySelector<HTMLInputElement>('input[type="time"]')?.value).toBe("");
    expect(screen.getByRole("button", { name: "Salvar Agendamento" })).toBeDisabled();
  });

  it("mostra erro de primeira saida no modal e invalida o aceite quando o salvamento devolve 409", async () => {
    const pedidoCompleto: PedidoAgenda = {
      ...PEDIDO,
      tutor: { id: 11, nome: "Maria" },
      paciente: { id: 21, nome: "Rex", tutor_id: 11, tutor: "Maria" },
    };
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/agenda/assistente/validar-oferta") return { data: { ok: true, valido: true } };
      if (url === "/agenda") {
        throw { response: { status: 409, data: { detail: {
          codigo: "PRIMEIRA_SAIDA_INVIAVEL",
          mensagem: "Nao ha tempo para sair de casa e chegar ao destino.",
        } } } };
      }
      return resposta();
    });
    const { container } = render(
      <NovoAgendamentoModal
        isOpen isAdmin pedidoWhatsApp={pedidoCompleto} onClose={vi.fn()} onSuccess={vi.fn()}
        defaultDate="2026-10-04" defaultTime="09:00"
        agendaSemanal={{ ...DEFAULT_AGENDA_SEMANAL, "1": { ativo: true, inicio: "08:00", fim: "18:00" } }}
        agendaFeriados={[]} agendaExcecoes={[]}
      />
    );
    fireEvent.click(await botaoGerar());
    fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar Agendamento" })).toBeEnabled());
    expect(container.querySelector<HTMLInputElement>('input[type="date"]')?.value).toBe("2026-10-05");
    expect(container.querySelector<HTMLInputElement>('input[type="time"]')?.value).toBe("14:00");
    fireEvent.click(screen.getByRole("button", { name: "Salvar Agendamento" }));
    await waitFor(() => expect(apiPost.mock.calls.map(([url]) => url)).toContain("/agenda"));
    const dialogo = screen.getByRole("dialog");
    const alerta = await within(dialogo).findByRole("alert");
    expect(alerta).toHaveTextContent("Nao ha tempo para sair de casa");
    const cabecalho = dialogo.querySelector(".fc-appointment-modal-header") as Element;
    const formulario = dialogo.querySelector("form") as Element;
    expect(cabecalho.compareDocumentPosition(alerta) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(alerta.compareDocumentPosition(formulario) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText(/Aceite do cliente registrado/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar Agendamento" })).toBeDisabled();
  });

  it("bloqueia a busca com período incompleto ou faixa horária invertida", async () => {
    montar();
    await botaoGerar();
    fireEvent.change(screen.getByLabelText("Quando deseja o atendimento"), { target: { value: "intervalo" } });
    expect(screen.getByRole("button", { name: "Gerar melhor oferta" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Primeiro dia"), { target: { value: "2026-10-05" } });
    fireEvent.change(screen.getByLabelText("Último dia"), { target: { value: "2026-10-06" } });
    fireEvent.change(screen.getByLabelText("Turno desejado"), { target: { value: "personalizado" } });
    fireEvent.change(screen.getByLabelText("A partir de"), { target: { value: "16:00" } });
    fireEvent.change(screen.getByLabelText("Terminar até"), { target: { value: "14:00" } });
    expect(screen.getByRole("button", { name: "Gerar melhor oferta" })).toBeDisabled();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("mostra preferência importada antes de gerar e preserva a interseção do turno com a faixa", async () => {
    montar({ ...PEDIDO, dados_coletados: { preferencia_agenda: { turno: "tarde", hora_inicio: "10:00", hora_fim: "17:00" } } });
    const botao = await botaoGerar();
    const campo = screen.getByRole("group", { name: "Preferências deste atendimento" });
    expect(campo.compareDocumentPosition(botao) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("A partir de")).toHaveValue("12:00");
    expect(screen.getByLabelText("Terminar até")).toHaveValue("17:00");
    fireEvent.click(botao);
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda/assistente/ofertas", expect.objectContaining({
      preferencia: { turno: "qualquer", hora_inicio: "12:00", hora_fim: "17:00" },
    })));
  });

  it("não reaplica resultado da sessão encerrada depois de reabrir o modal", async () => {
    let concluir!: (value: ReturnType<typeof resposta>) => void;
    apiPost.mockImplementationOnce(() => new Promise((resolve) => { concluir = resolve; }));
    const { rerender } = montar();
    fireEvent.click(await botaoGerar());
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    rerender(formulario(PEDIDO, false));
    rerender(formulario());
    await botaoGerar();
    await act(async () => { concluir(resposta()); });
    expect(screen.queryByRole("button", { name: "Cliente aceitou esta oferta" })).not.toBeInTheDocument();
  });

  it("mantém o filtro da edição quando a leitura de pacientes termina", async () => {
    let concluirPacientes!: (value: { data: { items: [] } }) => void;
    const getOriginal = apiGet.getMockImplementation()!;
    apiGet.mockImplementation((url: string) => url.startsWith("/pacientes")
      ? new Promise((resolve) => { concluirPacientes = resolve; }) : getOriginal(url));
    render(formulario(PEDIDO, true, { id: 5, clinica_id: 7, servico_id: 3, inicio: "2026-10-06T09:00:00", status: "Agendado" }));
    fireEvent.change(screen.getByLabelText("Turno desejado"), { target: { value: "manha" } });
    await waitFor(() => expect(concluirPacientes).toBeTypeOf("function"));
    await act(async () => { concluirPacientes({ data: { items: [] } }); });
    expect(screen.getByLabelText("Turno desejado")).toHaveValue("manha");
  });
});
