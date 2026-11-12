import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WhatsAppStagePage from "./page";

vi.mock("../layout-dashboard", () => ({
  default: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));

vi.mock("@/lib/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 99, nome: "Atendente atual", email: " ATUAL@example.com " }),
}));

const now = "2026-09-07T12:00:00.000Z";
const serviceWindow = {
  last_inbound_at: now,
  expires_at: "2026-09-08T12:00:00.000Z",
  is_open: true,
};

function conversation(id: string, subject: string) {
  return {
    id,
    subject,
    wa_phone_number: `55859999900${id}`,
    wa_psid: `55859999900${id}`,
    status: "open",
    last_agent_id: "11",
    assigned_agent_name: "Atendente atual",
    assigned_agent_email: "atual@example.com",
    last_activity_at: now,
    last_message_at: now,
    last_inbound_at: now,
    created_at: now,
    updated_at: now,
    last_message_body: `Prévia ${subject}`,
    unread: true,
    customer_service_window: serviceWindow,
  };
}

const firstConversation = conversation("1", "Clínica Azul");
const secondConversation = conversation("2", "Clínica Verde");

function message(id: number, conversationId = "1") {
  return {
    id: String(id),
    conversation_id: conversationId,
    wa_message_id: `wamid.${conversationId}.${id}`,
    from_me: false,
    body: `Mensagem histórica ${conversationId}-${id}`,
    type: "text",
    status: "received",
    created_at: new Date(Date.parse(now) - (100 - id) * 60_000).toISOString(),
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function conversationResponse(data = [firstConversation, secondConversation]) {
  return jsonResponse({ data, pagination: { page: 1, limit: 20, total: data.length } });
}

function botState(phone: string, responseId: number | null = null, body = "Sugestão inicial do copiloto") {
  return {
    wa_identity: phone, modo: "suggest", modo_origem: "institucional",
    pausado: false, pausado_ate: null, handoff_motivo: null,
    rascunho_pendente: responseId === null ? null : {
      resposta_id: responseId, texto_gerado: body, criado_em: now,
    },
    ultima_recusa: null, ultimo_silencio: null,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function installApi(options: {
  list?: (params: URLSearchParams) => Response | Promise<Response>;
  send?: (conversationId: string, init: RequestInit) => Response | Promise<Response>;
  messages?: (conversationId: string, params: URLSearchParams) => Response | Promise<Response>;
  bot?: (path: string, init?: RequestInit) => Response | Promise<Response>;
  botAction?: (path: string, init?: RequestInit) => Response | Promise<Response>;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;
    if (path === "/whatsapp/quick-replies") return jsonResponse({ data: [{
      id: "1", title: "Recebimento", shortcut: "recebido", category: "Atendimento", active: true,
      body: "Recebemos sua mensagem e já estamos verificando.", created_at: now, updated_at: now,
    }] });
    if (path === "/whatsapp/conversations") {
      return options.list?.(url.searchParams) ?? conversationResponse();
    }
    if (path === "/whatsapp/agents") return jsonResponse({ data: [
      { id: "11", name: "Atendente atual", email: "atual@example.com", role: "agent", active: true, created_at: now },
      { id: "22", name: "Colega da equipe", email: "colega@example.com", role: "agent", active: true, created_at: now },
    ] });
    if (path.endsWith("/templates")) return jsonResponse({ data: [] });
    const messagesMatch = path.match(/^\/whatsapp\/conversations\/(\d+)\/messages$/);
    if (messagesMatch) {
      const conversationId = messagesMatch[1];
      if (init?.method === "POST") return options.send?.(conversationId, init) ?? jsonResponse({ status: "sent" });
      return options.messages?.(conversationId, url.searchParams) ?? jsonResponse({
        data: [message(51, conversationId)],
        pagination: { page: 1, limit: 50, total: 1 },
        customer_service_window: serviceWindow,
      });
    }
    if (path.endsWith("/seen")) return jsonResponse({ data: { id: "1", last_seen_at: now } });
    if (path.endsWith("/claim") || path.endsWith("/unclaim")) return jsonResponse({ message: "Atribuição atualizada" });
    if (path.includes("/whatsapp/bot/conversas/")) return options.bot?.(path, init) ??
      jsonResponse(botState(decodeURIComponent(path.split("/").at(-2) || "")));
    if (path.includes("/whatsapp/bot/respostas/")) return options.botAction?.(path, init) ??
      jsonResponse({ status: "sent", idempotent: false });
    if (path === "/api/v1/whatsapp-contexto") return jsonResponse({
      normalized_phone: "5585999990001", resolution: "not_found", match_type: null,
      clinicas: [], tutores: [], pets: [], agendamentos: [], ordens_servico: [],
    });
    throw new Error(`URL inesperada no teste: ${String(input)}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function settle() {
  for (let index = 0; index < 10; index += 1) {
    await act(async () => { await Promise.resolve(); });
  }
}

async function openPage() {
  render(<WhatsAppStagePage />);
  await settle();
  expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();
}

async function selectConversation(name: string) {
  const item = screen.getAllByText(name).find((element) => element.closest("button"));
  expect(item).toBeDefined();
  await act(async () => { fireEvent.click(item!); });
  await settle();
}

function listRequests(fetchMock: ReturnType<typeof installApi>) {
  return fetchMock.mock.calls
    .map(([input]) => new URL(String(input), "http://localhost"))
    .filter((url) => url.pathname === "/whatsapp/conversations");
}

function messagePosts(fetchMock: ReturnType<typeof installApi>) {
  return fetchMock.mock.calls.filter(([input, init]) =>
    /\/conversations\/\d+\/messages$/.test(String(input)) && init?.method === "POST");
}

describe("produtividade da central de WhatsApp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(now));
    window.localStorage.setItem("token", "test-token");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("substitui somente o atalho final e mantém texto e arquivo sem enviar", async () => {
    const fetchMock = installApi();
    await openPage();
    const composer = screen.getByRole("textbox", { name: "Digite sua resposta" });
    fireEvent.change(composer, { target: { value: "Bom dia!\n/receb" } });
    fireEvent.change(screen.getByLabelText("Selecionar arquivo para anexar"), {
      target: { files: [new File(["exemplo"], "horarios.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Inserir resposta Recebimento" }));
    expect(composer).toHaveValue("Bom dia!\nRecebemos sua mensagem e já estamos verificando.");
    expect(screen.getByText("horarios.pdf")).toBeInTheDocument();
    expect(messagePosts(fetchMock)).toHaveLength(0);
  });

  it("buscar e gerenciar respostas rápidas fica fora do formulário de envio", async () => {
    const fetchMock = installApi();
    await openPage();
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Rascunho privado" } });
    const search = screen.getByRole("textbox", { name: "Buscar resposta rápida" });
    expect(search.closest("form")).toBeNull();
    fireEvent.keyDown(search, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Gerenciar respostas" }));
    const replyBody = screen.getByRole("textbox", { name: /Texto da resposta/ });
    expect(replyBody.closest("form")).toBeNull();
    fireEvent.keyDown(replyBody, { key: "Enter", ctrlKey: true });
    expect(messagePosts(fetchMock)).toHaveLength(0);
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("Rascunho privado");
  });

  it("mantém texto e anexo de cada conversa ao alternar entre contatos", async () => {
    installApi();
    await openPage();
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Rascunho para Azul" } });
    fireEvent.change(screen.getByLabelText("Selecionar arquivo para anexar"), {
      target: { files: [new File(["azul"], "azul.pdf", { type: "application/pdf" })] },
    });

    await selectConversation("Clínica Verde");
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("");
    expect(screen.queryByText("azul.pdf")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Rascunho para Verde" } });
    fireEvent.change(screen.getByLabelText("Selecionar arquivo para anexar"), {
      target: { files: [new File(["verde"], "verde.pdf", { type: "application/pdf" })] },
    });

    await selectConversation("Clínica Azul");
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("Rascunho para Azul");
    expect(screen.getByText("azul.pdf")).toBeInTheDocument();
    expect(screen.queryByText("verde.pdf")).not.toBeInTheDocument();
    await selectConversation("Clínica Verde");
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("Rascunho para Verde");
    expect(screen.getByText("verde.pdf")).toBeInTheDocument();
  });

  it("bloqueia submissões repetidas e preserva o rascunho quando o envio falha", async () => {
    const pendingSend = deferred<Response>();
    const fetchMock = installApi({ send: () => pendingSend.promise });
    await openPage();
    const composer = screen.getByRole("textbox", { name: "Digite sua resposta" });
    fireEvent.change(composer, { target: { value: "Mensagem para tentar novamente" } });
    const form = composer.closest("form")!;
    await act(async () => { fireEvent.submit(form); fireEvent.submit(form); });

    expect(messagePosts(fetchMock)).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Enviando/ })).toBeDisabled();
    await act(async () => { pendingSend.resolve(jsonResponse({ detail: "Falha temporária" }, 502)); });
    await settle();
    expect(composer).toHaveValue("Mensagem para tentar novamente");
    expect(screen.getByRole("button", { name: "Enviar" })).toBeEnabled();
    expect(screen.getByText(/Falha temporária/)).toBeInTheDocument();
  });

  it("preserva o arquivo e a legenda para tentar novamente após falha de rede", async () => {
    const pendingSend = deferred<Response>();
    const fetchMock = installApi({ send: () => pendingSend.promise });
    await openPage();
    const composer = screen.getByRole("textbox", { name: "Digite sua resposta" });
    const file = new File(["documento"], "documento.pdf", { type: "application/pdf" });
    fireEvent.change(composer, { target: { value: "Documento solicitado" } });
    fireEvent.change(screen.getByLabelText("Selecionar arquivo para anexar"), { target: { files: [file] } });
    await act(async () => { fireEvent.submit(composer.closest("form")!); });
    const [, init] = messagePosts(fetchMock)[0];
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("attachment")).toBe(file);
    expect((init?.body as FormData).get("body")).toBe("Documento solicitado");

    await act(async () => { pendingSend.reject(new TypeError("Falha de conexão")); });
    await settle();
    expect(composer).toHaveValue("Documento solicitado");
    expect(screen.getByText("documento.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeEnabled();
    expect(screen.getByText(/Não foi possível confirmar o envio/)).toBeInTheDocument();
  });

  it("conclui o envio na conversa original sem apagar o rascunho do contato aberto depois", async () => {
    const pendingSend = deferred<Response>();
    installApi({ send: () => pendingSend.promise });
    await openPage();
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Mensagem Azul" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Enviar" })); });
    await selectConversation("Clínica Verde");
    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua resposta" }), { target: { value: "Rascunho Verde" } });
    await act(async () => { pendingSend.resolve(jsonResponse({ status: "sent" })); });
    await settle();

    expect(screen.getByRole("heading", { name: "Clínica Verde", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("Rascunho Verde");
    await selectConversation("Clínica Azul");
    expect(screen.getByRole("textbox", { name: "Digite sua resposta" })).toHaveValue("");
  });

  it("acrescenta uma resposta rápida preservando o texto já preparado", async () => {
    installApi();
    await openPage();
    const composer = screen.getByRole("textbox", { name: "Digite sua resposta" });
    fireEvent.change(composer, { target: { value: "Bom dia, equipe." } });
    fireEvent.click(screen.getByRole("button", { name: "Inserir resposta Recebimento" }));
    expect((composer as HTMLTextAreaElement).value).toMatch(/^Bom dia, equipe\.\s+Recebemos sua mensagem e já estamos verificando\.$/);
  });

  it("filtra minhas conversas pelo atendente ligado ao email e combina o filtro de não lidas", async () => {
    const fetchMock = installApi();
    await openPage();
    const mine = screen.getByRole("option", { name: "Minhas conversas" }) as HTMLOptionElement;
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar por responsável" }), { target: { value: mine.value } });
    await settle();
    expect(listRequests(fetchMock).at(-1)?.searchParams.get("agent_id")).toBe("11");

    fireEvent.click(screen.getByRole("checkbox", { name: "Somente não lidas" }));
    await settle();
    const query = listRequests(fetchMock).at(-1)?.searchParams;
    expect(query?.get("unread")).toBe("true");
    expect(query?.get("agent_id")).toBe("11");
  });

  it("aguarda 300 ms na busca e ignora respostas de consultas anteriores", async () => {
    const oldSearch = deferred<Response>();
    const fetchMock = installApi({ list: (params) => {
      if (params.get("search") === "Azul") return oldSearch.promise;
      if (params.get("search") === "Verde") return conversationResponse([secondConversation]);
      return conversationResponse();
    } });
    await openPage();
    const initialCount = listRequests(fetchMock).length;
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar conversas" }), { target: { value: "Azul" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(299); });
    expect(listRequests(fetchMock)).toHaveLength(initialCount);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(listRequests(fetchMock).at(-1)?.searchParams.get("search")).toBe("Azul");

    fireEvent.change(screen.getByRole("textbox", { name: "Buscar conversas" }), { target: { value: "Verde" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    await settle();
    expect(screen.getByRole("button", { name: /Clínica Verde/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Clínica Azul/ })).not.toBeInTheDocument();
    await act(async () => { oldSearch.resolve(conversationResponse([firstConversation])); });
    await settle();
    expect(screen.getByRole("button", { name: /Clínica Verde/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Clínica Azul/ })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Buscar conversas" })).toHaveValue("Verde");
  });

  it("atualiza a caixa a cada 15 segundos preservando a conversa selecionada", async () => {
    let refresh = false;
    const fetchMock = installApi({ list: () => conversationResponse(refresh
      ? [firstConversation, { ...secondConversation, last_message_body: "Nova mensagem recebida" }]
      : [firstConversation, secondConversation]) });
    await openPage();
    await selectConversation("Clínica Verde");
    const initialCount = listRequests(fetchMock).length;
    refresh = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(14_999); });
    expect(listRequests(fetchMock)).toHaveLength(initialCount);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    await settle();

    expect(listRequests(fetchMock)).toHaveLength(initialCount + 1);
    expect(screen.getByText("Nova mensagem recebida")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Clínica Verde", level: 2 })).toBeInTheDocument();
  });

  it("carrega mensagens anteriores e mantém o histórico durante a atualização de cinco segundos", async () => {
    const fetchMock = installApi({ messages: (conversationId, params) => jsonResponse({
      data: params.get("page") === "2"
        ? [message(1, conversationId)]
        : Array.from({ length: 50 }, (_, index) => message(index + 2, conversationId)),
      pagination: { page: Number(params.get("page")), limit: 50, total: 51 },
      customer_service_window: serviceWindow,
    }) });
    await openPage();
    expect(screen.queryByText("Mensagem histórica 1-1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));
    await settle();
    const olderRequest = fetchMock.mock.calls.map(([input]) => new URL(String(input), "http://localhost"))
      .find((url) => url.pathname === "/whatsapp/conversations/1/messages" && url.searchParams.get("page") === "2");
    expect(olderRequest?.searchParams.get("order")).toBe("latest");
    expect(screen.getByText("Mensagem histórica 1-1")).toBeInTheDocument();
    expect(screen.getByText("Mensagem histórica 1-51")).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    await settle();
    expect(screen.getByText("Mensagem histórica 1-1")).toBeInTheDocument();
    expect(screen.getAllByText("Mensagem histórica 1-51")).toHaveLength(1);
  });

  it("mantém o destinatário escolhido para transferência e envia o atendente correto", async () => {
    const fetchMock = installApi();
    await openPage();
    const target = screen.getByRole("combobox", { name: "Transferir para" });
    fireEvent.change(target, { target: { value: "22" } });
    await settle();
    expect(target).toHaveValue("22");
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    await settle();
    expect(target).toHaveValue("22");

    fireEvent.click(screen.getByRole("button", { name: "Transferir" }));
    await settle();
    const claim = fetchMock.mock.calls.find(([input]) => String(input) === "/whatsapp/conversations/1/claim");
    expect(claim).toBeDefined();
    expect(JSON.parse(String(claim?.[1]?.body))).toEqual({ agent_id: 22 });
  });

  it("mantém a busca e os filtros atuais no refresh após um envio iniciado antes da busca", async () => {
    const pendingSend = deferred<Response>();
    const fetchMock = installApi({
      send: () => pendingSend.promise,
      list: (params) => conversationResponse(params.get("search") === "Verde"
        ? [secondConversation] : [firstConversation, secondConversation]),
    });
    await openPage();
    const composer = screen.getByRole("textbox", { name: "Digite sua resposta" });
    fireEvent.change(composer, { target: { value: "Envio iniciado na busca anterior" } });
    await act(async () => { fireEvent.submit(composer.closest("form")!); });

    fireEvent.change(screen.getByRole("textbox", { name: "Buscar conversas" }), { target: { value: "Verde" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    fireEvent.click(screen.getByRole("checkbox", { name: "Somente não lidas" }));
    await settle();
    const filteredRequestCount = listRequests(fetchMock).length;
    await act(async () => { pendingSend.resolve(jsonResponse({ status: "sent" })); });
    await settle();

    expect(listRequests(fetchMock).length).toBeGreaterThan(filteredRequestCount);
    expect(listRequests(fetchMock).at(-1)?.searchParams.get("search")).toBe("Verde");
    expect(listRequests(fetchMock).at(-1)?.searchParams.get("unread")).toBe("true");
    expect(screen.getByRole("textbox", { name: "Buscar conversas" })).toHaveValue("Verde");
    expect(screen.queryByRole("button", { name: /Clínica Azul/ })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Clínica Azul", level: 2 })).toBeInTheDocument();

    const afterSendCount = listRequests(fetchMock).length;
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    await settle();
    expect(listRequests(fetchMock).length).toBeGreaterThan(afterSendCount);
    expect(listRequests(fetchMock).at(-1)?.searchParams.get("search")).toBe("Verde");
    expect(listRequests(fetchMock).at(-1)?.searchParams.get("unread")).toBe("true");
  });

  it("recupera a lacuna do histórico após chegarem mais de cinquenta mensagens entre atualizações", async () => {
    let total = 100;
    installApi({ messages: (conversationId, params) => {
      const page = Number(params.get("page"));
      const newest = total - (page - 1) * 50;
      const oldest = Math.max(1, newest - 49);
      return jsonResponse({
        data: newest < 1 ? [] : Array.from({ length: newest - oldest + 1 }, (_, index) => message(oldest + index, conversationId)),
        pagination: { page, limit: 50, total },
        customer_service_window: serviceWindow,
      });
    } });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));
    await settle();
    expect(screen.getByText("Mensagem histórica 1-1")).toBeInTheDocument();
    expect(screen.getByText("Mensagem histórica 1-100")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Carregar mensagens anteriores" })).not.toBeInTheDocument();

    total = 151;
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    await settle();
    expect(screen.getByText("Mensagem histórica 1-151")).toBeInTheDocument();
    expect(screen.queryByText("Mensagem histórica 1-101")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));
    await settle();

    expect(screen.getByText("Mensagem histórica 1-101")).toBeInTheDocument();
    expect(screen.getByText("Mensagem histórica 1-1")).toBeInTheDocument();
    expect(screen.getAllByText("Mensagem histórica 1-100")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Carregar mensagens anteriores" })).not.toBeInTheDocument();
  });

  it("esconde a sugestão anterior ao trocar de contato enquanto o novo estado do copiloto carrega", async () => {
    const pendingGreenState = deferred<Response>();
    installApi({ bot: (path) => path.includes(firstConversation.wa_phone_number)
      ? jsonResponse(botState(firstConversation.wa_phone_number, 101, "Sugestão exclusiva para Azul"))
      : pendingGreenState.promise });
    await openPage();
    expect(screen.getByText("Sugestão exclusiva para Azul")).toBeInTheDocument();
    await selectConversation("Clínica Verde");
    expect(screen.getByRole("heading", { name: "Clínica Verde", level: 2 })).toBeInTheDocument();
    expect(screen.queryByText("Sugestão exclusiva para Azul")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Editar e enviar" })).not.toBeInTheDocument();

    await act(async () => {
      pendingGreenState.resolve(jsonResponse(botState(secondConversation.wa_phone_number, 202, "Sugestão exclusiva para Verde")));
    });
    await settle();
    expect(screen.getByText("Sugestão exclusiva para Verde")).toBeInTheDocument();
    expect(screen.queryByText("Sugestão exclusiva para Azul")).not.toBeInTheDocument();
  });

  it("preserva a edição manual da sugestão do mesmo rascunho durante o polling", async () => {
    const fetchMock = installApi({ bot: () => jsonResponse(botState(firstConversation.wa_phone_number, 101)) });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Editar e enviar" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Editar rascunho do bot" }), {
      target: { value: "Resposta revisada manualmente pela equipe" },
    });

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    await settle();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/whatsapp/bot/conversas/"))).toHaveLength(2);
    expect(screen.getByRole("textbox", { name: "Editar rascunho do bot" })).toHaveValue("Resposta revisada manualmente pela equipe");
  });

  it("encerra a edição antiga quando o servidor passa a sugerir outra resposta", async () => {
    let replacement = false;
    installApi({ bot: () => jsonResponse(botState(firstConversation.wa_phone_number,
      replacement ? 102 : 101, replacement ? "Nova sugestão gerada para outra mensagem" : "Sugestão anterior")) });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Editar e enviar" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Editar rascunho do bot" }), {
      target: { value: "Edição que pertence somente à resposta anterior" },
    });
    replacement = true;

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    await settle();
    expect(screen.queryByRole("textbox", { name: "Editar rascunho do bot" })).not.toBeInTheDocument();
    expect(screen.getByText("Nova sugestão gerada para outra mensagem")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Editar e enviar" }));
    expect(screen.getByRole("textbox", { name: "Editar rascunho do bot" })).toHaveValue("Nova sugestão gerada para outra mensagem");
  });

  it("não injeta o estado de uma pausa antiga no contato aberto durante a ação", async () => {
    const pendingPause = deferred<Response>();
    const fetchMock = installApi({ bot: (path, init) => {
      if (init?.method === "PATCH") return pendingPause.promise;
      return path.includes(firstConversation.wa_phone_number)
        ? jsonResponse(botState(firstConversation.wa_phone_number, 101, "Sugestão de Azul antes da pausa"))
        : jsonResponse(botState(secondConversation.wa_phone_number, 202, "Sugestão de Verde após a troca"));
    } });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Pausar bot" }));
    await settle();
    const pauseRequest = fetchMock.mock.calls.find(([input, init]) =>
      String(input).includes("/whatsapp/bot/conversas/") && init?.method === "PATCH");
    expect(String(pauseRequest?.[0])).toContain(firstConversation.wa_phone_number);
    expect(JSON.parse(String(pauseRequest?.[1]?.body))).toEqual({ pausar: true });
    await selectConversation("Clínica Verde");

    await act(async () => { pendingPause.resolve(jsonResponse({
      ...botState(firstConversation.wa_phone_number, 101, "Estado atrasado de Azul"),
      pausado: true, pausado_ate: "2026-09-07T13:00:00.000Z",
    })); });
    await settle();
    expect(screen.getByRole("heading", { name: "Clínica Verde", level: 2 })).toBeInTheDocument();
    expect(screen.queryByText("Estado atrasado de Azul")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retomar bot" })).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    await settle();
    expect(screen.getByText("Sugestão de Verde após a troca")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pausar bot" })).toBeInTheDocument();
  });

  it("suspende a atualização da fila enquanto a página está oculta e atualiza ao retornar", async () => {
    const fetchMock = installApi();
    await openPage();
    const initialCount = listRequests(fetchMock).length;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    await settle();
    expect(listRequests(fetchMock)).toHaveLength(initialCount);

    visibility.mockReturnValue("visible");
    fireEvent(document, new Event("visibilitychange"));
    await settle();
    expect(listRequests(fetchMock)).toHaveLength(initialCount + 1);
  });

  it("ignora uma página de histórico que chega depois de selecionar outra conversa", async () => {
    const pendingHistory = deferred<Response>();
    installApi({ messages: (conversationId, params) => {
      if (conversationId === "1" && params.get("page") === "2") return pendingHistory.promise;
      return jsonResponse({
        data: conversationId === "1"
          ? Array.from({ length: 50 }, (_, index) => message(index + 2))
          : [message(1, "2")],
        pagination: { page: 1, limit: 50, total: conversationId === "1" ? 51 : 1 },
        customer_service_window: serviceWindow,
      });
    } });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));
    await settle();
    await selectConversation("Clínica Verde");
    await act(async () => { pendingHistory.resolve(jsonResponse({
      data: [message(1)], pagination: { page: 2, limit: 50, total: 51 },
      customer_service_window: serviceWindow,
    })); });
    await settle();
    expect(screen.getByText("Mensagem histórica 2-1")).toBeInTheDocument();
    expect(screen.queryByText("Mensagem histórica 1-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Mensagem histórica 1-51")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Carregar mensagens anteriores" })).not.toBeInTheDocument();
  });
});
