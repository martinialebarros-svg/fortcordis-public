import { describe, expect, it } from "vitest";
import {
  addRacaCustomPorEspecie,
  editarRacaCatalogo,
  excluirRacaCatalogo,
  getRacaOptions,
  getRacasCatalogo,
} from "./racas";

describe("catálogo de raças", () => {
  it("lista as opções por ordem alfabética e mantém a raça histórica selecionável", () => {
    const opcoes = getRacaOptions("Equina", "Zebra", ["Árabe", "Crioulo"]);

    expect(opcoes).toEqual([
      "Appaloosa",
      "Árabe",
      "Crioulo",
      "Mangalarga Marchador",
      "Puro Sangue Ingles",
      "Quarto de Milha",
      "SRD",
      "Zebra",
    ]);
  });

  it("cadastra raças personalizadas sem duplicar e as mantém ordenadas", () => {
    const primeira = addRacaCustomPorEspecie({}, "Canina", "Vira-lata");
    const segunda = addRacaCustomPorEspecie(primeira, "Canina", "Affenpinscher");
    const duplicada = addRacaCustomPorEspecie(segunda, "Canina", "vira-lata");

    expect(segunda.Canina).toEqual(["Affenpinscher", "Vira-lata"]);
    expect(duplicada).toEqual(segunda);
  });

  it("renomeia e exclui tanto raça padrão quanto personalizada sem tocar em registros existentes", () => {
    const racasCustomPorEspecie = { Canina: ["Minha raça"] };
    const catalogoInicial = getRacasCatalogo("Canina", racasCustomPorEspecie.Canina);
    const poodle = catalogoInicial.find((raca) => raca.nome === "Poodle");
    const personalizada = catalogoInicial.find((raca) => raca.nome === "Minha raça");

    expect(poodle).toBeDefined();
    expect(personalizada).toBeDefined();

    const renomeada = editarRacaCatalogo(
      racasCustomPorEspecie,
      {},
      "Canina",
      poodle!,
      "Poodle Mini",
    );
    const aposRenomear = getRacasCatalogo(
      "Canina",
      renomeada.racasCustomPorEspecie.Canina,
      renomeada.ajustesPorEspecie,
    );

    expect(aposRenomear.some((raca) => raca.nome === "Poodle")).toBe(false);
    expect(aposRenomear.some((raca) => raca.nome === "Poodle Mini")).toBe(true);

    const excluidaPadrao = excluirRacaCatalogo(
      renomeada.racasCustomPorEspecie,
      renomeada.ajustesPorEspecie,
      "Canina",
      aposRenomear.find((raca) => raca.nome === "Poodle Mini")!,
    );
    const excluidaPersonalizada = excluirRacaCatalogo(
      excluidaPadrao.racasCustomPorEspecie,
      excluidaPadrao.ajustesPorEspecie,
      "Canina",
      getRacasCatalogo("Canina", excluidaPadrao.racasCustomPorEspecie.Canina).find(
        (raca) => raca.nome === "Minha raça",
      )!,
    );

    expect(
      getRacaOptions(
        "Canina",
        "Poodle",
        excluidaPersonalizada.racasCustomPorEspecie.Canina,
        excluidaPersonalizada.ajustesPorEspecie,
      ),
    ).toContain("Poodle");
    expect(
      getRacasCatalogo(
        "Canina",
        excluidaPersonalizada.racasCustomPorEspecie.Canina,
        excluidaPersonalizada.ajustesPorEspecie,
      ).map((raca) => raca.nome),
    ).not.toEqual(expect.arrayContaining(["Poodle Mini", "Minha raça"]));
  });
});
