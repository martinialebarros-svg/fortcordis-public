import { describe, expect, it } from "vitest";
import { findEchoNarrativeDiscrepancies } from "./echo-narrative-consistency";

describe("conferência numérica da narrativa ecocardiográfica", () => {
  it("sinaliza as três afirmações divergentes do padrão observado em PDF real, sem editar o texto", () => {
    const measurements = {
      VE_tecnica_relatorio: "modo_m", FE_Teicholz: "95", DeltaD_FS: "67", Vmax_aorta: "0.69",
    };
    const qualitative = {
      funcao: "Fração de ejeção estimada em 97% e fração de encurtamento de 71%.",
      vasos: "Velocidade aórtica superior a 3 m/s na via de saída do ventrículo esquerdo.",
    };
    expect(findEchoNarrativeDiscrepancies(measurements, qualitative, "").map((issue) => issue.key))
      .toEqual(["FE", "FEC", "Vmax_aorta"]);
    expect(qualitative.funcao).toContain("97%");
  });

  it("não bloqueia frases coerentes, pequenas diferenças de arredondamento ou métodos não selecionados", () => {
    const measurements = {
      VE_tecnica_relatorio: "2d", FE_Teicholz: "95", DeltaD_FS: "67",
      FE_Teicholz_2D: "61", DeltaD_FS_2D: "32", Vmax_aorta: "3.4",
    };
    expect(findEchoNarrativeDiscrepancies(
      measurements,
      { funcao: "Fração de ejeção de 61% e fração de encurtamento de 32%." },
      "Velocidade aórtica superior a 3 m/s.",
    )).toEqual([]);
    expect(findEchoNarrativeDiscrepancies(
      { FE_Teicholz: "95", DeltaD_FS: "67", FE_Teicholz_2D: "61" },
      { funcao: "Fração de ejeção de 97%." }, "",
    )).toEqual([]);
  });

  it("não equipara texto de via de saída a Vmax aórtica sem linguagem explícita", () => {
    expect(findEchoNarrativeDiscrepancies(
      { Vmax_aorta: "0.69" },
      { vasos: "Gradiente na via de saída acima de 3 m/s." }, "",
    )).toEqual([]);
  });
});

