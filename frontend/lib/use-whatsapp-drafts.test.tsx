import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useWhatsAppDrafts } from "./use-whatsapp-drafts";

describe("useWhatsAppDrafts", () => {
  it("preserva texto e arquivo por conversa sem misturar destinatários", () => {
    const file = new File(["documento"], "anexo.pdf", { type: "application/pdf" });
    const { result, rerender } = renderHook(({ id }) => useWhatsAppDrafts(id), {
      initialProps: { id: "a" },
    });

    act(() => {
      result.current.setBody("  Olá, clínica A.\n");
      result.current.setFile(file);
    });
    const originalSnapshot = result.current.draftSnapshot;
    rerender({ id: "b" });
    expect(result.current.body).toBe("");
    expect(result.current.file).toBeNull();
    expect(result.current.hasDraft("a")).toBe(true);
    expect(result.current.hasDraft("b")).toBe(false);

    act(() => result.current.setBody("Olá, clínica B."));
    rerender({ id: "a" });
    expect(result.current.body).toBe("  Olá, clínica A.\n");
    expect(result.current.file).toBe(file);
    expect(result.current.draftSnapshot).toBe(originalSnapshot);
    rerender({ id: "b" });
    expect(result.current.body).toBe("Olá, clínica B.");
    expect(result.current.file).toBeNull();
  });

  it("limpa o rascunho enviado mesmo após trocar de conversa e mantém o outro", () => {
    const { result, rerender } = renderHook(({ id }) => useWhatsAppDrafts(id), {
      initialProps: { id: "a" },
    });
    act(() => result.current.setBody("Mensagem enviada de A"));
    const sentSnapshot = result.current.draftSnapshot;
    rerender({ id: "b" });
    act(() => result.current.setBody("Mensagem em edição de B"));
    act(() => result.current.clearDraftIfUnchanged("a", sentSnapshot));

    expect(result.current.hasDraft("a")).toBe(false);
    expect(result.current.body).toBe("Mensagem em edição de B");
    rerender({ id: "a" });
    expect(result.current.body).toBe("");
    expect(result.current.file).toBeNull();
  });

  it("preserva uma edição feita enquanto o envio anterior aguardava resposta", () => {
    const { result } = renderHook(() => useWhatsAppDrafts("a"));
    act(() => result.current.setBody("Primeira mensagem"));
    const sentSnapshot = result.current.draftSnapshot;
    act(() => result.current.setBody("Próxima mensagem"));
    act(() => result.current.clearDraftIfUnchanged("a", sentSnapshot));

    expect(result.current.body).toBe("Próxima mensagem");
    expect(result.current.hasDraft("a")).toBe(true);
  });

  it("preserva um arquivo substituído enquanto o envio aguardava resposta", () => {
    const { result } = renderHook(() => useWhatsAppDrafts("a"));
    const firstFile = new File(["primeiro"], "anexo.pdf", { type: "application/pdf" });
    const replacement = new File(["segundo"], "anexo.pdf", { type: "application/pdf" });
    act(() => result.current.setFile(firstFile));
    const sentSnapshot = result.current.draftSnapshot;
    act(() => result.current.setFile(replacement));
    act(() => result.current.clearDraftIfUnchanged("a", sentSnapshot));

    expect(result.current.file).toBe(replacement);
    expect(result.current.hasDraft("a")).toBe(true);
  });

  it("não apaga uma nova edição que voltou ao mesmo conteúdo do envio anterior", () => {
    const { result } = renderHook(() => useWhatsAppDrafts("a"));
    act(() => result.current.setBody("Mensagem"));
    const sentSnapshot = result.current.draftSnapshot;
    act(() => result.current.setBody("Mensagem editada"));
    act(() => result.current.setBody("Mensagem"));
    act(() => result.current.clearDraftIfUnchanged("a", sentSnapshot));

    expect(result.current.body).toBe("Mensagem");
    expect(result.current.draftSnapshot).not.toBe(sentSnapshot);
  });

  it("descarta explicitamente somente o rascunho da conversa indicada", () => {
    const { result, rerender } = renderHook(({ id }) => useWhatsAppDrafts(id), {
      initialProps: { id: "a" },
    });
    act(() => result.current.setBody("Rascunho A"));
    rerender({ id: "b" });
    act(() => result.current.setFile(new File(["documento"], "anexo.pdf")));
    act(() => result.current.clearDraft("a"));
    expect(result.current.hasDraft("a")).toBe(false);
    expect(result.current.hasDraft("b")).toBe(true);
    act(() => result.current.clearDraft());
    expect(result.current.hasDraft("b")).toBe(false);
    expect(result.current.file).toBeNull();
  });

  it("não guarda rascunho sem conversa selecionada", () => {
    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useWhatsAppDrafts(id), {
      initialProps: { id: null as string | null },
    });
    act(() => {
      result.current.setBody("Sem destinatário");
      result.current.setFile(new File(["documento"], "anexo.pdf"));
      result.current.clearDraft();
    });
    rerender({ id: "a" });
    expect(result.current.body).toBe("");
    expect(result.current.file).toBeNull();
  });

  it("descarta os rascunhos ao desmontar a central", () => {
    const first = renderHook(() => useWhatsAppDrafts("a"));
    act(() => first.result.current.setBody("Conteúdo privado"));
    first.unmount();
    const second = renderHook(() => useWhatsAppDrafts("a"));
    expect(second.result.current.body).toBe("");
    expect(second.result.current.file).toBeNull();
    expect(second.result.current.hasDraft("a")).toBe(false);
  });
});
