import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_AGENDA_SEMANAL } from "@/lib/agenda-config";

const apiGet = vi.fn();
const apiPost = vi.fn();
const fortinhoConfirm = vi.fn(async (_config?: unknown) => false);

vi.mock("@/lib/axios", () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    put: vi.fn(),
  },
}));

vi.mock("@/components/fortinho/FortinhoProvider", () => ({
  useFortinho: () => ({
    notify: vi.fn(),
    confirm: (config: unknown) => fortinhoConfirm(config),
  }),
}));

vi.mock("@/lib/stable-catalog-cache", () => ({
  loadStableCatalog: ({ load }: { load: () => Promise<unknown> }) => load(),
}));

vi.mock("@/lib/credito-cliente", () => ({
  consultarSaldoCreditoCliente: vi.fn(async () => 0),
}));

import NovoAgendamentoModal from "./NovoAgendamentoModal";

const CLINICA = {
  id: 7,
  nome: "Pet Sanus Caucaia",
  latitude: -3.7327,
  longitude: -38.527,
};

const SERVICO = { id: 3, nome: "Ecocardiograma", duracao_minutos: 30 };

const OFERTA = {
  inicio: "2026-09-15 09:00",
  fim: "2026-09-15 09:30",
  score: 10,
  risco: 0,
  tempo_deslocamento_total_min: 12,
  anterior: null,
  proximo: null,
};

function montarModal(isAdmin = true, defaultDate = "2026-09-15", onSuccess = vi.fn()) {
  return render(
    <NovoAgendamentoModal
      isOpen
      isAdmin={isAdmin}
      onClose={vi.fn()}
      onSuccess={onSuccess}
      defaultDate={defaultDate}
      defaultTime="09:00"
      agendaSemanal={DEFAULT_AGENDA_SEMANAL}
      agendaFeriados={[]}
      agendaExcecoes={[]}
    />
  );
}

async function selecionarClinicaEServico() {
  const labelClinica = await waitFor(() => {
    const encontrado = Array.from(document.querySelectorAll("label")).find(
      (label) => label.textContent === "Clínica"
    );
    if (!encontrado) throw new Error("label da clinica ainda nao renderizado");
    return encontrado;
  });
  const blocoClinica = labelClinica.parentElement as HTMLElement;
  fireEvent.click(blocoClinica.querySelector("button[aria-expanded]") as HTMLButtonElement);
  fireEvent.click(await screen.findByText(CLINICA.nome));

  const selectServico = document.querySelectorAll("select");
  const servicoSelect = Array.from(selectServico).find((select) =>
    Array.from(select.options).some((option) => option.textContent === SERVICO.nome)
  );
  expect(servicoSelect).toBeTruthy();
  fireEvent.change(servicoSelect as HTMLSelectElement, { target: { value: String(SERVICO.id) } });
}

