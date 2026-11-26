import { describe, expect, it } from "vitest";
import type { FelinePediatricRange } from "../types/referencia-eco";
import { pediatricComparisonPosition } from "./pediatric-comparison-position";

const range: FelinePediatricRange = {
  status: "descriptive", lower: 8.6, upper: 15.3, unit: "mm", text: "8,60–15,30 mm",
  reason: "Coorte", source: "Gunther-Harrington et al. (2021)", doi: "10.1177/1098612X20946461",
  statistic: "published_cohort_reference_interval",
};

describe("posição visual na coorte pediátrica", () => {
  it.each([
    ["8.59", "diminuido"], ["8.6", "normal"], ["12,3", "normal"], ["15.3", "normal"], ["15.31", "aumentado"],
    [String(0.86 * 10), "normal"], [String(1.53 * 10), "normal"],
    [String(8.6 - 1e-10), "diminuido"], [String(15.3 + 1e-10), "aumentado"],
  ])("posiciona %s sem tratar arredondamento de conversão como diferença clínica", (value, status) => {
    expect(pediatricComparisonPosition(value, range)?.status).toBe(status);
  });

  it.each(["", " ", "0", "-1", "12 mm", "12abc", "12,3,4", "NaN", "Infinity", "1e999", "0x10", "0b10"])
    ("mantém neutro o valor inválido %s", (value) => {
      expect(pediatricComparisonPosition(value, range)).toBeNull();
    });

  it.each<Partial<FelinePediatricRange>>([
    { status: "requires_method" }, { status: "unavailable" },
    { lower: null }, { upper: null }, { lower: NaN }, { upper: Infinity },
    { lower: 15.3, upper: 8.6 }, { lower: 8.6, upper: 8.6 },
  ])("não colore uma faixa inelegível ou inválida: %j", (override) => {
    expect(pediatricComparisonPosition("12", { ...range, ...override })).toBeNull();
  });

  it("não cria faixa nem modifica os metadados recebidos", () => {
    expect(pediatricComparisonPosition("12")).toBeNull();
    const before = { ...range };
    expect(pediatricComparisonPosition("12", Object.freeze(range))?.text).toBe("Dentro da faixa da coorte");
    expect(range).toEqual(before);
  });
});
