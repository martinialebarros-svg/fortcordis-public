import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NovoLaudoPage from "./novo/page";
import EditarLaudoPage from "./[id]/editar/page";
import {
  criarEcocardiogramaEstruturadoInicial,
  extrairQualitativaEcoDaDescricao,
  montarDescricaoEcocardiograma,
  type EcocardiogramaEstruturadoPersistido,
} from "@/lib/ecocardiograma-estruturado";
import { parseStoredEchoMeasurements } from "@/lib/echo-derived-measurements";
import { EchoDiastolicProtocol } from "./components/EchoDiastolicProtocol";

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(),
  router: { push: vi.fn(), replace: vi.fn() },
  imported: {} as Record<string, string>,
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "905" }), useRouter: () => mocks.router }));
vi.mock("@/app/layout-dashboard", () => ({ default: ({ children }: PropsWithChildren) => <div>{children}</div> }));
vi.mock("@/lib/axios", () => ({ default: { get: mocks.get, post: mocks.post, put: mocks.put } }));
vi.mock("@/lib/clinicas", () => ({ listarTodasClinicas: vi.fn(async () => []) }));
vi.mock("@/app/laudos/components/EchoVoiceAssistant", () => ({ default: ({ currentMeasurements }: { currentMeasurements: Record<string, string> }) =>
  <output data-testid="narrative-page-measurements">{JSON.stringify(currentMeasurements)}</output> }));
vi.mock("@/app/laudos/components/EcoStudyImportUploader", () => ({ default: ({ onDadosImportados }: { onDadosImportados: (data: unknown) => void }) =>
  <button onClick={() => onDadosImportados({ paciente: {}, medidas: mocks.imported })}>Importar estudo sintético</button> }));