describe("NovoAgendamentoModal - excecao manual de horario", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    fortinhoConfirm.mockReset().mockResolvedValue(false);

    apiGet.mockImplementation(async (url: string) => {
      if (url.startsWith("/pacientes")) return { data: { items: [] } };
      if (url.startsWith("/tutores")) return { data: { items: [] } };
      if (url.startsWith("/clinicas")) return { data: { items: [CLINICA] } };
      if (url.startsWith("/servicos")) return { data: { items: [SERVICO] } };
      return { data: {} };
    });

    apiPost.mockImplementation(async (url: string) => {
      if (url === "/agenda/assistente/ofertas") {
        return {
          data: {
            panorama_ofertas: { items: [OFERTA], itens_ignorados_janela: 0, motivo: "" },
            mensagem_panorama: "",
            sugestao_proximidade: null,
          },
        };
      }
      if (url === "/agenda/sugestao-proximidade") {
        return { data: { sugerir: false, mensagem: "" } };
      }
      return { data: {} };
    });
  });

  it("mantem motivo e horario liberados ao trocar a data depois da excecao concedida", async () => {
    const { container } = montarModal();

    await selecionarClinicaEServico();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Gerar melhor oferta" }));
    });

    fireEvent.click(
      await screen.findByRole("button", {
        name: /Nenhuma oferta atende a necessidade do cliente/i,
      })
    );

    const motivo = await screen.findByPlaceholderText(/cliente so pode no turno da manha/i);
    fireEvent.change(motivo, { target: { value: "Cliente so tem disponibilidade na proxima semana." } });

    fireEvent.click(screen.getByRole("button", { name: /Conceder excecao e liberar horario manual/i }));

    const inputData = container.querySelector('input[type="date"]') as HTMLInputElement;
    const inputHora = container.querySelector('input[type="time"]') as HTMLInputElement;
    expect(inputData.disabled).toBe(false);
    expect(inputHora.disabled).toBe(false);

    await act(async () => {
      fireEvent.change(inputData, { target: { value: "2026-09-22" } });
    });

    expect(inputData.value).toBe("2026-09-22");
    expect(inputHora.disabled).toBe(false);
    expect(
      (screen.getByPlaceholderText(/cliente so pode no turno da manha/i) as HTMLTextAreaElement).value
    ).toBe("Cliente so tem disponibilidade na proxima semana.");
    expect(screen.getByText(/Excecao concedida por admin/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Data ajustada sob excecao concedida/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Oferta 1:/)).not.toBeInTheDocument();
  });

  it("mantem o bloqueio guiado sem excecao e volta a bloquear apos revogar", async () => {
    const { container } = montarModal();

    await selecionarClinicaEServico();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Gerar melhor oferta" }));
    });

    expect(await screen.findByText(/Oferta 1:/)).toBeInTheDocument();

    const inputData = container.querySelector('input[type="date"]') as HTMLInputElement;
    const inputHora = container.querySelector('input[type="time"]') as HTMLInputElement;
    expect(inputData.disabled).toBe(true);
    expect(inputHora.disabled).toBe(true);

    fireEvent.click(
      await screen.findByRole("button", {
        name: /Nenhuma oferta atende a necessidade do cliente/i,
      })
    );
    expect(inputData.disabled).toBe(true);
    expect(inputHora.disabled).toBe(true);

    const motivo = await screen.findByPlaceholderText(/cliente so pode no turno da manha/i);
    fireEvent.change(motivo, { target: { value: "Cliente so aceita horario noturno." } });
    fireEvent.click(screen.getByRole("button", { name: /Conceder excecao e liberar horario manual/i }));
    expect(inputData.disabled).toBe(false);
    expect(inputHora.disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /Revogar excecao/i }));
    expect(inputData.disabled).toBe(true);
    expect(inputHora.disabled).toBe(true);
  });
  it("admin abre a excecao sem ofertas, exige motivo e envia a autorizacao de rota", async () => {
    const onSuccess = vi.fn();
    const { container } = montarModal(true, "2099-05-25", onSuccess);
    await selecionarClinicaEServico();
    fireEvent.click(screen.getByRole("button", { name: "Usar horário manual como admin" }));

    const inputHora = container.querySelector('input[type="time"]') as HTMLInputElement;
    const motivo = screen.getByRole("textbox", { name: "Motivo da exceção administrativa" });
    expect(inputHora).toBeDisabled();
    fireEvent.change(motivo, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /Conceder excecao e liberar horario manual/i }));
    expect(inputHora).toBeDisabled();
    expect(screen.getByRole("button", { name: /Salvar Agendamento/i })).toBeDisabled();

    fireEvent.change(motivo, { target: { value: "Admin ja esta no local do atendimento." } });
    fireEvent.click(screen.getByRole("button", { name: /Conceder excecao e liberar horario manual/i }));
    expect(inputHora).toBeEnabled();
    fireEvent.change(inputHora, { target: { value: "08:30" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Marcar como reserva de horário/i }));
    fireEvent.click(screen.getByRole("button", { name: /Salvar Agendamento/i }));

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/agenda", expect.objectContaining({
      inicio: "2099-05-25T08:30:00",
      confirmar_conflito_deslocamento: true,
      excecao_operacional_concedida: true,
      motivo_excecao_operacional: "Admin ja esta no local do atendimento.",
    })));
    const payload = apiPost.mock.calls.find(([url]) => url === "/agenda")?.[1];
    expect(payload.observacoes).toContain("excecao manual concedida por admin");
    expect(payload.observacoes).not.toContain("sem opcao aderente");
    expect(apiPost.mock.calls.some(([url]) => url === "/agenda/assistente/ofertas")).toBe(false);
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("nao oferece excecao direta para nao-admin", async () => {
    const { container } = montarModal(false);
    await selecionarClinicaEServico();
    expect(screen.queryByRole("button", { name: "Usar horário manual como admin" })).not.toBeInTheDocument();
    expect(container.querySelector('input[type="time"]')).toBeDisabled();
    expect(screen.getByRole("button", { name: /Salvar Agendamento/i })).toBeDisabled();
  });

  it("trocar o servico revoga a excecao direta e bloqueia o horario novamente", async () => {
    const { container } = montarModal();
    await selecionarClinicaEServico();
    fireEvent.click(screen.getByRole("button", { name: "Usar horário manual como admin" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Motivo da exceção administrativa" }), {
      target: { value: "Horario conferido pelo admin." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Conceder excecao e liberar horario manual/i }));
    expect(container.querySelector('input[type="time"]')).toBeEnabled();
    const servico = Array.from(container.querySelectorAll("select")).find((select) =>
      Array.from(select.options).some((option) => option.textContent === SERVICO.nome));
    fireEvent.change(servico!, { target: { value: "" } });
    expect(container.querySelector('input[type="time"]')).toBeDisabled();
    expect(screen.queryByText(/Excecao concedida por admin/i)).not.toBeInTheDocument();
  });

  it.each([true, false])("primeira saida inviavel permite confirmar ou cancelar o salvamento (%s)", async (confirmar) => {
    const onSuccess = vi.fn();
    let tentativas = 0;
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/agenda/assistente/ofertas") return { data: { panorama_ofertas: { items: [{
        ...OFERTA, inicio: "2099-05-25 09:00", fim: "2099-05-25 09:30",
      }] } } };
      if (url === "/agenda/assistente/validar-oferta") return { data: { valido: true } };
      if (url === "/agenda") {
        tentativas += 1;
        if (tentativas === 1) throw { response: { status: 409, data: { detail: {
          codigo: "PRIMEIRA_SAIDA_INVIAVEL", mensagem: "A primeira chegada exige 09:10.", confirmavel: true,
        } } } };
        return { data: { id: 901 } };
      }
      return { data: { sugerir: false } };
    });
    fortinhoConfirm.mockResolvedValue(confirmar);
    montarModal(true, "2099-05-25", onSuccess);
    await selecionarClinicaEServico();
    fireEvent.click(screen.getByRole("button", { name: "Gerar melhor oferta" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar Agendamento" })).toBeEnabled());
    fireEvent.click(screen.getByRole("checkbox", { name: /Marcar como reserva de horário/i }));
    fireEvent.click(screen.getByRole("button", { name: "Salvar Agendamento" }));
    await waitFor(() => expect(fortinhoConfirm).toHaveBeenCalledWith(expect.objectContaining({
      title: "Conflito operacional", confirmLabel: "Conceder excecao",
    })));
    if (confirmar) {
      await waitFor(() => expect(onSuccess).toHaveBeenCalled());
      const gravacoes = apiPost.mock.calls.filter(([url]) => url === "/agenda");
      expect(gravacoes).toHaveLength(2);
      expect(gravacoes[0][1].confirmar_conflito_deslocamento).toBe(false);
      expect(gravacoes[1][1].confirmar_conflito_deslocamento).toBe(true);
    } else {
      await screen.findByText(/A primeira chegada exige 09:10/);
      expect(tentativas).toBe(1);
      expect(onSuccess).not.toHaveBeenCalled();
    }
  });

  it.each([
    { isAdmin: true, confirmar: true, gravacoes: 2 },
    { isAdmin: true, confirmar: true, gravacoes: 3 },
    { isAdmin: true, confirmar: false, gravacoes: 1 },
    { isAdmin: false, confirmar: true, gravacoes: 1 },
  ])("sobreposicao exige confirmacao especifica: %o", async ({ isAdmin, confirmar, gravacoes }) => {
    const onSuccess = vi.fn();
    let tentativas = 0;
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/agenda/assistente/ofertas") return { data: { panorama_ofertas: { items: [{
        ...OFERTA, inicio: "2099-05-25 09:00", fim: "2099-05-25 09:45",
      }] } } };
      if (url === "/agenda/assistente/validar-oferta") return { data: { valido: true } };
      if (url === "/agenda") {
        tentativas += 1;
        if (tentativas <= (gravacoes === 3 ? 2 : 1)) throw { response: { status: 409, data: { detail: {
          codigo: "CONFLITO_SOBREPOSICAO_AGENDA", mensagem: "Sobreposicao de 15 minutos com 09:30-10:00.",
          escopo: `token-sintetico-revisado-${tentativas}`, confirmavel: true,
        } } } };
        return { data: { id: 902 } };
      }
      return { data: { sugerir: false } };
    });
    fortinhoConfirm.mockResolvedValue(confirmar);
    montarModal(isAdmin, "2099-05-25", onSuccess);
    await selecionarClinicaEServico();
    fireEvent.click(screen.getByRole("button", { name: "Gerar melhor oferta" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cliente aceitou esta oferta" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Salvar Agendamento" })).toBeEnabled());
    fireEvent.click(screen.getByRole("checkbox", { name: /Marcar como reserva de horário/i }));
    fireEvent.click(screen.getByRole("button", { name: "Salvar Agendamento" }));
    await waitFor(() => expect(apiPost.mock.calls.filter(([url]) => url === "/agenda")).toHaveLength(gravacoes));
    if (isAdmin) {
      await waitFor(() => expect(fortinhoConfirm).toHaveBeenCalledWith(expect.objectContaining({
        title: "Autorizar sobreposição de horários", confirmLabel: "Autorizar sobreposição",
        message: expect.stringContaining("15 minutos"),
      })));
    } else {
      await screen.findByText(/Sobreposicao de 15 minutos/);
      expect(fortinhoConfirm).not.toHaveBeenCalled();
    }
    if (gravacoes > 1) {
      await waitFor(() => expect(onSuccess).toHaveBeenCalled());
      const gravados = apiPost.mock.calls.filter(([url]) => url === "/agenda");
      expect(gravados[0][1].confirmar_sobreposicao).toBe(false);
      expect(fortinhoConfirm).toHaveBeenCalledTimes(gravacoes - 1);
      expect(gravados[gravacoes - 1][1]).toMatchObject({
        confirmar_sobreposicao: true, escopo_sobreposicao_confirmado: `token-sintetico-revisado-${gravacoes - 1}`,
        motivo_excecao_sobreposicao: expect.stringContaining("autorizada explicitamente"),
      });
    } else {
      await waitFor(() => expect(screen.getByRole("button", { name: "Salvar Agendamento" })).toBeEnabled());
      expect(onSuccess).not.toHaveBeenCalled();
      expect(apiPost.mock.calls.filter(([url]) => url === "/agenda")).toHaveLength(1);
    }
  });

});