describe("comparação literal da narrativa com a tabela selecionada", () => {
  const keys = (measurements: Record<string, string>, text: string) =>
    findEchoNarrativeDiscrepancies(measurements, { camaras: text }, "", "Canina").map((issue) => issue.key);

  it.each([
    ["DIVEd", "30", "DIVEd de 42 mm."],
    ["SIVd", "6", "SIVd = 9 mm."],
    ["PLVEd", "7", "PLVEd de 10 mm."],
    ["DIVES", "18", "DIVEs de 25 mm."],
    ["SIVs", "9", "SIVs = 12 mm."],
    ["PLVES", "10", "PLVEs de 14 mm."],
  ])("compara %s do modo M com rótulo e unidade explícitos", (key, value, text) => {
    expect(keys({ VE_tecnica_relatorio: "modo_m", [key]: value }, text)).toEqual([key]);
  });

  it.each([
    ["DIVEd_2D", "30", "DIVEd 2D de 42 mm."],
    ["SIVd_2D", "6", "SIVd 2D = 9 mm."],
    ["PLVEd_2D", "7", "PLVEd 2D de 10 mm."],
    ["DIVES_2D", "18", "DIVEs 2D de 25 mm."],
    ["SIVs_2D", "9", "SIVs 2D = 12 mm."],
    ["PLVES_2D", "10", "PLVEs 2D de 14 mm."],
  ])("compara %s da técnica 2D selecionada", (key, value, text) => {
    expect(keys({ VE_tecnica_relatorio: "2d", [key]: value }, text)).toEqual([key]);
  });

  it.each([
    ["AE_Ao", "1.40", "Relação AE/Ao de 1,80."],
    ["Aorta", "18", "Aorta de 24 mm."],
    ["Atrio_esquerdo", "24", "Átrio esquerdo de 32 mm."],
    ["Vmax_aorta", "0.80", "Velocidade aórtica de 1,20 m/s."],
    ["Vmax_pulmonar", "0.80", "Vmax pulmonar = 120 cm/s."],
    ["Vmax_VSVE", "0.80", "Vmax da via de saída do VE de 1,20 m/s."],
  ])("compara %s sem inferir classificação clínica", (key, value, text) => {
    expect(keys({ [key]: value }, text)).toEqual([key]);
  });

  it("mantém trecho original, seção, sugestão manual e um único aviso por parâmetro", () => {
    const text = "Átrio esquerdo de 32,0 mm; átrio esquerdo de 33,0 mm.";
    const measurements = Object.freeze({ Atrio_esquerdo: "24" });
    const qualitative = Object.freeze({ camaras: text });
    const result = findEchoNarrativeDiscrepancies(measurements, qualitative, "", "Canina");
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ key: "Atrio_esquerdo", section: "Câmaras", excerpt: text, suggestion: expect.any(String) });
    expect(measurements).toEqual({ Atrio_esquerdo: "24" });
    expect(qualitative).toEqual({ camaras: text });
  });

  it("consulta também a conclusão como fonte oficial", () => {
    const text = "AE/Ao = 1,80.";
    expect(findEchoNarrativeDiscrepancies({ AE_Ao: "1.40" }, {}, text, "Felina"))
      .toEqual([expect.objectContaining({ key: "AE_Ao", section: "Conclusão", excerpt: text })]);
  });

  it("normaliza unidades declaradas no texto e na proveniência da tabela", () => {
    expect(keys({ VE_tecnica_relatorio: "modo_m", DIVEd: "30" }, "DIVEd de 3,0 cm.")).toEqual([]);
    expect(keys({ VE_tecnica_relatorio: "modo_m", DIVEd: "3", unidade_confirmada_DIVEd: "cm" }, "DIVEd de 30 mm.")).toEqual([]);
    expect(keys({ VE_tecnica_relatorio: "modo_m", DIVEd: "3", unidade_confirmada_DIVEd: "cm" }, "DIVEd de 42 mm.")).toEqual(["DIVEd"]);
    expect(keys({ Vmax_pulmonar: "0.80" }, "Vmax pulmonar de 80 cm/s.")).toEqual([]);
  });

  it("considera a precisão decimal escrita sem usar tolerância clínica", () => {
    expect(keys({ VE_tecnica_relatorio: "modo_m", DIVEd: "30.49" }, "DIVEd de 30 mm.")).toEqual([]);
    expect(keys({ VE_tecnica_relatorio: "modo_m", DIVEd: "30.51" }, "DIVEd de 30 mm.")).toEqual(["DIVEd"]);
    expect(keys({ AE_Ao: "1.604" }, "AE/Ao de 1,60.")).toEqual([]);
    expect(keys({ AE_Ao: "1.606" }, "AE/Ao de 1,60.")).toEqual(["AE_Ao"]);
    expect(keys({ Vmax_pulmonar: "0.804" }, "Vmax pulmonar de 0,80 m/s.")).toEqual([]);
    expect(keys({ Vmax_pulmonar: "0.806" }, "Vmax pulmonar de 0,80 m/s.")).toEqual(["Vmax_pulmonar"]);
  });

  it("seleciona uma família única válida e não mistura métodos ambíguos ou distintos", () => {
    expect(keys({ DIVEd: "30" }, "DIVEd de 42 mm.")).toEqual(["DIVEd"]);
    expect(keys({ DIVEd_2D: "30" }, "DIVEd de 42 mm.")).toEqual(["DIVEd_2D"]);
    expect(keys({ DIVEd: "30", DIVEd_2D: "32" }, "DIVEd de 42 mm.")).toEqual([]);
    expect(keys({ VE_tecnica_relatorio: "2d", DIVEd: "30" }, "DIVEd de 42 mm.")).toEqual([]);
    expect(keys({ VE_tecnica_relatorio: "2d", DIVEd: "42", DIVEd_2D: "30" }, "DIVEd em modo M de 42 mm.")).toEqual([]);
  });

  it("deixa dimensões com unidade de origem ambígua sem comparação", () => {
    expect(keys({ DIVEd: "3", SIVd: "0.6", PLVEd: "0.7" }, "DIVEd de 42 mm; SIVd de 9 mm.")).toEqual([]);
  });

  it("mantém os sítios de fluxo independentes e exige rótulos numéricos inequívocos", () => {
    expect(keys({ Vmax_aorta: "0.80", Vmax_VSVE: "1.20" }, "Vmax da via de saída do VE de 1,20 m/s.")).toEqual([]);
    expect(keys({ Vmax_VSVE: "0.80" }, "Velocidade aórtica de 1,20 m/s.")).toEqual([]);
    expect(keys({ DIVEd: "30", AE_Ao: "1.40", Aorta: "18" }, "VE de 42 mm; relação de 1,80; aorta sem alteração.")).toEqual([]);
    expect(keys({ DIVEd: "30", Vmax_pulmonar: "0.80" }, "DIVEd de 42; Vmax pulmonar de 1,20.")).toEqual([]);
  });

  it.each(["", "0", "-1", "NaN", "Infinity", "30abc", "3,0,0"])("não usa valor canônico inválido ou limpo %j nem ressuscita seu alias", (value) => {
    expect(keys({ VE_tecnica_relatorio: "modo_m", DIVEd: value, LVIDd: "30" }, "DIVEd de 42 mm.")).toEqual([]);
    expect(keys({ AE_Ao: value, LA_Ao: "1.40" }, "AE/Ao de 1,80.")).toEqual([]);
    expect(keys({ Vmax_pulmonar: value, Vmax_Pulm: "0.80" }, "Vmax pulmonar de 1,20 m/s.")).toEqual([]);
  });

  it.each([
    [{ LVIDd: "30" }, "DIVEd de 42 mm."],
    [{ Ao: "18" }, "Aorta de 24 mm."],
    [{ LA: "24" }, "Átrio esquerdo de 32 mm."],
    [{ LA_Ao: "1.40" }, "AE/Ao de 1,80."],
    [{ Vmax_Ao: "0.80" }, "Velocidade aórtica de 1,20 m/s."],
    [{ Vmax_Pulm: "0.80" }, "Vmax pulmonar de 1,20 m/s."],
  ])("não promove raw alias que a tabela não apresenta como medida canônica: %j", (measurements, text) => {
    expect(keys(measurements as Record<string, string>, text as string)).toEqual([]);
  });

  it.each([
    "Referência: AE/Ao de 1,80.",
    "Limite de referência: AE/Ao até 1,80.",
    "Faixa de referência da aorta: 18 a 24 mm.",
    "Exame anterior: AE/Ao de 1,80.",
    "Histórico: aorta de 24 mm; AE/Ao de 1,80.",
    "Se AE/Ao for de 1,80, confirmar a medida.",
    "Hipótese: aorta de 24 mm.",
    "AE/Ao de 1,80?",
    "Aorta de 24 mm não foi confirmada.",
    "AE/Ao de 1,80 foi desconsiderado por artefato.",
    "AE/Ao de 1,80, valor não mensurável neste exame.",
    "Na imagem de um ciclo isolado, aorta de 24 mm; a média utilizada na tabela é de 18 mm.",
    "DIVEd de 42 mm na imagem de ciclo isolado, diferente da média de 30 mm.",
  ])("não compara referência, contexto qualificado ou imagem isolada: %s", (text) => {
    expect(keys({ VE_tecnica_relatorio: "modo_m", DIVEd: "30", Aorta: "18", AE_Ao: "1.40" }, text)).toEqual([]);
  });

  it.each([
    "Não há refluxo; AE/Ao de 1,80.",
    "Não há refluxo e AE/Ao de 1,80.",
    "AE/Ao de 1,80; não há derrame pericárdico.",
    "No exame anterior, AE/Ao de 1,40. Neste exame, AE/Ao de 1,80.",
  ])("não deixa negação alheia ou histórico suprimir menção atual independente: %s", (text) => {
    expect(keys({ AE_Ao: "1.40" }, text)).toEqual(["AE_Ao"]);
  });

  it("preserva a tolerância antiga de FE/FEC e dá contexto literal a seus avisos", () => {
    const measurements = { VE_tecnica_relatorio: "modo_m", FE_Teicholz: "60", DeltaD_FS: "30" };
    expect(keys(measurements, "Fração de ejeção de 61% e fração de encurtamento de 31%.")).toEqual([]);
    expect(findEchoNarrativeDiscrepancies(measurements, { funcao: "Fração de ejeção de 62%." }, ""))
      .toEqual([expect.objectContaining({ key: "FE", section: "Função", excerpt: "Fração de ejeção de 62%.", suggestion: expect.any(String) })]);
    expect(keys(measurements, "Referência: fração de ejeção de 80% e fração de encurtamento de 40%.")).toEqual([]);
  });

  it.each([
    ["AE/Ao de 1,0 a 1,6.", []],
    ["AE/Ao: 1,0–1,6.", []],
    ["AE/Ao de 1,6%.", []],
    ["AE/Ao de 1,41 e AE/Ao de 1,80.", ["AE_Ao"]],
    ["Sem avaliação diastólica, AE/Ao de 1,80.", ["AE_Ao"]],
    ["AE/Ao de 1,80, sem avaliação diastólica.", ["AE_Ao"]],
    ["No exame anterior, AE/Ao de 1,8. DIVEd de 25 mm.", []],
    ["No exame anterior, AE/Ao de 1,8. Neste exame, DIVEd de 25 mm.", ["DIVEd"]],
    ["Não há refluxo, AE/Ao de 1,80.", ["AE_Ao"]],
  ] as const)("mantém o escopo literal e local na revisão independente: %s", (text, expected) => {
    expect(keys({ VE_tecnica_relatorio: "modo_m", AE_Ao: "1.41", DIVEd: "19.97" }, text)).toEqual(expected);
  });

  it.each([
    ["modo_m", "Modo 2D:\nDIVEd de 35 mm."],
    ["modo_m", "Em 2D, DIVEd de 35 mm."],
    ["2d", "Modo M:\nDIVEd de 30 mm."],
  ])("não cruza técnica de cabeçalho ou cláusula com a tabela %s: %s", (mode, text) => {
    expect(keys({ VE_tecnica_relatorio: mode, DIVEd: "30", DIVEd_2D: "35" }, text)).toEqual([]);
  });

  it.each([
    ["Velocidade da aorta de 120 cm/s.", []],
    ["Velocidade da aorta de 1,20 m/s.", []],
    ["Aorta de 12 mm; velocidade da aorta de 120 cm/s.", ["Aorta"]],
  ] as const)("não interpreta unidade de velocidade como comprimento: %s", (text, expected) => {
    expect(keys({ Aorta: "10", Vmax_aorta: "1.20" }, text)).toEqual(expected);
  });

  it.each(["cm²", "cm³", "cm^2", "cm^3", "mm Hg"])("não converte área, volume ou pressão %s em diâmetro", (unit) => {
    expect(keys({ Aorta: "10" }, `Aorta de 12 ${unit}.`)).toEqual([]);
  });

  it("mantém VD e pulmonar independentes e aceita sinônimo textual de campo canônico", () => {
    expect(keys({ Vmax_VSVD: "0.90", Vmax_pulmonar: "1.50" }, "Vmax da via de saída do VD de 150 cm/s.")).toEqual(["Vmax_VSVD"]);
    expect(keys({ Vmax_VSVD: "0.90", Vmax_pulmonar: "1.50" }, "Vmax pulmonar de 1,50 m/s.")).toEqual([]);
    expect(keys({ DIVEd: "30" }, "LVIDd de 42 mm.")).toEqual(["DIVEd"]);
  });

  it("preserva redações literais antigas de FE/FEC e a qualificação local da velocidade aórtica", () => {
    expect(keys({ FE_Teicholz: "60", DeltaD_FS: "30" }, "Fração de ejeção calculada em 62%; fração de encurtamento do VE de 32%."))
      .toEqual(["FE", "FEC"]);
    expect(keys({ Vmax_aorta: "0.80" }, "Não há velocidade aórtica superior a 3 m/s.")).toEqual([]);
    expect(keys({ Vmax_aorta: "0.80" }, "Sem avaliação diastólica, velocidade aórtica superior a 3 m/s.")).toEqual(["Vmax_aorta"]);
  });

  it.each(["modo_m", "2d"])("não compara FE explicitamente Simpson com Teicholz na técnica %s", (mode) => {
    const measurements = { VE_tecnica_relatorio: mode, FE_Teicholz: "82", FE_Teicholz_2D: "82" };
    for (const label of ["Simpson", "Simpson uniplanar", "Simpson biplanar"]) {
      expect(keys(measurements, `Fração de ejeção (${label}) de 97%.`)).toEqual([]);
      expect(keys(measurements, `Fração de ejeção de 97% (${label}).`)).toEqual([]);
    }
    expect(keys(measurements, "Fração de ejeção (Teicholz) de 97%.")).toEqual(["FE"]);
  });

  it.each([
    "Fração de ejeção superior a 60%.",
    "Fração de ejeção >60%.",
    "Fração de ejeção inferior a 90%.",
    "Fração de encurtamento inferior a 50%.",
    "Fração de ejeção ≥60%.",
    "Fração de ejeção <=90%.",
    "Fração de ejeção maior ou igual a 60%.",
    "Fração de ejeção de pelo menos 60%.",
    "Fração de ejeção de 60% ou mais.",
  ])("não trata limite percentual como medida pontual: %s", (text) => {
    expect(keys({ VE_tecnica_relatorio: "modo_m", FE_Teicholz: "82", DeltaD_FS: "48" }, text)).toEqual([]);
  });
});


