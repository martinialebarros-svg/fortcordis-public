import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FinanceiroPage from "./page";

const mocks = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), router: { push: vi.fn() } }));
vi.mock("../layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, patch: mocks.patch, post: mocks.post, put: mocks.put, delete: mocks.delete } }));
vi.mock("./TransacaoModal", () => ({ default: () => null }));

function result(description: string, total = 205) {
  return { data: { total, items: [{ id: 1, descricao: description, categoria: "consulta", tipo: "entrada", status: "Pago", valor_final: 10, data_transacao: "2026-09-13", forma_pagamento: "pix" }] } };
}
function setupReads(transactions: (url: string) => unknown) {
  mocks.get.mockImplementation((url: string) => {
    if (url.startsWith("/financeiro/transacoes?")) return transactions(url);
    if (url.startsWith("/financeiro/resumo")) return Promise.resolve({ data: { entradas: 999, saidas: 0, saldo: 999 } });
    return Promise.resolve({ data: { items: [] } });
  });
}
const searchInput = () => screen.getByRole("textbox");

const osItem = (id: number) => ({ id, numero_os: `OS-${id}`, status: "Pendente", valor_final: 10,
  data_atendimento: "2026-09-15", paciente: "Paciente sintetico", tutor: "Tutor sintetico", clinica: "Clinica sintetica", servico: "Servico sintetico" });

describe("Cobrancas remote groups", () => {
  const group = { chave: "clinica:1", nome_destinatario: "Clinica sintetica", tipo_destinatario: "clinica", quantidade_total: 101, quantidade_os: 101, total_pendente: 1010 };
  beforeEach(() => {
    mocks.get.mockReset(); mocks.patch.mockReset(); mocks.post.mockReset();
    localStorage.setItem("token", "synthetic-test");
    window.history.replaceState({}, "", "/financeiro?aba=cobrancas");
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/ordens-servico/cobrancas?")) return { data: { total: 51, total_os: 151, pendentes: 151, total_pendente: 1510, items: [group] } };
      if (url.startsWith("/ordens-servico?")) {
        const skip = Number(new URL(url, "http://test").searchParams.get("skip"));
        return { data: { total: 101, resumo: { pendentes: 101, valor_pendente: 1010 }, items: Array.from({ length: skip ? 1 : 100 }, (_, i) => ({ ...osItem(skip + i + 1), clinica_id: 1 })) } };
      }
      return { data: { items: [] } };
    });
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); window.history.replaceState({}, "", "/"); });
  it("initially loads only recipient summaries and pages remotely", async () => {
    render(<FinanceiroPage />);
    await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" });
    expect(mocks.get.mock.calls.some(([url]) => url.startsWith("/ordens-servico?"))).toBe(false);
    expect(screen.queryByRole("button", { name: "Receber pendentes" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([url]) => url.includes("cobrancas?") && url.includes("skip=50"))).toBe(true));
  });
  it("expands pending orders directly below the recipient row and collapses them", async () => {
    const compactGroup = { ...group, quantidade_total: 2, quantidade_os: 1, total_pendente: 10 };
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/ordens-servico/cobrancas?")) {
        return { data: { total: 1, total_os: 2, pendentes: 1, total_pendente: 10, items: [compactGroup] } };
      }
      if (url.startsWith("/ordens-servico?")) {
        return {
          data: {
            total: 2,
            resumo: { pendentes: 1, valor_pendente: 10 },
            items: [
              { ...osItem(1), clinica_id: 1 },
              { ...osItem(2), clinica_id: 1, status: "Pago" },
            ],
          },
        };
      }
      return { data: { items: [] } };
    });

    render(<FinanceiroPage />);
    const recipient = await screen.findByRole("region", { name: "Cobrancas de Clinica sintetica" });
    const open = within(recipient).getByRole("button", { name: "Abrir destinatario Clinica sintetica" });
    expect(open).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(open);

    expect(await within(recipient).findByText("OS #OS-1")).toBeInTheDocument();
    expect(within(recipient).queryByText("OS #OS-2")).not.toBeInTheDocument();
    const close = within(recipient).getByRole("button", { name: "Fechar destinatario Clinica sintetica" });
    expect(close).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(close);

    expect(within(recipient).queryByText("OS #OS-1")).not.toBeInTheDocument();
    expect(mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/ordens-servico?")).length).toBe(1);
  });
  it("refreshes only recipient summaries without restarting independent reads", async () => {
    render(<FinanceiroPage />);
    await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" });
    const refresh = screen.getByRole("button", { name: "Atualizar destinatarios" });
    await waitFor(() => expect(refresh).toBeEnabled());

    const count = (prefix: string) => mocks.get.mock.calls.filter(([url]) => String(url).startsWith(prefix)).length;
    const before = {
      cobrancas: count("/ordens-servico/cobrancas?"),
      resumo: count("/financeiro/resumo"),
      clinicas: count("/clinicas?"),
      servicos: count("/servicos?"),
      formas: count("/financeiro/formas-pagamento"),
      bandeiras: count("/financeiro/bandeiras-cartao"),
    };

    fireEvent.click(refresh);
    await waitFor(() => expect(count("/ordens-servico/cobrancas?")).toBe(before.cobrancas + 1));
    expect(count("/financeiro/resumo")).toBe(before.resumo);
    expect(count("/clinicas?")).toBe(before.clinicas);
    expect(count("/servicos?")).toBe(before.servicos);
    expect(count("/financeiro/formas-pagamento")).toBe(before.formas);
    expect(count("/financeiro/bandeiras-cartao")).toBe(before.bandeiras);
  });
  it("unlocks actions only after all recipient rows are loaded", async () => {
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" }));
    await screen.findByRole("button", { name: "Receber pendentes" });
    expect(mocks.get.mock.calls.some(([url]) => url.includes("destinatario_chave=clinica%3A1") && url.includes("skip=100"))).toBe(true);
    expect(mocks.patch).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled();
  });
  it("keeps actions unavailable when a later batch fails", async () => {
    const read = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url, options) => url.startsWith("/ordens-servico?") && url.includes("skip=100") ? Promise.reject(new Error("lote indisponivel")) : read(url, options));
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" }));
    await screen.findByText("lote indisponivel");
    expect(screen.queryByRole("button", { name: "Receber pendentes" })).not.toBeInTheDocument();
    expect(mocks.patch).not.toHaveBeenCalled(); expect(mocks.post).not.toHaveBeenCalled();
  });
  it("discards late detail results after changing the search", async () => {
    const read = mocks.get.getMockImplementation()!;
    let finish!: (value: unknown) => void;
    const late = new Promise((resolve) => { finish = resolve; });
    mocks.get.mockImplementation((url, options) => url.startsWith("/ordens-servico?") && url.includes("skip=100") ? late : read(url, options));
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([url]) => url.startsWith("/ordens-servico?") && url.includes("skip=100"))).toBe(true));
    fireEvent.change(screen.getByPlaceholderText(/Buscar/), { target: { value: "outra" } });
    await waitFor(() => expect(mocks.get.mock.calls.some(([url]) => url.includes("cobrancas?") && url.includes("search=outra"))).toBe(true));
    await act(async () => { finish({ data: { total: 101, resumo: { pendentes: 101, valor_pendente: 1010 }, items: [{ ...osItem(101), clinica_id: 1 }] } }); });
    expect(screen.queryByRole("button", { name: "Receber pendentes" })).not.toBeInTheDocument();
  });
});

