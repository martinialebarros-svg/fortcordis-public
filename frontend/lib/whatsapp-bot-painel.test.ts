import { describe, expect, it } from "vitest";
import {
  SEM_DADO,
  formatarCusto,
  formatarInteiro,
  formatarLatencia,
  formatarTaxa,
  linhasDoChecklist,
  ordenarPorPendencia,
  resumirProntidao,
  validarConteudoBot,
} from "./whatsapp-bot-painel";

describe("formatação de métricas", () => {
  it("nunca transforma null em 0%", () => {
    // O backend usa null para 'sem amostra'. Renderizar 0% faria
    // 'não medido' parecer 'medido e ruim'.
    expect(formatarTaxa(null)).toBe(SEM_DADO);
    expect(formatarTaxa(undefined)).toBe(SEM_DADO);
    expect(formatarTaxa(NaN)).toBe(SEM_DADO);
    expect(formatarTaxa(0)).toBe("0%");
    expect(formatarTaxa(0.6667)).toBe("66.7%");
    expect(formatarTaxa(1)).toBe("100%");
  });

  it("distingue zero de ausente em inteiros", () => {
    expect(formatarInteiro(null)).toBe(SEM_DADO);
    expect(formatarInteiro(0)).toBe("0");
    expect(formatarInteiro(7)).toBe("7");
  });

  it("formata latência em ms e s", () => {
    expect(formatarLatencia(null)).toBe(SEM_DADO);
    expect(formatarLatencia(420)).toBe("420 ms");
    expect(formatarLatencia(11794)).toBe("11.8 s");
  });

  it("não finge custo zero quando a tarifa não está configurada", () => {
    expect(formatarCusto(null, false)).toBe("não configurado");
    expect(formatarCusto(0, false)).toBe("não configurado");
    expect(formatarCusto(null, true)).toBe(SEM_DADO);
    expect(formatarCusto(10, true)).toContain("10");
  });
});

describe("prontidão", () => {
  const item = (over: Partial<Parameters<typeof ordenarPorPendencia>[0][number]>) => ({
    intent: "x",
    rotulo: "X",
    pronto: false,
    diagnostico: null,
    auto_elegivel: true,
    ...over,
  });

  it("põe pendência acionável antes de pronto e de dependente de conversa", () => {
    const ordenado = ordenarPorPendencia([
      item({ intent: "a", rotulo: "Pronto", pronto: true }),
      item({ intent: "b", rotulo: "Depende", pronto: false, depende_da_conversa: true }),
      item({ intent: "c", rotulo: "Falta", pronto: false }),
    ]);
    expect(ordenado.map((i) => i.intent)).toEqual(["c", "b", "a"]);
  });

  it("separa pendência acionável de dependente de conversa", () => {
    const resumo = resumirProntidao({
      tutor: {
        itens: [
          item({ pronto: true }),
          item({ pronto: false }),
          item({ pronto: false, depende_da_conversa: true }),
        ],
        total: 3,
        prontos: 1,
        pendentes: 2,
      },
    });
    expect(resumo.total).toBe(3);
    expect(resumo.prontos).toBe(1);
    expect(resumo.pendentes).toBe(2);
    // Só uma é resolvível cadastrando/configurando.
    expect(resumo.acionaveis).toBe(1);
  });

  it("aguenta payload ausente", () => {
    expect(resumirProntidao(undefined)).toEqual({
      total: 0,
      prontos: 0,
      pendentes: 0,
      acionaveis: 0,
    });
  });
});

describe("validação de conteúdo do bot", () => {
  const base = {
    titulo: "Como agendar",
    conteudo: "Para agendar, fale com a recepcao pelo WhatsApp ou telefone.",
    fonte: "Recepção",
    publico: "ambos",
  };

  it("aceita entrada completa", () => {
    expect(validarConteudoBot(base).valido).toBe(true);
  });

  it("exige fonte, porque o bot só afirma o que pode citar", () => {
    const r = validarConteudoBot({ ...base, fonte: "  " });
    expect(r.valido).toBe(false);
    expect(r.erros.join(" ")).toContain("fonte");
  });

  it("recusa conteúdo curto e público inválido", () => {
    expect(validarConteudoBot({ ...base, conteudo: "curto" }).valido).toBe(false);
    expect(validarConteudoBot({ ...base, publico: "staff" }).valido).toBe(false);
  });
});

describe("checklist de auto", () => {
  it("vira lista de itens, nunca um selo de liberado", () => {
    const linhas = linhasDoChecklist({
      tem_uma_semana_de_dados: true,
      tem_rascunho_decidido: true,
      amostra_suficiente_nas_duas_personas: false,
      decididos_por_persona: { tutor: 25 },
      min_decididos_por_persona: 20,
    });
    expect(linhas).toHaveLength(3);
    expect(linhas[2].atendido).toBe(false);
    expect(linhas[2].detalhe).toContain("tutor: 25/20");
    expect(linhas[2].detalhe).toContain("clinica: 0/20");
  });

  it("aguenta checklist ausente", () => {
    expect(linhasDoChecklist(undefined)).toEqual([]);
  });
});
