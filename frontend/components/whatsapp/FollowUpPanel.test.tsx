import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FollowUpPanel, { FollowUp, followUpDateInput, followUpLabel } from "./FollowUpPanel";
const agents = [{ id: "11", name: "Ana", email: "ana@example.com", active: true }, { id: "22", name: "Bia", email: "bia@example.com", active: false }];
const now = new Date("2026-09-08T12:00:00Z");
const existing: FollowUp = { due_at: "2026-09-09T12:00:00Z", note: "Confirmar disponibilidade", agent_id: "11", agent_name: "Ana", status: "pending", revision: 2, inbound_received_at: null, updated_at: now.toISOString() };
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function api(data: FollowUp | null = null, save?: (body: Record<string, unknown>) => Response | Promise<Response>) {
  return vi.fn(async (_url: unknown, init?: RequestInit) => init?.method === "PATCH"
    ? save?.(JSON.parse(String(init.body))) ?? response({ data: { ...existing, revision: (data?.revision ?? 0) + 1 } }) : response({ data }));
}
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(now); localStorage.clear(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function open(data: FollowUp | null = null, mock = api(data)) {
  vi.stubGlobal("fetch", mock); const changed = vi.fn();
  const result = render(<FollowUpPanel conversationId="1" agents={agents} defaultAgentId="11" onChanged={changed} />);
  await screen.findByRole("button", { name: data ? "Reagendar retorno" : "Agendar retorno" });
  return { ...result, mock, changed };
}
function edit() {
  fireEvent.click(screen.getByRole("button", { name: /^(Agendar|Reagendar) retorno$/ }));
  fireEvent.change(screen.getByLabelText("Nota interna do retorno"), { target: { value: "Retornar para confirmar" } });
}
const writes = (mock: ReturnType<typeof api>) => mock.mock.calls.filter(([, init]) => init?.method === "PATCH");
describe("retornos internos do WhatsApp", () => {
  it("agenda com responsável, nota, versão e horário de Fortaleza sem enviar mensagem", async () => {
    const { mock, changed } = await open(); edit();
    fireEvent.click(screen.getByRole("button", { name: "Amanhã às 9h" }));
    fireEvent.click(screen.getByRole("button", { name: "Salvar retorno" }));
    await screen.findByText("Retorno agendado. O lembrete é interno.");
    expect(writes(mock)).toHaveLength(1);
    expect(writes(mock)[0][0]).toBe("/whatsapp/conversations/1/follow-up");
    expect(JSON.parse(String(writes(mock)[0][1]?.body))).toEqual({ action: "schedule", expected_revision: 0, due_at: "2026-09-09T12:00:00.000Z", note: "Retornar para confirmar", agent_id: "11" });
    expect(changed).toHaveBeenCalledOnce();
    expect(mock.mock.calls.every(([url]) => !String(url).endsWith("/messages"))).toBe(true);
  });
  it("bloqueia horário passado e não oferece responsável inativo", async () => {
    const { mock } = await open(); edit();
    expect(screen.queryByRole("option", { name: "Bia" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Data e hora do retorno"), { target: { value: "2026-09-08T08:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar retorno" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("horário futuro"); expect(writes(mock)).toHaveLength(0);
  });
  it("mantém rascunho da nota em memória ao navegar entre conversas", async () => {
    const { rerender, changed } = await open(); edit();
    rerender(<FollowUpPanel conversationId="2" agents={agents} defaultAgentId="11" onChanged={changed} />);
    await screen.findByRole("button", { name: "Agendar retorno" });
    rerender(<FollowUpPanel conversationId="1" agents={agents} defaultAgentId="11" onChanged={changed} />);
    expect(screen.getByLabelText("Nota interna do retorno")).toHaveValue("Retornar para confirmar"); expect(localStorage.length).toBe(0);
  });
  it("não aplica gravação atrasada na outra conversa", async () => {
    const pending = deferred<Response>(); const { rerender, changed } = await open(null, api(null, () => pending.promise)); edit();
    fireEvent.click(screen.getByRole("button", { name: "Salvar retorno" }));
    rerender(<FollowUpPanel conversationId="2" agents={agents} defaultAgentId="11" onChanged={changed} />);
    await screen.findByRole("button", { name: "Agendar retorno" }); edit();
    fireEvent.change(screen.getByLabelText("Nota interna do retorno"), { target: { value: "Nota da segunda conversa" } });
    await act(async () => pending.resolve(response({ data: existing })));
    expect(screen.getByLabelText("Nota interna do retorno")).toHaveValue("Nota da segunda conversa");
    expect(screen.queryByText("Retorno agendado. O lembrete é interno.")).not.toBeInTheDocument();
  });
  it("exige revisão explícita após conflito e mantém o texto digitado", async () => {
    let latest = existing;
    const mock = vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "PATCH") { latest = { ...existing, revision: 3, note: "Nota da colega", inbound_received_at: now.toISOString() }; return response({ error: "O retorno mudou. Atualize." }, 409); }
      return response({ data: latest });
    });
    await open(existing, mock); edit(); fireEvent.click(screen.getByRole("button", { name: "Salvar retorno" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Atualize");
    fireEvent.click(screen.getByRole("button", { name: "Atualizar retorno" })); await screen.findByText("Nota da colega");
    expect(screen.getByRole("button", { name: "Salvar retorno" })).toBeDisabled();
    expect(screen.getByLabelText("Nota interna do retorno")).toHaveValue("Retornar para confirmar");
    expect(screen.getByText("Cliente respondeu · revisar retorno")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Usar versão atual e manter nota" }));
    expect(screen.getByRole("button", { name: "Salvar retorno" })).toBeEnabled();
  });
  it("protege contra clique duplo durante gravação", async () => {
    const pending = deferred<Response>(); const { mock } = await open(null, api(null, () => pending.promise)); edit();
    fireEvent.click(screen.getByRole("button", { name: "Salvar retorno" })); fireEvent.click(screen.getByRole("button", { name: "Salvar retorno" }));
    expect(writes(mock)).toHaveLength(1); await act(async () => pending.resolve(response({ data: existing })));
  });
  it.each(["Concluir retorno", "Cancelar retorno"])("%s altera só o retorno", async (label) => {
    const action = label.startsWith("Concluir") ? "complete" : "cancel";
    const mock = api(existing, () => response({ data: { ...existing, revision: 3, status: action === "complete" ? "completed" : "cancelled" } }));
    await open(existing, mock); fireEvent.click(screen.getByRole("button", { name: label }));
    await screen.findByRole("button", { name: "Agendar retorno" });
    expect(JSON.parse(String(writes(mock)[0][1]?.body))).toEqual({ action, expected_revision: 2 });
    expect(writes(mock)[0][0]).toBe("/whatsapp/conversations/1/follow-up");
  });
  it("oferece recuperação após falha de leitura", async () => {
    let fail = true; vi.stubGlobal("fetch", vi.fn(async () => fail ? response({}, 503) : response({ data: null })));
    render(<FollowUpPanel conversationId="1" agents={agents} onChanged={() => {}} />);
    await screen.findByRole("alert"); expect(screen.queryByRole("button", { name: "Agendar retorno" })).not.toBeInTheDocument();
    fail = false; fireEvent.click(screen.getByRole("button", { name: "Atualizar retorno" })); await screen.findByRole("button", { name: "Agendar retorno" });
  });
  it("não substitui gravação nova por leitura iniciada antes dela", async () => {
    const pendingRead = deferred<Response>(); let reads = 0;
    const mock = vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "PATCH") return response({ data: { ...existing, revision: 3, note: "Nota salva" } });
      reads++; return reads === 2 ? pendingRead.promise : response({ data: existing });
    });
    await open(existing, mock); fireEvent.click(screen.getByRole("button", { name: "Atualizar retorno" })); edit();
    fireEvent.click(screen.getByRole("button", { name: "Salvar retorno" })); await screen.findByText("Nota salva");
    await act(async () => pendingRead.resolve(response({ data: existing }))); expect(screen.getByText("Nota salva")).toBeInTheDocument();
  });
  it("formata o fuso da clínica e destaca atraso", () => {
    expect(followUpDateInput(now)).toBe("2026-09-08T09:00");
    expect(followUpLabel({ ...existing, due_at: "2026-09-08T11:59:00Z" }, now.getTime())).toContain("Retorno atrasado");
  });
});