describe.each(["Canina", "Felina"])("contexto histórico numérico da PR #508 — %s", (species) => {
  const measurements = Object.freeze({ AE_Ao: "1.40", DIVEd: "19.97", Vmax_aorta: "0.80" });

  describe.each(["qualitativa", "conclusao"])("fonte %s", (source) => {
    const review = (text: string) => {
      const qualitative = Object.freeze(source === "qualitativa" ? { camaras: text } : {});
      const conclusion = source === "conclusao" ? text : "";
      const before = JSON.stringify({ measurements, qualitative, conclusion });
      const results = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
      expect(JSON.stringify({ measurements, qualitative, conclusion })).toBe(before);
      return results;
    };

    it.each([
      "Sem histórico de síncope", "Histórico de síncope",
      "Sem histórico de cardiopatia", "História clínica de cardiopatia",
    ].flatMap((clinicalHistory) => [". ", "\n", "; "].map((separator) => [clinicalHistory + separator])))
    ("não propaga história clínica para a medida independente: %s", (prefix) => {
      const text = `${prefix}AE/Ao de 1,80.`;
      const results = review(text);
      expect(results.map((issue) => issue.key)).toEqual(["AE_Ao"]);
      expect(results[0]).toMatchObject({ section: source === "qualitativa" ? "Câmaras" : "Conclusão", suggestion: expect.any(String) });
      expect(text).toContain(results[0].excerpt);
      expect(results[0].excerpt).toContain("AE/Ao de 1,80.");
    });

    it.each([
      "Não há história de síncope. AE/Ao de 1,80.",
      "Não há histórico de cardiopatia, AE/Ao de 1,80.",
      "Histórico de síncope e AE/Ao de 1,80.",
      "Sem exame anterior disponível. AE/Ao de 1,80.",
      "Não há estudo prévio para comparação. AE/Ao de 1,80.",
      "Exame anterior indisponível. AE/Ao de 1,80.",
      "Sem acesso ao exame anterior. AE/Ao de 1,80.",
      "Não foi realizado exame anterior. AE/Ao de 1,80.",
      "Não temos o exame anterior. AE/Ao de 1,80.",
      "Não há registro de exame anterior. AE/Ao de 1,80.",
    ])("mantém negação e contexto clínico locais: %s", (text) => {
      expect(review(text).map((issue) => issue.key)).toEqual(["AE_Ao"]);
    });

    it.each([
      "Histórico:\nAE/Ao de 1,80. DIVEd de 25 mm.",
      "Histórico: AE/Ao de 1,80. DIVEd de 25 mm.",
      "No exame anterior, AE/Ao de 1,80. DIVEd de 25 mm.",
      "No estudo prévio, AE/Ao de 1,80. DIVEd de 25 mm.",
      "Na avaliação anterior, AE/Ao de 1,80. DIVEd de 25 mm.",
      "No exame de 2025, AE/Ao de 1,80. DIVEd de 25 mm.",
      "AE/Ao de 1,80, medida no exame anterior.",
    ])("preserva atribuição explícita a passagem histórica: %s", (text) => {
      expect(review(text)).toEqual([]);
    });

    it.each([
      "Neste exame", "No exame atual", "Exame atual:", "Neste estudo",
      "Na avaliação atual", "No laudo atual", "Atualmente", "Agora",
    ])("retoma uma medição explicitamente atual com %s", (current) => {
      expect(review(`No exame anterior, AE/Ao de 1,80. ${current}, DIVEd de 25 mm.`)
        .map((issue) => issue.key)).toEqual(["DIVEd"]);
    });

    it("preserva o limite aórtico legado após história clínica independente", () => {
      expect(review("Sem histórico de síncope. Velocidade aórtica superior a 3 m/s.")
        .map((issue) => issue.key)).toEqual(["Vmax_aorta"]);
      expect(review("No exame anterior, velocidade aórtica superior a 3 m/s.")).toEqual([]);
    });

    it("não relaxa a negação da própria medida nem suprime outro campo oficial", () => {
      expect(review("AE/Ao de 1,80 não foi confirmado.")).toEqual([]);
      expect(review("Sem mensuração de AE/Ao de 1,80.")).toEqual([]);
      expect(findEchoNarrativeDiscrepancies(measurements,
        Object.freeze({ camaras: "Histórico: AE/Ao de 1,80." }), "AE/Ao de 1,80.", species)
        .map((issue) => issue.section)).toEqual(["Conclusão"]);
    });
  });
});