describe("Ordens pagination", () => {
  beforeEach(() => {
    mocks.get.mockReset(); mocks.patch.mockReset(); mocks.post.mockReset();
    localStorage.setItem("token", "synthetic-test");
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/ordens-servico?")) return { data: { total: 201, items: [osItem(url.includes("skip=100") ? 101 : 1)], resumo: { pendentes: 201, valor_pendente: 2010 } } };
      if (/^\/ordens-servico\/\d+$/.test(url)) return { data: osItem(Number(url.split("/").pop())) };
      return { data: { items: [] } };
    });
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); window.history.replaceState({}, "", "/"); });

  it("retains selection across pages and validates every selected id", async () => {
    render(<FinanceiroPage />);
    await screen.findByText("OS #OS-1");
    fireEvent.click(screen.getByRole("button", { name: "Selecionar pendentes" }));
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    await screen.findByText("OS #OS-101");
    expect(screen.queryByText("OS #OS-1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Selecionar pendentes" }));
    expect(screen.getByText(/2 selecionada\(s\) para baixa/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Receber selecionadas" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/ordens-servico/101"));
    expect(mocks.get).toHaveBeenCalledWith("/ordens-servico/1");
    expect(mocks.patch).not.toHaveBeenCalled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("blocks changed selection without submitting a payment", async () => {
    const read = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation(async (url, options) => url === "/ordens-servico/1" ? { data: { ...osItem(1), valor_final: 20 } } : read(url, options));
    render(<FinanceiroPage />);
    await screen.findByText("OS #OS-1");
    fireEvent.click(screen.getByRole("button", { name: "Selecionar pendentes" }));
    fireEvent.click(screen.getByRole("button", { name: "Receber selecionadas" }));
    expect(await screen.findByText(/Uma OS mudou desde a selecao/)).toBeInTheDocument();
    expect(mocks.patch).not.toHaveBeenCalled();
  });

  it("searches remotely and clears selection when filters change", async () => {
    render(<FinanceiroPage />);
    await screen.findByText("OS #OS-1");
    fireEvent.click(screen.getByRole("button", { name: "Selecionar pendentes" }));
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    await screen.findByText("OS #OS-101");
    fireEvent.change(screen.getByPlaceholderText(/Buscar/), { target: { value: "antiga" } });
    await waitFor(() => expect(mocks.get.mock.calls.some(([url]) => url.includes("skip=0") && url.includes("search=antiga"))).toBe(true));
    expect(await screen.findByText(/0 selecionada\(s\) para baixa/)).toBeInTheDocument();
  });

  it("requests a deep-linked OS by id instead of depending on the first page", async () => {
    window.history.replaceState({}, "", "/financeiro?os_id=900");
    render(<FinanceiroPage />);
    await waitFor(() => expect(mocks.get.mock.calls.some(([url]) => url.includes("os_id=900"))).toBe(true));
  });

  it("keeps failed page distinct from empty and retries without exposing stale rows", async () => {
    let fail = true;
    const read = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation(async (url, options) => {
      if (url.includes("skip=100") && fail) throw new Error("offline");
      return read(url, options);
    });
    render(<FinanceiroPage />);
    await screen.findByText("OS #OS-1");
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    await screen.findByText("Nao foi possivel carregar as ordens.");
    expect(screen.queryByText("OS #OS-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Nenhuma ordem de servico encontrada")).not.toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Recarregar ordens" }));
    await screen.findByText("OS #OS-101");
  });

  it("discards a late page response after remote search", async () => {
    let resolvePage!: (value: unknown) => void;
    const read = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url, options) => url.includes("skip=100") ? new Promise((resolve) => { resolvePage = resolve; }) : read(url, options));
    render(<FinanceiroPage />);
    await screen.findByText("OS #OS-1");
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    await waitFor(() => expect(resolvePage).toBeDefined());
    fireEvent.change(screen.getByPlaceholderText(/Buscar/), { target: { value: "antiga" } });
    await screen.findByText("OS #OS-1");
    await act(async () => resolvePage({ data: { total: 201, items: [osItem(101)], resumo: { pendentes: 201, valor_pendente: 2010 } } }));
    expect(screen.queryByText("OS #OS-101")).not.toBeInTheDocument();
  });
});

