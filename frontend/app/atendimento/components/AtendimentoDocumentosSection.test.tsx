import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { formatDate } from "@/lib/atendimento-utils";
import AtendimentoDocumentosSection from "./AtendimentoDocumentosSection";

afterEach(() => {
  cleanup();
});

function noop() {}

function Harness({ uploadArquivosAnexoGeral, extra = {} }: { uploadArquivosAnexoGeral: (files: File[]) => Promise<void>; extra?: Record<string, unknown> }) {
  const [anexoArquivos, setAnexoArquivos] = useState<File[]>([]);
  const [anexoForm, setAnexoForm] = useState({ tipo: "documento", descricao: "", url: "" });

  return (
    <AtendimentoDocumentosSection
      ATENDIMENTO_ATTACHMENT_ACCEPT=".jpeg,.jpg,.pdf,.png,.webp"
      adicionarLinkAnexo={noop}
      anexosGerais={[]}
      anexoArquivos={anexoArquivos}
      anexoForm={anexoForm}
      abrirAnexo={noop}
      baixarPdfDocumentoClinico={noop}
      cancelarUploadAnexo={noop}
      criarDocumentoClinicoDeTemplate={noop}
      documentTemplates={[]}
      documentoClinicoForm={{ id: null, status: "rascunho", titulo: "", corpo: "" }}
      documentoTemplateForm={{ id: null, nome: "", tipo: "documento", titulo_padrao: "", corpo_template: "", ordem: "", ativo: 1 }}
      documentoTemplateSelecionado=""
      documentoVariaveisNaoResolvidas={[]}
      editarDocumentoTemplate={noop}
      evolucaoForm={{ descricao: "", sinais_vitais: "" }}
      excluirDocumentoClinico={noop}
      excluirAnexo={noop}
      formatBytes={(n: number) => `${n}B`}
      formatDate={(d: string) => d}
      gerandoDocumentoPdfId={null}
      novoDocumentoClinicoLivre={noop}
      openingAttachmentId={null}
      progressoUploadGeral={null}
      selecionado={123}
      setAnexoArquivos={setAnexoArquivos}
      setAnexoForm={setAnexoForm}
      setDocumentoClinicoForm={noop}
      setDocumentoTemplateForm={noop}
      setDocumentoTemplateSelecionado={noop}
      setErro={noop}
      setEvolucaoForm={noop}
      setShowDocumentoTemplateEditor={noop}
      setSucesso={noop}
      showDocumentoTemplateEditor={false}
      salvandoDocumentoClinico={false}
      salvandoDocumentoTemplate={false}
      salvarDocumentoClinico={noop}
      salvarDocumentoTemplate={noop}
      selecionarDocumentoClinico={noop}
      toggleDocumentoTemplate={noop}
      uploadArquivosAnexoGeral={uploadArquivosAnexoGeral}
      uploadGeralEmAndamento={false}
      abrirAtendimento={noop}
      api={{ post: vi.fn() }}
      form={{ documentos: [], evolucoes: [] }}
      {...extra}
    />
  );
}

function getAnexoFileInput(): HTMLInputElement {
  const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement | null;
  if (!fileInput) throw new Error("input de arquivo de anexo nao encontrado");
  return fileInput;
}

