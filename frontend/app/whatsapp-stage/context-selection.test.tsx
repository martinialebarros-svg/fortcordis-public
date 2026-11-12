import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WhatsAppStagePage from "./page";

vi.mock("../layout-dashboard", () => ({
  default: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));

const now = "2026-10-11T20:40:00.000Z";
const firstPhone = "558588018899";
const secondPhone = "558588010002";
const serviceWindow = { last_inbound_at: now, expires_at: "2026-10-12T20:40:00.000Z", is_open: true };
const candidates = {
  clinicas: [{ id: 10, nome: "Clínica de teste", cidade: "Fortaleza", estado: "CE" }],
  tutores: [{ id: 20, nome: "Tutor de teste" }],
};

function context(phone = firstPhone, selection: "clinica" | "tutor" | "invalid" | "cleared" | null = null, version = 0) {
  const matched = selection === "clinica" || selection === "tutor";
  const type = selection === "invalid" ? "clinica" : matched ? selection : null;
  return {
    normalized_phone: phone,
    resolution: selection === "invalid" ? "selection_invalid" : matched ? "matched" : "ambiguous",
    match_type: matched ? selection : null,
    contexto_chave: `${phone}:${version}`,
    candidatos: candidates,
    selecao: selection ? { match_type: type, cadastro_id: type === "clinica" ? 10 : type === "tutor" ? 20 : null,
      versao: version, valida: selection !== "invalid", atualizado_por_id: 1, updated_at: now } : null,
    clinicas: matched ? selection === "clinica" ? candidates.clinicas : [] : candidates.clinicas,
    tutores: matched ? selection === "tutor" ? candidates.tutores : [] : candidates.tutores,
    pets: [], agendamentos: [], ordens_servico: [],
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function installApi(options: {
  context?: (phone: string) => Response | Promise<Response>;
  save?: (phone: string, body: Record<string, unknown>) => Response | Promise<Response>;
  refusal?: { motivo: string; aviso_enviado?: boolean; decisao?: "handoff" | "blocked" };
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;
    if (path === "/api/v1/whatsapp/bot/solicitacoes") return jsonResponse({ itens: [], total: 0, contagens: {} });
    if (path === "/whatsapp/conversations") return jsonResponse({ data: [firstPhone, secondPhone].map((phone, index) => ({
      id: String(index + 1), wa_phone_number: phone, wa_psid: phone,
      subject: index === 0 ? "Primeira conversa" : "Segunda conversa", status: "open", last_agent_id: null,
      last_activity_at: now, created_at: now, updated_at: now, last_inbound_at: now, customer_service_window: serviceWindow,
    })), pagination: { page: 1, limit: 20, total: 2 } });
    if (["/whatsapp/agents", "/whatsapp/quick-replies", "/whatsapp/automation/templates"].includes(path)) return jsonResponse({ data: [] });
    if (/\/conversations\/\d+\/messages$/.test(path)) return jsonResponse({ data: [], pagination: { page: 1, limit: 50, total: 0 }, customer_service_window: serviceWindow });
    if (path.endsWith("/seen")) return jsonResponse({ data: { id: "1", last_seen_at: now } });
    if (path.endsWith("/follow-up")) return jsonResponse({ data: null });
    if (path.includes("/whatsapp/bot/conversas/")) return jsonResponse({
      wa_identity: path.split("/").at(-2), modo: "auto", modo_origem: "conversa", envio_automatico_liberado: true,
      pausado: true, pausado_ate: "2026-10-12T10:20:00.000Z", rascunho_pendente: null,
      handoff_motivo: null, ultimo_silencio: null,
      ultima_recusa: options.refusal ? { resposta_id: 51, decisao: "handoff", criado_em: now, ...options.refusal } : null,
    });
    if (path === "/api/v1/whatsapp-contexto") {
      const phone = url.searchParams.get("telefone")!;
      return options.context?.(phone) ?? jsonResponse(context(phone));
    }
    if (path.endsWith("/selecao")) return options.save?.(path.split("/").at(-2)!, JSON.parse(String(init?.body))) ?? jsonResponse(context());
    throw new Error(`URL inesperada: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function settle() {
  for (let count = 0; count < 10; count += 1) await act(async () => { await Promise.resolve(); });
}

async function openPage() {
  render(<WhatsAppStagePage />);
  await settle();
}

async function pickConversation(name: string) {
  const item = screen.getAllByText(name).find((element) => element.closest("button"));
  fireEvent.click(item!);
  await settle();
}

function selectionPatches(fetchMock: ReturnType<typeof installApi>) {
  return fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/selecao") && init?.method === "PATCH");
}

describe("escolha de cadastro da conversa WhatsApp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(now));
    window.localStorage.setItem("token", "test-token");
  });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); window.localStorage.clear(); });

  it("exige escolha explícita, salva com versão e atualiza contexto e bot sem remover pausa", async () => {
    let resolveSave!: (response: Response) => void;
    const api = installApi({ save: () => new Promise((resolve) => { resolveSave = resolve; }) });
    await openPage();
    expect(screen.getByLabelText("Cadastro para esta conversa")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Salvar escolha" })).toBeDisabled();
    expect(selectionPatches(api)).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Cadastro para esta conversa"), { target: { value: "clinica:10" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar escolha" }));
    expect(screen.getByLabelText("Cadastro para esta conversa")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Salvando escolha..." })).toBeDisabled();
    expect(selectionPatches(api)).toHaveLength(1);
    expect(JSON.parse(String(selectionPatches(api)[0][1]?.body))).toEqual({ match_type: "clinica", cadastro_id: 10, versao_esperada: 0 });
    await act(async () => { resolveSave(jsonResponse(context(firstPhone, "clinica", 1))); });
    await settle();
    expect(screen.getByText("Cadastro escolhido pela equipe")).toBeInTheDocument();
    expect(screen.getByText(/Escolha atual:/)).toHaveTextContent("Clínica: Clínica de teste");
    expect(screen.getByRole("button", { name: "Retomar bot" })).toBeInTheDocument();
    const botCalls = api.mock.calls.filter(([url]) => String(url).includes("/whatsapp/bot/conversas/"));
    expect(botCalls).toHaveLength(2);
    expect(botCalls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
    expect(api.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("remove a escolha sem remover cadastros e usa a nova versão ao escolher o tutor", async () => {
    const api = installApi({ context: () => jsonResponse(context(firstPhone, "clinica", 3)),
      save: (_phone, body) => jsonResponse(context(firstPhone, body.match_type === null ? "cleared" : "tutor", Number(body.versao_esperada) + 1)) });
    await openPage();
    fireEvent.click(screen.getByRole("button", { name: "Remover escolha" }));
    await settle();
    expect(JSON.parse(String(selectionPatches(api)[0][1]?.body))).toEqual({ match_type: null, cadastro_id: null, versao_esperada: 3 });
    expect(screen.getByLabelText("Cadastro para esta conversa")).toHaveValue("");
    expect(screen.getByText("Número presente em mais de um cadastro")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Clínica: Clínica de teste (#10)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Tutor: Tutor de teste (#20)" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Cadastro para esta conversa"), { target: { value: "tutor:20" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar escolha" }));
    await settle();
    expect(JSON.parse(String(selectionPatches(api)[1][1]?.body))).toEqual({ match_type: "tutor", cadastro_id: 20, versao_esperada: 4 });
    expect(screen.getByText(/Escolha atual:/)).toHaveTextContent("Tutor: Tutor de teste");
  });

  it("limita as opções aos vínculos diretos, sem oferecer os tutores relacionados de uma clínica", async () => {
    installApi({ context: () => jsonResponse({ ...context(firstPhone, "clinica", 1),
      candidatos: { clinicas: candidates.clinicas, tutores: [] }, tutores: [{ id: 99, nome: "Tutor relacionado somente pela clínica" }],
    }) });
    await openPage();
    expect(screen.getByText("Tutor relacionado somente pela clínica")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Cadastro para esta conversa")).queryByRole("option", { name: /Tutor/ })).not.toBeInTheDocument();
  });

  it("apresenta conflito no próprio seletor e permite recarregar antes de salvar uma nova versão", async () => {
    let reads = 0;
    const api = installApi({ context: () => jsonResponse(++reads === 1 ? context() : context(firstPhone, "tutor", 5)),
      save: () => jsonResponse({ detail: "versao_divergente" }, 409) });
    await openPage();
    fireEvent.change(screen.getByLabelText("Cadastro para esta conversa"), { target: { value: "clinica:10" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar escolha" }));
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("Os vínculos ou a escolha mudaram");
    expect(screen.queryByText("Cadastro escolhido pela equipe")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar vínculos" }));
    await settle();
    expect(screen.getByLabelText("Cadastro para esta conversa")).toHaveValue("tutor:20");
    expect(selectionPatches(api)).toHaveLength(1);
  });

  it("não anuncia sucesso após falha de rede e conserva a escolha para revisão", async () => {
    installApi({ save: async () => { throw new TypeError("Failed to fetch"); } });
    await openPage();
    fireEvent.change(screen.getByLabelText("Cadastro para esta conversa"), { target: { value: "clinica:10" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar escolha" }));
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível confirmar a escolha");
    expect(screen.getByLabelText("Cadastro para esta conversa")).toHaveValue("clinica:10");
    expect(screen.queryByText(/Cadastro escolhido para esta conversa/)).not.toBeInTheDocument();
  });

  it("não aplica o resultado de salvar após trocar de conversa e voltar à primeira", async () => {
    let resolveSave!: (response: Response) => void;
    const api = installApi({ save: () => new Promise((resolve) => { resolveSave = resolve; }) });
    await openPage();
    fireEvent.change(screen.getByLabelText("Cadastro para esta conversa"), { target: { value: "clinica:10" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar escolha" }));
    await pickConversation("Segunda conversa");
    expect(screen.getByLabelText("Cadastro para esta conversa")).toHaveValue("");
    await pickConversation("Primeira conversa");
    await act(async () => { resolveSave(jsonResponse(context(firstPhone, "clinica", 1))); });
    await settle();
    expect(screen.getByLabelText("Cadastro para esta conversa")).toHaveValue("");
    expect(screen.queryByText("Cadastro escolhido pela equipe")).not.toBeInTheDocument();
    expect(screen.queryByText(/Cadastro escolhido para esta conversa/)).not.toBeInTheDocument();
    expect(api.mock.calls.filter(([url]) => String(url).includes("/whatsapp/bot/conversas/"))).toHaveLength(3);
  });

  it("bloqueia contexto com seleção inválida e permite remover a escolha que perdeu vínculo", async () => {
    installApi({ context: () => jsonResponse({ ...context(firstPhone, "invalid", 2), candidatos: { clinicas: [], tutores: candidates.tutores } }) });
    await openPage();
    expect(screen.getByRole("alert")).toHaveTextContent("Escolha de cadastro inválida");
    expect(screen.getByLabelText("Cadastro para esta conversa")).toHaveValue("");
    expect(screen.queryByText("Vínculo automático por telefone")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remover escolha" })).toBeEnabled();
  });

  it.each([
    ["identidade_ambigua", "há mais de um cadastro vinculado a este número"],
    ["identidade_selecao_invalida", "o cadastro escolhido não está mais disponível para este número"],
    ["identidade_nao_resolvida", "não foi possível determinar qual cadastro usar nesta conversa"],
    ["identidade_indisponivel", "a consulta aos cadastros está temporariamente indisponível"],
  ])("explica o motivo %s sem apresentar ausência de cadastro como fato", async (motivo, label) => {
    installApi({ refusal: { motivo } });
    await openPage();
    expect(screen.getByRole("region", { name: "O bot não respondeu" })).toHaveTextContent(label);
    expect(screen.queryByText(/o número não foi reconhecido no cadastro/)).not.toBeInTheDocument();
  });

  it("mostra que o aviso de encaminhamento foi enviado sem expor texto recusado como rascunho", async () => {
    installApi({ refusal: { motivo: "identidade_ambigua", aviso_enviado: true } });
    await openPage();
    const notice = screen.getByRole("region", { name: "Encaminhamento para a equipe" });
    expect(notice).toHaveTextContent("Um aviso de encaminhamento para a equipe foi enviado ao cliente");
    expect(notice).not.toHaveTextContent("O texto que o bot chegou a montar");
    expect(within(notice).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Digite sua resposta")).toHaveValue("");
  });
});
