import { describe, expect, it } from "vitest";

import { aplicarFormatacaoMarkdownDocumento } from "./AtendimentoDocumentosSection";

function criarTextareaComSelecao(valor: string, inicio: number, fim: number): HTMLTextAreaElement {
  const textarea = document.createElement("textarea");
  textarea.value = valor;
  textarea.selectionStart = inicio;
  textarea.selectionEnd = fim;
  return textarea;
}

describe("aplicarFormatacaoMarkdownDocumento", () => {
  it("envolve o texto selecionado com ** para negrito", () => {
    const valor = "Paciente estavel";
    const textarea = criarTextareaComSelecao(valor, 9, 16); // "estavel"
    const resultado = aplicarFormatacaoMarkdownDocumento(textarea, valor, "negrito");
    expect(resultado?.valor).toBe("Paciente **estavel**");
    expect(resultado?.selecaoInicio).toBe(11);
    expect(resultado?.selecaoFim).toBe(18);
  });

  it("envolve o texto selecionado com * para italico", () => {
    const valor = "Observacao clinica";
    const textarea = criarTextareaComSelecao(valor, 0, 10); // "Observacao"
    const resultado = aplicarFormatacaoMarkdownDocumento(textarea, valor, "italico");
    expect(resultado?.valor).toBe("*Observacao* clinica");
  });

  it("insere um placeholder quando nao ha selecao (negrito)", () => {
    const valor = "";
    const textarea = criarTextareaComSelecao(valor, 0, 0);
    const resultado = aplicarFormatacaoMarkdownDocumento(textarea, valor, "negrito");
    expect(resultado?.valor).toBe("**texto em negrito**");
  });

  it("prefixa cada linha selecionada com '- ' para lista", () => {
    const valor = "Item A\nItem B\nItem C";
    const textarea = criarTextareaComSelecao(valor, 0, valor.length);
    const resultado = aplicarFormatacaoMarkdownDocumento(textarea, valor, "lista");
    expect(resultado?.valor).toBe("- Item A\n- Item B\n- Item C");
  });

  it("nao duplica o prefixo em linhas que ja sao itens de lista", () => {
    const valor = "- ja e item\nlinha comum";
    const textarea = criarTextareaComSelecao(valor, 0, valor.length);
    const resultado = aplicarFormatacaoMarkdownDocumento(textarea, valor, "lista");
    expect(resultado?.valor).toBe("- ja e item\n- linha comum");
  });

  it("insere um item de lista placeholder quando nao ha selecao", () => {
    const valor = "";
    const textarea = criarTextareaComSelecao(valor, 0, 0);
    const resultado = aplicarFormatacaoMarkdownDocumento(textarea, valor, "lista");
    expect(resultado?.valor).toBe("- Item da lista");
  });

  it("preserva o texto antes e depois da selecao", () => {
    const valor = "Antes MEIO depois";
    const textarea = criarTextareaComSelecao(valor, 6, 10); // "MEIO"
    const resultado = aplicarFormatacaoMarkdownDocumento(textarea, valor, "negrito");
    expect(resultado?.valor).toBe("Antes **MEIO** depois");
  });

  it("retorna null quando o textarea e null", () => {
    const resultado = aplicarFormatacaoMarkdownDocumento(null, "qualquer coisa", "negrito");
    expect(resultado).toBeNull();
  });
});
