import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QuickReplyLibrary, { QuickReply } from "./QuickReplyLibrary";

const original: QuickReply = {
  id: "1", title: "Saudação", body: "Olá, como podemos ajudar sua equipe?", category: "Geral", shortcut: "ola",
  active: true, created_at: "2026-09-08T10:00:00.000Z", updated_at: "2026-09-08T10:00:00.000Z",
};
const agenda: QuickReply = { ...original, id: "2", title: "Horários", body: "Informe a unidade e o melhor período.", category: "Agenda", shortcut: "horarios" };
const inactive: QuickReply = { ...original, id: "3", title: "Antiga", shortcut: "antiga", active: false };
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status, headers: { "Content-Type": "application/json" },
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

function setupApi(options: {
  list?: () => Response | Promise<Response>;
  write?: (path: string, init: RequestInit) => Response | Promise<Response>;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method === "POST" || init?.method === "PATCH") {
      return options.write?.(path, init) ?? json({ data: { ...original, ...JSON.parse(String(init.body)) } });
    }
    return options.list?.() ?? json({ data: [original, agenda, inactive] });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function manage() {
  await screen.findByRole("button", { name: "Inserir resposta Saudação" });
  fireEvent.click(screen.getByRole("button", { name: "Gerenciar respostas" }));
}

function fillNewReply() {
  fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Contato inicial" } });
  fireEvent.change(screen.getByLabelText("Atalho sem barra"), { target: { value: "CONTATO" } });
  fireEvent.change(screen.getByLabelText("Categoria"), { target: { value: "Geral" } });
  fireEvent.change(screen.getByLabelText(/Texto da resposta/), { target: { value: "Informe o nome da clínica." } });
}

describe("QuickReplyLibrary", () => {
  beforeEach(() => window.localStorage.setItem("token", "test-token"));
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); window.localStorage.clear(); });

  it("busca por título sem acento, conteúdo e categoria, inserindo somente no rascunho", async () => {
    const fetchMock = setupApi();
    const onInsert = vi.fn();
    render(<QuickReplyLibrary onInsert={onInsert} disabled={false} />);
    await screen.findByRole("button", { name: "Inserir resposta Saudação" });
    expect(screen.queryByRole("button", { name: "Inserir resposta Antiga" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar resposta rápida" }), { target: { value: "saudacao" } });
    expect(screen.getByRole("button", { name: "Inserir resposta Saudação" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Inserir resposta Horários" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar resposta rápida" }), { target: { value: "melhor período" } });
    expect(screen.getByRole("button", { name: "Inserir resposta Horários" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar resposta rápida" }), { target: { value: "" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Categoria da resposta rápida" }), { target: { value: "Agenda" } });
    fireEvent.click(screen.getByRole("button", { name: "Inserir resposta Horários" }));
    expect(onInsert).toHaveBeenCalledExactlyOnceWith(agenda.body);
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it("guarda somente IDs dos favoritos e mantém a preferência isolada por usuário", async () => {
    const fetchMock = setupApi();
    const onInsert = vi.fn();
    const { rerender } = render(<QuickReplyLibrary onInsert={onInsert} disabled={false} userId="99" />);
    await screen.findByRole("button", { name: "Inserir resposta Saudação" });
    fireEvent.click(screen.getByRole("button", { name: "Favoritar resposta Horários" }));
    expect(window.localStorage.getItem("whatsapp-quick-reply-favorites:99")).toBe('["2"]');
    fireEvent.click(screen.getByRole("checkbox", { name: "Somente favoritas" }));
    expect(screen.queryByRole("button", { name: "Inserir resposta Saudação" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inserir resposta Horários" })).toBeInTheDocument();
    rerender(<QuickReplyLibrary onInsert={onInsert} disabled={false} userId="100" />);
    expect(screen.getByRole("button", { name: "Favoritar resposta Horários" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("checkbox", { name: "Somente favoritas" }));
    expect(screen.queryByRole("button", { name: "Inserir resposta Horários" })).not.toBeInTheDocument();
    rerender(<QuickReplyLibrary onInsert={onInsert} disabled={false} userId="99" />);
    expect(screen.getByRole("button", { name: "Remover dos favoritos resposta Horários" })).toHaveAttribute("aria-pressed", "true");
    expect(onInsert).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it("filtra atalhos ativos e respeita o bloqueio de inserção sem impedir a gestão", async () => {
    setupApi();
    const onInsert = vi.fn();
    const { rerender } = render(<QuickReplyLibrary onInsert={onInsert} disabled={true} shortcutQuery="ho" />);
    const insert = await screen.findByRole("button", { name: "Inserir resposta Horários" });
    expect(insert).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Inserir resposta Saudação" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerenciar respostas" })).toBeEnabled();
    fireEvent.click(insert);
    expect(onInsert).not.toHaveBeenCalled();
    rerender(<QuickReplyLibrary onInsert={onInsert} disabled={false} shortcutQuery="ho" />);
    fireEvent.click(screen.getByRole("button", { name: "Inserir resposta Horários" }));
    expect(onInsert).toHaveBeenCalledExactlyOnceWith(agenda.body);
  });

  it("cria uma resposta para a equipe e impede a repetição do POST pendente", async () => {
    const pending = deferred<Response>();
    const fetchMock = setupApi({ write: () => pending.promise });
    render(<QuickReplyLibrary onInsert={vi.fn()} disabled={false} />);
    await manage();
    fillNewReply();
    fireEvent.click(screen.getByRole("button", { name: "Salvar resposta" }));
    fireEvent.click(screen.getByRole("button", { name: "Salvando..." }));
    const writes = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(writes).toHaveLength(1);
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
      title: "Contato inicial", shortcut: "contato", category: "Geral", body: "Informe o nome da clínica.",
    });
    await act(async () => pending.resolve(json({ data: { ...original, id: "4", title: "Contato inicial", shortcut: "contato" } }, 201)));
    expect(await screen.findByText("Resposta salva para a equipe.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inserir resposta Contato inicial" })).toBeInTheDocument();
    expect(screen.getByLabelText("Título")).toHaveValue("");
  });

  it("preserva a edição em conflito e só carrega a versão da equipe por ação explícita", async () => {
    const newest = { ...original, body: "Texto atualizado por outra pessoa", updated_at: "2026-09-08T10:01:00.000Z" };
    let conflicted = false;
    const fetchMock = setupApi({ write: (_path, init) => {
      if (!conflicted) {
        conflicted = true;
        return json({ code: "QUICK_REPLY_STALE", error: "Outra pessoa alterou esta resposta.", data: newest }, 409);
      }
      return json({ data: { ...newest, ...JSON.parse(String(init.body)) } });
    } });
    render(<QuickReplyLibrary onInsert={vi.fn()} disabled={false} />);
    await manage();
    fireEvent.click(screen.getByRole("button", { name: "Editar resposta Saudação" }));
    fireEvent.change(screen.getByLabelText(/Texto da resposta/), { target: { value: "Minha edição local" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar resposta" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Outra pessoa alterou esta resposta.");
    expect(screen.getByLabelText(/Texto da resposta/)).toHaveValue("Minha edição local");
    const firstPatch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(String(firstPatch?.[1]?.body)).expected_updated_at).toBe(original.updated_at);
    fireEvent.click(screen.getByRole("button", { name: "Carregar versão da equipe" }));
    expect(screen.getByLabelText(/Texto da resposta/)).toHaveValue(newest.body);
    fireEvent.click(screen.getByRole("button", { name: "Salvar resposta" }));
    await screen.findByText("Resposta salva para a equipe.");
    const lastPatch = fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH").at(-1);
    expect(JSON.parse(String(lastPatch?.[1]?.body)).expected_updated_at).toBe(newest.updated_at);
  });

  it("desativa sem excluir e permite reativar a resposta no cadastro", async () => {
    const fetchMock = setupApi({ write: (_path, init) => json({ data: {
      ...original, active: JSON.parse(String(init.body)).active, updated_at: "2026-09-08T10:01:00.000Z",
    } }) });
    render(<QuickReplyLibrary onInsert={vi.fn()} disabled={false} />);
    await manage();
    fireEvent.click(screen.getByRole("button", { name: "Desativar resposta Saudação" }));
    await screen.findByText("Resposta desativada e preservada no cadastro.");
    expect(screen.queryByRole("button", { name: "Inserir resposta Saudação" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar resposta Saudação" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reativar resposta Saudação" }));
    await screen.findByText("Resposta reativada.");
    expect(screen.getByRole("button", { name: "Inserir resposta Saudação" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  });

  it("permite recuperar falha de leitura e preserva texto quando a escrita falha na rede", async () => {
    let unavailable = true;
    setupApi({
      list: () => unavailable ? json({}, 503) : json({ data: [original] }),
      write: () => Promise.reject(new TypeError("Sem conexão")),
    });
    render(<QuickReplyLibrary onInsert={vi.fn()} disabled={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar");
    unavailable = false;
    fireEvent.click(screen.getByRole("button", { name: "Atualizar biblioteca" }));
    await manage();
    fillNewReply();
    fireEvent.click(screen.getByRole("button", { name: "Salvar resposta" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível confirmar a alteração"));
    expect(screen.getByLabelText("Título")).toHaveValue("Contato inicial");
    expect(screen.getByLabelText(/Texto da resposta/)).toHaveValue("Informe o nome da clínica.");
    expect(screen.getByRole("button", { name: "Salvar resposta" })).toBeEnabled();
  });

  it("não deixa uma leitura antiga apagar uma resposta salva enquanto a biblioteca atualizava", async () => {
    const lateRead = deferred<Response>();
    let reads = 0;
    setupApi({
      list: () => ++reads === 1 ? json({ data: [original] }) : lateRead.promise,
      write: () => json({ data: { ...original, id: "4", title: "Contato inicial", shortcut: "contato" } }, 201),
    });
    render(<QuickReplyLibrary onInsert={vi.fn()} disabled={false} />);
    await manage();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar biblioteca" }));
    fillNewReply();
    fireEvent.click(screen.getByRole("button", { name: "Salvar resposta" }));
    await screen.findByText("Resposta salva para a equipe.");
    await act(async () => lateRead.resolve(json({ data: [original] })));
    expect(screen.getByRole("button", { name: "Inserir resposta Contato inicial" })).toBeInTheDocument();
  });

  it("recusa atalho inválido localmente e mantém o cadastro ao receber erro de permissão", async () => {
    const fetchMock = setupApi({ write: () => json({ error: "Seu perfil não permite alterar a biblioteca." }, 403) });
    render(<QuickReplyLibrary onInsert={vi.fn()} disabled={false} />);
    await manage();
    fillNewReply();
    fireEvent.change(screen.getByLabelText("Atalho sem barra"), { target: { value: "/contato" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar resposta" }));
    expect(screen.getByRole("alert")).toHaveTextContent("sem a barra");
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Atalho sem barra"), { target: { value: "contato" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar resposta" }));
    expect(await screen.findByText("Seu perfil não permite alterar a biblioteca.")).toBeInTheDocument();
    expect(screen.getByLabelText("Título")).toHaveValue("Contato inicial");
  });
});
