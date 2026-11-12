import { describe, expect, it } from "vitest";
import { isFelineEchoSpecies, normalizeEchoSpecies } from "./echo-species";

describe("classificação explícita da espécie no ecocardiograma", () => {
  it.each(["Felina", "felino", "FELINOS", "Feline", " Gato ", "gatos", "Cat", "CATS"])
    ("reconhece o alias felino exato do backend: %s", (species) => {
      expect(normalizeEchoSpecies(species)).toBe("Felina");
      expect(isFelineEchoSpecies(species)).toBe(true);
    });

  it.each(["Canina", "canino", "CANINOS", "Canine", " Cão ", "cães", "cachorro", "cachorros", "Dog", "DOGS"])
    ("mantém os aliases caninos exatos do backend fora da classificação felina: %s", (species) => {
      expect(normalizeEchoSpecies(species)).toBe("Canina");
      expect(isFelineEchoSpecies(species)).toBe(false);
    });

  it.each(["", "Equina", "Catfish", "Cattle", "Gato selvagem", "feliniforme", "cat/dog", "gato e cão"])
    ("não infere felino por prefixo ou texto parcial: %s", (species) => {
      expect(isFelineEchoSpecies(species)).toBe(false);
      expect(normalizeEchoSpecies(species)).toBe(species);
    });

  it("mantém espécie ausente e desconhecida sem atribuir Canina ou Felina", () => {
    expect(normalizeEchoSpecies(undefined)).toBe("");
    expect(normalizeEchoSpecies(null)).toBe("");
    expect(isFelineEchoSpecies(undefined)).toBe(false);
    expect(normalizeEchoSpecies("  Outra espécie  ")).toBe("Outra espécie");
  });
});
