import { Blob as NodeBlob } from "node:buffer";
import { describe, expect, it, vi } from "vitest";
import { documentoPersistido, iniciarDownloadDocumento, validarPdfDocumento, reconciliarDocumentoSalvo } from "./atendimento-documentos";
import { formatDate } from "./atendimento-utils";
import { mergeAutoSavedFormState } from "./atendimento-form-merge";
describe("persistencia e download", () => {
  it("nao inventa sucesso se documento falta na lista", () => {
    expect(() => documentoPersistido([], 10)).toThrow(/nao foi confirmado/);
  });
  it("preserva documentos criados durante save", () => {
    const current = { id: 69, documentos: [{ id: 10, corpo: "Novo" }], exames: [], prescricao_itens: [] };
    expect(mergeAutoSavedFormState(current as never, { ...current, documentos: [] } as never)).toMatchObject({ documentos: current.documentos });
  });
  it("mostra UTC em Fortaleza", () => {
    expect(formatDate("2026-09-29T17:00:56+00:00")).toContain("14:00:56");
  });
  it("rejeita HTML, JSON e vazio", async () => {
    for (const [content, type] of [["<html>Erro</html>", "application/pdf"], ["{}", "application/json"], ["", "application/pdf"]]) {
      await expect(validarPdfDocumento(new NodeBlob([content], { type }) as Blob)).rejects.toThrow(/PDF/);
    }
    await expect(validarPdfDocumento(new NodeBlob(["%PDF-1.7\n"], { type: "application/pdf" }) as Blob)).resolves.toBeUndefined();
  });
  it("solicita download", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    iniciarDownloadDocumento("blob:teste", "parecer.pdf");
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector('a[download="parecer.pdf"]')).toBeNull();
    click.mockRestore();
  });
});

it("mantem texto digitado enquanto salva e recebe a nova versao", () => {
  const enviado = { id: 10, titulo: "Titulo", corpo: "Texto enviado", versao: "v1" };
  const atual = { ...enviado, corpo: "Digitado durante a rede" };
  const salvo = { ...enviado, versao: "v2" };
  expect(reconciliarDocumentoSalvo(atual, enviado, salvo)).toEqual({ ...atual, versao: "v2" });
  expect(reconciliarDocumentoSalvo({ ...atual, id: 11 }, enviado, salvo).id).toBe(11);
});