describe.each([
  { species: "Canina", prefix: "canine" }, { species: "Felina", prefix: "feline" },
])("contexto histórico das ondas na PR #508 — $species", ({ species, prefix }) => {
  const cases = [
    { label: "transmitral", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "separadas" },
      claim: "Relação E/A de 1,14.", families: ["transmitral"] },
    { label: "tecidual", measurements: { Diastolica_ondas: "separadas", TDI_ondas: "fundidas" },
      claim: "e′ lateral de 0,16 m/s.", families: ["tissue"] },
    { label: "E/e′ ambas", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" },
      claim: "Relação E/e′ de 6,75.", families: ["transmitral", "tissue"] },
  ];
  const expected = (families: string[]) => families.map((family) => `${prefix}_${family}_fusion`);

  describe.each(["qualitativa", "conclusao"])("fonte %s", (source) => {
    const review = (text: string, values: Record<string, string>) => {
      const measurements = Object.freeze({ ...values });
      const qualitative = Object.freeze(source === "qualitativa" ? { funcao_diastolica: text } : {});
      const conclusion = source === "conclusao" ? text : "";
      const before = JSON.stringify({ measurements, qualitative, conclusion });
      const results = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
      expect(JSON.stringify({ measurements, qualitative, conclusion })).toBe(before);
      return results;
    };

    it.each(cases.flatMap((family) => [
      "Sem histórico de síncope; ", "Histórico de cardiopatia, ",
      "História clínica de síncope\n", "Não há histórico de cardiopatia e ",
      "Sem histórico de cardiopatia. ", "Histórico de síncope\n",
      "Sem acesso ao exame anterior; ", "Não foi realizado exame anterior; ",
      "Não temos o exame anterior; ", "Não há registro de exame anterior; ",
      "História de síncope, ", "Sem história clínica de cardiopatia; ",
    ].map((clinicalContext) => ({ ...family, clinicalContext }))))
    ("não herda contexto clínico alheio para $label: $clinicalContext", ({ measurements, claim, families, clinicalContext }) => {
      const text = clinicalContext + claim;
      const results = review(text, measurements);
      expect(results.map((issue) => issue.key)).toEqual(expected(families));
      for (const issue of results) {
        expect(issue).toMatchObject({ section: source === "qualitativa" ? "Função diastólica" : "Conclusão", suggestion: expect.any(String) });
        expect(text).toContain(issue.excerpt);
        expect(issue.excerpt).toContain(claim);
      }
    });

    it.each(cases.flatMap((family) => ["No exame anterior, ", "Histórico: "]
      .map((historicalContext) => ({ ...family, historicalContext }))))
    ("preserva passagem histórica explícita de $label: $historicalContext", ({ measurements, claim, historicalContext }) => {
      expect(review(historicalContext + claim, measurements)).toEqual([]);
    });

    it("conserva negações próprias, históricos reais e retomadas atuais sem vazar entre fontes", () => {
      for (const { measurements, claim, families } of cases) {
        expect(review(`Histórico:\n${claim}`, measurements)).toEqual([]);
        expect(review(`No exame de 2024, ${claim} ${claim}`, measurements)).toEqual([]);
        expect(review(`Previamente, ${claim}`, measurements)).toEqual([]);
        expect(review(`${claim.slice(0, -1)}, não mensurável por fusão.`, measurements)).toEqual([]);
        expect(review("Sem histórico de síncope; relação E/e′ de 6,75.", measurements)
          .map((issue) => issue.key)).toEqual(expected(families));
      }
      const both = { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" };
      for (const current of ["neste exame", "neste estudo", "na avaliação atual", "no laudo atual", "atualmente"]) {
        expect(review(`No exame anterior, relação E/A de 1,14; ${current} relação e′/a′ de 1,33.`, both)
          .map((issue) => issue.key)).toEqual(expected(["tissue"]));
      }
      expect(findEchoNarrativeDiscrepancies(Object.freeze(both),
        Object.freeze({ funcao: "Histórico: relação E/A de 1,14." }), "Relação E/e′ de 6,75.", species)
        .map((issue) => issue.section)).toEqual(["Conclusão", "Conclusão"]);
    });
  });
});


