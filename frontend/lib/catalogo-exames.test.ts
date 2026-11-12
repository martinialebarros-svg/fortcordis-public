import { describe, expect, it } from "vitest";
import {
  ordenarCatalogoExames,
  parseCatalogoExameSinonimos,
  removeCatalogoExame,
  upsertCatalogoExame,
} from "./catalogo-exames";

describe("catalogo de exames customizados", () => {
  it("ordena alfabeticamente em portugues", () => {
    expect(
      ordenarCatalogoExames([
        { id: 2, nome: "Ultrassonografia" },
        { id: 1, nome: "Ácido úrico" },
        { id: 3, nome: "Creatinina" },
      ]).map((item) => item.nome)
    ).toEqual(["Ácido úrico", "Creatinina", "Ultrassonografia"]);
  });

  it("insere ou atualiza sem duplicar e conserva a ordenacao", () => {
    expect(
      upsertCatalogoExame(
        [
          { id: 1, nome: "Hemograma" },
          { id: 2, nome: "Ureia" },
        ],
        { id: 2, nome: "Creatinina" }
      )
    ).toEqual([
      { id: 2, nome: "Creatinina" },
      { id: 1, nome: "Hemograma" },
    ]);
  });

  it("remove somente o item informado", () => {
    expect(
      removeCatalogoExame(
        [
          { id: 1, nome: "Hemograma" },
          { id: 2, nome: "Ureia" },
        ],
        1
      )
    ).toEqual([{ id: 2, nome: "Ureia" }]);
  });

  it("normaliza sinonimos separados por virgula ou linha", () => {
    expect(parseCatalogoExameSinonimos("RPCU, UPC\nrpcu\n  relacao P/C  ")).toEqual([
      "RPCU",
      "UPC",
      "relacao P/C",
    ]);
  });
});