describe("Desfazer recebimento de OS", () => {
  let ordemAtual: ReturnType<typeof osItem>;

  beforeEach(() => {
    mocks.get.mockReset(); mocks.patch.mockReset(); mocks.post.mockReset();
    localStorage.setItem("token", "synthetic-test");
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    ordemAtual = { ...osItem(21), status: "Pago", valor_final: 180 };
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/ordens-servico?")) return {
        data: {
          total: 1, items: [{ ...ordemAtual }],
          resumo: {
            pendentes: ordemAtual.status === "Pendente" ? 1 : 0,
            valor_pendente: ordemAtual.status === "Pendente" ? ordemAtual.valor_final : 0,
          },
        },
      };
      if (url === "/ordens-servico/21") return { data: { ...ordemAtual } };
      return { data: { items: [] } };
    });
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); window.history.replaceState({}, "", "/"); });

  const abrirDesfazer = async () => {
    render(<FinanceiroPage />);
    const abrir = await screen.findByRole("button", { name: "Desfazer" });
    abrir.focus();
    fireEvent.click(abrir);
    return screen.findByRole("alertdialog", { name: "Desfazer recebimento?" });
  };

  it("identifica o recebimento e permite cancelar sem enviar a reversao", async () => {
    const modal = await abrirDesfazer();

    expect(modal).toHaveAttribute("aria-modal", "true");
    expect(within(modal).getByText(/OS-21/)).toBeInTheDocument();
    expect(within(modal).getByText(/Paciente sintetico/)).toBeInTheDocument();
    expect(within(modal).getByText(/R\$\s*180,00/)).toBeInTheDocument();
    expect(within(modal).getByRole("button", { name: "Cancelar" })).toHaveFocus();
    expect(mocks.patch).not.toHaveBeenCalled();

    fireEvent.click(within(modal).getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Desfazer" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Desfazer" })).toHaveFocus();
    expect(mocks.patch).not.toHaveBeenCalled();
    expect(window.confirm).not.toHaveBeenCalled();
    expect(window.alert).not.toHaveBeenCalled();
  });

  it("cancela por Escape antes de confirmar sem alterar o recebimento", async () => {
    await abrirDesfazer();

    fireEvent.keyDown(document.activeElement || window, { key: "Escape" });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Desfazer" })).toBeEnabled();
    expect(mocks.patch).not.toHaveBeenCalled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("mantem o foco dentro da confirmacao ao navegar por Tab e Shift+Tab", async () => {
    const modal = await abrirDesfazer();
    const cancelar = within(modal).getByRole("button", { name: "Cancelar" });
    const confirmar = within(modal).getByRole("button", { name: "Desfazer recebimento" });

    confirmar.focus();
    fireEvent.keyDown(confirmar, { key: "Tab" });
    expect(cancelar).toHaveFocus();
    fireEvent.keyDown(cancelar, { key: "Tab", shiftKey: true });
    expect(confirmar).toHaveFocus();
    expect(mocks.patch).not.toHaveBeenCalled();
  });

  it("bloqueia repeticoes enquanto processa e atualiza a OS apos uma unica reversao", async () => {
    let concluir!: (value: unknown) => void;
    mocks.patch.mockImplementation(() => new Promise((resolve) => { concluir = resolve; }));
    const modal = await abrirDesfazer();
    const confirmar = within(modal).getByRole("button", { name: "Desfazer recebimento" });
    const leiturasAntes = mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/ordens-servico?")).length;

    act(() => {
      fireEvent.click(confirmar);
      fireEvent.click(confirmar);
    });

    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1));
    expect(mocks.patch).toHaveBeenCalledWith("/ordens-servico/21/desfazer-recebimento");
    expect(within(modal).getByRole("button", { name: "Desfazendo..." })).toBeDisabled();
    expect(within(modal).getByRole("button", { name: "Cancelar" })).toBeDisabled();
    fireEvent.keyDown(document.activeElement || window, { key: "Escape" });
    expect(screen.getByRole("alertdialog", { name: "Desfazer recebimento?" })).toBeInTheDocument();
    expect(screen.queryByText("Recebimento da OS OS-21 desfeito com sucesso.")).not.toBeInTheDocument();

    await act(async () => {
      ordemAtual = { ...ordemAtual, status: "Pendente" };
      concluir({ data: { mensagem: "Recebimento desfeito com sucesso.", os_id: 21, status: "Pendente" } });
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Recebimento da OS OS-21 desfeito com sucesso.");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Receber" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Desfazer" })).not.toBeInTheDocument();
    expect(mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/ordens-servico?")).length).toBeGreaterThan(leiturasAntes);
    expect(mocks.patch).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(window.confirm).not.toHaveBeenCalled();
    expect(window.alert).not.toHaveBeenCalled();
  });

  it("mantem a confirmacao e mostra o detalhe da API quando a reversao falha", async () => {
    mocks.patch.mockRejectedValueOnce({ response: { status: 409, data: { detail: "A OS sintetica mudou. Confira o recebimento atual." } } });
    const modal = await abrirDesfazer();

    fireEvent.click(within(modal).getByRole("button", { name: "Desfazer recebimento" }));

    expect(await within(modal).findByRole("alert")).toHaveTextContent("A OS sintetica mudou. Confira o recebimento atual.");
    expect(screen.getByRole("alertdialog", { name: "Desfazer recebimento?" })).toBeInTheDocument();
    expect(within(modal).getByRole("button", { name: "Desfazer recebimento" })).toBeEnabled();
    expect(within(modal).getByRole("button", { name: "Cancelar" })).toBeEnabled();
    expect(screen.queryByText("Recebimento da OS OS-21 desfeito com sucesso.")).not.toBeInTheDocument();
    expect(mocks.patch).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(window.confirm).not.toHaveBeenCalled();
    expect(window.alert).not.toHaveBeenCalled();
  });
});

describe("Ordens vinculadas a laudos", () => {
  let ordem: ReturnType<typeof osItem> & { laudo_id?: number; clinica_id: number; servico_id: number };
  beforeEach(() => {
    mocks.get.mockReset(); mocks.put.mockReset(); mocks.delete.mockReset();
    mocks.put.mockResolvedValue({ data: {} }); mocks.delete.mockResolvedValue({ data: {} });
    localStorage.setItem("token", "synthetic-test");
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    ordem = { ...osItem(1), laudo_id: 20, clinica_id: 1, servico_id: 1 };
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/ordens-servico?")) return { data: { total: 1, items: [ordem], resumo: { pendentes: ordem.status === "Pendente" ? 1 : 0, valor_pendente: ordem.status === "Pendente" ? 10 : 0 } } };
      if (url.startsWith("/clinicas?")) return { data: { total: 1, items: [{ id: 1, nome: "Clinica sintetica" }] } };
      if (url.startsWith("/servicos?")) return { data: { items: [{ id: 1, nome: "Servico sintetico" }] } };
      return { data: { items: [] } };
    });
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); window.history.replaceState({}, "", "/"); });

  it("cancela a pendencia preservando a OS e o laudo", async () => {
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar OS" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/ordens-servico/1", { status: "Cancelado" }));
    expect(mocks.delete).not.toHaveBeenCalled();
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("laudo e o historico"));
  });

  it("exige desfazer recebimento antes de cancelar a OS paga", async () => {
    ordem.status = "Pago";
    render(<FinanceiroPage />);
    expect(await screen.findByRole("button", { name: "Cancelar OS" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Desfazer" })).toBeEnabled();
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.delete).not.toHaveBeenCalled();
  });

  it("preserva a exclusao das OS sem vinculo com laudo", async () => {
    delete ordem.laudo_id;
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Excluir OS" }));
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith("/ordens-servico/1"));
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("mantem a clinica vinculada ao editar OS ativa de laudo", async () => {
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    expect(screen.getByRole("combobox", { name: "Clinica da OS" })).toBeDisabled();
  });
});

describe("Ajuste de valor de OS pendente", () => {
  let ordemAtual: ReturnType<typeof osItem> & {
    clinica_id: number; servico_id: number; tipo_horario: string;
    valor_servico: number; desconto: number; observacoes: string;
  };

  beforeEach(() => {
    mocks.get.mockReset(); mocks.patch.mockReset(); mocks.put.mockReset(); mocks.post.mockReset();
    window.localStorage.setItem("token", "synthetic-test");
    window.history.replaceState({}, "", "/financeiro?aba=cobrancas");
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    ordemAtual = {
      ...osItem(1), clinica_id: 1, servico_id: 2, tipo_horario: "comercial",
      valor_servico: 110, desconto: 10, valor_final: 100, observacoes: "Original",
    };
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/ordens-servico/cobrancas?")) return {
        data: { total: 1, total_os: 1, pendentes: ordemAtual.status === "Pendente" ? 1 : 0,
          total_pendente: ordemAtual.status === "Pendente" ? ordemAtual.valor_final : 0,
          items: [{ chave: "clinica:1", nome_destinatario: "Clinica sintetica", tipo_destinatario: "clinica",
            quantidade_total: 1, quantidade_os: ordemAtual.status === "Pendente" ? 1 : 0,
            total_pendente: ordemAtual.status === "Pendente" ? ordemAtual.valor_final : 0 }] },
      };
      if (url.startsWith("/ordens-servico?")) return {
        data: { total: 1, items: [{ ...ordemAtual }],
          resumo: { pendentes: ordemAtual.status === "Pendente" ? 1 : 0,
            valor_pendente: ordemAtual.status === "Pendente" ? ordemAtual.valor_final : 0 } },
      };
      if (url === "/ordens-servico/1") return { data: { ...ordemAtual } };
      if (url.startsWith("/clinicas?")) return { data: { items: [{ id: 1, nome: "Clinica sintetica" }] } };
      if (url.startsWith("/servicos?")) return { data: { items: [{ id: 2, nome: "Servico sintetico" }] } };
      return { data: { items: [] } };
    });
    mocks.patch.mockImplementation(async (url: string, payload: { novo_valor_final: number }) => {
      if (url === "/ordens-servico/1/ajustar-valor") {
        ordemAtual = { ...ordemAtual, valor_final: payload.novo_valor_final,
          valor_servico: payload.novo_valor_final + ordemAtual.desconto };
      }
      return { data: { ...ordemAtual } };
    });
    mocks.put.mockResolvedValue({ data: {} });
  });
  afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); window.history.replaceState({}, "", "/"); });

  it("ajusta pela linha de Cobrancas, registra motivo e reabre o grupo com o novo total", async () => {
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" }));
    const grupo = await screen.findByRole("region", { name: "Cobrancas de Clinica sintetica" });
    fireEvent.click(within(grupo).getByTitle("Selecionar para baixa em lote"));
    fireEvent.click(within(grupo).getByRole("button", { name: "Ajustar valor da OS OS-1" }));
    const modal = await screen.findByRole("dialog", { name: "Ajustar valor da OS" });
    await waitFor(() => expect(within(modal).getByRole("textbox", { name: "Novo valor final (R$)" })).toHaveValue("100.00"));
    expect(mocks.get).toHaveBeenCalledWith("/ordens-servico/1");

    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar ajuste" }));
    expect(within(modal).getByRole("alert")).toHaveTextContent("O novo valor deve ser diferente");
    expect(mocks.patch).not.toHaveBeenCalled();
    fireEvent.change(within(modal).getByRole("textbox", { name: "Novo valor final (R$)" }), { target: { value: "95,001" } });
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar ajuste" }));
    expect(within(modal).getByRole("alert")).toHaveTextContent("ate duas casas decimais");
    fireEvent.change(within(modal).getByRole("textbox", { name: "Novo valor final (R$)" }), { target: { value: "99999999,99" } });
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar ajuste" }));
    expect(within(modal).getByRole("alert")).toHaveTextContent("somado ao desconto excede");
    fireEvent.change(within(modal).getByRole("textbox", { name: "Novo valor final (R$)" }), { target: { value: "95,00" } });
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar ajuste" }));
    expect(within(modal).getByRole("alert")).toHaveTextContent("Informe o motivo");
    fireEvent.change(within(modal).getByRole("textbox", { name: "Motivo do ajuste" }), { target: { value: "Correção do preço combinado" } });
    expect(within(modal).getByText(/Valor do serviço resultante/)).toHaveTextContent("R$ 105,00");
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar ajuste" }));

    await waitFor(() => expect(mocks.patch).toHaveBeenCalledWith("/ordens-servico/1/ajustar-valor", {
      valor_final_esperado: 100, novo_valor_final: 95, motivo: "Correção do preço combinado",
    }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Cobrancas de Clinica sintetica" }))
      .getByRole("button", { name: "Fechar destinatario Clinica sintetica" })).toHaveAttribute("aria-expanded", "true"));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Cobrancas de Clinica sintetica" }))
      .getAllByText(/R\$\s*95,00/)).toHaveLength(2));
    expect(within(screen.getByRole("region", { name: "Cobrancas de Clinica sintetica" }))
      .getByTitle("Selecionar para baixa em lote")).not.toBeChecked();
    expect(mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/ordens-servico/cobrancas?"))).toHaveLength(2);
    expect(mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/ordens-servico?"))).toHaveLength(2);
  });

  it("orienta recarregar após conflito e usa o novo valor como base", async () => {
    mocks.patch.mockImplementationOnce(async () => {
      ordemAtual = { ...ordemAtual, valor_final: 110 };
      throw { response: { status: 409 } };
    });
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ajustar valor da OS OS-1" }));
    const modal = await screen.findByRole("dialog", { name: "Ajustar valor da OS" });
    await waitFor(() => expect(within(modal).getByRole("textbox", { name: "Novo valor final (R$)" })).toHaveValue("100.00"));
    fireEvent.change(within(modal).getByRole("textbox", { name: "Novo valor final (R$)" }), { target: { value: "95" } });
    fireEvent.change(within(modal).getByRole("textbox", { name: "Motivo do ajuste" }), { target: { value: "Preço combinado" } });
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar ajuste" }));
    expect(await within(modal).findByRole("button", { name: "Recarregar OS" })).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "Recarregar OS" }));
    await waitFor(() => expect(within(modal).getByRole("textbox", { name: "Novo valor final (R$)" })).toHaveValue("110.00"));
  });

  it("mantem o preco ajustado ao editar somente observacoes", async () => {
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    fireEvent.change(screen.getByDisplayValue("Original"), { target: { value: "Nova observação" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar alteracoes" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/ordens-servico/1", { observacoes: "Nova observação" }));
    expect(mocks.put.mock.calls[0][1]).not.toHaveProperty("recalcular_preco");
    expect(ordemAtual.valor_final).toBe(100);
  });

  it("recebe individual com valor esperado da OS mesmo quando o pagamento excede esse valor", async () => {
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Receber" }));
    await screen.findByText("Receber Ordem de Servico");
    fireEvent.change(screen.getByDisplayValue("100.00"), { target: { value: "120.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar Recebimento" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledWith("/ordens-servico/1/receber", expect.objectContaining({
      valor_final_esperado: 100,
      pagamentos: [expect.objectContaining({ valor: 120 })],
      destino_credito_excedente: "cliente",
    })));
  });

  it("recarrega a OS e nao informa baixa individual quando o valor muda antes do PATCH", async () => {
    mocks.patch.mockImplementationOnce(async () => {
      ordemAtual = { ...ordemAtual, valor_final: 95 };
      throw { response: { status: 409, data: { detail: "O valor da OS mudou." } } };
    });
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Receber" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar Recebimento" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledWith("/ordens-servico/1/receber", expect.objectContaining({ valor_final_esperado: 100 })));
    await waitFor(() => expect(screen.queryByText("Receber Ordem de Servico")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText(/R\$\s*95,00/).length).toBeGreaterThanOrEqual(2));
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining("Nenhum recebimento foi registrado"));
    expect(window.alert).not.toHaveBeenCalledWith(expect.stringContaining("Recebimento registrado com sucesso"));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("envia o valor esperado de todas as OS em uma chamada e bloqueia o lote ao receber 409", async () => {
    const segunda = { ...ordemAtual, id: 2, numero_os: "OS-2", paciente: "Outro paciente" };
    const leituraOriginal = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/ordens-servico/2") return { data: { ...segunda } };
      const response = await leituraOriginal(url);
      if (url.startsWith("/ordens-servico/cobrancas?")) {
        return { data: { ...response.data, total_os: 2, pendentes: 2,
          total_pendente: ordemAtual.valor_final + segunda.valor_final,
          items: response.data.items.map((grupo: Record<string, unknown>) => ({ ...grupo, quantidade_total: 2,
            quantidade_os: 2, total_pendente: ordemAtual.valor_final + segunda.valor_final })) } };
      }
      if (url.startsWith("/ordens-servico?")) {
        return { data: { ...response.data, total: 2,
          items: [...response.data.items, { ...segunda }],
          resumo: { pendentes: 2, valor_pendente: ordemAtual.valor_final + segunda.valor_final } } };
      }
      return response;
    });
    mocks.patch.mockImplementationOnce(async () => {
      ordemAtual = { ...ordemAtual, valor_final: 95 };
      throw { response: { status: 409, data: { detail: "O valor da OS mudou." } } };
    });
    render(<FinanceiroPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Abrir destinatario Clinica sintetica" }));
    fireEvent.click(await screen.findByRole("button", { name: "Receber pendentes" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirmar baixa em lote" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledWith("/ordens-servico/receber-lote", expect.objectContaining({
      ordens: [{ os_id: 1, valor_final_esperado: "100.00" }, { os_id: 2, valor_final_esperado: "100.00" }],
      pagamentos: [expect.objectContaining({ valor: 200 })],
    })));
    const modal = screen.getByRole("dialog", { name: "Receber OS em lote" });
    expect(await within(modal).findByRole("alert")).toHaveTextContent("Nenhuma baixa deste lote foi registrada por esta operacao");
    expect(within(modal).getByRole("button", { name: "Confirmar baixa em lote" })).toBeDisabled();
    expect(within(modal).getByRole("spinbutton", { name: "Valor do pagamento 1" })).toHaveValue(200);
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Cobrancas de Clinica sintetica" }))
      .getAllByText(/R\$\s*195,00/)).toHaveLength(1));
    expect(mocks.patch).toHaveBeenCalledTimes(1);
    expect(window.alert).not.toHaveBeenCalledWith(expect.stringContaining("Baixa em lote registrada com sucesso"));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("nao oferece ajuste de valor para OS recebida", async () => {
    ordemAtual = { ...ordemAtual, status: "Pago" };
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    render(<FinanceiroPage />);
    await screen.findByText("OS #OS-1");
    expect(screen.queryByRole("button", { name: "Ajustar valor da OS OS-1" })).not.toBeInTheDocument();
  });
});