describe.each([
  { species: "Canina", prefix: "canine" }, { species: "Felina", prefix: "feline" },
])("contrações de indisponibilidade da PR #508 — $species", ({ species, prefix }) => {
  const cases: { label: string; measurements: Record<string, string>; claim: string; keys: string[]; separator: string }[] = [
    { label: "numérico", measurements: { AE_Ao: "1.40" }, claim: "AE/Ao de 1,80.", keys: ["AE_Ao"], separator: ". " },
    { label: "transmitral", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "separadas" },
      claim: "Relação E/A de 1,14.", keys: [`${prefix}_transmitral_fusion`], separator: "; " },
    { label: "tecidual", measurements: { Diastolica_ondas: "separadas", TDI_ondas: "fundidas" },
      claim: "e′ lateral de 0,16 m/s.", keys: [`${prefix}_tissue_fusion`], separator: "; " },
    { label: "E/e′ ambas", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" },
      claim: "Relação E/e′ de 6,75.", keys: [`${prefix}_transmitral_fusion`, `${prefix}_tissue_fusion`], separator: "; " },
  ];
  const complements = [
    "DO exame anterior", "da avaliação anterior", "dos exames anteriores", "das avaliações anteriores",
    "de o exame anterior", "de a avaliação anterior", "de os exames anteriores", "de as avaliações anteriores",
  ];

  describe.each(["qualitativa", "conclusao"])("fonte %s", (source) => {
    const review = (text: string, values: Record<string, string>) => {
      const measurements = Object.freeze({ ...values });
      const qualitative = Object.freeze(source === "qualitativa" ? { funcao: text } : {});
      const conclusion = source === "conclusao" ? text : "";
      const before = JSON.stringify({ measurements, qualitative, conclusion });
      const results = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
      expect(JSON.stringify({ measurements, qualitative, conclusion })).toBe(before);
      return results;
    };

    it.each(cases.flatMap((entry) => complements.map((complement) => ({ ...entry, complement }))))
    ("trata de + artigo como indisponibilidade no canal $label: $complement", ({ measurements, claim, keys, separator, complement }) => {
      for (const governor of ["Não dispomos", "Não há registro", "Sem histórico"]) {
        const text = `${governor} ${complement}${separator}${claim}`;
        const results = review(text, measurements);
        expect(results.map((issue) => issue.key)).toEqual(keys);
        for (const issue of results) {
          expect(issue.section).toBe(source === "qualitativa" ? "Função" : "Conclusão");
          expect(text).toContain(issue.excerpt);
          expect(issue.excerpt).toContain(claim);
        }
      }
    });

    it("preserva a cronologia real, a negação própria e o retorno atual em todos os canais", () => {
      for (const { measurements, claim, keys } of cases) {
        expect(review(`No exame anterior, não havia síncope; ${claim}`, measurements)).toEqual([]);
        expect(review(`Histórico: ${claim}`, measurements)).toEqual([]);
        expect(review(`No exame anterior, ${claim} Neste estudo, ${claim}`, measurements)
          .map((issue) => issue.key)).toEqual(keys);
        expect(review(`${claim.slice(0, -1)} não foi confirmado.`, measurements)).toEqual([]);
      }
    });
  });
});


