import { describe, expect, it } from "vitest";

import type { FraseEcoEstruturadoTeste } from "@/lib/ecocardiograma-estruturado-teste";

import {
  comporConclusaoDeFrases,
  comporRascunhoConclusaoDosAchados,
  obterOpcoesDeGrauRelacionadas,
} from "./ecocardiograma-compositor";

const frasesVe: FraseEcoEstruturadoTeste[] = [
  {
    id: 65,
    titulo: "VE com sobrecarga volumétrica leve",
    texto: "VE com discreta sobrecarga volumétrica.",
    tags: ["leve", "endocardiose", "cao"],
    ordem: 10,
  },
  {
    id: 66,
    titulo: "VE com sobrecarga volumétrica moderada",
    texto: "VE com sobrecarga volumétrica moderada.",
    tags: ["moderado", "endocardiose", "cao", "B2"],
    ordem: 20,
  },
  {
    id: 67,
    titulo: "VE com sobrecarga volumétrica importante",
    texto: "VE com sobrecarga volumétrica importante.",
    tags: ["grave", "endocardiose", "cao", "C"],
    ordem: 30,
  },
  {
    id: 70,
    titulo: "VE com hipertrofia concentrica moderada",
    texto: "VE com hipertrofia concentrica moderada.",
    tags: ["moderado", "hipertrofia", "gato", "hcm"],
    ordem: 40,
  },
];

