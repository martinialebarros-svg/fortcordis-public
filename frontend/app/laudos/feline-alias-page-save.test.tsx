import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import type { PropsWithChildren } from "react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NovoLaudoPage from "./novo/page";
import EditarLaudoPage from "./[id]/editar/page";
import { montarDescricaoEcocardiograma } from "@/lib/ecocardiograma-estruturado";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(),
  router: { push: vi.fn(), replace: vi.fn() },
  imported: {} as Record<string, string>,
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "904" }), useRouter: () => mocks.router }));
vi.mock("@/app/layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, post: mocks.post, put: mocks.put } }));
vi.mock("@/lib/clinicas", () => ({ listarTodasClinicas: vi.fn(async () => []) }));
vi.mock("@/app/laudos/components/EchoVoiceAssistant", () => ({
  default: ({ currentMeasurements }: { currentMeasurements: Record<string, string> }) =>
    <output data-testid="live-page-measurements">{JSON.stringify(currentMeasurements)}</output>,
}));
vi.mock("@/app/laudos/components/EcoStudyImportUploader", () => ({
  default: ({ onDadosImportados }: { onDadosImportados: (data: unknown) => void }) =>
    <button onClick={() => onDadosImportados({ paciente: {}, medidas: mocks.imported })}>Importar estudo sintético</button>,
}));
vi.mock("@/app/laudos/components/ReferenciaComparison", () => ({
  ReferenciaComparison: ({ especie, onMedidaChange }: { especie: string; onMedidaChange: (key: string, value: string) => void }) =>
    <div>
      <output data-testid="live-page-species">{especie}</output>
      <label>Ondas transmitrais QA<select onChange={(event) => onMedidaChange("Diastolica_ondas", event.target.value)} defaultValue="">
        <option value="">Não confirmadas</option><option value="fundidas">Fundidas</option><option value="separadas">Separadas</option>
      </select></label>
      <label>Ondas teciduais QA<select onChange={(event) => onMedidaChange("TDI_ondas", event.target.value)} defaultValue="">
        <option value="">Não confirmadas</option><option value="fundidas">Fundidas</option><option value="separadas">Separadas</option>
      </select></label>
    </div>,
}));
// Peripheral upload/clinical widgets are excluded; both actual page components,
// the measurement hook, effects, calculations and save serializers stay real.
vi.mock("@/app/laudos/components/XmlUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageHeaderUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImagePreviewModal", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoEditor", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoBiblioteca", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoUnitReview", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoNarrativeConsistencyNotice", () => ({ default: () => null }));

type Scenario = "fundidas" | "desconhecidas" | "separadas";
type Mode = "novo" | "editar";
const HISTORIC = { E_A: "1.13", E_TRIV: "2.66", E_E_linha: "6.95", doppler_tecidual_relacao: "2.60" };
const COMPUTED = { E_A: "1.14", E_TRIV: "2.7", E_E_linha: "6.75", doppler_tecidual_relacao: "2.67" };
const ORIGINS = { Onda_E: "1.08", Onda_A: "0.95", TRIV: "40", e_doppler: "0.16", a_doppler: "0.06" };
const EMPTY_QUALITATIVE = { valvas: "", camaras: "", funcao: "", pericardio: "", vasos: "", ad_vd: "" };
const capturedCases: Array<Record<string, unknown>> = [];
const cases = ["Gato", "Cat", "Felino", "Feline"].flatMap((species) =>
  (["fundidas", "desconhecidas", "separadas"] as Scenario[]).flatMap((scenario) =>
    (["novo", "editar"] as Mode[]).map((mode) => ({ species, scenario, mode }))));

function liveMeasurements(): Record<string, string> {
  return JSON.parse(screen.getByTestId("live-page-measurements").textContent || "{}");
}
function selectedRatios(values: Record<string, string>) {
  return Object.fromEntries(Object.keys(HISTORIC).map((key) => [key, values[key]]));
}

describe("páginas reais: aliases felinos, efeitos e payload de salvamento", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.imported = { ...ORIGINS, ...HISTORIC };
    localStorage.setItem("token", "synthetic-local-test-token");
    localStorage.setItem("user", JSON.stringify({ id: 7 }));
    sessionStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "alert").mockImplementation(() => {});
    mocks.post.mockResolvedValue({ data: { id: 904 } });
    mocks.put.mockImplementation(async (url, body) => ({ data: url.startsWith("/laudos/editor-drafts/")
      ? { draft_id: url.split("/").at(-1), revision: body.expected_revision + 1, context_key: body.context_key, snapshot: body.snapshot, updated_at: "2026-11-01T12:00:00Z" }
      : url.endsWith("/editor-update") ? { id: 904, request_id: body.request_id, updated: true } : { id: 904 } }));
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
  });
  afterAll(() => {
    const directory = process.env.FELINE_ALIAS_CAPTURE_DIR;
    if (!directory) return;
    mkdirSync(directory, { recursive: true });
    const run = process.env.FELINE_ALIAS_CAPTURE_RUN || "fixed";
    writeFileSync(resolve(directory, `${run}-page-save.json`), JSON.stringify({
      fixture: "Synthetic local-only patients and historic ratios; no network or real credentials.",
      source_revision: process.env.FELINE_ALIAS_SOURCE_REVISION || null,
      cases: capturedCases,
    }, null, 2) + "\n");
  });

  it.each(cases)("$mode · $species · $scenario mantém a política ao montar e salvar", async ({ species, scenario, mode }) => {
    const patient = { id: 901, nome: "QA FELINE ALIAS", tutor: "QA TUTOR", tutor_id: 902,
      especie: species, raca: "SRD", sexo: "Macho", peso_kg: 5.6, idade: "4 anos" };
    const metadata: Record<string, string> = scenario === "desconhecidas" ? {} : { Diastolica_ondas: scenario, TDI_ondas: scenario };
    const stored = { ...ORIGINS, ...HISTORIC, ...metadata };
    mocks.get.mockImplementation(async (url: string) => {
      if (url.startsWith("/laudos/editor-drafts/")) throw { response: { status: 404 } };
      if (url === "/pacientes/901") return { data: patient };
      if (url === "/laudos/904") return { data: { editor_revision: "echo-v1:" + "a".repeat(64), id: 904, tipo: "ecocardiograma", paciente_id: 901,
        paciente: patient, titulo: "QA HISTORICO ALIAS", diagnostico: "QA conclusão preservada", observacoes: "QA observação",
        data_exame: "2026-10-14", status: "Rascunho", medidas: stored,
        descricao: montarDescricaoEcocardiograma(stored, EMPTY_QUALITATIVE), imagens: [] } };
      if (url === "/portal/parceiros/veterinarios/opcoes") return { data: { items: [] } };
      throw new Error(`Unexpected mocked GET: ${url}`);
    });

    if (mode === "editar") {
      window.history.replaceState(null, "", "/laudos/904/editar");
      render(<EditarLaudoPage />);
      await screen.findByDisplayValue(patient.nome);
      expect(screen.getByDisplayValue(`${species} (felina)`)).toHaveValue(species);
      await waitFor(() => expect(liveMeasurements().Onda_E).toBe("1.08"));
    } else {
      window.history.replaceState(null, "", "/laudos/novo?paciente_id=901");
      render(<NovoLaudoPage />);
      await screen.findByDisplayValue(patient.nome);
      expect(screen.getByDisplayValue(`${species} (felina)`)).toHaveValue(species);
      fireEvent.click(screen.getByRole("button", { name: "Importar estudo sintético" }));
      await waitFor(() => expect(liveMeasurements().Onda_E).toBe("1.08"));
      if (scenario !== "desconhecidas") {
        fireEvent.click(screen.getByRole("button", { name: "Referências" }));
        fireEvent.change(screen.getByLabelText("Ondas transmitrais QA"), { target: { value: scenario } });
        fireEvent.change(screen.getByLabelText("Ondas teciduais QA"), { target: { value: scenario } });
      }
    }

    // Read the visible probe after actual effects, before clicking Save; do not
    // assert first, so a baseline failure still yields the corrupted payload.
    const observedBeforeSave = selectedRatios(liveMeasurements());
    fireEvent.click(screen.getByRole("button", { name: mode === "novo" ? "Emitir laudo" : "Atualizar laudo" }));
    const transport = mode === "novo" ? mocks.post : mocks.put;
    const target = mode === "novo" ? "/laudos" : "/laudos/904/editor-update";
    await waitFor(() => expect(transport.mock.calls.some(([url]) => url === target)).toBe(true));
    const envelope = JSON.parse(JSON.stringify(transport.mock.calls.find(([url]) => url === target)![1]));
    const payload = mode === "editar" ? envelope.payload_laudo : envelope;
    const patientPayload = mode === "editar"
      ? mocks.put.mock.calls.filter(([url]) => url.startsWith("/laudos/editor-drafts/")).at(-1)![1].snapshot.paciente : payload.paciente;
    const description = mode === "editar" ? payload.descricao : montarDescricaoEcocardiograma(payload.medidas, EMPTY_QUALITATIVE);
    const parsed = parseStoredEchoMeasurements(null, description);
    const expected = scenario === "separadas" ? COMPUTED : HISTORIC;
    capturedCases.push({ species, scenario, mode, payload, paciente_payload: patientPayload,
      captured_description: description, initial_description: montarDescricaoEcocardiograma(stored, EMPTY_QUALITATIVE),
      expected_historic: HISTORIC, expected, observed_before_save: observedBeforeSave,
      saved_ratios: selectedRatios(parsed) });

    expect(observedBeforeSave).toEqual(expected);
    expect(selectedRatios(parsed)).toEqual(expected);
    expect(patientPayload.especie).toBe(species);
    if (mode === "editar") expect(payload.diagnostico).toBe("QA conclusão preservada");
  });
});