describe.each([
  { species: "Canina", prefix: "canine" }, { species: "Felina", prefix: "feline" },
])("gramática estrutural de disponibilidade — $species", ({ species, prefix }) => {
  const channels: { label: string; measurements: Record<string, string>; claim: string; keys: string[] }[] = [
    { label: "numérico", measurements: { AE_Ao: "1.40" }, claim: "AE/Ao de 1,80.", keys: ["AE_Ao"] },
    { label: "transmitral", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "separadas" },
      claim: "Relação E/A de 1,14.", keys: [`${prefix}_transmitral_fusion`] },
    { label: "tecidual", measurements: { Diastolica_ondas: "separadas", TDI_ondas: "fundidas" },
      claim: "e′ lateral de 0,16 m/s.", keys: [`${prefix}_tissue_fusion`] },
    { label: "E/e′ ambas", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" },
      claim: "Relação E/e′ de 6,75.", keys: [`${prefix}_transmitral_fusion`, `${prefix}_tissue_fusion`] },
  ];
  const unavailable = [
    ...["Não temos", "Não tenho", "Não tivemos", "Não dispomos de", "Não possuímos"].flatMap((verb) =>
      ["acesso ao exame anterior", "registro da avaliação anterior", "uma cópia do laudo anterior",
        "informações do estudo prévio", "dados do exame anterior"].map((resource) => `${verb} ${resource}`)),
    ...["Não há", "Não houve", "Não havia", "Não existe", "Não consta"].flatMap((verb) =>
      ["registro do exame anterior", "uma cópia do estudo prévio", "informações da avaliação anterior",
        "possibilidade de acesso ao exame anterior"].map((resource) => `${verb} ${resource}`)),
    ...["registro do exame anterior", "cópia do laudo anterior", "informações da avaliação anterior",
      "possibilidade de consultar o estudo prévio"].map((resource) => `Sem ${resource}`),
    ...["Não foi possível", "Não é possível", "Não conseguimos", "Não pude", "Não pudemos"].flatMap((modal) =>
      ["obter", "acessar", "consultar"].map((action) => `${modal} ${action} o exame anterior`)),
    "Exame anterior indisponível", "Estudo prévio não está disponível",
    "Laudo anterior: não foi apresentado", "Avaliação anterior não disponível",
  ];

  describe.each(["qualitativa", "conclusao"])("fonte %s", (source) => {
    const review = (text: string, values: Record<string, string>) => {
      const measurements = Object.freeze({ ...values });
      const qualitative = Object.freeze(source === "qualitativa" ? { funcao: text } : {});
      const conclusion = source === "conclusao" ? text : "";
      const before = JSON.stringify({ measurements, qualitative, conclusion });
      const results = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
      expect(JSON.stringify({ measurements, qualitative, conclusion })).toBe(before);
      for (const issue of results) {
        expect(text).toContain(issue.excerpt);
        expect(issue.section).toBe(source === "qualitativa" ? "Função" : "Conclusão");
      }
      return results.map((issue) => issue.key);
    };

    it.each(channels)("compõe posse, recurso, regência e aquisição no canal $label", ({ measurements, claim, keys }) => {
      const results = unavailable.map((phrase) => ({ phrase, keys: review(`${phrase}; ${claim}`, measurements) }));
      expect(results).toEqual(unavailable.map((phrase) => ({ phrase, keys })));
    });

    it.each(channels)("preserva referência real ao passado e qualificações no canal $label", ({ measurements, claim, keys }) => {
      for (const history of [
        "Não houve arritmia no exame anterior", "Sem obstrução no exame anterior",
        "Sem acesso venoso no exame anterior", "Não foi possível excluir arritmia no exame anterior",
        "Não temos acesso venoso no exame anterior", "Não há registro de arritmia no exame anterior",
        "No exame anterior", "Exame anterior disponível", "Exame anterior não está indisponível",
      ]) expect(review(`${history}; ${claim}`, measurements)).toEqual([]);
      expect(review(`Histórico:\n${claim}`, measurements)).toEqual([]);
      expect(review(`No exame anterior, ${claim} Neste estudo, ${claim}`, measurements)).toEqual(keys);
      expect(review(`${claim.slice(0, -1)} não foi confirmado.`, measurements)).toEqual([]);
    });
  });
});


