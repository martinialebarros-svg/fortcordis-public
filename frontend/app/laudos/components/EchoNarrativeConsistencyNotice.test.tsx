import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EchoNarrativeConsistencyNotice from "./EchoNarrativeConsistencyNotice";

describe("aviso discreto de conferência clínica", () => {
  it.each(["Canina", "Cão", "Dog", "Canine"])("confere fusão canina em %s sem alterar medidas ou conclusão", (species) => {
    const measurements = Object.freeze({ Diastolica_ondas: "fundidas", TDI_ondas: "separadas", Onda_E: "0.80", Onda_A: "0.60" });
    const sentence = "Ondas E e A separadas e mensuráveis.";
    const qualitative = Object.freeze({ funcao: sentence });
    const onSave = vi.fn();
    render(<form onSubmit={(event) => { event.preventDefault(); onSave(); }}>
      <EchoNarrativeConsistencyNotice species={species} measurements={measurements} qualitative={qualitative}
        conclusion="Conclusão oficial preservada." />
      <button type="submit">Salvar teste canino</button>
    </form>);
    const notice = screen.getByRole("status", { name: "Conferência de coerência do laudo" });
    expect(notice).toHaveTextContent("Ondas E/A registradas como fundidas");
    fireEvent.click(within(notice).getByText(/Ver trecho/));
    expect(notice.querySelector("blockquote")).toHaveTextContent(sentence);
    expect(within(notice).queryByRole("button")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Salvar teste canino" }));
    expect(onSave).toHaveBeenCalledOnce();
    expect(qualitative.funcao).toBe(sentence);
    expect(measurements.Onda_E).toBe("0.80");
  });

  const numericCases: Array<{ label: string; measurements: Record<string, string>; sentence: string }> = [
    { label: "AE/Ao", measurements: { AE_Ao: "1.40" }, sentence: "Relação AE/Ao de 1,80." },
    { label: "DIVEd", measurements: { VE_tecnica_relatorio: "modo_m", DIVEd: "30" }, sentence: "DIVEd de 35 mm no modo M." },
    { label: "DIVEs", measurements: { VE_tecnica_relatorio: "modo_m", DIVES: "20" }, sentence: "DIVEs de 25 mm no modo M." },
    { label: "SIVd", measurements: { VE_tecnica_relatorio: "modo_m", SIVd: "7" }, sentence: "SIVd de 10 mm no modo M." },
    { label: "PLVEd", measurements: { VE_tecnica_relatorio: "modo_m", PLVEd: "7" }, sentence: "PLVEd de 10 mm no modo M." },
    { label: "DIVEd", measurements: { VE_tecnica_relatorio: "2d", DIVEd: "30", DIVEd_2D: "40" }, sentence: "DIVEd 2D de 45 mm." },
    { label: "DIVEs", measurements: { VE_tecnica_relatorio: "2d", DIVES: "20", DIVES_2D: "25" }, sentence: "DIVEs 2D de 30 mm." },
    { label: "DIVEd", measurements: { VE_tecnica_relatorio: "modo_m", DIVEd: "3", unidade_confirmada_DIVEd: "cm" }, sentence: "DIVEd de 35 mm no modo M." },
    { label: "Aorta", measurements: { Aorta: "10" }, sentence: "Aorta de 12 mm." },
    { label: "Átrio esquerdo", measurements: { Atrio_esquerdo: "14" }, sentence: "Átrio esquerdo de 18 mm." },
    { label: "aórtica", measurements: { Vmax_aorta: "0.80" }, sentence: "Velocidade máxima aórtica de 1,20 m/s." },
    { label: "pulmonar", measurements: { Vmax_pulmonar: "0.80" }, sentence: "Velocidade máxima pulmonar de 120 cm/s." },
    { label: "VE", measurements: { Vmax_VSVE: "0.90" }, sentence: "Velocidade máxima da via de saída do VE de 1,50 m/s." },
    { label: "VD", measurements: { Vmax_VSVD: "0.90" }, sentence: "Velocidade máxima da via de saída do VD de 150 cm/s." },
  ];
  it.each(numericCases)("mostra a diferença literal de $label sem substituir seu texto: $sentence", ({ label, measurements, sentence }) => {
    const values = Object.freeze({ ...measurements });
    const qualitative = Object.freeze({ funcao: sentence });
    const onSave = vi.fn();
    render(<form onSubmit={(event) => { event.preventDefault(); onSave(); }}>
      <EchoNarrativeConsistencyNotice species="Canina" measurements={values} qualitative={qualitative} conclusion="Conclusão preservada." />
      <button type="submit">Salvar teste numérico</button>
    </form>);
    const notice = screen.getByRole("status", { name: "Conferência de coerência do laudo" });
    expect(notice).toHaveTextContent(new RegExp(label, "i"));
    expect(notice.querySelector("blockquote")).toHaveTextContent(sentence);
    expect(within(notice).queryByRole("button")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Salvar teste numérico" }));
    expect(onSave).toHaveBeenCalledOnce();
    expect(values).toEqual(measurements);
    expect(qualitative.funcao).toBe(sentence);
  });

  const compatibleCases: Array<{ measurements: Record<string, string>; sentence: string }> = [
    { measurements: { AE_Ao: "1.40" }, sentence: "Relação AE/Ao de 1,40." },
    { measurements: { VE_tecnica_relatorio: "modo_m", DIVEd: "30" }, sentence: "DIVEd de 3,0 cm no modo M." },
    { measurements: { VE_tecnica_relatorio: "modo_m", DIVEd: "3", unidade_confirmada_DIVEd: "cm" }, sentence: "DIVEd de 30 mm no modo M." },
    { measurements: { VE_tecnica_relatorio: "2d", DIVEd: "30", DIVEd_2D: "40" }, sentence: "DIVEd 2D de 4,0 cm." },
    { measurements: { Aorta: "10", Atrio_esquerdo: "14" }, sentence: "Aorta de 1,0 cm e átrio esquerdo de 14 mm." },
    { measurements: { Vmax_aorta: "1.20", Vmax_pulmonar: "0.80" }, sentence: "Velocidade máxima aórtica de 120 cm/s e velocidade máxima pulmonar de 0,80 m/s." },
    { measurements: { Aorta: "10", Vmax_aorta: "1.20" }, sentence: "Velocidade da aorta de 120 cm/s." },
    { measurements: { Vmax_aorta: "0.80", Vmax_VSVE: "1.20", Vmax_pulmonar: "0.90", Vmax_VSVD: "1.50" }, sentence: "Velocidade máxima aórtica de 0,80 m/s. Velocidade máxima da via de saída do VE de 1,20 m/s. Velocidade máxima pulmonar de 90 cm/s. Velocidade máxima da via de saída do VD de 1,50 m/s." },
    { measurements: { VE_tecnica_relatorio: "2d", DIVEd: "30", DIVEd_2D: "40" }, sentence: "DIVEd de 40 mm." },
    { measurements: { VE_tecnica_relatorio: "2d", DIVEd: "30", DIVEd_2D: "40" }, sentence: "DIVEd de 30 mm no modo M." },
    { measurements: { VE_tecnica_relatorio: "modo_m", DIVEd: "30", DIVEd_2D: "35" }, sentence: "Modo 2D:\nDIVEd de 35 mm." },
    { measurements: { VE_tecnica_relatorio: "modo_m", DIVEd: "30", DIVEd_2D: "35" }, sentence: "Em 2D, DIVEd de 35 mm." },
    { measurements: { VE_tecnica_relatorio: "modo_m", LVIDd: "20" }, sentence: "DIVEd de 30 mm." },
    { measurements: { DIVEd: "30", DIVEd_2D: "40" }, sentence: "DIVEd de 35 mm." },
    { measurements: { DIVEd: "3", SIVd: "0.7", PLVEd: "0.7" }, sentence: "DIVEd de 30 mm no modo M." },
    { measurements: { AE_Ao: "1.40" }, sentence: "Referência: AE/Ao de 1,80." },
    { measurements: { AE_Ao: "1.40" }, sentence: "Se a relação AE/Ao fosse de 1,80, consideraríamos os demais achados." },
    { measurements: { AE_Ao: "1.40" }, sentence: "No exame anterior, relação AE/Ao de 1,80." },
    { measurements: { VE_tecnica_relatorio: "modo_m", DIVEd: "30" }, sentence: "A imagem mostra DIVEd de 35 mm; o valor de 30 mm é a média das mensurações." },
    { measurements: { AE_Ao: "1.40" }, sentence: "Átrio esquerdo com dimensões normais e sem sinais de sobrecarga." },
  ];
  it.each(compatibleCases)("não transforma concordância, referência, hipótese ou imagem/média em conflito: $sentence", ({ measurements, sentence }) => {
    const { container } = render(<EchoNarrativeConsistencyNotice species="Canina"
      measurements={measurements} qualitative={{ funcao: sentence }} conclusion="Interpretação integrada preservada." />);
    expect(container).toBeEmptyDOMElement();
  });

  it("mostra diferenças numéricas sem substituir a narrativa", () => {
    render(<EchoNarrativeConsistencyNotice
      measurements={{ VE_tecnica_relatorio: "modo_m", FE_Teicholz: "95", DeltaD_FS: "67" }}
      qualitative={{ funcao: "Fração de ejeção estimada em 97% e fração de encurtamento de 71%." }}
      conclusion=""
    />);
    expect(screen.getByRole("status")).toHaveTextContent("FE: o texto cita 97%");
    expect(screen.getByRole("status")).toHaveTextContent("FEC: o texto cita 71%");
    expect(screen.getByRole("status")).toHaveTextContent("Aviso de conferência");
  });

  it("não ocupa espaço quando a narrativa concorda com a técnica selecionada", () => {
    const { container } = render(<EchoNarrativeConsistencyNotice
      measurements={{ VE_tecnica_relatorio: "2d", FE_Teicholz_2D: "61" }}
      qualitative={{ funcao: "Fração de ejeção de 61%." }}
      conclusion=""
    />);
    expect(container).toBeEmptyDOMElement();
  });

  it("localiza o trecho e oferece sugestão somente para revisão manual", () => {
    const sentence = "Ondas E e A separadas e mensuráveis.";
    render(<EchoNarrativeConsistencyNotice species="Gato"
      measurements={{ Diastolica_ondas: "fundidas" }}
      qualitative={{ funcao: sentence }} conclusion="Conclusão clínica preservada."
    />);
    const notice = screen.getByRole("status", { name: "Conferência de coerência do laudo" });
    expect(notice).toHaveAttribute("data-echo-consistency-review");
    fireEvent.click(within(notice).getByText(/Ver trecho/));
    expect(within(notice).getByText(sentence, { selector: "blockquote" })).toBeInTheDocument();
    expect(within(notice).getByText("Sugestão para sua revisão:")).toBeInTheDocument();
    expect(within(notice).queryByRole("button")).not.toBeInTheDocument();
    expect(notice).toHaveTextContent("A interpretação e o salvamento permanecem sob sua decisão");
  });

  it("atualiza o aviso com a fusão e com a correção da narrativa", () => {
    const props = { species: "Felina", qualitative: { funcao: "Ondas E e A separadas e mensuráveis." }, conclusion: "" };
    const view = render(<EchoNarrativeConsistencyNotice {...props} measurements={{ Diastolica_ondas: "separadas" }} />);
    expect(view.container).toBeEmptyDOMElement();
    view.rerender(<EchoNarrativeConsistencyNotice {...props} measurements={{ Diastolica_ondas: "fundidas" }} />);
    expect(screen.getByRole("status", { name: "Conferência de coerência do laudo" })).toBeInTheDocument();
    view.rerender(<EchoNarrativeConsistencyNotice {...props} measurements={{ Diastolica_ondas: "fundidas" }}
      qualitative={{ funcao: "Ondas E/A fundidas, sem mensuração independente." }} />);
    expect(view.container).toBeEmptyDOMElement();
  });

  it.each([
    "E de 1,08 m/s e onda A de 0,95 m/s.",
    "Não há aumento atrial, e a relação E/A é 1,14.",
    "E/A=1,14, sem interpretação do Doppler tecidual.",
    "E/A=1,14; não interpretável a função sistólica por artefato.",
  ])("P2: mostra o trecho completo sem mudar a narrativa nem impedir o submit: %s", (sentence) => {
    const measurements = Object.freeze({ Diastolica_ondas: "fundidas", TDI_ondas: "separadas", Onda_E: "1.08", Onda_A: "0.95" });
    const qualitative = Object.freeze({ funcao: sentence });
    const conclusion = "Conclusão oficial preservada.";
    const onSave = vi.fn();
    render(<form onSubmit={(event) => { event.preventDefault(); onSave(); }}>
      <textarea aria-label="Narrativa oficial" readOnly value={sentence} />
      <EchoNarrativeConsistencyNotice species="Gato" measurements={measurements}
        qualitative={qualitative} conclusion={conclusion} />
      <button type="submit">Salvar laudo sintético</button>
    </form>);
    const notice = screen.getByRole("status", { name: "Conferência de coerência do laudo" });
    fireEvent.click(within(notice).getByText(/Ver trecho.*Função.*e sugestão/));
    expect(notice.querySelector("blockquote")?.textContent).toBe(sentence);
    expect(within(notice).getByText("Sugestão para sua revisão:")).toBeInTheDocument();
    expect(within(notice).queryByRole("button")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Salvar laudo sintético" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox", { name: "Narrativa oficial" })).toHaveValue(sentence);
    expect(qualitative.funcao).toBe(sentence);
    expect(measurements).toEqual({ Diastolica_ondas: "fundidas", TDI_ondas: "separadas", Onda_E: "1.08", Onda_A: "0.95" });
    expect(conclusion).toBe("Conclusão oficial preservada.");
  });

  it("P2: mantém a frase mista inteira na UI e avisa somente a família afirmada", () => {
    const sentence = "Relação E/A não mensurável por fusão; relação e′/a′ de 1,33.";
    render(<EchoNarrativeConsistencyNotice species="Cat"
      measurements={{ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" }}
      qualitative={{ funcao: sentence }} conclusion="Conclusão oficial preservada." />);
    const notice = screen.getByRole("status", { name: "Conferência de coerência do laudo" });
    expect(within(notice).getAllByRole("listitem")).toHaveLength(1);
    expect(notice).toHaveTextContent("Ondas e′/a′ registradas como fundidas");
    expect(notice).not.toHaveTextContent("Ondas E/A registradas como fundidas");
    fireEvent.click(within(notice).getByText(/Ver trecho/));
    expect(notice.querySelector("blockquote")?.textContent).toBe(sentence);
  });

  it.each([
    "Relação E/A de 1,14 não interpretável por fusão; relação e′/a′ de 1,33 desconsiderada por artefato.",
    "E =0,80 m/s, A =0,60 m/s, descartados por artefato.",
    "E =0,80 m/s, A =0,60 m/s, não interpretáveis por fusão.",
    "When E/A=1.14.",
    "E / A = 1,14 m/s, desconsiderada por artefato.",
    "E/e′=6,75, não interpretável por fusão tecidual.",
    "E/e′=6,75, não interpretável por fusão transmitral.",
    "Relação E/A de 1,14, registrada no exame anterior.",
    "Relação E/A de 1,14, com ondas fundidas.",
    "Relação e′/a′ de 1,33, registrada no exame anterior.",
    "Relação e′/a′ de 1,33, com ondas fundidas.",
    "No exame anterior, relação E/A de 1,14; relação e′/a′ de 1,33.",
    "Com ondas fundidas, relação E/A de1,14.",
    "Com ondas teciduais fundidas, relação e′/a′ de1,33.",
    "Não interpretável a relação E/A, relação E/A de1,14.",
    "Descartado o pico a′, a′ de 0,06 m/s.",
  ])("P2: continua vazio quando a afirmação está explicitamente desconsiderada ou condicionada: %s", (sentence) => {
    const { container } = render(<EchoNarrativeConsistencyNotice species="Felina"
      measurements={{ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" }}
      qualitative={{ funcao: sentence }}
      conclusion="Interpretação integrada preservada." />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each(["atualmente", "neste exame", "no exame atual"])("histórico na UI termina somente no retorno explícito %s", (current) => {
    const sentence = `No exame anterior, relação E/A de 1,14; ${current} relação e′/a′ de 1,33.`;
    render(<EchoNarrativeConsistencyNotice species="Gato"
      measurements={{ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" }}
      qualitative={{ funcao: sentence }} conclusion="Conclusão oficial preservada." />);
    const notice = screen.getByRole("status", { name: "Conferência de coerência do laudo" });
    expect(within(notice).getAllByRole("listitem")).toHaveLength(1);
    expect(notice).toHaveTextContent("Ondas e′/a′ registradas como fundidas");
    expect(notice).not.toHaveTextContent("Ondas E/A registradas como fundidas");
    fireEvent.click(within(notice).getByText(/Ver trecho/));
    expect(notice.querySelector("blockquote")?.textContent).toBe(sentence);
  });

  it.each([
    { sentence: "Com ondas E/A fundidas, relação e′/a′ de1,33.", expected: "Ondas e′/a′ registradas como fundidas", absent: "Ondas E/A registradas como fundidas" },
    { sentence: "Com ondas e′/a′ fundidas, relação E/A de1,14.", expected: "Ondas E/A registradas como fundidas", absent: "Ondas e′/a′ registradas como fundidas" },
  ])("ressalva inicial preserva outra família e o texto oficial ao salvar: $sentence", ({ sentence, expected, absent }) => {
    const measurements = Object.freeze({ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas" });
    const qualitative = Object.freeze({ funcao: sentence });
    const onSave = vi.fn();
    render(<form onSubmit={(event) => { event.preventDefault(); onSave(); }}>
      <textarea aria-label="Narrativa oficial" readOnly value={sentence} />
      <EchoNarrativeConsistencyNotice species="Gato" measurements={measurements}
        qualitative={qualitative} conclusion="Conclusão oficial preservada." />
      <button type="submit">Salvar laudo sintético</button>
    </form>);
    const notice = screen.getByRole("status", { name: "Conferência de coerência do laudo" });
    expect(within(notice).getAllByRole("listitem")).toHaveLength(1);
    expect(notice).toHaveTextContent(expected);
    expect(notice).not.toHaveTextContent(absent);
    fireEvent.click(within(notice).getByText(/Ver trecho/));
    expect(notice.querySelector("blockquote")?.textContent).toBe(sentence);
    fireEvent.click(screen.getByRole("button", { name: "Salvar laudo sintético" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox", { name: "Narrativa oficial" })).toHaveValue(sentence);
    expect(qualitative.funcao).toBe(sentence);
  });
});
