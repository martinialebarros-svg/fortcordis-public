import { describe, expect, it } from "vitest";
import { deriveAutomaticEchoMeasurements, parseStoredEchoMeasurements } from "./echo-derived-measurements";
import { buildEchoReportGroups, prepareEchoReportMeasurements } from "./echo-report-presentation";
import { deriveOutflowGradients, ECHO_OUTFLOW_SITES } from "./echo-outflow";

describe("locais de aquisição dos fluxos de saída", () => {
  it.each(ECHO_OUTFLOW_SITES)("preserva gradiente importado e precisão em $label ao salvar, reabrir e visualizar", ({ velocity, gradient }) => {
    const imported = {
      [velocity]: "1.01", [gradient]: "4.1107",
      [`${velocity}_origem`]: "importado", [`${velocity}_rotulo_origem`]: `${velocity} fonte`,
      [`${gradient}_origem`]: "importado", [`${gradient}_rotulo_origem`]: `${gradient} fonte`,
    };
    const saved = { ...imported, ...deriveAutomaticEchoMeasurements(imported, 4, "Felina") };
    const description = "## Medidas Ecocardiograficas\n" + Object.entries(saved)
      .map(([key, value]) => `- ${key}: ${value}`).join("\n") + "\n## Avaliacao Qualitativa";
    const reopened = parseStoredEchoMeasurements(null, description);
    const preview = prepareEchoReportMeasurements(reopened, 4, "Felina");
    expect(reopened).toMatchObject(imported);
    expect(preview.measurements[gradient]).toBe("4.1107");
    const rows = buildEchoReportGroups(preview.measurements, null).flatMap((group) => group.rows);
    expect(rows.map((row) => row.key)).toEqual(expect.arrayContaining([velocity, gradient]));
    expect(rows.find((row) => row.key === gradient)?.label).not.toContain("calculado");
    expect(rows.find((row) => row.key === gradient)?.value).toBe("4.1107 mmHg");
    expect(rows.filter((row) => row.key.startsWith("Vmax_")).map((row) => row.key)).toEqual([velocity]);
  });

  it.each(ECHO_OUTFLOW_SITES)("identifica fallback calculado, sem criar outro local: $label", ({ velocity, gradient }) => {
    const raw = { [velocity]: "1.01" };
    const measurements = { ...raw, ...deriveOutflowGradients(raw) };
    expect(measurements[gradient]).toBe("4.08");
    expect(measurements[`${gradient}_origem`]).toBe("calculado");
    const rows = buildEchoReportGroups(measurements, null).flatMap((group) => group.rows);
    expect(rows).toHaveLength(2);
    expect(rows.find((row) => row.key === gradient)?.label).toContain("calculado (4 × V²)");
    expect(raw).toEqual({ [velocity]: "1.01" });
  });

  it("mantém simultaneamente os quatro locais e os valores legados sem reatribuição", () => {
    const raw = { Vmax_VSVE: "1.01", Grad_VSVE: "4.11", Vmax_aorta: "1.2", Grad_aorta: "5.77",
      Vmax_VSVD: "0.80", Grad_VSVD: "2.57", Vmax_pulmonar: "0.9", Grad_pulmonar: "3.25" };
    const { measurements } = prepareEchoReportMeasurements(raw, 10, "Canina");
    expect(measurements).toEqual(raw);
    const rows = buildEchoReportGroups(measurements, null).flatMap((group) => group.rows);
    expect(rows).toHaveLength(8);
    expect(rows.every((row) => row.label.includes("origem não confirmada"))).toBe(true);
    const legacy = parseStoredEchoMeasurements({ Vmax_pulmonar: "0.80", Grad_pulmonar: "2.57" });
    expect(legacy).toEqual({ Vmax_pulmonar: "0.80", Grad_pulmonar: "2.57" });
    expect(deriveOutflowGradients(legacy)).toEqual({});
    expect(legacy).not.toHaveProperty("Vmax_VSVD");
  });

  it("recalcula apenas gradientes que já pertencem ao cálculo e limpa derivados sem velocidade", () => {
    expect(deriveOutflowGradients({ Vmax_VSVE: "2", Grad_VSVE: "4.08", Grad_VSVE_origem: "calculado" }))
      .toMatchObject({ Grad_VSVE: "16", Grad_VSVE_origem: "calculado" });
    expect(deriveOutflowGradients({ Vmax_VSVE: "", Grad_VSVE: "4.08", Grad_VSVE_origem: "calculado" }))
      .toMatchObject({ Grad_VSVE: "", Grad_VSVE_origem: "" });
    for (const value of ["4.1107", "0", "a confirmar", "-1"]) {
      expect(deriveOutflowGradients({ Vmax_VSVE: "2", Grad_VSVE: value })).toEqual({});
    }
    expect(deriveOutflowGradients({ Vmax_VSVE: "1.01foo" })).toEqual({});
    expect(deriveOutflowGradients({ Vmax_VSVE: "1e308" })).toEqual({});
    const rows = buildEchoReportGroups({ Vmax_VSVE: "1.01", Grad_VSVE: "a confirmar" }, null)
      .flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "Grad_VSVE")?.value).toBe("a confirmar (valor a confirmar)");
    const reopened = parseStoredEchoMeasurements(null, "## Medidas Ecocardiograficas\n- Vmax_VSVE: 1.01\n- Grad_VSVE: a confirmar\n## Avaliacao Qualitativa");
    expect(reopened.Grad_VSVE).toBe("a confirmar");
    expect(prepareEchoReportMeasurements(reopened, 4, "Felina").measurements.Grad_VSVE).toBe("a confirmar");
  });
});
