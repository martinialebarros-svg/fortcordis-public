import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AgendaFormalizacaoWorkspace from "./AgendaFormalizacaoWorkspace";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("AgendaFormalizacaoWorkspace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("carrega o contexto do agendamento e envia os dados preenchidos", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!init || (init.method || "GET").toUpperCase() === "GET") {
        return jsonResponse({
          clinica_nome: "Pet Sanus Caucaia",
          servico: "Ecocardiograma",
          data: "20/08/2026",
          hora: "14:30",
          expires_at: "2026-08-23T00:00:00.000Z",
        });
      }
      expect(url).toBe("/api/v1/agenda/formalizacao/test-token");
      const body = JSON.parse(String(init.body));
      expect(body).toEqual({
        nome_paciente: "Rex",
        nome_tutor: "João Silva",
        telefone_tutor: "(85) 98888-7777",
      });
      return jsonResponse({ agendamento_id: 42, status: "Agendado" });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AgendaFormalizacaoWorkspace token="test-token" />);

    expect(await screen.findByText("Pet Sanus Caucaia")).toBeInTheDocument();
    expect(screen.getByText("Ecocardiograma")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Nome do animal"), { target: { value: "Rex" } });
    fireEvent.change(screen.getByPlaceholderText("Nome do tutor responsável"), {
      target: { value: "João Silva" },
    });
    fireEvent.change(screen.getByPlaceholderText("(85) 99999-9999"), {
      target: { value: "(85) 98888-7777" },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /confirmar dados/i }));
    });

    expect(await screen.findByText("Dados enviados com sucesso")).toBeInTheDocument();
  });

  it("formaliza com primeiro nome e pet, sem exigir contato", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({ nome_paciente: "Pingo", nome_tutor: "Cristiane", telefone_tutor: "" });
        return jsonResponse({ agendamento_id: 42, status: "Agendado" });
      }
      return jsonResponse({ clinica_nome: "Clínica de teste", servico: "Consulta", data: "28/10/2026", hora: "14:30" });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AgendaFormalizacaoWorkspace token="test-token" />);
    await screen.findByText("Clínica de teste");
    fireEvent.change(screen.getByPlaceholderText("Nome do animal"), { target: { value: "Pingo" } });
    fireEvent.change(screen.getByPlaceholderText("Nome do tutor responsável"), { target: { value: "Cristiane" } });
    expect(screen.getByPlaceholderText("(85) 99999-9999")).not.toBeRequired();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /confirmar dados/i })); });
    expect(await screen.findByText("Dados enviados com sucesso")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("ignora dois envios enquanto a primeira requisicao ainda esta em andamento", async () => {
    let concluir!: (response: Response) => void;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") return new Promise<Response>((resolve) => { concluir = resolve; });
      return jsonResponse({ clinica_nome: "Clínica de teste", servico: "Consulta", data: "28/10/2026", hora: "14:30" });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AgendaFormalizacaoWorkspace token="test-token" />);
    await screen.findByText("Clínica de teste");
    fireEvent.change(screen.getByPlaceholderText("Nome do animal"), { target: { value: "Pingo" } });
    fireEvent.change(screen.getByPlaceholderText("Nome do tutor responsável"), { target: { value: "Cristiane" } });
    const form = screen.getByRole("button", { name: /confirmar dados/i }).closest("form")!;
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    await act(async () => { concluir(jsonResponse({ agendamento_id: 42, status: "Agendado" })); });
    expect(await screen.findByText("Dados enviados com sucesso")).toBeInTheDocument();
  });

  it("mostra erro quando o link e invalido", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "Este link expirou." }, 410)),
    );

    render(<AgendaFormalizacaoWorkspace token="expired-token" />);

    expect(await screen.findByText("Este link expirou.")).toBeInTheDocument();
  });
});