vi.mock("@/app/laudos/components/XmlUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageHeaderUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImageUploader", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ImagePreviewModal", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoBiblioteca", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/EchoUnitReview", () => ({ default: () => null }));
vi.mock("@/app/laudos/components/ReferenciaComparison", () => ({ ReferenciaComparison: ({ especie, medidas, onMedidaChange }: {
  especie: string; medidas: Record<string, string>; onMedidaChange: (key: string, value: string) => void;
}) => <EchoDiastolicProtocol especie={especie} medidas={medidas} onMedidaChange={onMedidaChange} /> }));
// Preserve the real page selection/save logic and the real consistency engine/notice.
// The editor substitute only provides a deterministic user edit of its public value.
vi.mock("@/app/laudos/components/EcocardiogramaEstruturadoEditor", () => ({ default: ({ value, onChange }: {
  value: EcocardiogramaEstruturadoPersistido;
  onChange: (next: EcocardiogramaEstruturadoPersistido) => void;
}) => <><textarea aria-label="Texto diastólico sintético" value={value.textos.funcao_diastolica || ""}
  onChange={(event) => onChange({ ...value, usar_no_laudo: true,
    textos: { ...value.textos, funcao_diastolica: event.target.value } })} />
  <button onClick={() => onChange({ ...value, usar_no_laudo: false, textos: { ...value.textos,
    funcao_diastolica: "Função diastólica preservada, com padrão de enchimento adequado ao Doppler transmitral." } })}>
    Preparar rascunho conflitante sem aplicar
  </button>
  <button onClick={() => onChange({ ...value, usar_no_laudo: false, textos: { ...value.textos,
    funcao_diastolica: "Ondas E/A fundidas; a avaliação diastólica considera os demais parâmetros disponíveis." } })}>
    Preparar rascunho compatível sem aplicar
  </button>
  <button onClick={() => onChange({ ...value, usar_no_laudo: true, textos: { ...value.textos,
    funcao_diastolica: "Relação AE/Ao de 1,80." } })}>Aplicar preset numérico sintético</button>
  <button onClick={() => onChange({ ...value, usar_no_laudo: true, textos: { ...value.textos,
    conclusao: "Interpretação clínica integrada preservada para revisão do médico veterinário." } })}>
    Definir conclusão oficial sintética
  </button></> }));

type Mode = "novo" | "editar";
type Section = "Paciente" | "Medidas" | "Qualitativa" | "Referências";
const MODES: Mode[] = ["novo", "editar"];
const CONFLICT = "Função diastólica preservada, com padrão de enchimento adequado ao Doppler transmitral.";
const REVIEWED = "Ondas E/A fundidas; a avaliação diastólica considera os demais parâmetros disponíveis.";
const CONCLUSION = "Interpretação clínica integrada preservada para revisão do médico veterinário.";
const PANEL = "Conferência de coerência do laudo";
const MEASURES = { Onda_E: "1.08", Onda_A: "0.95", E_A: "1.14", TD: "51", TRIV: "40",
  e_doppler: "0.16", a_doppler: "0.06", E_E_linha: "6.95", doppler_tecidual_relacao: "2.60" };
let patient: Record<string, unknown>;
let stored: Record<string, string>;
let description: string;
let savedStructured: EcocardiogramaEstruturadoPersistido | undefined;
const sectionButtons = new Map<Section, HTMLElement>();
let saveButton: HTMLElement | null;

const qualitative = (text: string) => ({ valvas: "", camaras: "", funcao: text, pericardio: "", vasos: "", ad_vd: "" });
const live = (): Record<string, string> => JSON.parse(screen.getByTestId("narrative-page-measurements").textContent || "{}");
const panel = () => screen.queryByRole("status", { name: PANEL });

function selectSection(section: Section) {
  const button = sectionButtons.get(section);
  if (!button) throw new Error(`Report section not mounted: ${section}`);
  fireEvent.click(button);
}

async function editNarrative(text: string) {
  selectSection("Qualitativa");
  fireEvent.change(screen.getByRole("textbox", { name: "Texto diastólico sintético" }), { target: { value: text } });
}

async function changeWaves(updates: ReadonlyArray<readonly [string, string]>, destination: Section = "Medidas") {
  // Canine acquisition controls already live in References; feline controls
  // are also directly available in Measurements. Exercise their existing UI.
  if (updates.some(([label]) => !screen.queryByLabelText(label))) selectSection("Referências");
  const controls = updates.map(([label, value]) => [screen.getByLabelText(label), value] as const);
  // Initial acquisition values are independent controls. Apply both events in
  // one React batch instead of remounting the large measurement form twice.
  act(() => {
    for (const [control, value] of controls) fireEvent.change(control, { target: { value } });
  });
  selectSection(destination);
}

async function changeWave(label: string, value: string, destination: Section = "Medidas") {
  await changeWaves([[label, value]], destination);
}

async function openPage(mode: Mode, options: { species?: string; flow?: string; tissue?: string; official?: string; draft?: string; measurements?: Record<string, string> } = {}) {
  const { species = "Gato", flow = "separadas", tissue = "separadas", official = CONFLICT, draft, measurements = {} } = options;
  patient = { id: 901, nome: "QA COERÊNCIA CLÍNICA", especie: species, tutor: "QA TUTOR", tutor_id: 902,
    peso_kg: 5.6, sexo: "Macho", raca: "SRD", idade: "4 anos" };
  stored = { ...MEASURES, ...measurements, Diastolica_ondas: flow, TDI_ondas: tissue };
  mocks.imported = { ...MEASURES, ...measurements };
  description = montarDescricaoEcocardiograma(stored, qualitative(official));
  savedStructured = draft === undefined ? undefined : { ...criarEcocardiogramaEstruturadoInicial(),
    usar_no_laudo: true, textos: { funcao_diastolica: draft, conclusao: "Conclusão do rascunho ainda não aplicada." } };
  mocks.get.mockImplementation(async (url: string) => {
    if (url.startsWith("/laudos/editor-drafts/")) throw { response: { status: 404 } };
    if (url === "/pacientes/901") return { data: patient };
    if (url === "/laudos/905") return { data: { editor_revision: "echo-v1:" + "a".repeat(64), id: 905, tipo: "ecocardiograma", paciente_id: 901, paciente: patient,
      titulo: "QA COERÊNCIA", diagnostico: CONCLUSION, observacoes: "Observação preservada.",
      data_exame: "2026-10-15", status: "Rascunho", medidas: stored, descricao: description,
      ecocardiograma_estruturado: savedStructured, imagens: [] } };
    if (url === "/portal/parceiros/veterinarios/opcoes") return { data: { items: [] } };
    throw new Error(`Unexpected mocked GET: ${url}`);
  });
  window.history.replaceState(null, "", mode === "novo" ? "/laudos/novo?paciente_id=901" : "/laudos/905/editar");
  render(mode === "novo" ? <NovoLaudoPage /> : <EditarLaudoPage />);
  await screen.findByDisplayValue(String(patient.nome));
  // Use the real navigation landmark and persistent header control. Looking up
  // every button in the whole Measurements form scans hundreds of +/- controls.
  const navigation = within(screen.getByRole("tablist", { name: "Seções do laudo" }));
  for (const section of ["Paciente", "Medidas", "Qualitativa", "Referências"] as const) {
    sectionButtons.set(section, navigation.getByRole("button", { name: section }));
  }
  saveButton = screen.getByRole("button", { name: mode === "novo" ? "Emitir laudo" : "Atualizar laudo" });
  if (mode === "novo") {
    fireEvent.click(screen.getByRole("button", { name: "Importar estudo sintético" }));
    await waitFor(() => expect(live().Onda_E).toBe("1.08"));
    await editNarrative(official);
  }
  selectSection("Medidas");
  if (mode === "novo") {
    await changeWaves([["Ondas transmitrais E/A", flow], ["Ondas teciduais e'/a'", tissue]]);
  }
  await waitFor(() => expect(live()).toMatchObject({ Diastolica_ondas: flow, TDI_ondas: tissue }));
}

async function save(mode: Mode) {
  expect(saveButton).not.toBeNull();
  fireEvent.click(saveButton!);
  const transport = mode === "novo" ? mocks.post : mocks.put;
  const url = mode === "novo" ? "/laudos" : "/laudos/905/editor-update";
  await waitFor(() => expect(transport.mock.calls.some(([target]) => target === url)).toBe(true));
  const body = transport.mock.calls.find(([target]) => target === url)![1];
  return mode === "editar" ? body.payload_laudo : body;
}

describe("páginas reais: conferência da narrativa canina e felina", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sectionButtons.clear(); saveButton = null;
    localStorage.setItem("token", "synthetic-local-token");
    localStorage.setItem("user", JSON.stringify({ id: 7 }));
    sessionStorage.clear();
    mocks.imported = { ...MEASURES };
    mocks.post.mockResolvedValue({ data: { id: 905 } });
    mocks.put.mockImplementation(async (url, body) => ({ data: url.startsWith("/laudos/editor-drafts/")
      ? { draft_id: url.split("/").at(-1), revision: body.expected_revision + 1, context_key: body.context_key, snapshot: body.snapshot, updated_at: "2026-11-01T12:00:00Z" }
      : url.endsWith("/editor-update") ? { id: 905, request_id: body.request_id, updated: true } : { id: 905 } }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); window.history.replaceState(null, "", "/"); });

  const speciesModes = MODES.flatMap((mode) => ["Gato", "Canina"].map((species) => ({ mode, species })));
  it.each(speciesModes)("$mode/$species recalcula o aviso real ao mudar fusão ou corrigir a redação nas duas abas", async ({ mode, species }) => {
    await openPage(mode, { species });
    expect(panel()).not.toBeInTheDocument();
    await changeWave("Ondas transmitrais E/A", "fundidas");
    await waitFor(() => expect(panel()).toBeInTheDocument());
    const notice = panel()!;
    expect(notice).toHaveAttribute("data-echo-consistency-review");
    expect(within(notice).getByText(/Ver trecho.*Função.*e sugestão/i, { selector: "summary" })).toBeInTheDocument();
    expect(notice.querySelector("blockquote")).toHaveTextContent(CONFLICT);
    expect(within(notice).getByText("Sugestão para sua revisão:")).toBeInTheDocument();
    expect(notice).toHaveTextContent(/fundidas/i);
    expect(live()).toMatchObject({ Onda_E: "1.08", Onda_A: "0.95", TD: "51", TRIV: "40", e_doppler: "0.16" });
    await changeWave("Ondas transmitrais E/A", "separadas");
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    await changeWave("Ondas transmitrais E/A", "fundidas", "Qualitativa");
    expect(panel()).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Texto diastólico sintético" }), { target: { value: REVIEWED } });
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    selectSection("Medidas");
    expect(panel()).not.toBeInTheDocument();
    expect(live().Diastolica_ondas).toBe("fundidas");
  });

  it.each(speciesModes)("$mode/$species deixa salvar o conflito sem aplicar sugestão nem apagar dados", async ({ mode, species }) => {
    await openPage(mode, { species, flow: "fundidas" });
    await waitFor(() => expect(panel()).toBeInTheDocument());
    const before = Object.fromEntries(Object.entries(live()).filter(([, value]) => value !== ""));
    const payload = await save(mode);
    const savedQualitative = mode === "novo" ? payload.qualitativa : extrairQualitativaEcoDaDescricao(payload.descricao);
    const savedMeasures = mode === "novo" ? payload.medidas : parseStoredEchoMeasurements(null, payload.descricao);
    expect(savedQualitative.funcao).toBe(CONFLICT);
    expect(Object.fromEntries(Object.entries(savedMeasures).filter(([, value]) => value !== ""))).toEqual(before);
    if (mode === "editar") {
      expect(payload.diagnostico).toBe(CONCLUSION);
      expect(payload.aplicar_qualitativa_estruturada).toBe(false);
    }
    expect(payload.ecocardiograma_estruturado?.textos.funcao_diastolica || CONFLICT).toBe(CONFLICT);
  });

  it.each(["Gato", "Canina"])("%s compara o texto oficial salvo mesmo quando o rascunho estruturado contém uma redação compatível", async (species) => {
    await openPage("editar", { species, flow: "fundidas", official: CONFLICT, draft: REVIEWED });
    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(panel()!.querySelector("blockquote")).toHaveTextContent(CONFLICT);
    const payload = await save("editar");
    expect(extrairQualitativaEcoDaDescricao(payload.descricao).funcao).toBe(CONFLICT);
    expect(payload.ecocardiograma_estruturado.textos.funcao_diastolica).toBe(REVIEWED);
    expect(payload.diagnostico).toBe(CONCLUSION);
    expect(payload.aplicar_qualitativa_estruturada).toBe(false);
  });

  it.each(["Gato", "Canina"])("%s ignora um conflito apenas no rascunho e passa a avisar quando o médico aplica a redação", async (species) => {
    await openPage("editar", { species, flow: "fundidas", official: REVIEWED, draft: CONFLICT });
    expect(panel()).not.toBeInTheDocument();
    await editNarrative(`${CONFLICT} Revisado manualmente.`);
    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(panel()!.querySelector("blockquote")).toHaveTextContent(CONFLICT);
    const payload = await save("editar");
    expect(extrairQualitativaEcoDaDescricao(payload.descricao).funcao).toBe(`${CONFLICT} Revisado manualmente.`);
    expect(payload.aplicar_qualitativa_estruturada).toBe(true);
    expect(payload.diagnostico).toBe(CONCLUSION);
  });

  it.each([
    { official: REVIEWED, draft: "conflitante", expected: false },
    { official: CONFLICT, draft: "compatível", expected: true },
  ])("novo considera o legado selecionado quando o rascunho $draft está desabilitado", async ({ official, draft, expected }) => {
    await openPage("novo", { flow: "fundidas", official });
    selectSection("Qualitativa");
    fireEvent.click(screen.getByRole("button", { name: `Preparar rascunho ${draft} sem aplicar` }));
    const expectedDraft = expected ? REVIEWED : CONFLICT;
    expect(screen.getByRole("textbox", { name: "Texto diastólico sintético" })).toHaveValue(expectedDraft);
    if (expected) {
      await waitFor(() => expect(panel()).toBeInTheDocument());
      expect(panel()!.querySelector("blockquote")).toHaveTextContent(official);
    } else {
      await waitFor(() => expect(panel()).not.toBeInTheDocument());
    }
    selectSection("Medidas");
    if (expected) expect(panel()).toBeInTheDocument();
    else expect(panel()).not.toBeInTheDocument();
    expect(live().Diastolica_ondas).toBe("fundidas");
    const payload = await save("novo");
    expect(payload.qualitativa.funcao).toBe(official);
    expect(payload.ecocardiograma_estruturado.usar_no_laudo).toBe(false);
    expect(payload.ecocardiograma_estruturado.textos.funcao_diastolica).toBe(expectedDraft);
  });

  it.each(MODES)("%s confere também a narrativa canina nas duas abas", async (mode) => {
    await openPage(mode, { species: "Canina", flow: "fundidas" });
    await waitFor(() => expect(panel()).toBeInTheDocument());
    selectSection("Qualitativa");
    expect(panel()).toBeInTheDocument();
  });

  it.each(MODES)("%s recalcula a conferência após alterar a espécie do formulário", async (mode) => {
    await openPage(mode, { flow: "fundidas" });
    await waitFor(() => expect(panel()).toBeInTheDocument());
    for (const [species, expected] of [["Canina", true], ["Felina", true]] as const) {
      selectSection("Paciente");
      const selector = screen.getByText("Espécie", { selector: "label" }).parentElement?.querySelector("select");
      expect(selector).not.toBeNull();
      fireEvent.change(selector!, { target: { value: species } });
      selectSection("Medidas");
      await waitFor(() => expected ? expect(panel()).toBeInTheDocument() : expect(panel()).not.toBeInTheDocument());
    }
    expect(live().Diastolica_ondas).toBe("fundidas");
  });

  it.each(MODES)("%s identifica TDI fundido sem depender de fusão transmitral", async (mode) => {
    await openPage(mode, { flow: "separadas", tissue: "fundidas", official: "Relação e′/a′ de 1,33." });
    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(panel()!.querySelector("blockquote")).toHaveTextContent("Relação e′/a′ de 1,33.");
    await changeWave("Ondas teciduais e'/a'", "separadas");
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    expect(live().Diastolica_ondas).toBe("separadas");
  });

  it.each(MODES)("%s atualiza a diferença numérica após preset, medida e texto sem impedir o salvamento", async (mode) => {
    await openPage(mode, { species: "Canina", official: "Relação AE/Ao de 1,40.",
      measurements: { Aorta: "10", Atrio_esquerdo: "14", AE_Ao: "1.40" } });
    expect(panel()).not.toBeInTheDocument();
    selectSection("Qualitativa");
    fireEvent.click(screen.getByRole("button", { name: "Definir conclusão oficial sintética" }));
    fireEvent.click(screen.getByRole("button", { name: "Aplicar preset numérico sintético" }));
    await waitFor(() => expect(panel()).toBeInTheDocument());
    expect(panel()!.querySelector("blockquote")).toHaveTextContent("Relação AE/Ao de 1,80.");
    selectSection("Medidas");
    const aorta = screen.getByText("Aorta (mm)", { selector: "label" }).parentElement?.querySelector("input");
    expect(aorta).not.toBeNull();
    fireEvent.change(aorta!, { target: { value: "7.78" } });
    await waitFor(() => expect(Number(live().AE_Ao)).toBeCloseTo(1.80, 2));
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    fireEvent.change(aorta!, { target: { value: "10" } });
    await waitFor(() => expect(panel()).toBeInTheDocument());
    await editNarrative("Relação AE/Ao de 1,40.");
    await waitFor(() => expect(panel()).not.toBeInTheDocument());
    const before = { ...live() };
    const payload = await save(mode);
    const savedQualitative = mode === "novo" ? payload.qualitativa : extrairQualitativaEcoDaDescricao(payload.descricao);
    const savedMeasures = mode === "novo" ? payload.medidas : parseStoredEchoMeasurements(null, payload.descricao);
    expect(savedQualitative.funcao).toBe("Relação AE/Ao de 1,40.");
    expect(savedMeasures.AE_Ao).toBe(before.AE_Ao);
    expect(savedMeasures.Aorta).toBe("10");
    expect(savedMeasures.Atrio_esquerdo).toBe("14");
    expect(mode === "novo" ? payload.conteudo.conclusao : payload.diagnostico).toBe(CONCLUSION);
    expect(payload.ecocardiograma_estruturado.textos.funcao_diastolica).toBe("Relação AE/Ao de 1,40.");
  });
});
