import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EchoOutflowMeasurements from "./EchoOutflowMeasurements";
import { useEchoMeasurements } from "../hooks/useEchoMeasurements";
import { deriveAutomaticEchoMeasurements, parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";
import { mapImportedEchoMeasurements } from "@/lib/echo-outflow-editor";
import { ECHO_OUTFLOW_SITES } from "@/lib/echo-outflow";
import { buildEchoReportGroups, prepareEchoReportMeasurements } from "@/lib/echo-report-presentation";

describe("campos Doppler de aquisição", () => {
  it("oferece quatro locais independentes e permite editar gradiente importado com Vmax", () => {
    const onChange = vi.fn();
    render(<EchoOutflowMeasurements measurements={{ Vmax_VSVE: "1.01", Grad_VSVE: "4.11",
      Grad_VSVE_origem: "importado", Grad_VSVE_rotulo_origem: "LVOT Max PG" }} onChange={onChange} />);
    expect(screen.getAllByRole("textbox")).toHaveLength(8);
    for (const site of ECHO_OUTFLOW_SITES) expect(screen.getByRole("group", { name: site.label })).toBeInTheDocument();
    const left = within(screen.getByRole("group", { name: "Via de saída do VE (VSVE/LVOT)" }));
    const gradient = left.getByLabelText("Gradiente (mmHg)");
    expect(gradient).not.toHaveAttribute("readonly");
    expect(gradient).toHaveValue("4.11");
    expect(left.getByText(/Rótulo de origem: LVOT Max PG/)).toBeInTheDocument();
    fireEvent.change(gradient, { target: { value: "4.12" } });
    expect(onChange).toHaveBeenCalledWith("Grad_VSVE", "4.12");
  });

  it("explicita cálculo e local não confirmado dos dados legados", () => {
    render(<EchoOutflowMeasurements measurements={{ Vmax_VSVE: "1.01", Grad_VSVE: "4.08", Grad_VSVE_origem: "calculado",
      Vmax_pulmonar: "0.80", Grad_pulmonar: "2.57" }} onChange={vi.fn()} />);
    expect(screen.getByText("Calculado: 4 × V².")).toBeInTheDocument();
    expect(screen.getByText(/Registro legado com local de aquisição não confirmado/)).toBeInTheDocument();
    const right = within(screen.getByRole("group", { name: "Via de saída do VD (VSVD/RVOT)" }));
    expect(right.getByLabelText("Vmax (m/s)")).toHaveValue("");
    expect(right.getByLabelText("Gradiente (mmHg)")).toHaveValue("");
  });

  it.each(["Canina", "Felina"])("importa, salva, reabre e prepara prévia de cada local em %s", (species) => {
    const imported = mapImportedEchoMeasurements(Object.fromEntries(ECHO_OUTFLOW_SITES.flatMap((site, index) => [
      [site.velocity, String([1.01, 1.2, 0.8, 0.9][index])],
      [site.gradient, String([4.11, 5.79, 2.57, 3.25][index])],
      [`${site.velocity}_origem`, "importado"], [`${site.gradient}_origem`, "importado"],
      [`${site.velocity}_rotulo_origem`, `${site.label} Vmax`], [`${site.gradient}_rotulo_origem`, `${site.label} PG`],
    ])));
    const { result } = renderHook(() => useEchoMeasurements());
    act(() => result.current.importMeasurements(imported));
    const payload = { ...result.current.measurements, ...deriveAutomaticEchoMeasurements(result.current.measurements, "10", species) };
    const stored = JSON.parse(JSON.stringify(payload));
    act(() => result.current.replaceMeasurements(parseStoredEchoMeasurements(stored)));
    expect(result.current.measurements).toEqual(imported);
    const preview = prepareEchoReportMeasurements(result.current.measurements, "10", species);
    const rows = buildEchoReportGroups(preview.measurements, null, preview.ambiguousKeys, 10, species).flatMap((group) => group.rows);
    expect(rows).toHaveLength(8);
    expect(rows.find((row) => row.key === "Grad_VSVE")?.value).toBe("4.11 mmHg");
    expect(rows.find((row) => row.key === "Grad_VSVD")?.value).toBe("2.57 mmHg");
    for (const site of ECHO_OUTFLOW_SITES) {
      expect(rows.filter((row) => row.key === site.velocity)).toHaveLength(1);
      expect(rows.filter((row) => row.key === site.gradient)).toHaveLength(1);
    }
    render(<EchoOutflowMeasurements measurements={result.current.measurements} onChange={vi.fn()} />);
    expect(screen.queryByText(/Registro legado/)).not.toBeInTheDocument();
  });

  it("não herda a identificação do aparelho anterior ao reimportar um valor sem fonte", () => {
    const { result } = renderHook(() => useEchoMeasurements());
    act(() => result.current.importMeasurements({ Vmax_VSVD: "0.8", Vmax_VSVD_origem: "importado", Vmax_VSVD_rotulo_origem: "RVOT Vmax" }));
    act(() => result.current.importMeasurements({ Vmax_VSVD: "0.81" }));
    expect(result.current.measurements).toEqual({ Vmax_VSVD: "0.81" });
  });
});