describe("AtendimentoDocumentosSection - selecao multipla de anexos", () => {
  it("aceita mais de um arquivo no input", () => {
    render(<Harness uploadArquivosAnexoGeral={async () => {}} />);
    const input = getAnexoFileInput();
    expect(input.multiple).toBe(true);
  });

  it("mostra um chip por arquivo selecionado e o rotulo do botao no plural", () => {
    render(<Harness uploadArquivosAnexoGeral={async () => {}} />);
    const input = getAnexoFileInput();
    const exame1 = new File(["a"], "exame-sangue.pdf", { type: "application/pdf" });
    const exame2 = new File(["b"], "raio-x-torax.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [exame1, exame2] } });

    expect(screen.getByText(/exame-sangue\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/raio-x-torax\.pdf/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Enviar 2 arquivos/ })).toBeInTheDocument();
  });

  it("envia todos os arquivos selecionados de uma vez ao clicar em enviar", async () => {
    const uploadArquivosAnexoGeral = vi.fn().mockResolvedValue(undefined);
    render(<Harness uploadArquivosAnexoGeral={uploadArquivosAnexoGeral} />);
    const input = getAnexoFileInput();
    const exame1 = new File(["a"], "exame-sangue.pdf", { type: "application/pdf" });
    const exame2 = new File(["b"], "raio-x-torax.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [exame1, exame2] } });
    fireEvent.click(screen.getByRole("button", { name: /Enviar 2 arquivos/ }));

    expect(uploadArquivosAnexoGeral).toHaveBeenCalledTimes(1);
    expect(uploadArquivosAnexoGeral).toHaveBeenCalledWith([exame1, exame2]);
  });

  it("permite remover um arquivo da selecao antes de enviar", () => {
    render(<Harness uploadArquivosAnexoGeral={async () => {}} />);
    const input = getAnexoFileInput();
    const exame1 = new File(["a"], "exame-sangue.pdf", { type: "application/pdf" });
    const exame2 = new File(["b"], "raio-x-torax.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [exame1, exame2] } });
    fireEvent.click(screen.getByRole("button", { name: /Remover exame-sangue.pdf da selecao/ }));

    expect(screen.queryByText(/exame-sangue\.pdf/)).not.toBeInTheDocument();
    expect(screen.getByText(/raio-x-torax\.pdf/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar arquivo" })).toBeInTheDocument();
  });
});


describe("documentos preservados", () => {
  it("mostra emissao real em Fortaleza e arquivo restauravel", () => {
    const restore = vi.fn();
    render(<Harness uploadArquivosAnexoGeral={async () => {}} extra={{
      formatDate,
      restaurarDocumentoClinico: restore,
      form: { documentos: [{ id: 10, titulo: "Parecer de teste", status: "arquivado", emitido_at: "2026-09-29T17:00:56+00:00", updated_at: "2026-09-29T17:10:28+00:00" }], evolucoes: [] },
    }} />);
    expect(screen.getByText(/Emissao:.*14:00:56/)).toBeTruthy();
    expect(screen.getByText("Arquivados (1)")).toBeTruthy();
    expect(screen.getByRole("button", { name: "PDF" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Restaurar" }));
    expect(restore).toHaveBeenCalledWith(expect.objectContaining({ id: 10 }));
    expect(screen.queryByRole("button", { name: "Remover" })).toBeNull();
  });
  it("disponibiliza abrir e baixar novamente", () => {
    render(<Harness uploadArquivosAnexoGeral={async () => {}} extra={{ documentoPdfDownload: { url: "blob:pdf", filename: "teste.pdf" } }} />);
    expect(screen.getByRole("link", { name: "Abrir PDF" })).toHaveAttribute("href", "blob:pdf");
    expect(screen.getByRole("link", { name: "Baixar novamente" })).toHaveAttribute("download", "teste.pdf");
  });
});

it("emissao nao declara download nem entrega", () => {
  render(<Harness uploadArquivosAnexoGeral={async () => {}} extra={{ documentoClinicoForm: { id: 10, titulo: "Teste", corpo: "Teste", status: "emitido" } }} />);
  expect(screen.getByText(/Isso nao confirma o download nem a entrega/)).toBeTruthy();
  expect(screen.queryByText(/gerado e entregue/)).toBeNull();
});

it("permite editar e salvar documento emitido em atendimento concluido", () => {
  const salvar = vi.fn();
  const editar = vi.fn();
  render(<Harness uploadArquivosAnexoGeral={async () => {}} extra={{
    form: { status: "Concluido", documentos: [], evolucoes: [] },
    documentoClinicoForm: { id: 10, atendimento_id: 123, titulo: "Encaminhamento", corpo: "Texto original", status: "emitido", versao: "v1" },
    setDocumentoClinicoForm: editar,
    salvarDocumentoClinico: salvar,
  }} />);
  const corpo = screen.getByPlaceholderText("Texto do documento...") as HTMLTextAreaElement;
  expect(corpo.readOnly).toBe(false);
  fireEvent.change(corpo, { target: { value: "Texto corrigido" } });
  expect(editar).toHaveBeenCalledWith(expect.objectContaining({ corpo: "Texto corrigido" }));
  const botao = screen.getByRole("button", { name: "Salvar documento" });
  expect(botao).not.toBeDisabled();
  fireEvent.click(botao);
  expect(salvar).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: /Historico de edicoes deste documento/ })).toBeInTheDocument();
});
