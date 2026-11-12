import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EcocardiogramaEstruturadoBiblioteca from "./EcocardiogramaEstruturadoBiblioteca";

vi.mock("@/lib/frases-ecocardiograma-estruturado-teste-api", () => ({
  carregarBancoEcoEstruturadoTeste: vi.fn().mockResolvedValue({
    version: "1",
    mode: "teste",
    last_updated: "",
    aspectos: [{
      key: "funcao_diastolica",
      label: "Funcao diastolica",
      categoria: "Funcao",
      descricao: "",
      placeholder: "",
      legacy_field: "funcao",
      ordem: 1,
      frases: [{
        id: 301,
        titulo: "Função diastólica felina: padrão restritivo",
        texto: "Padrão restritivo após avaliação integrada.",
        ativo: 1,
      }],
    }],
    presets: [{
      id: 81,
      key: "felino_diastolica_restritivo",
      label: "Função diastólica felina: padrão restritivo",
      patologia: "Função diastólica felina",
      tags: ["gato", "diastolica", "complementar"],
      ativo: 1,
      selecoes: [{
        aspecto: "funcao_diastolica",
        frase_id: null,
        frase_titulo: "Função diastólica felina: padrão restritivo",
      }],
    }],
  }),
}));

describe("biblioteca de presets ecocardiográficos", () => {
  it("reconhece a frase pelo título quando o preset não possui ID da frase", async () => {
    render(<EcocardiogramaEstruturadoBiblioteca />);
    fireEvent.click(await screen.findByRole("button", { name: "Presets" }));
    fireEvent.click(screen.getByRole("button", { name: /Função diastólica felina: padrão restritivo Função diastólica felina Ativo/ }));

    const opcao = screen.getByRole("option", {
      name: "Função diastólica felina: padrão restritivo",
    });
    expect((opcao as HTMLOptionElement).selected).toBe(true);
  });
});
