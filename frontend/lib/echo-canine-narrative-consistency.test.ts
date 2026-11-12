import { describe, expect, it } from "vitest";
import { findEchoNarrativeDiscrepancies } from "./echo-narrative-consistency";

const flow = { Diastolica_ondas: "fundidas", TDI_ondas: "separadas" };
const tissue = { Diastolica_ondas: "separadas", TDI_ondas: "fundidas" };
const both = { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" };
const speciesCases = [
  { species: "Canina", prefix: "canine" },
  { species: "Felina", prefix: "feline" },
] as const;

const check = (text: string, measurements: Record<string, string>, species: string) =>
  findEchoNarrativeDiscrepancies(measurements, { funcao: text }, "", species);

describe.each(speciesCases)("coerência contextual de ondas pela entrada pública: $species", ({ species, prefix }) => {
  it.each([
    "Ondas E e A separadas e mensuráveis.",
    "Ondas E/A individualizadas.",
    "Relação E/A de 1,14.",
    "E/TRIV: 2,7.",
    "Onda E de 1,08 m/s.",
    "Pico A: 0,95m/s.",
    "E = 108 cm/s, A = 95 cm/s.",
    "Função diastólica preservada, com padrão de enchimento adequado ao Doppler transmitral.",
    "Não há aumento atrial, e a relação E/A é 1,14.",
  ])("aponta a afirmação transmitral atual sem alterar o trecho: %s", (text) => {
    expect(check(text, flow, species)).toMatchObject([
      { key: `${prefix}_transmitral_fusion`, section: "Função", excerpt: text },
    ]);
    expect(check(text, tissue, species)).toEqual([]);
  });

  it.each([
    "Ondas e′ e a′ separadas e mensuráveis.",
    "Relação e′/a′ de 1,33.",
    "e′ lateral de 0,16 m/s.",
    "a′ septal de 0,06 m/s.",
  ])("aponta somente a família tecidual correspondente: %s", (text) => {
    expect(check(text, tissue, species)).toMatchObject([
      { key: `${prefix}_tissue_fusion`, section: "Função", excerpt: text },
    ]);
    expect(check(text, flow, species)).toEqual([]);
  });

  it("trata E/e′ como dependente das duas famílias de ondas", () => {
    const text = "Relação E/e′ de 6,75.";
    expect(check(text, flow, species).map((issue) => issue.key)).toEqual([`${prefix}_transmitral_fusion`]);
    expect(check(text, tissue, species).map((issue) => issue.key)).toEqual([`${prefix}_tissue_fusion`]);
    expect(check(text, both, species).map((issue) => issue.key))
      .toEqual([`${prefix}_transmitral_fusion`, `${prefix}_tissue_fusion`]);
  });

  it.each([
    "Não há separação entre as ondas E e A.",
    "E/A não mensurável por fusão.",
    "Relação E/A de 1,14, desconsiderada por artefato.",
    "E =0,80 m/s, A =0,60 m/s, descartados por artefato.",
    "Relação e′/a′ de 1,33, registrada no exame anterior.",
    "No exame anterior, relação E/A de 1,14; relação e′/a′ de 1,33.",
    "No exame de 2024, E/A = 1,2.",
    "Se ondas E e A separadas, avaliar E/A = 1,2.",
    "Hipótese de padrão restritivo ao Doppler transmitral.",
    "Relação E/A de 1,14?",
    "Com ondas fundidas, relação E/A de1,14.",
    "Função diastólica preservada pela avaliação multiparamétrica.",
    "Função sistólica aumentada em contexto de estresse, FE 94%, FEC 64%.",
  ])("preserva contexto qualificado, histórico ou avaliação integrada: %s", (text) => {
    expect(check(text, both, species)).toEqual([]);
  });

  it("encerra o histórico somente no retorno explícito ao exame atual", () => {
    const text = "No exame anterior, relação E/A de 1,14; neste exame relação e′/a′ de 1,33.";
    expect(check(text, both, species)).toMatchObject([
      { key: `${prefix}_tissue_fusion`, excerpt: text },
    ]);
  });

  it("mantém as famílias independentes diante de ressalva da outra família", () => {
    expect(check("Com ondas E/A fundidas, relação e′/a′ de1,33.", both, species)
      .map((issue) => issue.key)).toEqual([`${prefix}_tissue_fusion`]);
    expect(check("Com ondas e′/a′ fundidas, relação E/A de1,14.", both, species)
      .map((issue) => issue.key)).toEqual([`${prefix}_transmitral_fusion`]);
  });

  it.each([undefined, "", "separadas", "nao_confirmadas"])("não infere fusão de números ou da separação %s", (waves) => {
    const measurements = { Onda_E: "1.08", Onda_A: "0.95", E_A: "1.14", FE_Teicholz: "94", DeltaD_FS: "64",
      ...(waves === undefined ? {} : { Diastolica_ondas: waves, TDI_ondas: waves }) };
    expect(check("Ondas E/A separadas. Relação e′/a′ de 1,33.", measurements, species)).toEqual([]);
  });

  it("localiza a conclusão e limita os avisos a um por família sem modificar entradas", () => {
    const measurements = Object.freeze({ ...both, Onda_E: "1.08", e_doppler: "0.16" });
    const qualitative = Object.freeze({ funcao: "Interpretação integrada preservada." });
    const conclusion = "Relação E/A de 1,14. Relação E/A de 1,30. Relação e′/a′ de 1,33.";
    const result = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ key: `${prefix}_transmitral_fusion`, section: "Conclusão", excerpt: "Relação E/A de 1,14." });
    expect(result[1]).toMatchObject({ key: `${prefix}_tissue_fusion`, section: "Conclusão", excerpt: "Relação e′/a′ de 1,33." });
    expect(result.every((issue) => Boolean(issue.suggestion))).toBe(true);
    expect(measurements).toEqual({ ...both, Onda_E: "1.08", e_doppler: "0.16" });
    expect(qualitative.funcao).toBe("Interpretação integrada preservada.");
    expect(conclusion).toBe("Relação E/A de 1,14. Relação E/A de 1,30. Relação e′/a′ de 1,33.");
  });
});

describe("aliases exatos de espécie na conferência contextual", () => {
  it.each(["Canina", "Canino", "Caninos", " Canine ", "Cão", "Cães", "Cao", "Caes", "Cachorro", "Cachorros", "Dog", "DOGS"])(
    "usa chave canina sem reescrever a espécie %s", (species) => {
      expect(check("Ondas E/A separadas.", flow, species)).toMatchObject([{ key: "canine_transmitral_fusion" }]);
    },
  );
  it.each(["Felina", "Felino", "Felinos", "Feline", "Gato", "Gatos", "Cat", " CATS "])(
    "preserva as chaves felinas na entrada pública para %s", (species) => {
      expect(check("Ondas E/A separadas.", flow, species)).toMatchObject([{ key: "feline_transmitral_fusion" }]);
    },
  );
  it.each(["", "Cattle", "Catfish", "Gato selvagem", "Canina desconhecida", "Dogfish", "Equina"])(
    "não aplica a regra por substring à espécie %s", (species) => {
      expect(check("Ondas E/A separadas. Relação e′/a′ de 1,33.", both, species)).toEqual([]);
    },
  );
});