describe("Recebimento atomico em lote", () => {
  let ordens: Array<ReturnType<typeof osItem> & { clinica_id: number }>;

  beforeEach(() => {
    mocks.get.mockReset(); mocks.patch.mockReset(); mocks.post.mockReset();
    localStorage.setItem("token", "synthetic-test");
    window.history.replaceState({}, "", "/financeiro?aba=ordens");
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    ordens = [
      { ...osItem(1), clinica_id: 1, valor_final: 10.01 },
      { ...osItem(2), clinica_id: 1, valor_final: 20.02 },
    ];
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/ordens-servico?")) return { data: {
        total: ordens.length, items: ordens.map((os) => ({ ...os })),
        resumo: { pendentes: ordens.filter((os) => os.status === "Pendente").length, valor_pendente: 30.03 },
      } };
      if (/^\/ordens-servico\/\d+$/.test(url)) return { data: { ...ordens.find((os) => os.id === Number(url.split("/").pop())) } };
      return { data: { items: [] } };
    });
    mocks.post.mockResolvedValue({ data: { mensagem: "Recibo enviado" } });
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); window.history.replaceState({}, "", "/"); });

  const abrirLote = async () => {
    render(<FinanceiroPage />);
    await screen.findByText("OS #OS-1");
    fireEvent.click(screen.getByRole("button", { name: "Selecionar pendentes" }));
    fireEvent.click(screen.getByRole("button", { name: "Receber selecionadas" }));
    const modal = await screen.findByRole("dialog", { name: "Receber OS em lote" });
    fireEvent.click(within(modal).getByRole("checkbox", { name: /Enviar um recibo PDF consolidado/ }));
    return modal;
  };

  it("envia uma unica baixa com valores esperados e pagamentos integrais e aguarda todas as OS para pedir o recibo", async () => {
    let concluir!: (result: unknown) => void;
    mocks.patch.mockImplementation(() => new Promise((resolve) => { concluir = resolve; }));
    const modal = await abrirLote();
    fireEvent.change(within(modal).getByRole("spinbutton", { name: "Valor do pagamento 1" }), { target: { value: "15.01" } });
    fireEvent.click(within(modal).getByRole("button", { name: "+ Adicionar forma de pagamento" }));
    fireEvent.change(within(modal).getByRole("spinbutton", { name: "Valor do pagamento 2" }), { target: { value: "15.02" } });
    fireEvent.change(within(modal).getByLabelText("Data do Recebimento"), { target: { value: "2026-10-09" } });
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar baixa em lote" }));
    expect(mocks.patch).toHaveBeenCalledTimes(1);
    expect(mocks.patch).toHaveBeenCalledWith("/ordens-servico/receber-lote", {
      ordens: [{ os_id: 1, valor_final_esperado: "10.01" }, { os_id: 2, valor_final_esperado: "20.02" }],
      pagamentos: [expect.objectContaining({ valor: 15.01 }), expect.objectContaining({ valor: 15.02 })],
      data_recebimento: "2026-10-09",
    });
    expect(within(modal).getByRole("button", { name: "Recebendo..." })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
    await act(async () => concluir({ data: { os_ids: [2, 1], mensagem: "Lote recebido" } }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/ordens-servico/whatsapp/recibos-pdf", {
      os_ids: [2, 1], idempotency_key: expect.any(String),
    }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Receber OS em lote" })).not.toBeInTheDocument();
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining("Baixa em lote registrada e recibo PDF consolidado enviado"));
  });

  it.each(["Pago", "Cancelado"])("mantem o lote original e impede retry reduzido quando outra pessoa deixa uma OS %s", async (status) => {
    mocks.patch.mockImplementation(async () => {
      ordens[1] = { ...ordens[1], status };
      throw { response: { status: 409, data: { detail: "Uma OS deixou de estar pendente." } } };
    });
    const modal = await abrirLote();
    const confirmar = within(modal).getByRole("button", { name: "Confirmar baixa em lote" });
    fireEvent.click(confirmar);
    expect(await within(modal).findByRole("alert")).toHaveTextContent("Nenhuma baixa deste lote foi registrada por esta operacao");
    await waitFor(() => expect(mocks.get.mock.calls.filter(([url]) => url.startsWith("/ordens-servico?"))).toHaveLength(2));
    expect(within(modal).getByText("2 OS selecionada(s) para este lote")).toBeInTheDocument();
    expect(within(modal).getByText(/OS OS-2 -/)).toBeInTheDocument();
    expect(within(modal).getByRole("spinbutton", { name: "Valor do pagamento 1" })).toHaveValue(30.03);
    expect(confirmar).toBeDisabled();
    fireEvent.click(confirmar);
    expect(mocks.patch).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(within(modal).getByRole("button", { name: "Fechar e revisar selecao" }));
    expect(screen.getByText(/0 selecionada\(s\) para baixa/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Receber selecionadas" })).toBeDisabled();
  });

  it("preserva o modal, a data e os pagamentos em uma recusa e nao pede recibo", async () => {
    mocks.patch.mockRejectedValue({ response: { status: 422, data: { detail: "Forma de pagamento indisponivel." } } });
    const modal = await abrirLote();
    fireEvent.change(within(modal).getByLabelText("Data do Recebimento"), { target: { value: "2026-10-09" } });
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar baixa em lote" }));
    expect(await within(modal).findByRole("alert")).toHaveTextContent("Forma de pagamento indisponivel");
    expect(within(modal).getByLabelText("Data do Recebimento")).toHaveValue("2026-10-09");
    expect(within(modal).getByRole("spinbutton", { name: "Valor do pagamento 1" })).toHaveValue(30.03);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(window.alert).not.toHaveBeenCalled();
  });

  it.each([undefined, 500])("nao afirma rollback em falha com resultado desconhecido (HTTP %s)", async (status) => {
    mocks.patch.mockRejectedValue(status ? { response: { status } } : new Error("timeout"));
    const modal = await abrirLote();
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar baixa em lote" }));
    const alerta = await within(modal).findByRole("alert");
    expect(alerta).toHaveTextContent("O lote pode ter sido registrado");
    expect(alerta).not.toHaveTextContent("Nenhuma baixa");
    expect(within(modal).getByRole("button", { name: "Confirmar baixa em lote" })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(window.alert).not.toHaveBeenCalled();
  });

  it.each([[1], [1, 1], [1, 3], []])("nao pede recibo quando a resposta nao confirma a selecao completa: %j", async (...osIds) => {
    mocks.patch.mockResolvedValue({ data: { os_ids: osIds, mensagem: "Lote recebido" } });
    const modal = await abrirLote();
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar baixa em lote" }));
    expect(await within(modal).findByRole("alert")).toHaveTextContent("Nao foi possivel confirmar o recebimento de todas as OS");
    expect(within(modal).getByRole("button", { name: "Confirmar baixa em lote" })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(window.alert).not.toHaveBeenCalled();
  });

  it("mantem a baixa confirmada quando apenas o envio do recibo falha", async () => {
    mocks.patch.mockResolvedValue({ data: { os_ids: [1, 2], mensagem: "Lote recebido" } });
    mocks.post.mockRejectedValue(new Error("timeout no recibo"));
    const modal = await abrirLote();
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar baixa em lote" }));
    await waitFor(() => expect(window.alert).toHaveBeenCalledWith(expect.stringContaining("Baixa em lote registrada com sucesso.")));
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining("nao foi possivel confirmar o envio do recibo"));
    expect(mocks.patch).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Receber OS em lote" })).not.toBeInTheDocument();
  });

  it("bloqueia o recibo automatico acima de vinte OS e permite a baixa integral", async () => {
    ordens = Array.from({ length: 21 }, (_, index) => ({ ...osItem(index + 1), clinica_id: 1 }));
    mocks.patch.mockResolvedValue({ data: { os_ids: ordens.map((os) => os.id), mensagem: "Lote recebido" } });
    const modal = await abrirLote();
    expect(within(modal).getByRole("checkbox", { name: /Enviar um recibo PDF consolidado/ })).toBeDisabled();
    expect(within(modal).getByText(/permite no maximo 20 OS por vez/)).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar baixa em lote" }));
    await waitFor(() => expect(window.alert).toHaveBeenCalledWith("Baixa em lote registrada com sucesso!"));
    expect(mocks.patch).toHaveBeenCalledWith("/ordens-servico/receber-lote", expect.objectContaining({
      ordens: ordens.map((os) => ({ os_id: os.id, valor_final_esperado: "10.00" })),
    }));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("mantem o erro e a selecao original quando a recarga apos conflito tambem falha", async () => {
    const modal = await abrirLote();
    const read = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url: string, options) => url.startsWith("/ordens-servico?")
      ? Promise.reject(new Error("Lista indisponivel")) : read(url, options));
    mocks.patch.mockRejectedValue({ response: { status: 409 } });
    fireEvent.click(within(modal).getByRole("button", { name: "Confirmar baixa em lote" }));
    expect(await within(modal).findByRole("alert")).toHaveTextContent("Nenhuma baixa deste lote foi registrada por esta operacao");
    await screen.findByText("Nao foi possivel carregar as ordens.");
    expect(within(modal).getByText(/OS OS-2 -/)).toBeInTheDocument();
    expect(within(modal).getByRole("button", { name: "Confirmar baixa em lote" })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("limita o formulario a vinte pagamentos", async () => {
    const modal = await abrirLote();
    const adicionar = within(modal).getByRole("button", { name: "+ Adicionar forma de pagamento" });
    for (let i = 1; i < 20; i += 1) fireEvent.click(adicionar);
    expect(within(modal).getAllByRole("spinbutton")).toHaveLength(20);
    expect(adicionar).toBeDisabled();
    expect(mocks.patch).not.toHaveBeenCalled();
  });
});

describe("Financeiro transaction pagination", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    window.localStorage.setItem("token", "synthetic-test");
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); });

  it("uses server totals, pages, and resets remote search to the first page", async () => {
    setupReads((url) => Promise.resolve(url.includes("search=rex") ? result("Rex remoto", 1) : result(url.includes("skip=100") ? "Segunda pagina" : "Primeira pagina")));
    render(<FinanceiroPage />);
    expect(await screen.findByText("Primeira pagina")).toBeInTheDocument();
    expect(screen.getByText(/Pagina 1 de 3/)).toBeInTheDocument();
    expect(screen.getAllByText(/999,00/).length).toBeGreaterThan(0);
    expect(mocks.get).toHaveBeenCalledWith("/financeiro/transacoes?limit=100&skip=0", expect.anything());
    expect(mocks.get.mock.calls.some(([url]) => url.startsWith("/ordens-servico"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    expect(await screen.findByText("Segunda pagina")).toBeInTheDocument();
    fireEvent.change(searchInput(), { target: { value: "rex" } });
    expect(screen.queryByText("Segunda pagina")).not.toBeInTheDocument();
    expect(await screen.findByText("Rex remoto")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/financeiro/transacoes?limit=100&skip=0&search=rex", expect.anything());
    expect(screen.getByRole("button", { name: "Proxima" })).toBeDisabled();
  });

  it("shows a retryable failure instead of stale rows or a false empty result", async () => {
    let fail = true;
    setupReads(() => fail ? Promise.reject(new Error("timeout")) : Promise.resolve(result("Recuperada", 1)));
    render(<FinanceiroPage />);
    expect(await screen.findByText("Nao foi possivel carregar as transacoes.")).toBeInTheDocument();
    expect(screen.queryByText("Nenhuma transacao encontrada")).not.toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Recarregar transacoes" }));
    expect(await screen.findByText("Recuperada")).toBeInTheDocument();
  });

  it("discards a delayed response superseded by a new search", async () => {
    let resolveOld!: (value: ReturnType<typeof result>) => void;
    setupReads((url) => url.includes("search=rex") ? Promise.resolve(result("Atual", 1)) : new Promise((resolve) => { resolveOld = resolve; }));
    const view = render(<FinanceiroPage />);
    await waitFor(() => expect(resolveOld).toBeDefined());
    const oldSignal = mocks.get.mock.calls.find(([url]) => url.startsWith("/financeiro/transacoes"))?.[1].signal;
    fireEvent.change(searchInput(), { target: { value: "rex" } });
    expect(await screen.findByText("Atual")).toBeInTheDocument();
    expect(oldSignal.aborted).toBe(true);
    await act(async () => resolveOld(result("Obsoleta")));
    expect(screen.queryByText("Obsoleta")).not.toBeInTheDocument();
    view.unmount();
  });

  it("returns to a valid page when the last page disappears", async () => {
    setupReads((url) => Promise.resolve(url.includes("skip=100") ? { data: { total: 100, items: [] } } : result("Pagina valida", 101)));
    render(<FinanceiroPage />);
    await screen.findByText("Pagina valida");
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    await waitFor(() => expect(mocks.get.mock.calls.filter(([url]) => url === "/financeiro/transacoes?limit=100&skip=0")).toHaveLength(2));
    expect(await screen.findByText("Pagina valida")).toBeInTheDocument();
  });

  it("resets date filters before requesting and shows a confirmed empty result", async () => {
    setupReads((url) => Promise.resolve(url.includes("data_inicio=") ? { data: { total: 0, items: [] } } : result("Sem filtro")));
    const view = render(<FinanceiroPage />);
    await screen.findByText("Sem filtro");
    fireEvent.click(screen.getByRole("button", { name: "Proxima" }));
    await waitFor(() => expect(screen.getByText(/Pagina 2 de 3/)).toBeInTheDocument());
    fireEvent.change(view.container.querySelector('input[type="date"]')!, { target: { value: "2026-09-01" } });
    expect(await screen.findByText("Nenhuma transacao encontrada")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/financeiro/transacoes?limit=100&skip=0&data_inicio=2026-09-01", expect.anything());
    expect(screen.getByText(/Pagina 1 de 1/)).toBeInTheDocument();
  });

  it("keeps successful transactions available when an independent section fails", async () => {
    setupReads(() => Promise.resolve(result("Disponivel", 1)));
    const original = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url, options) => url.startsWith("/financeiro/resumo") ? Promise.reject(new Error("summary timeout")) : original(url, options));
    render(<FinanceiroPage />);
    expect(await screen.findByText("Disponivel")).toBeInTheDocument();
    expect(screen.getByText(/Secoes indisponiveis: Resumo financeiro/)).toBeInTheDocument();
  });
});