describe("compositor de ecocardiograma", () => {
  it("oferece graus mutuamente exclusivos da mesma familia clinica", () => {
    const opcoes = obterOpcoesDeGrauRelacionadas(frasesVe, "66");

    expect(opcoes.map((opcao) => [opcao.label, opcao.frase.id])).toEqual([
      ["Discreta", 65],
      ["Moderada", 66],
      ["Importante", 67],
    ]);
    expect(opcoes.some((opcao) => opcao.frase.id === 70)).toBe(false);
  });

  it("nao inventa alternativas quando nao ha familia relacionada suficiente", () => {
    const frases: FraseEcoEstruturadoTeste[] = [
      { id: 1, titulo: "Achado leve isolado", texto: "A.", tags: ["leve"] },
      { id: 2, titulo: "Outro achado grave", texto: "B.", tags: ["grave"] },
    ];

    expect(obterOpcoesDeGrauRelacionadas(frases, "1")).toEqual([]);
  });

  it("compoe somente textos aprovados, preserva ordem e remove duplicatas", () => {
    const conclusoes: FraseEcoEstruturadoTeste[] = [
      { id: 1, titulo: "Valvopatia", texto: "* Doença valvar mixomatosa." },
      { id: 2, titulo: "HP", texto: "Alta probabilidade de hipertensão pulmonar." },
    ];

    expect(comporConclusaoDeFrases(conclusoes, ["1", "2", "1"], "topicos")).toBe(
      "* Doença valvar mixomatosa.\n* Alta probabilidade de hipertensão pulmonar.",
    );
    expect(comporConclusaoDeFrases(conclusoes, ["1", "2"], "paragrafo")).toBe(
      "Doença valvar mixomatosa. Alta probabilidade de hipertensão pulmonar.",
    );
  });

  it("normaliza marcadores internos ao alternar entre topicos e paragrafo", () => {
    const conclusoes: FraseEcoEstruturadoTeste[] = [
      {
        id: 1,
        titulo: "Valvopatia com HP",
        texto: "* Doença valvar mixomatosa.\n* Alta probabilidade de hipertensão pulmonar.",
      },
      {
        id: 2,
        titulo: "Efusao leve",
        texto: "• Efusão pericárdica discreta. * Sem sinais de tamponamento.",
      },
    ];

    expect(comporConclusaoDeFrases(conclusoes, ["1", "2"], "topicos")).toBe(
      "* Doença valvar mixomatosa.\n" +
        "* Alta probabilidade de hipertensão pulmonar.\n" +
        "* Efusão pericárdica discreta.\n" +
        "* Sem sinais de tamponamento.",
    );
    expect(comporConclusaoDeFrases(conclusoes, ["1", "2"], "paragrafo")).toBe(
      "Doença valvar mixomatosa. Alta probabilidade de hipertensão pulmonar. " +
        "Efusão pericárdica discreta. Sem sinais de tamponamento.",
    );
  });

  it("ignora ids ausentes ou frases inativas sem criar texto clinico", () => {
    const conclusoes: FraseEcoEstruturadoTeste[] = [
      { id: 1, titulo: "Ativa", texto: "Texto aprovado.", ativo: 1 },
      { id: 2, titulo: "Inativa", texto: "Nao deve aparecer.", ativo: 0 },
    ];

    expect(comporConclusaoDeFrases(conclusoes, ["2", "999"], "topicos")).toBe("");
  });

  it("gera rascunho automatico somente a partir dos achados selecionados relevantes", () => {
    const achados = [
      {
        aspecto: "valva_mitral",
        label: "Valva mitral",
        texto: "Texto detalhado da mitral.",
        frase: {
          id: 3,
          titulo: "Espessamento mitral leve com refluxo leve",
          texto: "Texto detalhado da mitral.",
          tags: ["endocardiose", "leve"],
        },
      },
      {
        aspecto: "aorta",
        label: "Aorta",
        texto: "Aorta normal.",
        frase: {
          id: 91,
          titulo: "Aorta normal",
          texto: "Aorta normal.",
          tags: ["normal"],
        },
      },
      {
        aspecto: "pericardio",
        label: "Pericardio",
        texto: "Efusao pericardica discreta sem tamponamento.",
      },
      {
        aspecto: "conclusao",
        label: "Conclusao",
        texto: "Conclusao anterior.",
      },
    ];

    expect(comporRascunhoConclusaoDosAchados(achados, "topicos")).toBe(
      "* Valva mitral: Espessamento mitral leve com refluxo leve.\n" +
        "* Pericardio: Efusao pericardica discreta sem tamponamento.",
    );
    expect(comporRascunhoConclusaoDosAchados(achados, "paragrafo")).toBe(
      "Valva mitral: Espessamento mitral leve com refluxo leve. " +
        "Pericardio: Efusao pericardica discreta sem tamponamento.",
    );
  });

  it("preserva a conclusao do preset e acrescenta somente os aspectos alterados", () => {
    const conclusaoBase =
      "* Disfunção diastólica grau I.\n" +
      "* Redução do diâmetro ventricular associada à desidratação.";
    const achados = [
      {
        aspecto: "valva_mitral",
        label: "Valva mitral",
        texto: "Texto detalhado da mitral.",
        origem: "alterado" as const,
        frase: {
          id: 3,
          titulo: "Espessamento mitral leve com refluxo leve",
          texto: "Texto detalhado da mitral.",
          tags: ["endocardiose", "leve"],
        },
      },
      {
        aspecto: "ventriculo_esquerdo",
        label: "Ventriculo esquerdo",
        texto: "Diâmetro reduzido.",
        origem: "preset" as const,
        frase: {
          id: 77,
          titulo: "VE Desidratação",
          texto: "Diâmetro reduzido.",
        },
      },
      {
        aspecto: "pericardio",
        label: "Pericardio",
        texto: "Efusao pericardica discreta sem tamponamento.",
        origem: "manual" as const,
      },
    ];

    expect(comporRascunhoConclusaoDosAchados(achados, "topicos", conclusaoBase)).toBe(
      `${conclusaoBase}\n` +
        "* Valva mitral: Espessamento mitral leve com refluxo leve.\n" +
        "* Pericardio: Efusao pericardica discreta sem tamponamento.",
    );
    expect(comporRascunhoConclusaoDosAchados(achados, "paragrafo", conclusaoBase)).toBe(
      `${conclusaoBase} ` +
        "Valva mitral: Espessamento mitral leve com refluxo leve. " +
        "Pericardio: Efusao pericardica discreta sem tamponamento.",
    );
  });
});
