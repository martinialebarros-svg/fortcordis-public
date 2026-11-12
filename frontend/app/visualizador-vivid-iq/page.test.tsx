import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VividIqStudy } from "@/lib/vivid-iq-dicom.mjs";
import VisualizadorVividIqPage from "./page";

const mocks = vi.hoisted(() => ({
  parse: vi.fn(),
  identify: vi.fn(),
  createObjectURL: vi.fn(),
  revokeObjectURL: vi.fn(),
  fetch: vi.fn(),
}));

vi.mock("../layout-dashboard", () => ({
  default: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));

vi.mock("@/lib/vivid-iq-dicom.mjs", () => ({
  VIVID_IQ_MAX_FILE_BYTES: 512 * 1024 * 1024,
  parseVividIqDicom: mocks.parse,
  getVividIqIdentification: mocks.identify,
  getVividIqFramePixels: () => new Uint8Array([100, 100, 100, 100]),
  getVividIqPreviewJpeg: () => null,
  detectVividIqPreviewAspectRatio: () => null,
  createVividIqDisplayMap: () => new Int32Array([0, 1, 2, 3]),
}));

function makeStudy(): VividIqStudy {
  return {
    fileName: "arquivo local",
    fileSize: 1024,
    transferSyntax: "1.2.840.10008.1.2.1",
    modality: "US",
    manufacturer: "GE",
    model: "Vivid iq",
    equipment: "GE · Vivid iq",
    cineType: "2D",
    previewWidth: null,
    previewHeight: null,
    width: 2,
    height: 2,
    displayWidth: 2,
    displayHeight: 2,
    displayAspectRatio: 1,
    displayAspectRatioSource: "native-pixels",
    frameSize: 4,
    frameDimensions: [{ width: 2, height: 2, frameCount: 3 }],
    maxFrameWidth: 2,
    scanConversion: false,
    previewJpegOffset: null,
    previewJpegLength: 0,
    frameCount: 3,
    frameRate: 10,
    durationSeconds: 0.2,
    firstTimestamp: 1,
    frames: [0, 1, 2].map((index) => ({
      offset: index * 4,
      timestampSeconds: 1 + index / 10,
      width: 2,
      height: 2,
      frameSize: 4,
    })),
    warnings: [],
    sourceBuffer: new ArrayBuffer(12),
  };
}

class ControlledFileReader {
  static instances: ControlledFileReader[] = [];
  result: ArrayBuffer | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  readAsArrayBuffer = vi.fn();
  abort = vi.fn(() => this.onabort?.());

  constructor() {
    ControlledFileReader.instances.push(this);
  }

  succeed() {
    this.result = new ArrayBuffer(12);
    this.onload?.();
  }
}

function canvasContext() {
  return {
    createImageData: vi.fn((width: number, height: number) => ({
      width, height, data: new Uint8ClampedArray(width * height * 4), colorSpace: "srgb",
    })),
    putImageData: vi.fn(),
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    imageSmoothingEnabled: false,
    imageSmoothingQuality: "low",
    fillStyle: "",
    font: "",
  };
}

type TestCanvasContext = ReturnType<typeof canvasContext>;
let contexts: Map<HTMLCanvasElement, TestCanvasContext>;
let blobCallbacks: BlobCallback[];
let rafCallbacks: Map<number, FrameRequestCallback>;
let rafId: number;
let clockMilliseconds: number;
let fullscreenTarget: Element | null;
let fullscreenRequested: HTMLElement | null;
const originalFullscreen = Object.getOwnPropertyDescriptor(document, "fullscreenElement");
const originalRequest = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "requestFullscreen");
const originalExit = Object.getOwnPropertyDescriptor(document, "exitFullscreen");
const originalVisibilityState = Object.getOwnPropertyDescriptor(document, "visibilityState");

function restoreProperty(target: object, key: string, descriptor?: PropertyDescriptor) {
  if (descriptor) Object.defineProperty(target, key, descriptor);
  else Reflect.deleteProperty(target, key);
}

function chooseFiles(files: File[]) {
  fireEvent.change(screen.getByLabelText(/Selecionar (outro )?arquivo DICOM/), {
    target: { files },
  });
  return ControlledFileReader.instances[ControlledFileReader.instances.length - 1];
}

function chooseFile(name = "SYNTHETIC_CINE") {
  return chooseFiles([new File(["synthetic"], name)]);
}

function addFiles(files: File[]) {
  fireEvent.change(screen.getByLabelText("Adicionar arquivos DICOM"), { target: { files } });
}

function selectedFiles() {
  return screen.getByRole("list", { name: "Lista de arquivos locais" });
}

function fileButton(index: number, name: string) {
  return within(selectedFiles()).getByRole("button", { name: `Abrir arquivo ${index}: ${name}` });
}

async function finishRead(reader: ControlledFileReader) {
  await act(async () => reader.succeed());
}

async function openStudy({ expandAdjustments = true } = {}) {
  render(<VisualizadorVividIqPage />);
  await finishRead(chooseFile());
  if (expandAdjustments) {
    const summary = screen.queryByText("Trecho e ajustes");
    if (summary) fireEvent.click(summary);
  }
  return screen.getByRole("region", { name: "Player do cine Vivid IQ" });
}

function advanceFrame(milliseconds: number) {
  act(() => {
    clockMilliseconds += milliseconds;
    const callbacks = [...rafCallbacks.values()];
    rafCallbacks.clear();
    callbacks.forEach((callback) => callback(clockMilliseconds));
  });
}

