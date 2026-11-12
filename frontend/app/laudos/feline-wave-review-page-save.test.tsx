import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NovoLaudoPage from "./novo/page";
import EditarLaudoPage from "./[id]/editar/page";
import { montarDescricaoEcocardiograma } from "@/lib/ecocardiograma-estruturado";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), router: { push: vi.fn(), replace: vi.fn() },
  imported: {} as Record<string, string>,
  legacySeed: {} as Record<string, string>,
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "905" }), useRouter: () => mocks.router }));
vi.mock("@/app/layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, post: mocks.post, put: mocks.put } }));
vi.mock("@/lib/clinicas", () => ({ listarTodasClinicas: vi.fn(async () => []) }));
vi.mock("@/app/laudos/components/EchoVoiceAssistant", () => ({ default: ({ currentMeasurements, onApply }: {
  currentMeasurements: Record<string, string>;
  onApply: (patch: { fields: Record<string, string>; measurements: Record<string, string>; skipped: string[] }) => void;
}) => <><output data-testid="wave-page-measurements">{JSON.stringify(currentMeasurements)}</output>
  <button onClick={() => onApply({ fields: {}, measurements: mocks.legacySeed, skipped: [] })}>Carregar legado sintético para salvar</button></> }));
vi.mock("@/app/laudos/components/EcoStudyImportUploader", () => ({ default: ({ onDadosImportados }: { onDadosImportados: (data: unknown) => void }) =>
  <button onClick={() => onDadosImportados({ paciente: {}, medidas: mocks.imported })}>Importar estudo sintético de ondas</button> }));
vi.mock("@/app/laudos/components/ReferenciaComparison", () => ({ ReferenciaComparison: ({ onMedidaChange }: { onMedidaChange: (key: string, value: string) => void }) =>
  <><button onClick={() => onMedidaChange("Diastolica_metodo", "felino_adulto_nao_sedado_pw_apical_clique_aortico")}>Confirmar protocolo PW sintético</button>
    <button onClick={() => onMedidaChange("TDI_metodo", "felino_pw_anel_lateral")}>Confirmar sítio TDI sintético</button>
    <button onClick={() => onMedidaChange("Diastolica_ondas", "nao_confirmadas")}>Exigir reconfirmação transmitral sintética</button></> }));
vi.mock("@/app/laudos/components/XmlUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageHeaderUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImagePreviewModal", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoEditor", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoBiblioteca", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoUnitReview", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoNarrativeConsistencyNotice", () => ({ default: () => null }));

type Mode = "novo" | "editar";
type Group = "transmitral" | "tissue";
const ORIGINS = { Onda_E: "1.08", Onda_A: "0.95", TD: "51", TRIV: "40", e_doppler: "0.16", a_doppler: "0.06", Vmax_pulmonar: "0.83" };
const HISTORIC = { E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.95", doppler_tecidual_relacao: "2.60" };
const METHODS = { Diastolica_metodo: "felino_adulto_nao_sedado_pw_apical_clique_aortico", TDI_metodo: "felino_pw_anel_lateral" };
const QUALITATIVE = { valvas: "", camaras: "", funcao: "QA função preservada", pericardio: "", vasos: "", ad_vd: "" };
const LABELS = { E_A: "E/A (relação adimensional)", E_TRIV: "E/TRIV (índice E [cm/s] / TRIV [ms])", E_E_linha: "E/E' (adimensional)", doppler_tecidual_relacao: "Doppler tecidual (relação e'/a', adimensional)" };
let patient: Record<string, unknown>;
let stored: Record<string, string>;
let description: string;

const live = (): Record<string, string> => JSON.parse(screen.getByTestId("wave-page-measurements").textContent || "{}");
function input(label: string) {
  const element = screen.getByText(label, { selector: "label" }).parentElement?.querySelector("input");
  expect(element).not.toBeNull();
  return element as HTMLInputElement;
}
async function openPage(mode: Mode, flow: string, tissue: string, species = "Gato", overrides: Record<string, string> = {}) {
  patient = { id: 901, nome: "QA DESCARTE DE ONDAS", especie: species, tutor: "QA TUTOR", tutor_id: 902, peso_kg: 5.6, sexo: "Macho", raca: "SRD", idade: "4 anos" };
  stored = { ...ORIGINS, ...HISTORIC, ...METHODS, Diastolica_ondas: flow, TDI_ondas: tissue, ...overrides };
  description = montarDescricaoEcocardiograma(stored, QUALITATIVE);
  mocks.get.mockImplementation(async (url: string) => {
    if (url.startsWith("/laudos/editor-drafts/")) throw { response: { status: 404 } };
    if (url === "/pacientes/901") return { data: patient };
    if (url === "/laudos/905") return { data: { editor_revision: "echo-v1:" + "a".repeat(64), id: 905, tipo: "ecocardiograma", paciente_id: 901, paciente: patient,
      titulo: "QA DESCARTE", diagnostico: "QA conclusão preservada", observacoes: "QA observação",
      data_exame: "2026-10-14", status: "Rascunho", medidas: stored, descricao: description, imagens: [] } };
    if (url === "/portal/parceiros/veterinarios/opcoes") return { data: { items: [] } };
    throw new Error(`Unexpected mocked GET: ${url}`);
  });
  window.history.replaceState(null, "", mode === "novo" ? "/laudos/novo?paciente_id=901" : "/laudos/905/editar");
  const view = render(mode === "novo" ? <NovoLaudoPage /> : <EditarLaudoPage />);
  await screen.findByDisplayValue(String(patient.nome));
  if (mode === "novo") {
    fireEvent.click(screen.getByRole("button", { name: "Importar estudo sintético de ondas" }));
    await waitFor(() => expect(live().Onda_E).toBe("1.08"));
    if (species !== "Canina") {
      fireEvent.click(screen.getByRole("button", { name: "Referências" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirmar protocolo PW sintético" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirmar sítio TDI sintético" }));
    }
  }
  fireEvent.click(screen.getByRole("button", { name: "Medidas" }));
  if (mode === "novo" && species !== "Canina") {
    fireEvent.change(screen.getByLabelText("Ondas transmitrais E/A"), { target: { value: flow } });
    fireEvent.change(screen.getByLabelText("Ondas teciduais e'/a'"), { target: { value: tissue } });
  }
  const expectedFlow = mode === "novo" && species === "Canina" ? "separadas" : flow;
  await waitFor(() => expect(live().Diastolica_ondas || "").toBe(expectedFlow));
  return view;
}
async function savePage(mode: Mode) {
  fireEvent.click(screen.getByRole("button", { name: mode === "novo" ? "Emitir laudo" : "Atualizar laudo" }));
  const transport = mode === "novo" ? mocks.post : mocks.put;
  const target = mode === "novo" ? "/laudos" : "/laudos/905/editor-update";
  await waitFor(() => expect(transport.mock.calls.some(([url]) => url === target)).toBe(true));
  const envelope = transport.mock.calls.find(([url]) => url === target)![1];
    const payload = mode === "editar" ? envelope.payload_laudo : envelope;
  const capturedDescription = mode === "novo" ? montarDescricaoEcocardiograma(payload.medidas, QUALITATIVE) : payload.descricao;
  return { payload, description: capturedDescription, measurements: parseStoredEchoMeasurements(null, capturedDescription) };
}

describe("páginas reais: revisão e descarte explícito de ondas", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem("token", "synthetic-local-test-token");
    localStorage.setItem("user", JSON.stringify({ id: 7 }));
    sessionStorage.clear();
    mocks.imported = { ...ORIGINS, ...HISTORIC };
    mocks.legacySeed = {};
    mocks.post.mockResolvedValue({ data: { id: 905 } });
    mocks.put.mockImplementation(async (url, body) => ({ data: url.startsWith("/laudos/editor-drafts/")
      ? { draft_id: url.split("/").at(-1), revision: body.expected_revision + 1, context_key: body.context_key, snapshot: body.snapshot, updated_at: "2026-11-01T12:00:00Z" }
      : url.endsWith("/editor-update") ? { id: 905, request_id: body.request_id, updated: true } : { id: 905 } }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); window.history.replaceState(null, "", "/"); });

  const legacyClearCases = (["novo", "editar"] as Mode[]).flatMap((mode) =>
    ["Canina", "Felina"].flatMap((species) => ["", null, "0"].map((value) => ({ mode, species, value }))));
  it.each(legacyClearCases)("$mode/$species preserva a canônica '$value' contra alias positivo ao salvar e reabrir", async ({ mode, species, value }) => {
    const patch = { MV_E: "1.80", Onda_E: value } as unknown as Record<string, string>;
    const before = { ...patch };
    const view = await openPage(mode, species === "Canina" ? "" : "fundidas",
      species === "Canina" ? "" : "separadas", species, mode === "editar" ? patch : {});
    if (mode === "novo") {
      mocks.legacySeed = patch;
      fireEvent.click(screen.getByRole("button", { name: "Carregar legado sintético para salvar" }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Referências" }));
    fireEvent.click(screen.getByRole("button", { name: "Exigir reconfirmação transmitral sintética" }));
    await waitFor(() => expect(live().Diastolica_ondas).toBe("nao_confirmadas"));
    const historicalRatios = Object.fromEntries(["E_A", "E_TRIV", "E_E_linha"].map((key) => [key, live()[key]]));
    const saved = await savePage(mode);
    expect(saved.description).toContain(`- Onda_E: ${String(value ?? "")}\n`);
    expect(saved.description).toContain("- MV_E: 1.80\n");
    expect(saved.measurements).toMatchObject({ Onda_E: String(value ?? ""), MV_E: "1.80", Diastolica_ondas: "nao_confirmadas" });
    expect(saved.measurements).toMatchObject(historicalRatios);
    if (mode === "novo") expect(saved.payload.medidas).toMatchObject({ Onda_E: value, MV_E: "1.80" });
    view.unmount();
    stored = saved.measurements;
    description = saved.description;
    render(<EditarLaudoPage />);
    await screen.findByDisplayValue(String(patient.nome));
    await waitFor(() => expect(live()).toMatchObject({ Onda_E: String(value ?? ""), MV_E: "1.80", Diastolica_ondas: "nao_confirmadas" }));
    expect(live()).toMatchObject(historicalRatios);
    expect(patch).toEqual(before);
  });

  const discardCases = ["Gato", "Cat"].flatMap((species) => (["novo", "editar"] as Mode[]).flatMap((mode) =>
    (["transmitral", "tissue"] as Group[]).map((group) => ({ species, mode, group }))));
  it.each(discardCases)("$mode/$species descarta somente $group e mantém a exclusão após salvar e reabrir", async ({ mode, group, species }) => {
    const flow = group === "transmitral" ? "fundidas" : "separadas";
    const tissue = group === "tissue" ? "fundidas" : "separadas";
    const view = await openPage(mode, flow, tissue, species);
    const review = screen.getByRole("region", { name: "Revisão de ondas diastólicas felinas" });
    expect(within(review).getByRole("status")).toHaveTextContent(/não serão apresentados como valores mensuráveis/);
    // Marking fusion itself must retain the historical data for explicit review.
    expect(live().E_E_linha).toBe("6.95");
    fireEvent.click(within(review).getByRole("button", { name: group === "transmitral" ? "Remover medidas de E/A fundidas" : "Remover medidas de TDI fundidas" }));
    const removed = group === "transmitral" ? ["Onda_E", "Onda_A", "TD", "E_A", "E_TRIV", "E_E_linha"] : ["e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"];
    await waitFor(() => removed.forEach((key) => expect(live()[key] || "").toBe("")));
    expect(live()).toMatchObject({ ...METHODS, Diastolica_ondas: flow, TDI_ondas: tissue, TRIV: "40", Vmax_pulmonar: "0.83" });
    if (group === "transmitral") expect(live()).toMatchObject({ e_doppler: "0.16", a_doppler: "0.06", doppler_tecidual_relacao: "2.67" });
    else expect(live()).toMatchObject({ Onda_E: "1.08", Onda_A: "0.95", TD: "51", E_A: "1.14", E_TRIV: "2.7" });
    const saved = await savePage(mode);
    removed.forEach((key) => expect(saved.measurements).not.toHaveProperty(key));
    expect(saved.measurements).toMatchObject({ ...METHODS, Diastolica_ondas: flow, TDI_ondas: tissue, TRIV: "40" });
    if (mode === "editar") expect(saved.payload.diagnostico).toBe("QA conclusão preservada");
    view.unmount();
    stored = saved.measurements;
    description = saved.description;
    render(<EditarLaudoPage />);
    await screen.findByDisplayValue(String(patient.nome));
    await waitFor(() => removed.forEach((key) => expect(live()[key] || "").toBe("")));
    expect(live()).toMatchObject({ TRIV: "40", ...METHODS, Diastolica_ondas: flow, TDI_ondas: tissue });
  });

  it.each(["novo", "editar"] as Mode[])("%s permite corrigir e limpar relações importadas suspensas", async (mode) => {
    await openPage(mode, "fundidas", "fundidas");
    for (const [key, label] of Object.entries(LABELS)) {
      expect(input(label)).not.toHaveAttribute("readonly");
      fireEvent.change(input(label), { target: { value: "9.11" } });
      expect(live()[key]).toBe("9.11");
      fireEvent.change(input(label), { target: { value: "" } });
      expect(live()[key] || "").toBe("");
    }
    const saved = await savePage(mode);
    Object.keys(LABELS).forEach((key) => expect(saved.measurements).toHaveProperty(key, ""));
    expect(saved.measurements).toMatchObject({ Diastolica_ondas: "fundidas", TDI_ondas: "fundidas", TRIV: "40" });
  });

  it.each(["novo", "editar"] as Mode[])("%s protege as quatro relações quando existe cálculo aplicável", async (mode) => {
    await openPage(mode, "separadas", "separadas");
    await waitFor(() => expect(live().E_E_linha).toBe("6.75"));
    for (const label of Object.values(LABELS)) expect(input(label)).toHaveAttribute("readonly");
    expect(live()).toMatchObject({ E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.75", doppler_tecidual_relacao: "2.67" });
  });

  it.each(["novo", "editar"] as Mode[])("%s mantém a política original dos campos caninos mesmo sem numerador", async (mode) => {
    await openPage(mode, "", "", "Canina");
    expect(screen.queryByText(/Ref\.: ≤2,5/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Ref\.: ≤12/)).not.toBeInTheDocument();
    fireEvent.change(input("Onda E (m/s)"), { target: { value: "0" } });
    for (const key of ["E_A", "E_TRIV", "E_E_linha"] as const) expect(input(LABELS[key])).toHaveAttribute("readonly");
    expect(input(LABELS.doppler_tecidual_relacao)).not.toHaveAttribute("readonly");
    expect(screen.queryByRole("region", { name: "Revisão de ondas diastólicas felinas" })).not.toBeInTheDocument();
  });

  const clearCases = (["novo", "editar"] as Mode[]).flatMap((mode) => [
    { mode, label: "Onda E (m/s)", key: "Onda_E", removed: ["E_A", "E_TRIV", "E_E_linha"], kept: { e_doppler: "0.16", doppler_tecidual_relacao: "2.67", TRIV: "40" } },
    { mode, label: "e' (Doppler tecidual, m/s)", key: "e_doppler", removed: ["doppler_tecidual_relacao", "E_E_linha"], kept: { Onda_E: "1.08", E_A: "1.14", E_TRIV: "2.7", TRIV: "40" } },
  ]);
  it.each(clearCases)("$mode limpa dependentes quando zera explicitamente $key", async ({ mode, label, key, removed, kept }) => {
    await openPage(mode, "separadas", "separadas");
    fireEvent.change(input(label), { target: { value: "0" } });
    await waitFor(() => removed.forEach((ratio) => expect(live()[ratio] || "").toBe("")));
    expect(live()).toMatchObject({ [key]: "0", ...kept });
    const saved = await savePage(mode);
    removed.forEach((ratio) => expect(saved.measurements).not.toHaveProperty(ratio));
    expect(saved.measurements).toMatchObject({ [key]: "0", ...kept });
  });
});
