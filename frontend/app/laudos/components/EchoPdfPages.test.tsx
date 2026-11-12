import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EchoPdfPages from "./EchoPdfPages";

const mocks = vi.hoisted(() => ({ getDocument: vi.fn(), GlobalWorkerOptions: { workerSrc: "" } }));
vi.mock("pdfjs-dist/legacy/build/pdf.mjs", () => mocks);
const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const BYTES = [37, 80, 68, 70, 45, 49, 46, 52];
const blob = () => Object.assign(new Blob([new Uint8Array(BYTES)], { type: "application/pdf" }), {
  arrayBuffer: vi.fn(async () => new Uint8Array(BYTES).buffer),
});
const page = () => ({
  getViewport: vi.fn(({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale })),
  render: vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() })), cleanup: vi.fn(),
});
const document = () => {
  const pages = [page(), page(), page()];
  return { numPages: 3, getPage: vi.fn(async (number: number) => pages[number - 1]), pages };
};
const task = (pdf = document()) => ({ promise: Promise.resolve(pdf), destroy: vi.fn(async () => {}) });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getDocument.mockImplementation(() => task());
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("páginas PDF renderizadas sem plug-in nativo", () => {
  it("carrega sob demanda biblioteca/worker locais e desenha somente a primeira página", async () => {
    const pdf = document(); mocks.getDocument.mockReturnValue(task(pdf));
    render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toHaveClass("invisible"));
    expect(screen.getByText("Página 1 de 3")).toBeInTheDocument();
    expect(pdf.getPage).toHaveBeenCalledTimes(1); expect(pdf.getPage).toHaveBeenCalledWith(1);
    expect(pdf.pages[0].render).toHaveBeenCalledWith(expect.objectContaining({ canvas: expect.any(HTMLCanvasElement) }));
    expect(pdf.pages[1].render).not.toHaveBeenCalled();
    expect(mocks.getDocument).toHaveBeenCalledWith({ data: new Uint8Array(BYTES), useWorkerFetch: false, isEvalSupported: false });
    expect(mocks.getDocument.mock.calls[0][0]).not.toHaveProperty("url");
    expect(mocks.GlobalWorkerOptions.workerSrc).toContain("pdf.worker.min.mjs");
    expect(mocks.GlobalWorkerOptions.workerSrc).not.toMatch(/cdn|unpkg|jsdelivr/);
    expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled();
    expect(screen.getByTitle("Prévia do laudo em PDF — rascunho")).toHaveAttribute("aria-label", "Prévia do laudo em PDF — rascunho");
  });
  it("navega páginas com limite e limpa renderização anterior", async () => {
    const pdf = document(); mocks.getDocument.mockReturnValue(task(pdf));
    render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toHaveClass("invisible"));
    fireEvent.click(screen.getByRole("button", { name: "Próxima página" }));
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 2 do PDF de rascunho" })).not.toHaveClass("invisible"));
    expect(pdf.pages[0].cleanup).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Próxima página" }));
    await waitFor(() => expect(screen.getByText("Página 3 de 3")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Próxima página" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Página anterior" }));
    await waitFor(() => expect(screen.getByText("Página 2 de 3")).toBeInTheDocument());
    expect(pdf.getPage.mock.calls.map(([number]) => number)).toEqual([1, 2, 3, 2]);
  });
  it("Blob novo destrói o carregamento/documento anterior e ignora resultado tardio", async () => {
    const pending = deferred<ReturnType<typeof document>>();
    const oldTask = { promise: pending.promise, destroy: vi.fn(async () => {}) };
    const next = document(); mocks.getDocument.mockReturnValueOnce(oldTask).mockReturnValueOnce(task(next));
    const { rerender } = render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(mocks.getDocument).toHaveBeenCalledOnce());
    rerender(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toHaveClass("invisible"));
    expect(oldTask.destroy).toHaveBeenCalledOnce();
    const old = document(); await act(async () => pending.resolve(old));
    expect(old.getPage).not.toHaveBeenCalled(); expect(next.getPage).toHaveBeenCalledOnce();
  });
  it("desmontar cancela a página ainda em renderização e destrói o documento", async () => {
    const pending = deferred<void>(); const cancel = vi.fn();
    const pdf = document(); pdf.pages[0].render.mockReturnValue({ promise: pending.promise, cancel });
    const loading = task(pdf); mocks.getDocument.mockReturnValue(loading);
    const { unmount } = render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(pdf.pages[0].render).toHaveBeenCalled());
    unmount(); expect(cancel).toHaveBeenCalledOnce(); expect(loading.destroy).toHaveBeenCalledOnce();
    await act(async () => pending.resolve()); expect(pdf.pages[0].cleanup).toHaveBeenCalled();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
  it("trocar página cancela render anterior mesmo que ele termine tarde", async () => {
    const pending = deferred<void>(); const cancel = vi.fn();
    const pdf = document(); pdf.pages[0].render.mockReturnValue({ promise: pending.promise, cancel });
    mocks.getDocument.mockReturnValue(task(pdf)); render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(pdf.pages[0].render).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Próxima página" }));
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 2 do PDF de rascunho" })).not.toHaveClass("invisible"));
    expect(cancel).toHaveBeenCalledOnce(); await act(async () => pending.resolve());
    expect(screen.queryByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toBeInTheDocument();
  });
  it("falha de carregamento fica local e permite tentar visualizar novamente", async () => {
    const bad = { promise: Promise.reject(new Error("private reader detail")), destroy: vi.fn(async () => {}) };
    mocks.getDocument.mockReturnValueOnce(bad).mockReturnValueOnce(task());
    render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível visualizar o PDF"));
    expect(screen.getByRole("alert")).not.toHaveTextContent("private reader detail");
    fireEvent.click(screen.getByRole("button", { name: "Tentar visualizar novamente" }));
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toHaveClass("invisible"));
    expect(bad.destroy).toHaveBeenCalledOnce();
  });
  it("falha ao renderizar uma página não afeta a próxima nem o PDF original", async () => {
    const pdf = document(); pdf.pages[0].render.mockImplementation(() => ({ promise: Promise.reject(new Error("render failure")), cancel: vi.fn() }));
    mocks.getDocument.mockReturnValue(task(pdf)); render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível visualizar esta página"));
    fireEvent.click(screen.getByRole("button", { name: "Próxima página" }));
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 2 do PDF de rascunho" })).not.toHaveClass("invisible"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("não inicia PDF.js quando fecha durante a leitura assíncrona do Blob", async () => {
    const pending = deferred<ArrayBuffer>();
    const input = blob(); input.arrayBuffer.mockReturnValue(pending.promise);
    const { unmount } = render(<EchoPdfPages blob={input} />);
    await waitFor(() => expect(input.arrayBuffer).toHaveBeenCalledOnce());
    unmount(); await act(async () => pending.resolve(new Uint8Array(BYTES).buffer));
    expect(mocks.getDocument).not.toHaveBeenCalled();
  });
  it("troca de Blob durante leitura ignora bytes anteriores e só carrega o atual", async () => {
    const pending = deferred<ArrayBuffer>();
    const previous = blob(); previous.arrayBuffer.mockReturnValue(pending.promise);
    const current = blob(); const { rerender } = render(<EchoPdfPages blob={previous} />);
    await waitFor(() => expect(previous.arrayBuffer).toHaveBeenCalledOnce());
    rerender(<EchoPdfPages blob={current} />);
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toHaveClass("invisible"));
    await act(async () => pending.resolve(new Uint8Array(BYTES).buffer));
    expect(mocks.getDocument).toHaveBeenCalledOnce(); expect(current.arrayBuffer).toHaveBeenCalledOnce();
  });
  it("tentativa repetida cria buffer próprio mesmo após transferência/detach do primeiro ao worker", async () => {
    let firstData: Uint8Array | undefined;
    mocks.getDocument.mockImplementationOnce((options: { data: Uint8Array }) => {
      firstData = options.data;
      structuredClone(options.data.buffer, { transfer: [options.data.buffer] });
      return { promise: Promise.reject(new Error("simulated worker failure")), destroy: vi.fn(async () => {}) };
    }).mockImplementationOnce(() => task());
    const input = blob(); render(<EchoPdfPages blob={input} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(firstData!.byteLength).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Tentar visualizar novamente" }));
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toHaveClass("invisible"));
    const retryData = mocks.getDocument.mock.calls[1][0].data;
    expect(retryData).toEqual(new Uint8Array(BYTES)); expect(retryData.buffer).not.toBe(firstData!.buffer);
    expect(input.arrayBuffer).toHaveBeenCalledTimes(2); expect(input.size).toBe(BYTES.length);
  });
  it("mantém largura do canvas limitada ao contêiner e refaz apenas página atual ao redimensionar", async () => {
    let observed: (() => void) | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal("ResizeObserver", class { constructor(callback: () => void) { observed = callback; } observe() {} disconnect = disconnect; });
    let width = 280; vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(() => width);
    const pdf = document(); mocks.getDocument.mockReturnValue(task(pdf));
    const { unmount } = render(<EchoPdfPages blob={blob()} />);
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).not.toHaveClass("invisible"));
    const canvas = screen.getByRole("img", { name: "Página 1 do PDF de rascunho" }); expect(canvas).toHaveStyle({ width: "280px" });
    width = 2000; act(() => observed?.());
    await waitFor(() => expect(screen.getByRole("img", { name: "Página 1 do PDF de rascunho" })).toHaveStyle({ width: "900px" }));
    expect(pdf.getPage.mock.calls.every(([number]) => number === 1)).toBe(true);
    unmount(); expect(disconnect).toHaveBeenCalledOnce();
  });
});