function expectFrame(index: number) {
  expect(screen.getByRole("slider", { name: "Posicao no cine" })).toHaveValue(String(index));
  expect(screen.getByText(`Quadro ${index + 1} de 3`)).toBeInTheDocument();
}

describe("Visualizador Vivid IQ: controles locais e privacidade", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    ControlledFileReader.instances = [];
    contexts = new Map();
    blobCallbacks = [];
    rafCallbacks = new Map();
    rafId = 0;
    clockMilliseconds = 0;
    fullscreenTarget = null;
    fullscreenRequested = null;
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    mocks.parse.mockReset().mockImplementation(makeStudy);
    mocks.identify.mockReset().mockReturnValue({
      patientName: "Paciente Sintético",
      patientNameRaw: "SINTETICO^PACIENTE",
      studyDate: "22/10/2025",
      studyTime: "14:07:23",
      acquisitionDateTime: "22/10/2025 · 14:11:02",
      contentDate: "22/10/2025",
      contentTime: "14:11:02",
      timezoneOffset: null,
      warnings: [],
    });
    mocks.createObjectURL.mockReturnValue("blob:synthetic-capture");
    vi.stubGlobal("FileReader", ControlledFileReader);
    vi.stubGlobal("fetch", mocks.fetch);
    const OriginalURL = globalThis.URL;
    vi.stubGlobal("URL", class extends OriginalURL {
      static createObjectURL = mocks.createObjectURL;
      static revokeObjectURL = mocks.revokeObjectURL;
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (this: HTMLCanvasElement) {
      if (!contexts.has(this)) contexts.set(this, canvasContext());
      return contexts.get(this) as unknown as CanvasRenderingContext2D;
    });
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => {
      blobCallbacks.push(callback);
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.spyOn(XMLHttpRequest.prototype, "open").mockImplementation(() => undefined);
    vi.spyOn(window.performance, "now").mockImplementation(() => clockMilliseconds);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      rafCallbacks.set(++rafId, callback);
      return rafId;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
      rafCallbacks.delete(id);
    });
    Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => fullscreenTarget });
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn(async function (this: HTMLElement) {
        fullscreenRequested = this;
        fullscreenTarget = this;
        document.dispatchEvent(new Event("fullscreenchange"));
      }),
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: vi.fn(async () => {
        fullscreenTarget = null;
        document.dispatchEvent(new Event("fullscreenchange"));
      }),
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    restoreProperty(document, "fullscreenElement", originalFullscreen);
    restoreProperty(HTMLElement.prototype, "requestFullscreen", originalRequest);
    restoreProperty(document, "exitFullscreen", originalExit);
    restoreProperty(document, "visibilityState", originalVisibilityState);
  });

  it("mantém RGB em cinza no contraste fracionário e restaura os ajustes", async () => {
    await openStudy();
    fireEvent.change(screen.getByRole("slider", { name: /Contraste/ }), { target: { value: "1.05" } });
    const canvas = screen.getByLabelText("Cine do Vivid iq, quadro 1 de 3") as HTMLCanvasElement;
    const context = contexts.get(canvas)!;
    const rendered = () => context.putImageData.mock.lastCall?.[0].data as Uint8ClampedArray;
    expect([...rendered()]).toEqual(Array.from({ length: 4 }, () => [99, 99, 99, 255]).flat());
    fireEvent.change(screen.getByRole("slider", { name: /Brilho/ }), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Inverter lado" }));
    fireEvent.click(screen.getByRole("button", { name: "Restaurar imagem" }));
    expect([...rendered()]).toEqual(Array.from({ length: 4 }, () => [100, 100, 100, 255]).flat());
    expect(screen.getByRole("slider", { name: /Contraste/ })).toHaveValue("1");
    expect(screen.getByRole("slider", { name: /Brilho/ })).toHaveValue("0");
    expect(screen.getByRole("button", { name: "Inverter lado" })).toHaveAttribute("aria-pressed", "false");
  });

  it("cancela a leitura e ignora um retorno tardio do arquivo cancelado", async () => {
    render(<VisualizadorVividIqPage />);
    const reader = chooseFile();
    expect(screen.getByRole("status")).toHaveTextContent("Lendo o cine localmente");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Cancelar leitura" })));
    expect(reader.abort).toHaveBeenCalledOnce();
    await finishRead(reader);
    expect(mocks.parse).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tentar abrir novamente" })).toBeEnabled();
    expect(fileButton(1, "SYNTHETIC_CINE")).toHaveAttribute("aria-current", "true");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rejeita arquivo grande durante leitura sem deixar carregamento preso", async () => {
    render(<VisualizadorVividIqPage />);
    const reader = chooseFile();
    const oversized = new File(["synthetic"], "OVERSIZED");
    Object.defineProperty(oversized, "size", { value: 512 * 1024 * 1024 + 1 });
    const dropzone = screen.getByLabelText("Selecionar arquivo DICOM").parentElement!;
    await act(async () => fireEvent.drop(dropzone, { dataTransfer: { files: [oversized] } }));
    expect(reader.abort).toHaveBeenCalledOnce();
    await finishRead(reader);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("512 MB");
    expect(mocks.parse).not.toHaveBeenCalled();
    await finishRead(chooseFile("VALID_RETRY"));
    expectFrame(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("mantém somente o arquivo mais recente e permite tentar novamente após erro de leitura", async () => {
    render(<VisualizadorVividIqPage />);
    const first = chooseFile("FIRST");
    const second = chooseFile("SECOND");
    await finishRead(first);
    expect(mocks.parse).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeInTheDocument();
    await act(async () => second.onerror?.());
    expect(screen.getByRole("alert")).toHaveTextContent("Verifique se a unidade continua conectada");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await finishRead(chooseFile("RETRY"));
    expect(mocks.parse).toHaveBeenCalledOnce();
    expectFrame(0);
  });

  it("exibe falha do parser e recupera com outro arquivo", async () => {
    render(<VisualizadorVividIqPage />);
    mocks.parse.mockImplementationOnce(() => { throw new Error("Arquivo sintético inválido."); });
    await finishRead(chooseFile("INVALID"));
    expect(screen.getByRole("alert")).toHaveTextContent("Arquivo sintético inválido");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await finishRead(chooseFile("VALID"));
    expectFrame(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("leva controles e aviso junto para tela cheia e sincroniza a saída", async () => {
    const player = await openStudy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Tela cheia" })));
    expect(fullscreenRequested).toBe(player);
    expect(within(fullscreenRequested!).getByRole("button", { name: "Reproduzir" })).toBeVisible();
    expect(within(fullscreenRequested!).getByText(/imagem não calibrada/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Sair da tela cheia" })).toBeInTheDocument();
    act(() => {
      fullscreenTarget = null;
      document.dispatchEvent(new Event("fullscreenchange"));
    });
    expect(screen.getByRole("button", { name: "Tela cheia" })).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Tela cheia" })));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sair da tela cheia" })));
    expect(document.exitFullscreen).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Tela cheia" })).toBeInTheDocument();
  });

  it("usa atalhos no player sem capturar teclas dos campos ou modificadores", async () => {
    const player = await openStudy();
    fireEvent.keyDown(player, { key: "ArrowRight" });
    expectFrame(1);
    fireEvent.keyDown(player, { key: "ArrowLeft" });
    expectFrame(0);
    fireEvent.keyDown(player, { key: " " });
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    fireEvent.keyDown(player, { key: " ", repeat: true });
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    fireEvent.keyDown(player, { key: " " });
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("slider", { name: /Contraste/ }), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Velocidade" }), { key: " " });
    fireEvent.keyDown(screen.getByRole("checkbox", { name: "Repetir trecho" }), { key: " " });
    fireEvent.keyDown(player, { key: "ArrowRight", ctrlKey: true });
    expect(fireEvent.keyDown(screen.getByRole("button", { name: "Limpar exame" }), { key: " " })).toBe(true);
    expect(fireEvent.keyDown(screen.getByRole("button", { name: "Tela cheia" }), { key: " " })).toBe(true);
    expectFrame(0);
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("button", { name: "Reproduzir" }), { key: "ArrowRight" });
    expectFrame(1);
    fireEvent.keyDown(screen.getByRole("button", { name: "Reproduzir" }), { key: "ArrowLeft" });
    expectFrame(0);
    await act(async () => fireEvent.keyDown(screen.getByRole("button", { name: "Reproduzir" }), { key: "f" }));
    expect(fullscreenRequested).toBe(player);
  });

  it("respeita A–B e repete mantendo o último quadro durante seu intervalo", async () => {
    await openStudy();
    fireEvent.click(screen.getByRole("button", { name: "Proximo quadro" }));
    fireEvent.click(screen.getByRole("button", { name: "Marcar início (A)" }));
    fireEvent.click(screen.getByRole("button", { name: "Ultimo quadro" }));
    fireEvent.click(screen.getByRole("button", { name: "Marcar fim (B)" }));
    expect(screen.getByText("2–3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Repetir trecho" }));
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    expectFrame(1);
    advanceFrame(100);
    expectFrame(2);
    advanceFrame(50);
    expectFrame(2);
    advanceFrame(50);
    expectFrame(1);
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pausar" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Repetir trecho" }));
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    expectFrame(2);
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Usar cine inteiro" }));
    expect(screen.getByText("1–3")).toBeInTheDocument();
  });

  it("lê identificação apenas por solicitação e a oculta ao esconder, limpar ou trocar arquivo", async () => {
    await openStudy();
    expect(mocks.identify).not.toHaveBeenCalled();
    expect(screen.queryByText("Paciente Sintético")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar identificação do exame" }));
    expect(mocks.identify).toHaveBeenCalledOnce();
    expect(screen.getByText("Paciente Sintético")).toBeInTheDocument();
    expect(screen.getByText("22/10/2025 · 14:07:23")).toBeInTheDocument();
    expect(screen.getByText("Não informado no arquivo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ocultar identificação" }));
    expect(screen.queryByText("Paciente Sintético")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar identificação do exame" }));
    await finishRead(chooseFile("ANOTHER_EXAM"));
    expect(screen.queryByText("Paciente Sintético")).not.toBeInTheDocument();
    expect(mocks.identify).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Mostrar identificação do exame" }));
    fireEvent.click(screen.getByRole("button", { name: "Limpar exame" }));
    expect(screen.queryByText("Paciente Sintético")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Escolher arquivo" })).toBeInTheDocument();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
  });

  it("pausa para PNG e inclui rodapé técnico sem identificação do paciente", async () => {
    await openStudy();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar identificação do exame" }));
    fireEvent.change(screen.getByRole("slider", { name: /Contraste/ }), { target: { value: "1.05" } });
    fireEvent.click(screen.getByRole("button", { name: "Inverter lado" }));
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    expectFrame(1);
    fireEvent.click(screen.getByRole("button", { name: "Baixar quadro PNG" }));
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    const captureEntry = [...contexts.entries()].find(([, context]) => context.fillText.mock.calls.length > 0)!;
    expect(captureEntry[0].height).toBe(98);
    const footer = captureEntry[1].fillText.mock.calls.map((call) => call[0]).join("\n");
    expect(footer).toContain("Captura derivada — não calibrada");
    expect(footer).toContain("Quadro 2 de 3 · 0,10 s");
    expect(footer).toContain("Contraste 1,05x");
    expect(footer).toContain("Inversão lateral: sim");
    expect(footer).not.toMatch(/Paciente Sintético|SINTETICO|22\/10\/2025/);
    act(() => blobCallbacks[0](new Blob(["synthetic png"], { type: "image/png" })));
    expect(mocks.createObjectURL).toHaveBeenCalledOnce();
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
  });

  it("descarta exportação atrasada quando o exame é limpo", async () => {
    await openStudy();
    fireEvent.click(screen.getByRole("button", { name: "Baixar quadro PNG" }));
    fireEvent.click(screen.getByRole("button", { name: "Limpar exame" }));
    act(() => blobCallbacks[0](new Blob(["stale png"], { type: "image/png" })));
    expect(mocks.createObjectURL).not.toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });

  it("abre foco compacto com controles essenciais e Escape restaura o foco e a rolagem", async () => {
    const player = await openStudy({ expandAdjustments: false });
    const header = screen.getByRole("heading", { name: "Visualizador Vivid IQ" }).closest("header")!;
    const previousInert = header.inert;
    expect(screen.getByText("Trecho e ajustes").closest("details")).not.toHaveAttribute("open");
    const focusButton = screen.getByRole("button", { name: "Modo foco" });
    document.body.style.overflow = "scroll";
    focusButton.focus();
    fireEvent.click(focusButton);
    const dialog = screen.getByRole("dialog", { name: "Player do cine Vivid IQ" });
    expect(dialog).toBe(player);
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(document.body.style.overflow).toBe("hidden");
    expect(header.inert).toBe(true);
    expect(within(dialog).getByRole("button", { name: "Reproduzir" })).toBeVisible();
    expect(within(dialog).getByRole("slider", { name: "Posicao no cine" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Sair do modo foco" })).toBeVisible();
    expect(within(dialog).getByText(/imagem não calibrada/)).toBeVisible();
    expect(screen.getByText("Trecho e ajustes").closest("details")).not.toHaveAttribute("open");
    fireEvent.keyDown(within(dialog).getByRole("spinbutton", { name: "Ir para o quadro" }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modo foco" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("scroll");
    expect(header.inert).toBe(previousInert);
    document.body.style.overflow = "";
  });

  it("mantém Tab dentro do modo foco e libera a rolagem quando desmontado", async () => {
    await openStudy({ expandAdjustments: false });
    const previousOverflow = document.body.style.overflow;
    fireEvent.click(screen.getByRole("button", { name: "Modo foco" }));
    const dialog = screen.getByRole("dialog", { name: "Player do cine Vivid IQ" });
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>(
      "button, input, select, summary, a[href], [tabindex='0']",
    )).filter((element) => {
      if (element.hasAttribute("disabled") || element.getAttribute("type") === "hidden") return false;
      const closedDetails = element.closest("details:not([open])");
      return !closedDetails || element.tagName === "SUMMARY";
    });
    expect(controls.length).toBeGreaterThan(2);
    const first = controls[0];
    const last = controls[controls.length - 1];
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
    cleanup();
    expect(document.body.style.overflow).toBe(previousOverflow);
  });

  it("oferece modo foco recuperável quando a tela cheia nativa falha", async () => {
    await openStudy({ expandAdjustments: false });
    vi.mocked(HTMLElement.prototype.requestFullscreen).mockRejectedValueOnce(new Error("Fullscreen unavailable"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Tela cheia" })));
    expect(screen.getByRole("dialog", { name: "Player do cine Vivid IQ" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/modo foco/i);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sair do modo foco" }));
    expect(screen.getByRole("region", { name: "Player do cine Vivid IQ" })).toBeInTheDocument();
  });

  it.each(["", "0", "4", "1.5", "-1"])("rejeita salto inválido '%s' sem mudar de quadro", async (target) => {
    await openStudy({ expandAdjustments: false });
    fireEvent.click(screen.getByRole("button", { name: "Proximo quadro" }));
    const form = screen.getByRole("form", { name: "Navegação por quadro" });
    const input = within(form).getByRole("spinbutton", { name: "Ir para o quadro" });
    fireEvent.change(input, { target: { value: target } });
    fireEvent.submit(form);
    expectFrame(1);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(within(form).getByRole("alert")).toHaveTextContent(/1.*3/);
  });

  it("salta para quadro válido, pausa a reprodução e mantém Enter no formulário", async () => {
    await openStudy({ expandAdjustments: false });
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    const form = screen.getByRole("form", { name: "Navegação por quadro" });
    const input = within(form).getByRole("spinbutton", { name: "Ir para o quadro" });
    fireEvent.change(input, { target: { value: "3" } });
    expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(true);
    fireEvent.submit(form);
    expectFrame(2);
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-invalid", "true");
    expect(within(form).queryByRole("alert")).not.toBeInTheDocument();
    advanceFrame(1000);
    expectFrame(2);
  });

  it("pausa ao ocultar a aba e só retoma quando solicitado", async () => {
    await openStudy({ expandAdjustments: false });
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    expectFrame(1);
    act(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    advanceFrame(5000);
    expectFrame(1);
    act(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    advanceFrame(1000);
    expectFrame(1);
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    expectFrame(2);
  });

  it("amplia apenas a visualização e exporta o quadro inteiro, preservando o reset", async () => {
    await openStudy({ expandAdjustments: false });
    const canvas = screen.getByLabelText("Cine do Vivid iq, quadro 1 de 3") as HTMLCanvasElement;
    const originalWidth = canvas.width;
    const originalHeight = canvas.height;
    const viewport = screen.getByRole("region", { name: "Área de visualização" });
    Object.defineProperties(viewport, {
      clientWidth: { configurable: true, value: 600 },
      clientHeight: { configurable: true, value: 400 },
    });
    fireEvent(window, new Event("resize"));
    const visibleSize = canvas.parentElement!;
    const initialVisibleWidth = Number.parseFloat(visibleSize.style.width);
    const initialVisibleHeight = Number.parseFloat(visibleSize.style.height);
    const zoom = screen.getByRole("combobox", { name: "Ampliação" });
    fireEvent.change(zoom, { target: { value: "3" } });
    expect(zoom).toHaveValue("3");
    expect(Number.parseFloat(visibleSize.style.width)).toBe(initialVisibleWidth * 3);
    expect(Number.parseFloat(visibleSize.style.height)).toBe(initialVisibleHeight * 3);
    expect(canvas.width).toBe(originalWidth);
    expect(canvas.height).toBe(originalHeight);
    fireEvent.click(screen.getByRole("button", { name: "Baixar quadro PNG" }));
    const capture = [...contexts.entries()].find(([, context]) => context.fillText.mock.calls.length > 0)!;
    expect(capture[0].height).toBe(originalHeight + 96);
    expect(capture[1].drawImage).toHaveBeenCalledWith(canvas, (capture[0].width - originalWidth) / 2, 0);
    fireEvent.click(screen.getByRole("button", { name: "Ajustar imagem" }));
    expect(zoom).toHaveValue("1");
    fireEvent.change(zoom, { target: { value: "2" } });
    await finishRead(chooseFile("NEW_CINE"));
    expect(screen.getByRole("combobox", { name: "Ampliação" })).toHaveValue("1");
  });

  it("aceita novamente o mesmo arquivo após erro sem manter o valor da seleção", async () => {
    render(<VisualizadorVividIqPage />);
    const file = new File(["synthetic"], "SAME_CINE");
    const input = screen.getByLabelText("Selecionar arquivo DICOM") as HTMLInputElement;
    let inputValue = "";
    const setValue = vi.fn((value: string) => { inputValue = value; });
    Object.defineProperty(input, "value", { configurable: true, get: () => inputValue, set: setValue });
    inputValue = "C:\\fakepath\\SAME_CINE";
    fireEvent.change(input, { target: { files: [file] } });
    expect(setValue).toHaveBeenCalledWith("");
    expect(inputValue).toBe("");
    await act(async () => ControlledFileReader.instances[0].onerror?.());
    inputValue = "C:\\fakepath\\SAME_CINE";
    fireEvent.change(input, { target: { files: [file] } });
    expect(inputValue).toBe("");
    expect(ControlledFileReader.instances).toHaveLength(2);
    await finishRead(ControlledFileReader.instances[1]);
    expectFrame(0);
  });

  it("seleciona vários arquivos na ordem recebida, sem deduplicar nomes nem ler os inativos", async () => {
    render(<VisualizadorVividIqPage />);
    const files = [new File(["first"], "Z_CINE"), new File(["second"], "A_CINE"), new File(["third"], "Z_CINE")];
    expect(screen.getByLabelText("Selecionar arquivo DICOM")).toHaveAttribute("multiple");
    const firstReader = chooseFiles(files);
    expect(screen.getByRole("region", { name: "Arquivos selecionados" })).toBeInTheDocument();
    expect(selectedFiles().tagName).toBe("OL");
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(3);
    expect(fileButton(1, "Z_CINE")).toHaveAttribute("aria-current", "true");
    expect(fileButton(2, "A_CINE")).not.toHaveAttribute("aria-current", "true");
    expect(fileButton(3, "Z_CINE")).not.toHaveAttribute("aria-current", "true");
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(firstReader.readAsArrayBuffer).toHaveBeenCalledWith(files[0]);
    expect(mocks.parse).not.toHaveBeenCalled();
    await finishRead(firstReader);
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(mocks.parse.mock.calls[0][1]).toBe("arquivo local");
    expect(mocks.identify).not.toHaveBeenCalled();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Arquivo anterior" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Próximo arquivo" })).toBeEnabled();

    const replacement = new File(["replacement"], "REPLACEMENT");
    await finishRead(chooseFiles([replacement]));
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(1);
    expect(fileButton(1, "REPLACEMENT")).toHaveAttribute("aria-current", "true");
    expect(screen.queryByRole("button", { name: "Abrir arquivo 1: Z_CINE" })).not.toBeInTheDocument();
  });

  it("aceita vários arquivos arrastados e abre somente o primeiro", async () => {
    render(<VisualizadorVividIqPage />);
    const files = [new File(["first"], "DROP_B"), new File(["second"], "DROP_A")];
    const dropzone = screen.getByLabelText("Selecionar arquivo DICOM").parentElement!;
    fireEvent.drop(dropzone, { dataTransfer: { files } });
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(ControlledFileReader.instances[0].readAsArrayBuffer).toHaveBeenCalledWith(files[0]);
    expect(fileButton(1, "DROP_B")).toHaveAttribute("aria-current", "true");
    expect(fileButton(2, "DROP_A")).toBeInTheDocument();
    await finishRead(ControlledFileReader.instances[0]);
    expect(mocks.parse).toHaveBeenCalledOnce();
  });

  it("acrescenta referências locais sem interromper ou reler o cine ativo", async () => {
    await openStudy();
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    expectFrame(1);
    const activeReader = ControlledFileReader.instances[0];
    const added = [new File(["second"], "SYNTHETIC_CINE"), new File(["third"], "ADDED")];
    expect(screen.getByLabelText("Adicionar arquivos DICOM")).toHaveAttribute("multiple");
    addFiles(added);
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(activeReader.abort).not.toHaveBeenCalled();
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(mocks.identify).not.toHaveBeenCalled();
    expectFrame(1);
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    expect(fileButton(1, "SYNTHETIC_CINE")).toHaveAttribute("aria-current", "true");
    expect(fileButton(2, "SYNTHETIC_CINE")).toBeInTheDocument();
    expect(fileButton(3, "ADDED")).toBeInTheDocument();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
  });

  it("mantém a leitura pendente quando arquivos são acrescentados", async () => {
    render(<VisualizadorVividIqPage />);
    const activeReader = chooseFile("READING");
    addFiles([new File(["queued"], "QUEUED")]);
    expect(activeReader.abort).not.toHaveBeenCalled();
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(mocks.parse).not.toHaveBeenCalled();
    expect(fileButton(1, "READING")).toHaveAttribute("aria-current", "true");
    await finishRead(activeReader);
    expectFrame(0);
    expect(fileButton(2, "QUEUED")).toBeInTheDocument();
  });

  it("rejeita uma seleção inicial acima de 100 arquivos antes de ler qualquer conteúdo", () => {
    render(<VisualizadorVividIqPage />);
    chooseFiles(Array.from({ length: 101 }, (_, index) => new File(["synthetic"], `CINE_${index}`)));
    expect(screen.getByRole("alert")).toHaveTextContent("100");
    expect(ControlledFileReader.instances).toHaveLength(0);
    expect(mocks.parse).not.toHaveBeenCalled();
    expect(screen.queryByRole("list", { name: "Lista de arquivos locais" })).not.toBeInTheDocument();
  });

  it("aceita 100 arquivos e preserva coleção e ativo ao rejeitar acréscimo ou substituição acima do limite", async () => {
    await openStudy();
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    const remaining = Array.from({ length: 99 }, (_, index) => new File(["synthetic"], `QUEUED_${index}`));
    addFiles(remaining);
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(100);
    expect(ControlledFileReader.instances).toHaveLength(1);
    addFiles([new File(["overflow"], "OVER_LIMIT")]);
    expect(screen.getByRole("alert")).toHaveTextContent("100");
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(100);
    expect(fileButton(1, "SYNTHETIC_CINE")).toHaveAttribute("aria-current", "true");
    expect(screen.queryByRole("button", { name: /Abrir arquivo.*OVER_LIMIT/ })).not.toBeInTheDocument();
    expectFrame(1);
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    chooseFiles(Array.from({ length: 101 }, (_, index) => new File(["replacement"], `REPLACEMENT_${index}`)));
    expect(screen.getByRole("alert")).toHaveTextContent("100");
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(100);
    expect(fileButton(1, "SYNTHETIC_CINE")).toHaveAttribute("aria-current", "true");
    expectFrame(1);
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(mocks.identify).not.toHaveBeenCalled();
  });

  it("cancela sem perder a coleção e permite reler o mesmo ativo", async () => {
    render(<VisualizadorVividIqPage />);
    const files = [new File(["first"], "RETRY_THIS"), new File(["second"], "KEEP_THIS")];
    const firstReader = chooseFiles(files);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Cancelar leitura" })));
    expect(firstReader.abort).toHaveBeenCalledOnce();
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(2);
    expect(fileButton(1, "RETRY_THIS")).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Limpar exame" })).toBeEnabled();
    await finishRead(firstReader);
    expect(mocks.parse).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Tentar abrir novamente" }));
    const retryReader = ControlledFileReader.instances[1];
    expect(retryReader.readAsArrayBuffer).toHaveBeenCalledWith(files[0]);
    await finishRead(retryReader);
    expectFrame(0);
    expect(fileButton(2, "KEEP_THIS")).toBeInTheDocument();
  });

  it("isola erros de leitura e parser sem impedir a navegação para outro arquivo", async () => {
    render(<VisualizadorVividIqPage />);
    const files = ["READ_ERROR", "PARSE_ERROR", "GOOD"].map((name) => new File(["synthetic"], name));
    const firstReader = chooseFiles(files);
    await act(async () => firstReader.onerror?.());
    expect(screen.getByRole("alert")).toHaveTextContent("Verifique se a unidade continua conectada");
    expect(screen.getByRole("button", { name: "Tentar abrir novamente" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Próximo arquivo" }));
    mocks.parse.mockImplementationOnce(() => { throw new Error("Cine inválido desta coleção."); });
    await finishRead(ControlledFileReader.instances[1]);
    expect(screen.getByRole("alert")).toHaveTextContent("Cine inválido desta coleção");
    expect(fileButton(2, "PARSE_ERROR")).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "Próximo arquivo" }));
    await finishRead(ControlledFileReader.instances[2]);
    expectFrame(0);
    expect(fileButton(3, "GOOD")).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Próximo arquivo" })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(3);
  });

  it("troca o ativo durante leitura, aborta o anterior e ignora seu callback tardio", async () => {
    render(<VisualizadorVividIqPage />);
    const files = [new File(["first"], "FIRST"), new File(["second"], "SECOND")];
    const firstReader = chooseFiles(files);
    await act(async () => fireEvent.click(fileButton(2, "SECOND")));
    expect(firstReader.abort).toHaveBeenCalledOnce();
    const secondReader = ControlledFileReader.instances[1];
    expect(secondReader.readAsArrayBuffer).toHaveBeenCalledWith(files[1]);
    await finishRead(firstReader);
    expect(mocks.parse).not.toHaveBeenCalled();
    expect(fileButton(2, "SECOND")).toHaveAttribute("aria-current", "true");
    await finishRead(secondReader);
    expect(mocks.parse).toHaveBeenCalledOnce();
    expectFrame(0);
    fireEvent.click(screen.getByRole("button", { name: "Arquivo anterior" }));
    const reopenedReader = ControlledFileReader.instances[2];
    expect(reopenedReader.readAsArrayBuffer).toHaveBeenCalledWith(files[0]);
    await finishRead(reopenedReader);
    expect(mocks.parse).toHaveBeenCalledTimes(2);
    expect(fileButton(1, "FIRST")).toHaveAttribute("aria-current", "true");
  });

  it("trocar de arquivo limpa identificação, ajustes, trecho, ampliação e reprodução", async () => {
    render(<VisualizadorVividIqPage />);
    await finishRead(chooseFiles([new File(["first"], "ADJUSTED"), new File(["second"], "FRESH")]));
    fireEvent.click(screen.getByText("Trecho e ajustes"));
    fireEvent.click(screen.getByRole("button", { name: "Mostrar identificação do exame" }));
    fireEvent.change(screen.getByRole("slider", { name: /Brilho/ }), { target: { value: "20" } });
    fireEvent.change(screen.getByRole("slider", { name: /Contraste/ }), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Inverter lado" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Velocidade" }), { target: { value: "0.5" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Ampliação" }), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Proximo quadro" }));
    fireEvent.click(screen.getByRole("button", { name: "Marcar início (A)" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Repetir trecho" }));
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    expect(screen.getByText("Paciente Sintético")).toBeInTheDocument();
    fireEvent.click(fileButton(2, "FRESH"));
    expect(screen.queryByText("Paciente Sintético")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pausar" })).not.toBeInTheDocument();
    expect(rafCallbacks.size).toBe(0);
    await finishRead(ControlledFileReader.instances[1]);
    const adjustments = screen.getByText("Trecho e ajustes").closest("details")!;
    if (!adjustments.open) fireEvent.click(screen.getByText("Trecho e ajustes"));
    expectFrame(0);
    expect(screen.getByRole("slider", { name: /Brilho/ })).toHaveValue("0");
    expect(screen.getByRole("slider", { name: /Contraste/ })).toHaveValue("1");
    expect(screen.getByRole("combobox", { name: "Velocidade" })).toHaveValue("1");
    expect(screen.getByRole("combobox", { name: "Ampliação" })).toHaveValue("1");
    expect(screen.getByRole("checkbox", { name: "Repetir trecho" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Inverter lado" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("1–3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reproduzir" })).toBeInTheDocument();
    expect(mocks.identify).toHaveBeenCalledOnce();
    expect(screen.queryByText("Paciente Sintético")).not.toBeInTheDocument();
  });

  it("remove inativo sem reler e remove ativo abrindo próximo ou anterior, até limpar a coleção", async () => {
    render(<VisualizadorVividIqPage />);
    const files = ["FIRST", "SECOND", "THIRD", "LAST"].map((name) => new File(["synthetic"], name));
    await finishRead(chooseFiles(files));
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    fireEvent.click(screen.getByRole("button", { name: "Remover arquivo 4: LAST" }));
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Remover arquivo 1: FIRST" }));
    expect(ControlledFileReader.instances[1].readAsArrayBuffer).toHaveBeenCalledWith(files[1]);
    await finishRead(ControlledFileReader.instances[1]);
    expect(fileButton(1, "SECOND")).toHaveAttribute("aria-current", "true");
    fireEvent.click(fileButton(2, "THIRD"));
    await finishRead(ControlledFileReader.instances[2]);
    fireEvent.click(screen.getByRole("button", { name: "Remover arquivo 2: THIRD" }));
    expect(ControlledFileReader.instances[3].readAsArrayBuffer).toHaveBeenCalledWith(files[1]);
    await finishRead(ControlledFileReader.instances[3]);
    expect(fileButton(1, "SECOND")).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "Remover arquivo 1: SECOND" }));
    expect(screen.queryByRole("list", { name: "Lista de arquivos locais" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Player do cine Vivid IQ" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Escolher arquivo" })).toBeEnabled();
    expect(ControlledFileReader.instances).toHaveLength(4);
  });

  it("remover um arquivo anterior ao ativo preserva o estudo e apenas renumera sua posição", async () => {
    render(<VisualizadorVividIqPage />);
    const files = ["BEFORE", "ACTIVE", "AFTER"].map((name) => new File(["synthetic"], name));
    await finishRead(chooseFiles(files));
    fireEvent.click(fileButton(2, "ACTIVE"));
    await finishRead(ControlledFileReader.instances[1]);
    fireEvent.click(screen.getByRole("button", { name: "Mostrar identificação do exame" }));
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    fireEvent.click(screen.getByRole("button", { name: "Remover arquivo 1: BEFORE" }));
    expect(fileButton(1, "ACTIVE")).toHaveAttribute("aria-current", "true");
    expect(fileButton(2, "AFTER")).toBeInTheDocument();
    expectFrame(1);
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    expect(screen.getByText("Paciente Sintético")).toBeInTheDocument();
    expect(ControlledFileReader.instances).toHaveLength(2);
    expect(mocks.parse).toHaveBeenCalledTimes(2);
    expect(mocks.identify).toHaveBeenCalledOnce();
  });

  it("cancelar o seletor ou fornecer uma seleção vazia preserva o ativo e a coleção", async () => {
    await openStudy();
    fireEvent.click(screen.getByRole("button", { name: "Proximo quadro" }));
    chooseFiles([]);
    addFiles([]);
    expect(fileButton(1, "SYNTHETIC_CINE")).toHaveAttribute("aria-current", "true");
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(1);
    expectFrame(1);
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("descarta PNG atrasado de outro arquivo e limpa coleção durante leitura pendente", async () => {
    render(<VisualizadorVividIqPage />);
    await finishRead(chooseFiles([new File(["first"], "PRIVATE_NAME"), new File(["second"], "NEXT")]));
    fireEvent.click(screen.getByRole("button", { name: "Mostrar identificação do exame" }));
    fireEvent.click(screen.getByRole("button", { name: "Baixar quadro PNG" }));
    const exportedText = [...contexts.values()].flatMap((context) => context.fillText.mock.calls.map((call) => call[0])).join("\n");
    expect(exportedText).not.toMatch(/PRIVATE_NAME|Paciente Sintético|SINTETICO|22\/10\/2025/);
    fireEvent.click(fileButton(2, "NEXT"));
    act(() => blobCallbacks[0](new Blob(["old capture"], { type: "image/png" })));
    expect(mocks.createObjectURL).not.toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
    const pending = ControlledFileReader.instances[1];
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Limpar exame" })));
    expect(pending.abort).toHaveBeenCalledOnce();
    await finishRead(pending);
    expect(screen.queryByRole("list", { name: "Lista de arquivos locais" })).not.toBeInTheDocument();
    expect(screen.queryByText("Paciente Sintético")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Escolher arquivo" })).toBeEnabled();
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
  });

  it("mantém arquivo grande inativo na coleção e o rejeita antes da leitura quando selecionado", async () => {
    render(<VisualizadorVividIqPage />);
    const valid = new File(["synthetic"], "VALID");
    const oversized = new File(["synthetic"], "LARGE");
    Object.defineProperty(oversized, "size", { value: 512 * 1024 * 1024 + 1 });
    await finishRead(chooseFiles([valid, oversized]));
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fileButton(2, "LARGE")).toBeInTheDocument();
    fireEvent.click(fileButton(2, "LARGE"));
    expect(screen.getByRole("alert")).toHaveTextContent("512 MB");
    expect(fileButton(2, "LARGE")).toHaveAttribute("aria-current", "true");
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Arquivo anterior" }));
    expect(ControlledFileReader.instances[1].readAsArrayBuffer).toHaveBeenCalledWith(valid);
    await finishRead(ControlledFileReader.instances[1]);
    expectFrame(0);
    expect(fileButton(1, "VALID")).toHaveAttribute("aria-current", "true");
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("remover o ativo durante leitura aborta seu leitor e mantém somente o retorno do próximo", async () => {
    render(<VisualizadorVividIqPage />);
    const files = [new File(["first"], "REMOVED"), new File(["second"], "NEXT")];
    const removedReader = chooseFiles(files);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remover arquivo 1: REMOVED" })));
    expect(removedReader.abort).toHaveBeenCalledOnce();
    expect(ControlledFileReader.instances).toHaveLength(2);
    const nextReader = ControlledFileReader.instances[1];
    expect(nextReader.readAsArrayBuffer).toHaveBeenCalledWith(files[1]);
    expect(fileButton(1, "NEXT")).toHaveAttribute("aria-current", "true");
    await finishRead(removedReader);
    expect(mocks.parse).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Player do cine Vivid IQ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Abrir arquivo 1: REMOVED" })).not.toBeInTheDocument();
    await finishRead(nextReader);
    expect(mocks.parse).toHaveBeenCalledOnce();
    expectFrame(0);
    expect(fileButton(1, "NEXT")).toHaveAttribute("aria-current", "true");
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(1);
  });

  it("arrastar arquivos sobre a lista acrescenta à coleção sem interromper a reprodução", async () => {
    await openStudy();
    fireEvent.click(screen.getByRole("button", { name: "Reproduzir" }));
    advanceFrame(100);
    const files = [new File(["second"], "DROP_SECOND"), new File(["third"], "DROP_THIRD")];
    fireEvent.drop(selectedFiles().parentElement!, { dataTransfer: { files } });
    expect(within(selectedFiles()).getAllByRole("listitem")).toHaveLength(3);
    expect(fileButton(1, "SYNTHETIC_CINE")).toHaveAttribute("aria-current", "true");
    expect(fileButton(2, "DROP_SECOND")).toBeInTheDocument();
    expect(fileButton(3, "DROP_THIRD")).toBeInTheDocument();
    expectFrame(1);
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    expect(ControlledFileReader.instances).toHaveLength(1);
    expect(ControlledFileReader.instances[0].abort).not.toHaveBeenCalled();
    expect(mocks.parse).toHaveBeenCalledOnce();
    expect(mocks.identify).not.toHaveBeenCalled();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
  });
});