describe.each([
  { species: "Canina", prefix: "canine" }, { species: "Felina", prefix: "feline" },
])("predicado completo depois do exame anterior — $species", ({ species, prefix }) => {
  const channels: { label: string; measurements: Record<string, string>; claim: string; keys: string[] }[] = [
    { label: "numérico", measurements: { AE_Ao: "1.40" }, claim: "AE/Ao de 1,80.", keys: ["AE_Ao"] },
    { label: "transmitral", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "separadas" },
      claim: "Relação E/A de 1,14.", keys: [`${prefix}_transmitral_fusion`] },
    { label: "tecidual", measurements: { Diastolica_ondas: "separadas", TDI_ondas: "fundidas" },
      claim: "e′ lateral de 0,16 m/s.", keys: [`${prefix}_tissue_fusion`] },
    { label: "E/e′ ambas", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" },
      claim: "Relação E/e′ de 6,75.", keys: [`${prefix}_transmitral_fusion`, `${prefix}_tissue_fusion`] },
  ];
  const measureStatements = ["Exame anterior", "Avaliação anterior"].flatMap((exam) => [
    ["obtida", "fração de ejeção"], ["apresentada", "função diastólica"], ["realizada", "medida do átrio esquerdo"],
  ].flatMap(([participle, object]) => ["a ", ""].flatMap((article) => ["", "para comparação ", "até o momento "]
    .map((modifier) => `${exam}: não foi ${participle} ${modifier}${article}${object}.`))));
  const completeStatements = [
    { exam: "Exame anterior", predicate: "não foi obtido" },
    { exam: "Avaliação anterior", predicate: "não foi obtida" },
  ].flatMap(({ exam, predicate }) => ["", " para comparação", " até o momento", " para comparação até o momento",
    " para consulta", " para revisão", " no momento", " atualmente", " até o momento para comparação"]
    .flatMap((modifier) => ["; ", ". ", "\n", ", "].map((boundary) => `${exam}: ${predicate}${modifier}${boundary}`)));

  describe.each(["qualitativa", "conclusao"])("fonte %s", (source) => {
    const review = (text: string, values: Record<string, string>) => {
      const measurements = Object.freeze({ ...values });
      const qualitative = Object.freeze(source === "qualitativa" ? { funcao: text } : {});
      const conclusion = source === "conclusao" ? text : "";
      const before = JSON.stringify({ measurements, qualitative, conclusion });
      const results = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
      expect(JSON.stringify({ measurements, qualitative, conclusion })).toBe(before);
      for (const issue of results) {
        expect(text).toContain(issue.excerpt);
        expect(issue.section).toBe(source === "qualitativa" ? "Função" : "Conclusão");
      }
      return results.map((issue) => issue.key);
    };

    it.each(channels)("não transforma objeto clínico negado em ausência do exame no canal $label", ({ measurements, claim }) => {
      const actual = measureStatements.map((statement) => ({ statement, keys: review(`${statement} ${claim}`, measurements) }));
      expect(actual).toEqual(measureStatements.map((statement) => ({ statement, keys: [] })));
    });

    it.each(channels)("aceita indisponibilidade completa com finalidade/tempo e fronteira no canal $label", ({ measurements, claim, keys }) => {
      const actual = completeStatements.map((statement) => ({ statement, keys: review(statement + claim, measurements) }));
      expect(actual).toEqual(completeStatements.map((statement) => ({ statement, keys })));
    });
  });
});


