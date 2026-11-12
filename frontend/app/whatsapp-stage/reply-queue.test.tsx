import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WhatsAppStagePage from "./page";

vi.mock("../layout-dashboard", () => ({
  default: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));
vi.mock("@/lib/useCurrentUser", () => ({
  // O id do usuário do sistema é distinto do id do atendente do WhatsApp.
  useCurrentUser: () => ({ id: 99, nome: "Atendente atual", email: " ATUAL@example.com " }),
}));
vi.mock("@/components/whatsapp/FollowUpPanel", () => ({ default: () => null, followUpLabel: () => "Retorno" }));
vi.mock("@/components/whatsapp/QuickReplyLibrary", () => ({ default: () => null }));

const now = "2026-09-07T12:00:00.000Z";
const viewedMessageId = "9007199254740993";
const serviceWindow = { last_inbound_at: now, expires_at: "2026-09-08T12:00:00.000Z", is_open: true };

function conversation(id: string, subject: string, owner: string | null = "11") {
  return {
    id, subject, wa_phone_number: `55859999900${id}`, wa_psid: `55859999900${id}`,
    status: "open", last_agent_id: owner, assigned_agent_name: owner ? "Atendente atual" : null,
    assigned_agent_email: owner ? "atual@example.com" : null,
    last_activity_at: now, last_message_at: now, last_inbound_at: now, created_at: now, updated_at: now,
    last_message_body: `Prévia ${subject}`, unread: true, needs_reply: true,
    waiting_since: "2026-09-07T10:30:00.000Z", customer_service_window: serviceWindow,
  };
}
type ConversationFixture = ReturnType<typeof conversation>;

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function listResponse(data: ConversationFixture[], limit = 20) {
  return jsonResponse({ data, pagination: { page: 1, limit, total: data.length },
    summary: { total: 37, unread: 12, needs_reply: 19, unassigned: 8, open: 20, pending: 10, closed: 7 } });
}

function messagesResponse(conversationId: string, lastId = viewedMessageId) {
  return jsonResponse({
    data: [{ id: lastId, conversation_id: conversationId, wa_message_id: `wamid.${conversationId}.${lastId}`,
      from_me: false, body: `Mensagem ${conversationId}-${lastId}`, type: "text", status: "received", created_at: now }],
    last_message_id: lastId, pagination: { page: 1, limit: 50, total: 1 }, customer_service_window: serviceWindow,
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function installApi(options: {
  conversations?: ConversationFixture[];
  list?: (params: URLSearchParams, records: ConversationFixture[]) => Response | Promise<Response>;
  status?: (conversationId: string, init: RequestInit) => Response | Promise<Response>;
  claim?: (conversationId: string, init: RequestInit) => Response | Promise<Response>;
  seen?: (conversationId: string) => Response | Promise<Response>;
  messages?: (conversationId: string) => Response | Promise<Response>;
} = {}) {
  const records = options.conversations ?? [conversation("1", "Clínica Azul"), conversation("2", "Clínica Verde")];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;
    if (path === "/whatsapp/conversations") {
      if (options.list) return options.list(url.searchParams, records);
      const data = records.filter((item) =>
        (!url.searchParams.has("needs_reply") || item.needs_reply) &&
        (!url.searchParams.has("unread") || item.unread) &&
        (!url.searchParams.has("status") || item.status === url.searchParams.get("status")) &&
        (!url.searchParams.has("agent_id") || item.last_agent_id === url.searchParams.get("agent_id")) &&
        (!url.searchParams.has("search") || item.subject.includes(url.searchParams.get("search")!)));
      return listResponse(data, Number(url.searchParams.get("limit") || 20));
    }
    if (path === "/whatsapp/agents") return jsonResponse({ data: [
      { id: "22", name: "Colega da equipe", email: "colega@example.com", role: "agent", active: true, created_at: now },
      { id: "11", name: "Atendente atual", email: "atual@example.com", role: "agent", active: true, created_at: now },
    ] });
    if (path.endsWith("/templates")) return jsonResponse({ data: [] });
    if (path === "/api/v1/whatsapp/bot/atendimentos/assumir") {
      const id = JSON.parse(String(init?.body)).conversation_id;
      const response = await (options.claim?.(id, init!) ?? jsonResponse({message:"Conversa e pedidos assumidos"}));
      const record = records.find(item => item.id === id);
      if (response.ok && record) record.last_agent_id = "11";
      return response;
    }
    const action = path.match(/^\/whatsapp\/conversations\/(\d+)\/(messages|seen|status|claim)$/);
    if (action) {
      const [, id, name] = action;
      const record = records.find((item) => item.id === id);
      if (name === "messages") return options.messages?.(id) ?? messagesResponse(id);
      if (name === "seen") {
        const response = await (options.seen?.(id) ?? jsonResponse({ data: { id, last_seen_at: now } }));
        if (response.ok && record) record.unread = false;
        return response;
      }
      if (name === "status") {
        const response = await (options.status?.(id, init!) ?? jsonResponse({ data: { ...record, status: "closed" }, changed: true }));
        if (response.ok && record) { record.status = "closed"; record.needs_reply = false; }
        return response;
      }
      if (name === "claim") {
        const response = await (options.claim?.(id, init!) ?? jsonResponse({ message: "Responsável atualizado" }));
        if (response.ok && record) record.last_agent_id = String(JSON.parse(String(init?.body)).agent_id);
        return response;
      }
    }
    if (path.includes("/whatsapp/bot/conversas/")) return jsonResponse({
      wa_identity: "5585999990001", modo: "suggest", modo_origem: "institucional", pausado: false,
      pausado_ate: null, handoff_motivo: null, rascunho_pendente: null, ultima_recusa: null, ultimo_silencio: null,
    });
    if (path === "/api/v1/whatsapp-contexto") return jsonResponse({
      normalized_phone: "5585999990001", resolution: "not_found", match_type: null,
      clinicas: [], tutores: [], pets: [], agendamentos: [], ordens_servico: [],
    });
    throw new Error(`URL inesperada no teste: ${String(input)}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
type FetchMock = ReturnType<typeof installApi>;

async function settle() {
  for (let index = 0; index < 10; index += 1) await act(async () => { await Promise.resolve(); });
}

async function openPage() {
  render(<WhatsAppStagePage />);
  await settle();
  expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
}

function row(name: string) {
  return screen.getAllByText(name).find((element) => element.closest("button"))!.closest("button")!;
}

async function selectConversation(name: string) {
  fireEvent.click(row(name));
  await settle();
}

function listRequests(mock: FetchMock) {
  return mock.mock.calls.map(([input]) => new URL(String(input), "http://localhost"))
    .filter((url) => url.pathname === "/whatsapp/conversations");
}

function statusRequests(mock: FetchMock) {
  return mock.mock.calls.filter(([input, init]) => /\/conversations\/\d+\/status$/.test(String(input)) && init?.method === "PATCH");
}

function nextRequests(mock: FetchMock) {
  return listRequests(mock).filter((url) => url.searchParams.get("limit") === "2");
}

async function combineFilters() {
  fireEvent.change(screen.getByRole("combobox", { name: "Filtrar por responsável" }), { target: { value: "mine" } });
  await settle();
  fireEvent.click(screen.getByRole("checkbox", { name: "Somente não lidas" }));
  await settle();
  fireEvent.change(screen.getByRole("textbox", { name: "Buscar conversas" }), { target: { value: "Clínica" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  await settle();
  fireEvent.click(screen.getByRole("button", { name: "Em atendimento" }));
  await settle();
  fireEvent.click(screen.getByRole("checkbox", { name: "Precisa de resposta" }));
  await settle();
}

describe("fila de resposta e conclusão de atendimento WhatsApp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(now));
    window.localStorage.setItem("token", "test-token");
  });
  afterEach(() => {
    cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); window.localStorage.clear();
  });

  it("mostra pendência do responsável e limpa o aviso ao trocar para conversa livre", async () => {
    installApi({ conversations: [conversation("1", "Clínica Azul"), conversation("2", "Clínica Verde", null)] });
    await openPage();
    const notice = screen.getByRole("status", { name: "Resposta pendente da equipe" });
    expect(notice).toHaveTextContent("Responsável: Atendente atual");
    expect(notice).toHaveTextContent("Aguardando há 1 h 30 min");
    await selectConversation("Clínica Verde");
    expect(screen.queryByRole("status", { name: "Resposta pendente da equipe" })).toBeNull();
  });

  it("combina pendência, responsável atual, não lidas, busca e status e limpa todos os filtros", async () => {
    const fetchMock = installApi();
    await openPage();
    await combineFilters();
    const query = listRequests(fetchMock).at(-1)!.searchParams;
    expect(Object.fromEntries(query)).toMatchObject({ needs_reply: "true", agent_id: "11", unread: "true", search: "Clínica", status: "open" });
    expect(query.has("assigned")).toBe(false);
    expect(screen.getByText("Mais antigas primeiro. Ler a mensagem não encerra a pendência.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    await settle();
    expect(Object.fromEntries(listRequests(fetchMock).at(-1)!.searchParams)).toEqual({ page: "1", limit: "20", summary_agent_id: "11" });
    expect(screen.getByRole("checkbox", { name: "Precisa de resposta" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Somente não lidas" })).not.toBeChecked();
    expect(screen.getByRole("textbox", { name: "Buscar conversas" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Filtrar por responsável" })).toHaveValue("all");
  });

  it("o card global mostra o total do servidor e abre a fila completa de pendências", async () => {
    const fetchMock = installApi();
    await openPage();
    await combineFilters();
    const card = screen.getByRole("button", { name: "Ver conversas que precisam de resposta" });
    expect(within(card).getByText("19")).toBeInTheDocument();
    fireEvent.click(card);
    await settle();
    expect(Object.fromEntries(listRequests(fetchMock).at(-1)!.searchParams)).toEqual({ page: "1", limit: "20", needs_reply: "true", summary_agent_id: "11" });
    expect(screen.getByRole("checkbox", { name: "Precisa de resposta" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Somente não lidas" })).not.toBeChecked();
    expect(screen.getByRole("textbox", { name: "Buscar conversas" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Filtrar por responsável" })).toHaveValue("all");
  });

  it("remove o indicador de não lida após seen sem apagar a pendência ou o tempo de espera", async () => {
    const pendingSeen = deferred<Response>();
    const fetchMock = installApi({ seen: () => pendingSeen.promise });
    await openPage();
    expect(within(row("Clínica Azul")).getByLabelText("Não lida")).toBeInTheDocument();
    await act(async () => { pendingSeen.resolve(jsonResponse({ data: { id: "1", last_seen_at: now } })); });
    await settle();
    expect(within(row("Clínica Azul")).queryByLabelText("Não lida")).not.toBeInTheDocument();
    expect(within(row("Clínica Azul")).getByText("Aguardando há 1 h 30 min")).toBeInTheDocument();
    expect(screen.getAllByText("Aguardando há 1 h 30 min")).toHaveLength(3);
    expect(statusRequests(fetchMock)).toHaveLength(0);
  });

  it("assume a conversa sem dono com o id WhatsApp vinculado ao email do usuário", async () => {
    const pendingClaim = deferred<Response>();
    const fetchMock = installApi({ conversations: [conversation("1", "Clínica Azul", null)], claim: () => pendingClaim.promise });
    await openPage();
    const button = screen.getByRole("button", { name: "Assumir atendimento" });
    await act(async () => { fireEvent.click(button); fireEvent.click(button); });
    const claims = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/atendimentos/assumir"));
    expect(claims).toHaveLength(1);
    expect(claims[0][1]?.method).toBe("POST");
    expect(JSON.parse(String(claims[0][1]?.body))).toEqual({ conversation_id: "1", telefone: "558599999001" });
    expect(button).toBeDisabled();
    await act(async () => { pendingClaim.resolve(jsonResponse({ message: "Responsável atualizado" })); });
    await settle();
    expect(screen.queryByRole("button", { name: "Assumir atendimento" })).not.toBeInTheDocument();
  });

  it("preserva o novo responsável quando outro atendente assume antes da confirmação", async () => {
    const records = [conversation("1", "Clínica Azul", null), conversation("2", "Clínica Verde")];
    const fetchMock = installApi({ conversations: records, claim: () => {
      records[0].last_agent_id = "22";
      records[0].assigned_agent_name = "Colega da equipe";
      records[0].assigned_agent_email = "colega@example.com";
      return jsonResponse({ code: "CONVERSATION_ALREADY_ASSIGNED" }, 409);
    } });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Assumir atendimento" }));
    await settle();
    expect(screen.getByText("Esta conversa já foi assumida por outra pessoa. O responsável foi mantido.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assumir atendimento" })).not.toBeInTheDocument();
    expect(records[0].last_agent_id).toBe("22");
    const claims = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/atendimentos/assumir"));
    expect(claims).toHaveLength(1);
  });

  it.each(["11", "22"])("não oferece assumir silenciosamente uma conversa com responsável %s", async (owner) => {
    const fetchMock = installApi({ conversations: [conversation("1", "Clínica Azul", owner)] });
    await openPage();
    expect(screen.queryByRole("button", { name: "Assumir atendimento" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/atendimentos/assumir"))).toHaveLength(0);
  });

  it("resolve usando a última mensagem vista e consulta no servidor a próxima pendência com os filtros atuais", async () => {
    const third = conversation("3", "Clínica Amarela");
    const fetchMock = installApi({ list: (params, records) => params.get("limit") === "2"
      ? listResponse([third], 2) : listResponse(records) });
    await openPage();
    await combineFilters();
    expect(screen.queryByText("Clínica Amarela")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    expect(statusRequests(fetchMock)).toHaveLength(1);
    expect(String(statusRequests(fetchMock)[0][0])).toBe("/whatsapp/conversations/1/status");
    expect(JSON.parse(String(statusRequests(fetchMock)[0][1]?.body))).toEqual({ status: "closed", expected_last_message_id: viewedMessageId });
    expect(nextRequests(fetchMock)).toHaveLength(1);
    expect(Object.fromEntries(nextRequests(fetchMock)[0].searchParams)).toEqual({
      page: "1", limit: "2", needs_reply: "true", agent_id: "11", unread: "true", search: "Clínica", status: "open",
    });
    expect(screen.getByRole("heading", { name: "Clínica Amarela", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Conversa resolvida. Próxima pendência aberta.")).toBeInTheDocument();
  });

  it("mantém rascunho e anexo da conversa resolvida ao avançar e retornar", async () => {
    installApi();
    await openPage();
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Informação ainda em preparo" } });
    fireEvent.change(screen.getByLabelText("Selecionar arquivo para anexar"), {
      target: { files: [new File(["conteúdo"], "documento.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Verde", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("");
    expect(screen.queryByText("documento.pdf")).not.toBeInTheDocument();
    await selectConversation("Clínica Azul");
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("Informação ainda em preparo");
    expect(screen.getByText("documento.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolver e abrir próxima" })).toBeDisabled();
  });

  it("bloqueia a conclusão enquanto o histórico ainda não confirma a última mensagem", async () => {
    const pendingHistory = deferred<Response>();
    const fetchMock = installApi({ messages: () => pendingHistory.promise });
    await openPage();
    const button = screen.getByRole("button", { name: "Resolver e abrir próxima" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(statusRequests(fetchMock)).toHaveLength(0);
    await act(async () => { pendingHistory.resolve(messagesResponse("1")); });
    await settle();
    expect(button).toBeEnabled();
  });

  it("envia uma única atualização de status mesmo com dois cliques consecutivos", async () => {
    const pendingStatus = deferred<Response>();
    const fetchMock = installApi({ status: () => pendingStatus.promise });
    await openPage();
    const button = screen.getByRole("button", { name: "Resolver e abrir próxima" });
    await act(async () => { fireEvent.click(button); fireEvent.click(button); });
    expect(statusRequests(fetchMock)).toHaveLength(1);
    expect(button).toBeDisabled();
    expect(nextRequests(fetchMock)).toHaveLength(0);
    await act(async () => { pendingStatus.resolve(jsonResponse({ changed: true })); });
    await settle();
    expect(nextRequests(fetchMock)).toHaveLength(1);
  });

  it("mantém a conversa e o rascunho quando a alteração de status falha", async () => {
    const fetchMock = installApi({ status: () => jsonResponse({ error: "Falha temporária" }, 502) });
    await openPage();
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Rascunho preservado" } });
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("Rascunho preservado");
    expect(screen.getByRole("button", { name: "Resolver e abrir próxima" })).toBeEnabled();
    expect(screen.getByText("Não foi possível atualizar o status. Tente novamente.")).toBeInTheDocument();
    expect(nextRequests(fetchMock)).toHaveLength(0);
  });

  it("em conflito de nova mensagem avisa, atualiza o histórico e só fecha com o novo marcador após revisão", async () => {
    let conflict = true;
    let historyReads = 0;
    const newMessageId = "9007199254740994";
    const fetchMock = installApi({
      status: () => conflict ? jsonResponse({ code: "CONVERSATION_CHANGED" }, 409) : jsonResponse({ changed: true }),
      messages: (id) => { historyReads += 1; return messagesResponse(id, historyReads === 1 ? viewedMessageId : newMessageId); },
    });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Chegou uma nova mensagem. Revise o histórico antes de resolver a conversa.")).toBeInTheDocument();
    expect(screen.getByText(`Mensagem 1-${newMessageId}`)).toBeInTheDocument();
    expect(historyReads).toBe(2);
    expect(nextRequests(fetchMock)).toHaveLength(0);
    conflict = false;
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    expect(JSON.parse(String(statusRequests(fetchMock)[1][1]?.body))).toEqual({ status: "closed", expected_last_message_id: newMessageId });
  });

  it("informa quando a conversa foi resolvida e a fila não tem outra pendência", async () => {
    const fetchMock = installApi({ conversations: [conversation("1", "Clínica Azul")] });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    expect(nextRequests(fetchMock)).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Conversa resolvida. Não há outra pendência nos filtros atuais.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolver e abrir próxima" })).toBeDisabled();
  });

  it("preserva a conclusão e informa a falha caso não consiga carregar a próxima pendência", async () => {
    installApi({ list: (params, records) => params.get("limit") === "2"
      ? jsonResponse({ error: "Falha temporária" }, 502) : listResponse(records) });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Conversa resolvida. Não foi possível carregar a próxima pendência; atualize a fila.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolver e abrir próxima" })).toBeDisabled();
  });

  it.each(["status", "next"] as const)("não redireciona após trocar de conversa enquanto %s está pendente", async (phase) => {
    const pending = deferred<Response>();
    const third = conversation("3", "Clínica Amarela");
    const fetchMock = installApi({
      status: () => phase === "status" ? pending.promise : jsonResponse({ changed: true }),
      list: (params, records) => params.get("limit") === "2" ? pending.promise : listResponse(records),
    });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    await selectConversation("Clínica Verde");
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Escrevendo para Verde" } });
    await act(async () => { pending.resolve(phase === "status" ? jsonResponse({ changed: true }) : listResponse([third], 2)); });
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Verde", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("Escrevendo para Verde");
    expect(nextRequests(fetchMock)).toHaveLength(phase === "status" ? 0 : 1);
    expect(screen.queryByText("Conversa resolvida. Próxima pendência aberta.")).not.toBeInTheDocument();
  });

  it.each(["status", "next"] as const)("não redireciona após mudar os filtros enquanto %s está pendente", async (phase) => {
    const pending = deferred<Response>();
    const third = conversation("3", "Clínica Amarela");
    const fetchMock = installApi({
      status: () => phase === "status" ? pending.promise : jsonResponse({ changed: true }),
      list: (params, records) => params.get("limit") === "2" ? pending.promise : listResponse(records),
    });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar conversas" }), { target: { value: "Nova busca" } });
    await act(async () => { pending.resolve(phase === "status" ? jsonResponse({ changed: true }) : listResponse([third], 2)); });
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Buscar conversas" })).toHaveValue("Nova busca");
    expect(nextRequests(fetchMock)).toHaveLength(phase === "status" ? 0 : 1);
    expect(screen.queryByText("Conversa resolvida. Próxima pendência aberta.")).not.toBeInTheDocument();
  });

  it("não retoma a navegação automática após sair e voltar à conversa durante a conclusão", async () => {
    const pendingStatus = deferred<Response>();
    const fetchMock = installApi({ status: () => pendingStatus.promise });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" }));
    await settle();
    await selectConversation("Clínica Verde");
    await selectConversation("Clínica Azul");
    await act(async () => { pendingStatus.resolve(jsonResponse({ changed: true })); });
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
    expect(nextRequests(fetchMock)).toHaveLength(0);
  });
  it("filtra retornos por vencimento e responsável próprio sem confundir com o dono da conversa", async () => {
    const fetchMock = installApi(); await openPage();
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar retornos" }), { target: { value: "today" } }); await settle();
    fireEvent.click(screen.getByRole("checkbox", { name: "Meus retornos" })); await settle();
    expect(Object.fromEntries(listRequests(fetchMock).at(-1)!.searchParams)).toEqual({ page: "1", limit: "20", follow_up: "today", follow_up_agent_id: "11", summary_agent_id: "11" });
    fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" })); await settle();
    expect(screen.getByRole("combobox", { name: "Filtrar retornos" })).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: "Meus retornos" })).not.toBeChecked();
    expect(listRequests(fetchMock).at(-1)!.searchParams.has("follow_up")).toBe(false);
    expect(listRequests(fetchMock).at(-1)!.searchParams.has("follow_up_agent_id")).toBe(false);
  });
  it("abre lembretes pessoais ignorando filtros que poderiam escondê-los", async () => {
    const fetchMock = installApi(); await openPage(); await combineFilters();
    fireEvent.click(screen.getByRole("button", { name: /Meus retornos para revisar/ })); await settle();
    expect(Object.fromEntries(listRequests(fetchMock).at(-1)!.searchParams)).toEqual({ page: "1", limit: "20", follow_up: "ready", follow_up_agent_id: "11", summary_agent_id: "11" });
    expect(screen.getByRole("checkbox", { name: "Somente não lidas" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Precisa de resposta" })).not.toBeChecked();
  });
  it("resolver e abrir próxima respeita também o filtro de retornos", async () => {
    const fetchMock = installApi(); await openPage();
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar retornos" }), { target: { value: "due" } }); await settle();
    fireEvent.click(screen.getByRole("checkbox", { name: "Meus retornos" })); await settle();
    fireEvent.click(screen.getByRole("button", { name: "Resolver e abrir próxima" })); await settle();
    expect(nextRequests(fetchMock).at(-1)!.searchParams.get("follow_up")).toBe("due");
    expect(nextRequests(fetchMock).at(-1)!.searchParams.get("follow_up_agent_id")).toBe("11");
  });

});
