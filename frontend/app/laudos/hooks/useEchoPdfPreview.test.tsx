import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEchoPdfPreview, type EchoPdfPreviewOptions } from "./useEchoPdfPreview";

const pdf = () => new Blob(["%PDF-1.4\nSYNTHETIC"], { type: "application/pdf" });
const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const options = (requestPreview = vi.fn(async (_signal: AbortSignal) => pdf())): EchoPdfPreviewOptions => ({
  scopeKey: "owner:1/new", snapshotKey: "snapshot:1", requestPreview,
});
let createUrl: ReturnType<typeof vi.fn>;
let revokeUrl: ReturnType<typeof vi.fn>;
beforeEach(() => {
  createUrl = vi.fn(() => "blob:synthetic-preview"); revokeUrl = vi.fn();
  vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL: createUrl, revokeObjectURL: revokeUrl }));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("prévia PDF vinculada ao snapshot privado", () => {
  it("não gera ao montar; valida PDF real e não persiste payload ou URL", async () => {
    const input = options();
    const local = vi.spyOn(Storage.prototype, "setItem");
    const hook = renderHook(() => useEchoPdfPreview(input));
    expect(input.requestPreview).not.toHaveBeenCalled();
    act(() => { void hook.result.current.generate(); });
    await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    expect(hook.result.current.url).toBe("blob:synthetic-preview");
    expect(hook.result.current.blob).toBeInstanceOf(Blob);
    expect(createUrl).toHaveBeenCalledWith(hook.result.current.blob);
    expect(input.requestPreview).toHaveBeenCalledWith(expect.any(AbortSignal));
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob));
    expect(local).not.toHaveBeenCalled();
  });
  it.each([
    () => new Blob(["<html>login</html>"], { type: "text/html" }),
    () => new Blob(["<html>error</html>"], { type: "application/pdf" }),
    () => new Blob([], { type: "application/pdf" }),
  ])("recusa resposta que não é PDF, sem abrir Blob de HTML", async (response) => {
    const hook = renderHook(() => useEchoPdfPreview(options(vi.fn(async () => response()))));
    act(() => { void hook.result.current.generate(); });
    await waitFor(() => expect(hook.result.current.status).toBe("error"));
    expect(hook.result.current.url).toBeNull(); expect(hook.result.current.blob).toBeNull(); expect(createUrl).not.toHaveBeenCalled();
  });
  it("uma falha mantém erro local e permite nova tentativa sem emitir", async () => {
    const request = vi.fn().mockRejectedValueOnce(new Error("private provider detail")).mockResolvedValueOnce(pdf());
    const hook = renderHook(() => useEchoPdfPreview(options(request)));
    act(() => { void hook.result.current.generate(); });
    await waitFor(() => expect(hook.result.current.error).toMatch(/rascunho continua preservado/));
    expect(hook.result.current.error).not.toContain("private provider");
    act(() => { void hook.result.current.generate(); });
    await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    expect(request).toHaveBeenCalledTimes(2);
  });
  it("edição invalida resposta antiga mesmo quando o transporte ignora AbortSignal", async () => {
    const pending = deferred<Blob>(); const request = vi.fn((_signal: AbortSignal) => pending.promise);
    const initial = options(request);
    const hook = renderHook((props: EchoPdfPreviewOptions) => useEchoPdfPreview(props), { initialProps: initial });
    act(() => { void hook.result.current.generate(); });
    hook.rerender({ ...initial, snapshotKey: "snapshot:2" });
    expect(request.mock.calls[0][0].aborted).toBe(true);
    expect(hook.result.current.status).toBe("stale");
    await act(async () => pending.resolve(pdf()));
    expect(createUrl).not.toHaveBeenCalled(); expect(hook.result.current.url).toBeNull(); expect(hook.result.current.blob).toBeNull();
  });
  it.each(["scope", "disabled"])("mudança de %s esconde, aborta e descarta conteúdo de outra revisão", async (change) => {
    const pending = deferred<Blob>(); const request = vi.fn((_signal: AbortSignal) => pending.promise);
    const initial = options(request);
    const hook = renderHook((props: EchoPdfPreviewOptions) => useEchoPdfPreview(props), { initialProps: initial });
    act(() => { void hook.result.current.generate(); });
    hook.rerender({ ...initial, ...(change === "scope" ? { scopeKey: "owner:2/edit:44" } : { enabled: false }) });
    expect(request.mock.calls[0][0].aborted).toBe(true);
    expect(hook.result.current.visible).toBe(false); expect(hook.result.current.blob).toBeNull();
    await act(async () => pending.resolve(pdf()));
    expect(createUrl).not.toHaveBeenCalled();
  });
  it("mudança de conteúdo revoga URL já exibida, em vez de manter PDF obsoleto", async () => {
    const initial = options(); const hook = renderHook((props: EchoPdfPreviewOptions) => useEchoPdfPreview(props), { initialProps: initial });
    act(() => { void hook.result.current.generate(); }); await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    hook.rerender({ ...initial, snapshotKey: "image-caption-changed" });
    expect(revokeUrl).toHaveBeenCalledWith("blob:synthetic-preview");
    expect(hook.result.current.status).toBe("stale"); expect(hook.result.current.url).toBeNull(); expect(hook.result.current.blob).toBeNull();
  });
  it("recriar callback sem mudar conteúdo não invalida; a próxima geração usa callback atual", async () => {
    const initial = options(); const hook = renderHook((props: EchoPdfPreviewOptions) => useEchoPdfPreview(props), { initialProps: initial });
    act(() => { void hook.result.current.generate(); }); await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    const nextRequest = vi.fn(async (_signal: AbortSignal) => pdf());
    hook.rerender({ ...initial, requestPreview: nextRequest });
    expect(hook.result.current.status).toBe("ready"); expect(revokeUrl).not.toHaveBeenCalled();
    act(() => { void hook.result.current.generate(); }); await waitFor(() => expect(nextRequest).toHaveBeenCalledOnce());
    await waitFor(() => expect(hook.result.current.status).toBe("ready"));
  });
  it("fechar e desmontar revogam URL e cancelam requisição em andamento", async () => {
    const hook = renderHook(() => useEchoPdfPreview(options()));
    act(() => { void hook.result.current.generate(); }); await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    act(() => hook.result.current.close()); expect(revokeUrl).toHaveBeenCalledTimes(1); expect(hook.result.current.visible).toBe(false); expect(hook.result.current.blob).toBeNull();
    act(() => { void hook.result.current.generate(); }); await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    hook.unmount(); expect(revokeUrl).toHaveBeenCalledTimes(2);
    const pending = deferred<Blob>(); const request = vi.fn((_signal: AbortSignal) => pending.promise);
    const second = renderHook(() => useEchoPdfPreview(options(request)));
    act(() => { void second.result.current.generate(); }); second.unmount();
    expect(request.mock.calls[0][0].aborted).toBe(true);
    await act(async () => pending.resolve(pdf())); expect(createUrl).toHaveBeenCalledTimes(2);
  });
  it("duas gerações concorrentes aceitam apenas a última resposta", async () => {
    const one = deferred<Blob>(); const two = deferred<Blob>();
    const request = vi.fn().mockReturnValueOnce(one.promise).mockReturnValueOnce(two.promise);
    const hook = renderHook(() => useEchoPdfPreview(options(request)));
    act(() => { void hook.result.current.generate(); }); act(() => { void hook.result.current.generate(); });
    await act(async () => two.resolve(pdf())); await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    await act(async () => one.resolve(pdf())); expect(createUrl).toHaveBeenCalledTimes(1);
  });
  it("timeout encerra espera mesmo se o transporte não responder; resposta tardia é ignorada", async () => {
    vi.useFakeTimers();
    const pending = deferred<Blob>(); const request = vi.fn((_signal: AbortSignal) => pending.promise);
    const hook = renderHook(() => useEchoPdfPreview({ ...options(request), timeoutMs: 100 }));
    act(() => { void hook.result.current.generate(); });
    await act(async () => vi.advanceTimersByTimeAsync(100));
    expect(hook.result.current.status).toBe("error"); expect(hook.result.current.error).toMatch(/demorou/);
    expect(request.mock.calls[0][0].aborted).toBe(true);
    await act(async () => pending.resolve(pdf())); expect(createUrl).not.toHaveBeenCalled();
  });
  it("cancelar não deixa o timer de uma requisição abandonada ativo", async () => {
    vi.useFakeTimers();
    const pending = deferred<Blob>(); const request = vi.fn((_signal: AbortSignal) => pending.promise);
    const hook = renderHook(() => useEchoPdfPreview(options(request)));
    act(() => { void hook.result.current.generate(); }); expect(vi.getTimerCount()).toBe(1);
    act(() => hook.result.current.close()); expect(vi.getTimerCount()).toBe(0);
    await act(async () => pending.resolve(pdf())); expect(createUrl).not.toHaveBeenCalled();
  });
  it("desabilitar após PDF pronto revoga URL e impede gerar outra prévia", async () => {
    const initial = options(); const hook = renderHook((props: EchoPdfPreviewOptions) => useEchoPdfPreview(props), { initialProps: initial });
    act(() => { void hook.result.current.generate(); }); await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    hook.rerender({ ...initial, enabled: false }); expect(hook.result.current.visible).toBe(false); expect(hook.result.current.blob).toBeNull(); expect(revokeUrl).toHaveBeenCalledOnce();
    act(() => { void hook.result.current.generate(); }); expect(initial.requestPreview).toHaveBeenCalledOnce();
  });
});
