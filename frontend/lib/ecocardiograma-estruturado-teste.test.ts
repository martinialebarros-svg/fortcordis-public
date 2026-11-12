import { describe, expect, it } from "vitest";
import { presetCompativelComEspecie, type PresetEcoEstruturadoTeste } from "./ecocardiograma-estruturado-teste";

const preset = (tags: string[]): PresetEcoEstruturadoTeste => ({
  id: 1, key: "teste", label: "Teste", tags, selecoes: [],
});

describe("compatibilidade de preset por espécie", () => {
  it.each(["Felina", "felino", "FELINOS", "Feline", " Gato ", "gatos", "Cat", "CATS"])
    ("bloqueia presets exclusivamente caninos e mantém os comuns para %s", (species) => {
      expect(presetCompativelComEspecie(preset(["cao"]), species)).toBe(false);
      expect(presetCompativelComEspecie(preset(["gato"]), species)).toBe(true);
      expect(presetCompativelComEspecie(preset(["cao", "gato"]), species)).toBe(true);
      expect(presetCompativelComEspecie(preset([]), species)).toBe(true);
    });

  it("não atribui a restrição felina a espécie ausente ou desconhecida", () => {
    for (const species of [undefined, "Equina", "Catfish", "feliniforme", "Dogfish", "Caniniforme", "Cão selvagem"]) {
      expect(presetCompativelComEspecie(preset(["cao"]), species)).toBe(true);
      expect(presetCompativelComEspecie(preset(["gato"]), species)).toBe(true);
    }
  });

  it.each(["Canina", "canino", "CANINOS", "Canine", " Cao ", "Cão", "Cães", "cachorro", "CACHORROS", " Dog ", "Dogs"])
    ("bloqueia presets exclusivamente felinos e mantém os comuns para %s", (species) => {
      expect(presetCompativelComEspecie(preset(["gato"]), species)).toBe(false);
      expect(presetCompativelComEspecie(preset(["cao"]), species)).toBe(true);
      expect(presetCompativelComEspecie(preset(["cao", "gato"]), species)).toBe(true);
      expect(presetCompativelComEspecie(preset([]), species)).toBe(true);
    });

  it("mantém opções comuns e separa opções exclusivas de gato e cão", () => {
    expect(presetCompativelComEspecie(preset(["gato"]), "Felina")).toBe(true);
    expect(presetCompativelComEspecie(preset(["gato"]), "Canina")).toBe(false);
    expect(presetCompativelComEspecie(preset(["cao"]), "Felina")).toBe(false);
    expect(presetCompativelComEspecie(preset(["cao", "gato"]), "Felina")).toBe(true);
    expect(presetCompativelComEspecie(preset([]), "Canina")).toBe(true);
  });
});
