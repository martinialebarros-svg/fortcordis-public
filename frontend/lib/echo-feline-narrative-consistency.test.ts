import { describe, expect, it } from "vitest";
import { findFelineNarrativeDiscrepancies } from "./echo-feline-narrative-consistency";

const flow = { Diastolica_ondas: "fundidas", TDI_ondas: "separadas" };
const tissue = { Diastolica_ondas: "separadas", TDI_ondas: "fundidas" };
const check = (text: string, measurements = flow, species = "Felina") =>
  findFelineNarrativeDiscrepancies(measurements, { funcao: text }, "", species);

describe("conferência conservadora da narrativa diastólica felina", () => {
  it.each([
    "Ondas E e A separadas e mensuráveis.",
    "Ondas E/A individualizadas.",
    "Função diastólica preservada, com padrão de enchimento adequado ao Doppler transmitral.",
    "Relação E/A de 1,14.", "E/A = 1.14.", "E/TRIV: 2,7.", "E/e′ de 6,75.",
    "Padrão tipo I com inversão da relação E/A ao Doppler transmitral.",
    "Padrão de enchimento com relação E/A aparentemente normal (pseudonormal).",
    "Relação E/A acentuadamente elevada, tempo de desaceleração encurtado e velocidade de onda E elevada.",
    "Relação E/A encontra-se normal.",
    "Sem sinais congestivos, relação E/A de 1,14.",
  ])("sinaliza a afirmação transmitral atual: %s", (text) => {
    expect(check(text)).toMatchObject([{ key: "feline_transmitral_fusion", section: "Função", excerpt: text }]);
  });

  it.each([
    "Função diastólica preservada pela avaliação multiparamétrica.",
    "Função sistólica aumentada em contexto de estresse, FE 94%, FEC 64%.",
    "Não há separação entre as ondas E e A.",
    "E/A não mensurável por fusão.",
    "Não foi possível avaliar o padrão transmitral.",
    "Em exame anterior, E/A=1,2; neste exame há fusão.",
    "No exame de 2024, E/A = 1,2.",
    "Relação E/A importada de 1,14, sem interpretação independente.",
    "Quando separadas, E e A devem ser mensuradas.",
    "Se ondas E e A separadas, avaliar E/A = 1,2.",
    "Hipótese de padrão restritivo ao Doppler transmitral.",
    "Relação E/A de 1,14 não interpretável por fusão.",
    "Relação E/A de 1,14, desconsiderada por artefato.",
    "Relação E/A de 1,14?",
    "Avaliar padrão de enchimento adequado ao Doppler transmitral.",
    "Doppler tecidual lateral: e′ de 0,16 m/s e a′ de 0,06 m/s.",
    "Relação e′/a′ de 2,67.",
  ])("preserva afirmação integrada, independente ou qualificada: %s", (text) => {
    expect(check(text)).toEqual([]);
  });

  it.each(["Ondas e′ e a′ separadas e mensuráveis.", "Relação e’/a’ de 1,33.", "E/e' = 6.95.", "e′ lateral de 0,16 m/s."])(
    "suspensão tecidual sinaliza somente o grupo correspondente: %s", (text) => {
      expect(check(text, tissue)).toMatchObject([{ key: "feline_tissue_fusion", excerpt: text }]);
    },
  );

  it.each(["Relação E/A de 1,14.", "Ondas E e A separadas.", "E/TRIV = 2,7."])(
    "fusão tecidual não invalida transmitral independente: %s", (text) => expect(check(text, tissue)).toEqual([]),
  );

  it.each(["Felina", "Felino", "Gato", "Cat", " cats "])("aceita somente os aliases exatos conhecidos: %s", (species) => {
    expect(check("Ondas E/A separadas.", flow, species)).toHaveLength(1);
  });
  it.each(["", "Canina", "Cattle", "Catfish", "Gato selvagem"])("não aplica regra felina à espécie %s", (species) => {
    expect(check("Ondas E/A separadas.", flow, species)).toEqual([]);
  });

  it("não infere fusão de números e preserva integralmente os dados", () => {
    const measurements = Object.freeze({ Diastolica_ondas: "", TDI_ondas: "", E_A: "1.14", FE_Teicholz: "94" });
    const qualitative = Object.freeze({ funcao: "Ondas E/A separadas." });
    expect(findFelineNarrativeDiscrepancies(measurements, qualitative, "", "Felina")).toEqual([]);
    expect(measurements).toEqual({ Diastolica_ondas: "", TDI_ondas: "", E_A: "1.14", FE_Teicholz: "94" });
    expect(qualitative.funcao).toBe("Ondas E/A separadas.");
  });

  it("localiza a conclusão e limita cada família a um aviso", () => {
    const measurements = { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" };
    const issues = findFelineNarrativeDiscrepancies(measurements, {}, "Relação E/A de 1,14. Relação E/A de 1,3. Relação e′/a′ de 2,67.", "Cat");
    expect(issues).toHaveLength(2);
    expect(issues[0]).toMatchObject({ key: "feline_transmitral_fusion", section: "Conclusão", excerpt: "Relação E/A de 1,14." });
    expect(issues[1].key).toBe("feline_tissue_fusion");
  });

  describe("regressões P2: velocidades transmitrais individuais", () => {
    it.each([
      "E de 1,08 m/s e onda A de 0,95 m/s.",
      "Velocidade da onda E de 1,08 m/s e da onda A de 0,95 m/s.",
      "Ondas E 1,08 m/s e A 0,95 m/s.",
      "Onda E de 1,08 m/s.",
      "Onda A de 0,95 m/s.",
      "E de 1,08 m/s.",
      "A de 0,95 m/s.",
      "Pico E de 1.08 m/s.",
      "Pico A: 0,95m/s.",
      "Onda E = 108 cm/s, onda A = 95 cm/s.",
      "Pico A de 95cm/s.",
    ])("avisa sobre o pico individual atual com unidade: %s", (text) => {
      expect(check(text)).toMatchObject([
        { key: "feline_transmitral_fusion", section: "Função", excerpt: text },
      ]);
      expect(check(text, tissue)).toEqual([]);
    });

    it.each([
      "Não foi possível medir a onda E de 1,08 m/s.",
      "Onda E de 1,08 m/s não mensurável por fusão.",
      "Onda A de 0,95 m/s, desconsiderada por artefato.",
      "Em exame anterior, onda E de 1,08 m/s e onda A de 0,95 m/s.",
      "No exame de 2024, pico A de 95 cm/s.",
      "Quando separadas, E de 1,08 m/s e A de 0,95 m/s.",
      "Se as ondas estiverem separadas, medir E de 1,08 m/s e A de 0,95 m/s.",
      "Verificar onda E de 1,08 m/s.",
      "Pico E de 1,08 m/s?",
      "E=0,80 m/s, A=0,60 m/s, ambos descartados.",
      "E =0,80 m/s, A =0,60 m/s, descartados por artefato.",
      "E =0,80 m/s, A =0,60 m/s, não interpretáveis por fusão.",
      "E / A = 1,14 m/s, desconsiderada por artefato.",
      "Onda E de 1,08.",
      "Pico A de 0,95 cm.",
      "Distância E de 1,08 mm.",
      "Doppler tecidual: e′ de 0,16 m/s e a′ de 0,06 m/s.",
    ])("preserva limitação, contexto, unidade ausente ou família independente: %s", (text) => {
      expect(check(text)).toEqual([]);
    });

    it.each([
      "Relação E / A de 1,14.",
      "Relação E / A de 1,14 m/s.",
    ])("mantém a família da razão espaçada, inclusive com unidade inadequada: %s", (text) => {
      expect(check(text)).toMatchObject([{ key: "feline_transmitral_fusion", excerpt: text }]);
      expect(check(text, tissue)).toEqual([]);
    });
  });

  describe("regressões P2: qualificador restrito à afirmação correspondente", () => {
    it.each([
      "Com ondas fundidas, relação E/A de1,14.",
      "Com ondas transmitrais fundidas, relação E/A de1,14.",
      "Com ondas E/A fundidas, relação E/A de1,14.",
      "Com ondas fundidas, relação e′/a′ de1,33.",
      "Com ondas teciduais fundidas, relação e′/a′ de1,33.",
      "Com ondas e′/a′ fundidas, relação e′/a′ de1,33.",
      "Não interpretável a relação E/A, relação E/A de1,14.",
      "Descartada a relação E/A, relação E/A de1,14.",
      "Não interpretável o pico e′, e′ de 0,16 m/s.",
      "Descartado o pico a′, a′ de 0,06 m/s.",
    ])("ressalva inicial explícita limita a própria medida: %s", (text) => {
      expect(check(text, { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" })).toEqual([]);
    });

    it.each([
      { text: "Com ondas E/A fundidas, relação e′/a′ de1,33.", key: "feline_tissue_fusion" },
      { text: "Com ondas e′/a′ fundidas, relação E/A de1,14.", key: "feline_transmitral_fusion" },
      { text: "Com ondas E/A fundidas, ondas e′ e a′ separadas e mensuráveis.", key: "feline_tissue_fusion" },
      { text: "Com ondas e′/a′ fundidas, ondas E e A separadas e mensuráveis.", key: "feline_transmitral_fusion" },
      { text: "Não há refluxo, relação E/A de1,14.", key: "feline_transmitral_fusion" },
    ])("ressalva inicial não oculta afirmação de outra família ou achado independente: $text", ({ text, key }) => {
      const issues = check(text, { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" });
      expect(issues).toHaveLength(1);
      expect(issues[0]).toMatchObject({ key, section: "Função", excerpt: text });
    });

    it.each([
      "Não há aumento atrial, e a relação E/A é 1,14.",
      "Não há derrame pericárdico; relação E/A de 1,14.",
      "Não foi observado refluxo mitral, relação E/A = 1,14.",
      "Relação E/A de 1,14, não há refluxo.",
      "E/A=1,14, sem interpretação do Doppler tecidual.",
      "E/A=1,14; não interpretável a função sistólica por artefato.",
      "Não há aumento atrial; onda E de 1,08 m/s e onda A de 0,95 m/s.",
    ])("um achado negativo independente não oculta o claim transmitral: %s", (text) => {
      const issues = check(text);
      expect(issues).toHaveLength(1);
      expect(issues[0]).toMatchObject({ key: "feline_transmitral_fusion", excerpt: text });
    });

    it.each([
      "Não há aumento atrial, e a relação e′/a′ é 1,33.",
      "Não há derrame pericárdico; relação e′/a′ de 1,33.",
      "Não há hipertrofia ventricular; e′ lateral de 0,16 m/s.",
    ])("um achado negativo independente não oculta o claim tecidual: %s", (text) => {
      const issues = check(text, tissue);
      expect(issues).toHaveLength(1);
      expect(issues[0]).toMatchObject({ key: "feline_tissue_fusion", excerpt: text });
    });

    it.each([
      "Não há aumento atrial, e a relação E/A não é mensurável.",
      "Não há relação E/A de 1,14 mensurável neste exame.",
      "Relação E/A de 1,14 desconsiderada por artefato.",
      "Relação E/A de 1,14 registrada no exame anterior.",
      "Relação E/A de 1,14, registrada no exame anterior.",
      "Relação E/A de 1,14, com ondas fundidas.",
      "Relação E/A de1,14, importada do relatório anterior.",
      "Relação E/A de1,14, previamente registrada no exame anterior.",
      "Relação E/A de1,14, sobreposição de ondas.",
      "Em exame anterior, relação E/A de 1,14.",
      "Se as ondas forem individualizadas, avaliar relação E/A de 1,14.",
      "Quando as ondas estiverem separadas, relação E/A de 1,14 poderá ser avaliada.",
      "When E/A=1.14.",
      "Hipótese de relação E/A de 1,14.",
      "Não há relação e′/a′ de 1,33 mensurável neste exame.",
      "Relação e′/a′ de 1,33 desconsiderada por artefato.",
      "Anteriormente, relação e′/a′ de 1,33.",
      "Se as ondas teciduais forem separadas, avaliar relação e′/a′ de 1,33.",
      "Relação e′/a′ de 1,33 não interpretável por fusão.",
      "Relação e′/a′ de 1,33, registrada no exame anterior.",
      "Relação e′/a′ de 1,33, com ondas fundidas.",
      "No exame anterior, relação E/A de 1,14; relação e′/a′ de 1,33.",
    ])("continua respeitando negação, histórico e condição aplicados ao claim: %s", (text) => {
      expect(check(text, { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" })).toEqual([]);
    });

    it.each([
      { text: "E/e′=6,75, não interpretável por fusão tecidual.", measurements: flow },
      { text: "E/e′=6,75, não interpretável por fusão transmitral.", measurements: tissue },
    ])("respeita a limitação da relação compartilhada E/e′: $text", ({ text, measurements }) => {
      expect(check(text, measurements)).toEqual([]);
    });

    it.each([
      { text: "Relação E/A não mensurável por fusão; relação e′/a′ de 1,33.", key: "feline_tissue_fusion" },
      { text: "Relação E/A não mensurável por fusão, mas relação e′/a′ de 1,33.", key: "feline_tissue_fusion" },
      { text: "Relação e′/a′ não mensurável por fusão; relação E/A de 1,14.", key: "feline_transmitral_fusion" },
      { text: "Relação e′/a′ de 1,33 desconsiderada por artefato, mas relação E/A de 1,14.", key: "feline_transmitral_fusion" },
      { text: "Em exame anterior, E/A de 1,20; e′ lateral de 0,16 m/s neste exame.", key: "feline_tissue_fusion" },
      { text: "Se as ondas E/A estiverem separadas, avaliar E/A de 1,14; relação e′/a′ de 1,33.", key: "feline_tissue_fusion" },
      { text: "Onda E de 1,08 m/s desconsiderada por artefato; onda A de 0,95 m/s.", key: "feline_transmitral_fusion" },
      { text: "Relação E/A de 1,14 desconsiderada por artefato; relação E/A de 1,20.", key: "feline_transmitral_fusion" },
      { text: "Em exame anterior, relação E/A de 1,14; atualmente relação E/A de 1,20.", key: "feline_transmitral_fusion" },
      { text: "Se as ondas estiverem separadas, relação E/A de 1,14; atualmente relação E/A de 1,20.", key: "feline_transmitral_fusion" },
      { text: "No exame anterior, relação E/A de 1,14; atualmente relação e′/a′ de 1,33.", key: "feline_tissue_fusion" },
      { text: "No exame anterior, relação E/A de 1,14; neste exame relação e′/a′ de 1,33.", key: "feline_tissue_fusion" },
      { text: "No exame anterior, relação E/A de 1,14; no exame atual relação e′/a′ de 1,33.", key: "feline_tissue_fusion" },
    ])("detecta somente o claim afirmativo na frase mista: $text", ({ text, key }) => {
      const issues = check(text, { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" });
      expect(issues).toHaveLength(1);
      expect(issues[0]).toMatchObject({ key, section: "Função", excerpt: text });
    });

    it("preserva os objetos e o literal inteiro ao avaliar duas famílias na conclusão", () => {
      const measurements = Object.freeze({ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas", Onda_E: "1.08", Onda_A: "0.95" });
      const qualitative = Object.freeze({ funcao: "Interpretação integrada preservada." });
      const conclusion = "Não há aumento atrial; E de 1,08 m/s e relação e′/a′ de 1,33.";
      const issues = findFelineNarrativeDiscrepancies(measurements, qualitative, conclusion, "Gato");
      expect(issues).toHaveLength(2);
      expect(issues.map(({ key }) => key)).toEqual(["feline_transmitral_fusion", "feline_tissue_fusion"]);
      issues.forEach((issue) => expect(issue).toMatchObject({ section: "Conclusão", excerpt: conclusion }));
      expect(measurements).toEqual({ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas", Onda_E: "1.08", Onda_A: "0.95" });
      expect(qualitative).toEqual({ funcao: "Interpretação integrada preservada." });
    });
  });
});