describe.each(["Canina", "Felina"])("hipótese explícita antes da indisponibilidade — %s", (species) => {
  const unavailable = ["não foi possível obter o exame anterior", "não tivemos acesso ao exame anterior"];
  const hypotheses = ["Se", "Quando", "Hipótese:", "Suspeita:", "Possivelmente", "É possível que"];

  describe.each(["qualitativa", "conclusao"])("fonte %s", (source) => {
    const review = (text: string, values: Record<string, string> = { AE_Ao: "1.40" }) => {
      const measurements = Object.freeze({ ...values });
      const qualitative = Object.freeze(source === "qualitativa" ? { funcao: text } : {});
      const conclusion = source === "conclusao" ? text : "";
      const before = JSON.stringify({ measurements, qualitative, conclusion });
      const results = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
      expect(JSON.stringify({ measurements, qualitative, conclusion })).toBe(before);
      return results;
    };

    it.each(hypotheses.flatMap((hypothesis) => unavailable.map((absence) => ({ hypothesis, absence }))))
    ("preserva $hypothesis sem interpretar $absence como hipótese atual", ({ hypothesis, absence }) => {
      expect(review(`${hypothesis} ${absence}, AE/Ao de 1,80.`)).toEqual([]);
    });

    it("mantém ausência afirmativa, retorno atual, ondas e fontes independentes", () => {
      for (const absence of unavailable) {
        const actual = `${absence}, AE/Ao de 1,80.`;
        const results = review(actual);
        expect(results.map((issue) => issue.key)).toEqual(["AE_Ao"]);
        expect(actual).toContain(results[0].excerpt);
        expect(review(`Se ${absence}, neste exame AE/Ao de 1,80.`)
          .map((issue) => issue.key)).toEqual(["AE_Ao"]);
        expect(review(`Se ${absence}, relação E/A de 1,14.`, { Diastolica_ondas: "fundidas" })).toEqual([]);
      }
      expect(review("Caso não tenhamos acesso ao exame anterior, AE/Ao de 1,80.")).toEqual([]);
      expect(review("Poderia faltar o exame anterior, AE/Ao de 1,80.")).toEqual([]);
      expect(findEchoNarrativeDiscrepancies(Object.freeze({ AE_Ao: "1.40" }),
        Object.freeze({ funcao: "Se não foi possível obter o exame anterior, AE/Ao de 1,80." }),
        "AE/Ao de 1,80.", species).map((issue) => issue.section)).toEqual(["Conclusão"]);
    });
  });
});


describe.each([
  { species: "Canina", prefix: "canine" }, { species: "Felina", prefix: "feline" },
])("hipótese compartilhada nos quatro canais — $species", ({ species, prefix }) => {
  const channels: { label: string; measurements: Record<string, string>; claim: string; keys: string[] }[] = [
    { label: "numérico", measurements: { AE_Ao: "1.40" }, claim: "AE/Ao de 1,80.", keys: ["AE_Ao"] },
    { label: "transmitral", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "separadas" },
      claim: "Relação E/A de 1,14.", keys: [`${prefix}_transmitral_fusion`] },
    { label: "tecidual", measurements: { Diastolica_ondas: "separadas", TDI_ondas: "fundidas" },
      claim: "Relação e′/a′ de 1,33.", keys: [`${prefix}_tissue_fusion`] },
    { label: "E/e′ ambas", measurements: { Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" },
      claim: "Relação E/e′ de 6,75.", keys: [`${prefix}_transmitral_fusion`, `${prefix}_tissue_fusion`] },
  ];
  const hypotheses = ["Se", "Quando", "Hipótese:", "Suspeita:", "Possivelmente", "É possível que"];
  const unavailable = ["não foi possível obter o exame anterior", "não tivemos acesso ao exame anterior"];

  describe.each(["qualitativa", "conclusao"])("fonte %s", (source) => {
    const review = (text: string, values: Record<string, string>) => {
      const measurements = Object.freeze({ ...values });
      const qualitative = Object.freeze(source === "qualitativa" ? { funcao: text } : {});
      const conclusion = source === "conclusao" ? text : "";
      const before = JSON.stringify({ measurements, qualitative, conclusion });
      const results = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
      expect(JSON.stringify({ measurements, qualitative, conclusion })).toBe(before);
      for (const issue of results) expect(text).toContain(issue.excerpt);
      return results;
    };

    it.each(channels)("respeita marcadores externos à disponibilidade no canal $label", ({ measurements, claim }) => {
      const texts = hypotheses.flatMap((hypothesis) => unavailable.map((absence) => `${hypothesis} ${absence}, ${claim}`));
      expect(texts.map((text) => ({ text, keys: review(text, measurements).map((issue) => issue.key) })))
        .toEqual(texts.map((text) => ({ text, keys: [] })));
    });

    it.each(channels)("preserva ausência factual, retorno atual e fontes independentes no canal $label", ({ measurements, claim, keys }) => {
      for (const absence of unavailable) {
        expect(review(`${absence}, ${claim}`, measurements).map((issue) => issue.key)).toEqual(keys);
        expect(review(`É possível que ${absence}, neste exame ${claim}`, measurements)
          .map((issue) => issue.key)).toEqual(keys);
      }
      expect(findEchoNarrativeDiscrepancies(Object.freeze({ ...measurements }),
        Object.freeze({ funcao: `É possível que não foi possível obter o exame anterior, ${claim}` }), claim, species)
        .map((issue) => issue.section)).toEqual(keys.map(() => "Conclusão"));
    });
  });
});
