"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
  type FormEvent,
} from "react";
import {
  Activity,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Download,
  FileVideo,
  FlipHorizontal2,
  Focus,
  Gauge,
  Loader2,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  RotateCcw,
  Repeat2,
  ShieldCheck,
  Sun,
  Upload,
  X,
} from "lucide-react";

import DashboardLayout from "../layout-dashboard";
import VividIqViewport from "@/components/vivid-iq/VividIqViewport";
import {
  VIVID_IQ_MAX_FILE_BYTES,
  createVividIqDisplayMap,
  detectVividIqPreviewAspectRatio,
  getVividIqFramePixels,
  getVividIqIdentification,
  getVividIqPreviewJpeg,
  parseVividIqDicom,
  type VividIqStudy,
  type VividIqIdentification,
} from "@/lib/vivid-iq-dicom.mjs";
import {
  buildVividIqGrayscaleLut,
  resolveVividIqPlayback,
  vividIqCaptureLines,
} from "@/lib/vivid-iq-player";

const PLAYBACK_SPEEDS = [0.25, 0.5, 1, 2] as const;
const MAX_LOCAL_FILES = 100;

type LocalCineFile = {
  id: number;
  file: File;
  status: "pending" | "loading" | "ready" | "error";
};

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1).replace(".", ",")} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

function formatSeconds(seconds: number) {
  return `${seconds.toFixed(2).replace(".", ",")} s`;
}

function clampFrame(study: VividIqStudy, frameIndex: number) {
  return Math.max(0, Math.min(study.frameCount - 1, frameIndex));
}

function formatFrameDimensions(study: VividIqStudy) {
  return study.frameDimensions
    .map(({ width, height }) => `${width} x ${height}`)
    .join(" → ");
}

function displayGeometryLabel(source: VividIqStudy["displayAspectRatioSource"]) {
  if (source === "ultrasound-region") {
    return "Proporção da região 2D do equipamento; orientação estimada";
  }
  if (source === "preview-image") {
    return "Proporção e orientação estimadas pela prévia local";
  }
  if (source === "estimated-sector") {
    return "orientacao setorial estimada";
  }
  return "orientacao nativa dos pixels";
}

function readableError(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Nao foi possivel abrir este arquivo. Confirme se ele e o DICOM original exportado pelo Vivid iq.";
}

export default function VisualizadorVividIqPage() {
  const [localFiles, setLocalFiles] = useState<LocalCineFile[]>([]);
  const [activeFileId, setActiveFileId] = useState<number | null>(null);
  const [collectionError, setCollectionError] = useState("");
  const [study, setStudy] = useState<VividIqStudy | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [brightness, setBrightness] = useState(0);
  const [contrast, setContrast] = useState(1);
  const [lateralFlip, setLateralFlip] = useState(true);
  const [previewAspectRatio, setPreviewAspectRatio] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [identification, setIdentification] = useState<VividIqIdentification | null>(null);
  const [loopPlayback, setLoopPlayback] = useState(false);
  const [segmentStart, setSegmentStart] = useState(0);
  const [segmentEnd, setSegmentEnd] = useState<number | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isFocusMode, setIsFocusMode] = useState(false);
  const [viewNotice, setViewNotice] = useState("");
  const [frameTarget, setFrameTarget] = useState("");
  const [frameTargetError, setFrameTargetError] = useState("");

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const playerRef = useRef<HTMLElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const addFilesInputRef = useRef<HTMLInputElement | null>(null);
  const nextFileIdRef = useRef(0);
  const activeReaderRef = useRef<FileReader | null>(null);
  const frameIndexRef = useRef(0);
  const animationFrameRef = useRef<number | null>(null);
  const loadRequestRef = useRef(0);
  const imageDataRef = useRef<{
    width: number;
    height: number;
    imageData: ImageData;
  } | null>(null);
  const displayMapRef = useRef<Map<string, Int32Array>>(new Map());
  const grayscaleLut = useMemo(() => buildVividIqGrayscaleLut(brightness, contrast), [brightness, contrast]);
  const rangeEnd = segmentEnd ?? Math.max(0, (study?.frameCount ?? 1) - 1);
  const isExpanded = isFullscreen || isFocusMode;
  const activeFileIndex = localFiles.findIndex(({ id }) => id === activeFileId);
  const activeFile = localFiles[activeFileIndex];

  const displayGeometry = useMemo(() => {
    if (!study) {
      return null;
    }
    const aspectRatio = previewAspectRatio || study.displayAspectRatio;
    const equipmentHeight = study.displayAspectRatioSource === "ultrasound-region"
      ? study.displayHeight
      : 1;
    let height = Math.min(768, Math.max(1, study.maxFrameWidth, equipmentHeight));
    let width = Math.max(1, Math.round(height * aspectRatio));
    if (width > 768) {
      const scale = 768 / width;
      width = 768;
      height = Math.max(1, Math.round(height * scale));
    }
    return {
      aspectRatio,
      width,
      height,
      source: previewAspectRatio
        ? "preview-image" as const
        : study.displayAspectRatioSource,
    };
  }, [previewAspectRatio, study]);

  const goToFrame = useCallback((nextIndex: number) => {
    if (!study) {
      return;
    }
    const clamped = clampFrame(study, nextIndex);
    frameIndexRef.current = clamped;
    setFrameIndex(clamped);
  }, [study]);

  const stopPlayback = useCallback(() => {
    setIsPlaying(false);
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
  }, []);

  const resetCurrentStudy = useCallback(() => {
    loadRequestRef.current += 1;
    activeReaderRef.current?.abort();
    activeReaderRef.current = null;
    stopPlayback();
    setIsLoading(false);
    setStudy(null);
    setFrameIndex(0);
    frameIndexRef.current = 0;
    setBrightness(0);
    setContrast(1);
    setLateralFlip(true);
    setPreviewAspectRatio(null);
    setIdentification(null);
    setPlaybackSpeed(1);
    setLoopPlayback(false);
    setSegmentStart(0);
    setSegmentEnd(null);
    setIsFocusMode(false);
    setViewNotice("");
    setFrameTarget("");
    setFrameTargetError("");
    setErrorMessage("");
    imageDataRef.current = null;
    displayMapRef.current.clear();
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (addFilesInputRef.current) {
      addFilesInputRef.current.value = "";
    }
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (canvas && context) {
      context.clearRect(0, 0, canvas.width, canvas.height);
    }
  }, [stopPlayback]);

  const clearStudy = useCallback(() => {
    resetCurrentStudy();
    setLocalFiles([]);
    setActiveFileId(null);
    setCollectionError("");
  }, [resetCurrentStudy]);

  const loadFile = useCallback(async (entry: LocalCineFile) => {
    resetCurrentStudy();
    const requestId = loadRequestRef.current;
    const { file } = entry;
    setActiveFileId(entry.id);
    setCollectionError("");
    const setFileStatus = (status: LocalCineFile["status"]) => {
      setLocalFiles((current) => current.map((item) => item.id === entry.id
        ? { ...item, status }
        : item.status === "loading" ? { ...item, status: "pending" } : item));
    };

    if (file.size > VIVID_IQ_MAX_FILE_BYTES) {
      setFileStatus("error");
      setErrorMessage("O arquivo excede o limite local de 512 MB.");
      return;
    }

    setFileStatus("loading");
    setIsLoading(true);
    try {
      const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
        const reader = new FileReader();
        activeReaderRef.current = reader;
        reader.onload = () => reader.result instanceof ArrayBuffer
          ? resolve(reader.result)
          : reject(new Error("Não foi possível ler o arquivo local."));
        reader.onerror = () => reject(new Error("Não foi possível ler o arquivo. Verifique se a unidade continua conectada."));
        reader.onabort = () => reject(new DOMException("Leitura cancelada.", "AbortError"));
        reader.readAsArrayBuffer(file);
      });
      if (requestId !== loadRequestRef.current) {
        return;
      }
      const parsed = parseVividIqDicom(buffer, "arquivo local");
      if (requestId !== loadRequestRef.current) {
        return;
      }
      setStudy(parsed);
      setFileStatus("ready");
      setFrameIndex(0);
      frameIndexRef.current = 0;
    } catch (error) {
      if (requestId === loadRequestRef.current) {
        setFileStatus("error");
        setErrorMessage(readableError(error));
      }
    } finally {
      if (requestId === loadRequestRef.current) {
        activeReaderRef.current = null;
        setIsLoading(false);
      }
    }
  }, [resetCurrentStudy]);

  const selectFiles = (files: File[], append = false) => {
    if (!files.length) return;
    if (files.length + (append ? localFiles.length : 0) > MAX_LOCAL_FILES) {
      setCollectionError(`Selecione no máximo ${MAX_LOCAL_FILES} arquivos por vez. Nenhum arquivo desta seleção foi adicionado; a lista anterior foi mantida.`);
      return;
    }
    // Keep only File handles in the collection; decode just the active cine.
    // Names are local labels, never patient identity, sort keys or deduplication keys.
    const entries = files.map((file): LocalCineFile => ({ id: ++nextFileIdRef.current, file, status: "pending" }));
    setCollectionError("");
    setLocalFiles(append ? [...localFiles, ...entries] : entries);
    if (!append || activeFileId === null) void loadFile(entries[0]);
  };

  const cancelRead = () => {
    resetCurrentStudy();
    setLocalFiles((current) => current.map((item) => item.id === activeFileId ? { ...item, status: "pending" } : item));
  };

  const removeFile = (entry: LocalCineFile) => {
    const remaining = localFiles.filter(({ id }) => id !== entry.id);
    if (!remaining.length) {
      clearStudy();
      return;
    }
    setLocalFiles(remaining);
    setCollectionError("");
    if (entry.id === activeFileId) {
      void loadFile(remaining[Math.min(activeFileIndex, remaining.length - 1)]);
    }
  };

  const fileNavigation = localFiles.length > 1 && (
    <div className="flex min-w-0 flex-wrap items-center gap-2" role="group" aria-label="Navegação entre arquivos">
      <button type="button" disabled={activeFileIndex <= 0} onClick={() => void loadFile(localFiles[activeFileIndex - 1])} aria-label="Arquivo anterior" className="rounded-lg border border-ink-200 p-2 text-ink-700 hover:bg-ink-50 disabled:opacity-40"><ChevronLeft className="h-4 w-4" /></button>
      <span className="whitespace-nowrap text-xs font-semibold text-ink-600">Arquivo {activeFileIndex + 1} de {localFiles.length}</span>
      <button type="button" disabled={activeFileIndex >= localFiles.length - 1} onClick={() => void loadFile(localFiles[activeFileIndex + 1])} aria-label="Próximo arquivo" className="rounded-lg border border-ink-200 p-2 text-ink-700 hover:bg-ink-50 disabled:opacity-40"><ChevronRight className="h-4 w-4" /></button>
    </div>
  );

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    selectFiles(files);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    selectFiles(Array.from(event.dataTransfer.files ?? []));
  };

  useEffect(() => {
    setPreviewAspectRatio(null);
    if (!study || study.displayAspectRatioSource !== "estimated-sector") {
      return;
    }
    const previewJpeg = getVividIqPreviewJpeg(study);
    if (!previewJpeg || typeof createImageBitmap !== "function") {
      return;
    }

    let cancelled = false;
    let bitmap: ImageBitmap | null = null;
    const detectPreviewGeometry = async () => {
      try {
        const jpegCopy = new Uint8Array(previewJpeg.length);
        jpegCopy.set(previewJpeg);
        bitmap = await createImageBitmap(new Blob([jpegCopy.buffer], { type: "image/jpeg" }));
        if (cancelled) {
          return;
        }
        const previewCanvas = document.createElement("canvas");
        previewCanvas.width = bitmap.width;
        previewCanvas.height = bitmap.height;
        const previewContext = previewCanvas.getContext("2d", { willReadFrequently: true });
        if (!previewContext) {
          return;
        }
        previewContext.drawImage(bitmap, 0, 0);
        const previewPixels = previewContext.getImageData(
          0,
          0,
          bitmap.width,
          bitmap.height,
        );
        const detected = detectVividIqPreviewAspectRatio(
          previewPixels.data,
          bitmap.width,
          bitmap.height,
          4,
        );
        if (!cancelled && detected) {
          displayMapRef.current.clear();
          imageDataRef.current = null;
          setPreviewAspectRatio(detected);
        }
      } catch {
        // A geometria 1:1 prudente permanece ativa se a previa nao puder ser decodificada.
      } finally {
        bitmap?.close();
      }
    };
    void detectPreviewGeometry();
    return () => {
      cancelled = true;
      bitmap?.close();
    };
  }, [study]);

  const renderFrame = useCallback(() => {
    if (!study || !displayGeometry || !canvasRef.current) {
      return;
    }
    const canvas = canvasRef.current;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) {
      return;
    }

    if (
      canvas.width !== displayGeometry.width
      || canvas.height !== displayGeometry.height
    ) {
      canvas.width = displayGeometry.width;
      canvas.height = displayGeometry.height;
      imageDataRef.current = null;
      displayMapRef.current.clear();
    }
    if (
      !imageDataRef.current
      || imageDataRef.current.width !== displayGeometry.width
      || imageDataRef.current.height !== displayGeometry.height
    ) {
      imageDataRef.current = {
        width: displayGeometry.width,
        height: displayGeometry.height,
        imageData: context.createImageData(displayGeometry.width, displayGeometry.height),
      };
    }

    const frame = study.frames[frameIndex];
    const source = getVividIqFramePixels(study, frameIndex);
    const mapKey = [
      frame.width,
      frame.height,
      displayGeometry.width,
      displayGeometry.height,
      Number(study.scanConversion),
      Number(lateralFlip),
    ].join(":");
    let displayMap = displayMapRef.current.get(mapKey);
    if (!displayMap) {
      displayMap = createVividIqDisplayMap(
        frame.width,
        frame.height,
        displayGeometry.width,
        displayGeometry.height,
        study.scanConversion,
        lateralFlip,
      );
      displayMapRef.current.set(mapKey, displayMap);
    }
    const target = imageDataRef.current.imageData.data;
    const targetPixels = new Uint32Array(
      target.buffer,
      target.byteOffset,
      target.byteLength / Uint32Array.BYTES_PER_ELEMENT,
    );
    for (let pixelIndex = 0; pixelIndex < displayMap.length; pixelIndex += 1) {
      const sourceIndex = displayMap[pixelIndex];
      targetPixels[pixelIndex] = sourceIndex < 0 ? 0xff000000 : grayscaleLut[source[sourceIndex]];
    }
    context.putImageData(imageDataRef.current.imageData, 0, 0);
  }, [grayscaleLut, displayGeometry, frameIndex, lateralFlip, study]);

  useEffect(() => {
    renderFrame();
  }, [renderFrame]);

  useEffect(() => {
    if (!isPlaying || !study) {
      return;
    }

    const anchorIndex = frameIndexRef.current;
    const anchorWallClock = window.performance.now();

    const tick = (now: number) => {
      const elapsedSeconds = (now - anchorWallClock) / 1000;
      const next = resolveVividIqPlayback(study, anchorIndex, elapsedSeconds, playbackSpeed, segmentStart, rangeEnd, loopPlayback);
      if (next.frameIndex !== frameIndexRef.current) {
        frameIndexRef.current = next.frameIndex;
        setFrameIndex(next.frameIndex);
      }
      if (next.ended) {
        setIsPlaying(false);
        animationFrameRef.current = null;
        return;
      }

      animationFrameRef.current = window.requestAnimationFrame(tick);
    };

    animationFrameRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [isPlaying, playbackSpeed, study, segmentStart, rangeEnd, loopPlayback]);

  useEffect(() => () => {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
    }
    loadRequestRef.current += 1;
    activeReaderRef.current?.abort();
  }, []);

  useEffect(() => {
    const syncFullscreen = () => setIsFullscreen(Boolean(playerRef.current && document.fullscreenElement === playerRef.current));
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  useEffect(() => {
    const pauseWhenHidden = () => {
      if (document.visibilityState === "hidden") {
        stopPlayback();
      }
    };
    document.addEventListener("visibilitychange", pauseWhenHidden);
    return () => document.removeEventListener("visibilitychange", pauseWhenHidden);
  }, [stopPlayback]);

  useEffect(() => {
    const player = playerRef.current;
    if (!isFocusMode || !player) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const background: Array<{ element: HTMLElement; inert: boolean }> = [];
    let branch: HTMLElement = player;
    while (branch.parentElement) {
      for (const sibling of Array.from(branch.parentElement.children)) {
        if (sibling !== branch && sibling instanceof HTMLElement) {
          background.push({ element: sibling, inert: sibling.inert });
          sibling.inert = true;
        }
      }
      branch = branch.parentElement;
      if (branch === document.body) break;
    }
    document.body.style.overflow = "hidden";
    player.focus({ preventScroll: true });
    const handleFocusKeys = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !document.fullscreenElement) {
        event.preventDefault();
        setIsFocusMode(false);
        setViewNotice("");
        return;
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(player.querySelectorAll<HTMLElement>(
        "button, input, select, summary, [tabindex='0']",
      )).filter((element) => !element.matches(":disabled") && !element.closest("[hidden]") && (
        !element.closest("details:not([open])") || element.tagName === "SUMMARY"
      ));
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first || !last) {
        event.preventDefault();
        player.focus();
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === player)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !player.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleFocusKeys);
    return () => {
      document.removeEventListener("keydown", handleFocusKeys);
      document.body.style.overflow = previousOverflow;
      background.forEach(({ element, inert }) => { element.inert = inert; });
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [isFocusMode]);

  const currentSeconds = useMemo(() => {
    if (!study) {
      return 0;
    }
    return Math.max(
      0,
      study.frames[frameIndex].timestampSeconds - study.firstTimestamp,
    );
  }, [frameIndex, study]);

  const togglePlayback = () => {
    if (!study) {
      return;
    }
    if (isPlaying) {
      stopPlayback();
      return;
    }
    if (frameIndexRef.current >= rangeEnd || frameIndexRef.current < segmentStart) {
      goToFrame(segmentStart);
    }
    setIsPlaying(true);
  };

  const stepFrame = (delta: number) => {
    stopPlayback();
    goToFrame(frameIndexRef.current + delta);
  };

  const resetImageAdjustments = () => {
    setBrightness(0);
    setContrast(1);
    setLateralFlip(true);
  };

  const requestFullscreen = async () => {
    const requestId = loadRequestRef.current;
    if (!playerRef.current) return;
    try {
      if (document.fullscreenElement === playerRef.current) {
        await document.exitFullscreen();
      } else if (playerRef.current?.requestFullscreen) {
        await playerRef.current.requestFullscreen();
      } else {
        throw new Error("Tela cheia indisponível.");
      }
    } catch {
      if (requestId !== loadRequestRef.current) return;
      setIdentification(null);
      setIsFocusMode(true);
      setViewNotice("O navegador não disponibilizou tela cheia. O modo foco está ativo nesta janela.");
    }
  };

  const handlePlayerKey = (event: KeyboardEvent<HTMLElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("input, select, textarea, [contenteditable='true'], summary")) return;
    if (event.key === " " && target?.closest("button, a, [role='button']")) return;
    if (event.key === " " || event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key.toLowerCase() === "f") {
      event.preventDefault();
      if (event.key === " ") {
        if (!event.repeat) togglePlayback();
      } else if (event.key === "ArrowLeft") stepFrame(-1);
      else if (event.key === "ArrowRight") stepFrame(1);
      else if (!event.repeat) void requestFullscreen();
    }
  };

  const jumpToFrame = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = Number(frameTarget);
    if (!study || !frameTarget.trim() || !Number.isInteger(value) || value < 1 || value > study.frameCount) {
      setFrameTargetError(`Informe um quadro inteiro entre 1 e ${study?.frameCount ?? 1}.`);
      return;
    }
    stopPlayback();
    goToFrame(value - 1);
    setFrameTargetError("");
  };

  const toggleIdentification = () => {
    if (identification) {
      setIdentification(null);
    } else if (study) {
      try {
        setIdentification(getVividIqIdentification(study));
      } catch {
        setErrorMessage("Não foi possível ler a identificação deste exame.");
      }
    }
  };

  const downloadCurrentFrame = () => {
    const canvas = canvasRef.current;
    if (!canvas || !study) {
      return;
    }
    stopPlayback();
    const requestId = loadRequestRef.current;
    const footer = vividIqCaptureLines({ frameIndex, frameCount: study.frameCount, currentSeconds, brightness, contrast, lateralInverted: !lateralFlip });
    const captureCanvas = document.createElement("canvas");
    captureCanvas.width = Math.max(480, canvas.width);
    captureCanvas.height = canvas.height + 96;
    const captureContext = captureCanvas.getContext("2d", { alpha: false });
    if (!captureContext) {
      setErrorMessage("Nao foi possivel preparar a captura PNG deste quadro.");
      return;
    }
    captureContext.imageSmoothingEnabled = true;
    captureContext.imageSmoothingQuality = "high";
    captureContext.fillStyle = "#000000";
    captureContext.fillRect(0, 0, captureCanvas.width, captureCanvas.height);
    captureContext.drawImage(canvas, (captureCanvas.width - canvas.width) / 2, 0);
    captureContext.fillStyle = "#ffffff";
    captureContext.font = "12px sans-serif";
    footer.forEach((line, index) => captureContext.fillText(line, 12, canvas.height + 24 + index * 22, captureCanvas.width - 24));

    captureCanvas.toBlob((blob) => {
      if (requestId !== loadRequestRef.current) return;
      if (!blob) {
        setErrorMessage("Nao foi possivel gerar a captura PNG deste quadro.");
        return;
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `vivid-iq-quadro-${String(frameIndex + 1).padStart(4, "0")}.png`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    }, "image/png");
  };

  return (
    <DashboardLayout>
      <div className="fc-page space-y-4">
        <header className={`rounded-3xl bg-gradient-to-br from-ink-900 via-ink-700 to-vital-900 px-6 text-white shadow-fort-card sm:px-8 ${study ? "py-4" : "py-7"}`}>
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div className="max-w-3xl">
              {!study && <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-vital-100">
                <Activity className="h-4 w-4" /> Imagem cardiologica
              </div>}
              <h1 className={`font-bold ${study ? "text-xl" : "text-2xl sm:text-3xl"}`}>Visualizador Vivid IQ</h1>
              {!study && <p className="mt-3 max-w-2xl text-sm leading-6 text-white/75">
                Abra um ou vários arquivos DICOM originais, mesmo sem extensão, e navegue pelos cines salvos pelo equipamento GE.
              </p>}
            </div>
            <div className="flex items-center gap-2 rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white/90">
              <ShieldCheck className="h-5 w-5 text-vital-100" />
              Processamento somente neste navegador
            </div>
          </div>
        </header>

        {!study && <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex gap-3 rounded-2xl border border-vital-200 bg-vital-50 p-4 text-sm leading-6 text-vital-900">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-vital-600" />
            <div>
              <p className="font-semibold">O exame nao e enviado ao servidor</p>
              <p className="mt-1 text-vital-700">
                O arquivo permanece em memoria local e e descartado ao sair ou limpar esta tela.
              </p>
            </div>
          </div>
          <div className="flex gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div>
              <p className="font-semibold">Uso experimental: nao realize medicoes</p>
              <p className="mt-1 text-amber-800">
                Escala, orientacao espacial e traces privados da GE ainda nao foram homologados.
              </p>
            </div>
          </div>
        </div>}

        {localFiles.length > 0 && (
          <section aria-label="Arquivos selecionados" className="min-w-0 rounded-2xl border border-ink-100 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-ink-900">Arquivos selecionados · {localFiles.length}</h2>
                <p className="mt-1 text-xs text-ink-500">Só o arquivo ativo é carregado. A ordem é a da seleção, não a data do exame.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => addFilesInputRef.current?.click()} className="inline-flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50"><Upload className="h-4 w-4" /> Adicionar arquivos</button>
                <button type="button" onClick={clearStudy} className="inline-flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50"><X className="h-4 w-4" /> Limpar exame</button>
              </div>
            </div>
            <p className="mt-3 text-xs text-amber-900">Lista local: não confirma que os arquivos pertencem ao mesmo paciente ou exame. A identificação é consultada separadamente em cada arquivo.</p>
            <div onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); event.stopPropagation(); selectFiles(Array.from(event.dataTransfer.files ?? []), true); }}>
              <ol aria-label="Lista de arquivos locais" className="mt-3 grid max-h-40 gap-2 overflow-y-auto rounded-xl sm:grid-cols-2 xl:grid-cols-3">
                {localFiles.map((entry, index) => (
                  <li key={entry.id} className={`flex min-w-0 items-center rounded-xl border ${entry.id === activeFileId ? "border-vital-500 bg-vital-50" : "border-ink-100 bg-ink-50"}`}>
                    <button type="button" onClick={() => void loadFile(entry)} aria-label={`Abrir arquivo ${index + 1}: ${entry.file.name}`} aria-current={entry.id === activeFileId ? "true" : undefined} className="min-w-0 flex-1 rounded-xl p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-vital-500">
                      <span className="block truncate text-xs font-semibold text-ink-900" title={entry.file.name}>{index + 1}. {entry.file.name}</span>
                      <span className="mt-1 block text-xs text-ink-500">{formatBytes(entry.file.size)} · {entry.status === "error" ? "Não foi possível abrir" : entry.status === "loading" ? "Lendo…" : entry.status === "ready" ? entry.id === activeFileId ? "Aberto" : "Já aberto" : "Não aberto"}</span>
                    </button>
                    <button type="button" onClick={() => removeFile(entry)} aria-label={`Remover arquivo ${index + 1}: ${entry.file.name}`} className="mr-1 rounded-lg p-2 text-ink-500 hover:bg-ink-100"><X className="h-4 w-4" /></button>
                  </li>
                ))}
              </ol>
            </div>
            {!study && <div className="mt-3">{fileNavigation}</div>}
            <input ref={addFilesInputRef} type="file" multiple aria-label="Adicionar arquivos DICOM" className="sr-only" onChange={(event) => { const files = Array.from(event.target.files ?? []); event.target.value = ""; selectFiles(files, true); }} />
          </section>
        )}
        {collectionError && <p role="alert" className="rounded-2xl border border-cordis-200 bg-cordis-50 p-4 text-sm text-cordis-900">{collectionError}</p>}

        {!study && (
          <section className="rounded-3xl border border-ink-100 bg-white p-5 shadow-fort-card sm:p-7">
            <div
              onDragEnter={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                event.preventDefault();
                if (event.currentTarget === event.target) {
                  setIsDragging(false);
                }
              }}
              onDrop={handleDrop}
              className={`flex min-h-72 flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
                isDragging
                  ? "border-vital-500 bg-vital-50"
                  : "border-ink-200 bg-ink-50 hover:border-vital-500 hover:bg-vital-50/60"
              }`}
            >
              {isLoading ? (
                <div role="status" aria-live="polite" className="flex flex-col items-center">
                  <Loader2 className="h-11 w-11 animate-spin text-vital-600" />
                  <h2 className="mt-5 text-lg font-semibold text-ink-900">Lendo o cine localmente...</h2>
                  <p className="mt-2 max-w-lg text-sm leading-6 text-ink-500">
                    Arquivos grandes podem levar alguns segundos. Nenhum dado esta sendo enviado.
                  </p>
                  <button type="button" onClick={cancelRead} className="mt-5 rounded-xl border border-ink-200 bg-white px-4 py-2 text-sm font-semibold text-ink-700">
                    Cancelar leitura
                  </button>
                </div>
              ) : (
                <>
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-vital-600 shadow-sm">
                    <Upload className="h-7 w-7" />
                  </div>
                  <h2 className="mt-5 text-lg font-semibold text-ink-900">Selecione ou arraste os arquivos do Vivid iq</h2>
                  <p id="vivid-iq-file-help" className="mt-2 max-w-lg text-sm leading-6 text-ink-500">
                    Com ou sem extensão. Até 100 arquivos, 512 MB por arquivo. Uma nova seleção substitui a lista atual.
                  </p>
                  {activeFile && <button type="button" onClick={() => void loadFile(activeFile)} className="mt-4 rounded-xl border border-vital-200 bg-vital-50 px-4 py-2 text-sm font-semibold text-vital-900">Tentar abrir novamente</button>}
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="mt-6 inline-flex items-center gap-2 rounded-xl bg-cordis-600 px-5 py-3 text-sm font-semibold text-white shadow-fort-soft transition hover:bg-cordis-700"
                  >
                    <FileVideo className="h-4 w-4" /> Escolher arquivo
                  </button>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileInput}
                aria-label="Selecionar arquivo DICOM"
                aria-describedby={isLoading ? undefined : "vivid-iq-file-help"}
                className="sr-only"
              />
            </div>
          </section>
        )}

        {errorMessage && !study && (
          <div role="alert" className="flex items-start justify-between gap-4 rounded-2xl border border-cordis-200 bg-cordis-50 p-4 text-sm text-cordis-900">
            <div className="flex gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <p>{errorMessage}</p>
            </div>
            <button
              type="button"
              onClick={() => setErrorMessage("")}
              aria-label="Fechar mensagem"
              className="rounded-lg p-1 hover:bg-cordis-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {study && displayGeometry && (
          <div className="flex flex-col gap-4">
            <section
              ref={playerRef}
              tabIndex={0}
              role={isFocusMode ? "dialog" : undefined}
              aria-modal={isFocusMode ? true : undefined}
              aria-label="Player do cine Vivid IQ"
              onKeyDown={handlePlayerKey}
              className={`bg-white outline-none focus-visible:ring-2 focus-visible:ring-vital-500 ${isFocusMode ? "fixed inset-0 z-[100] flex h-dvh w-full flex-col overflow-y-auto overscroll-contain" : isFullscreen ? "flex h-dvh w-full flex-col overflow-y-auto overscroll-contain" : "overflow-hidden rounded-3xl border border-ink-100 shadow-fort-card"}`}
            >
              <div className="flex shrink-0 items-center gap-2 bg-amber-50 px-4 py-2 text-xs text-amber-900">
                <AlertTriangle className="h-4 w-4 shrink-0" /> Uso experimental — imagem não calibrada. Não realize medições.
              </div>
              <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-3 py-2 sm:px-4">
                <div className="min-w-0 basis-full space-y-1 sm:basis-64 sm:flex-1">
                  <p className="truncate text-xs font-semibold text-ink-900" title={activeFile?.file.name}>{activeFile?.file.name}</p>
                  <p className="text-xs font-semibold text-ink-600">{isPlaying ? "Em reprodução" : "Pausado"} · {study.cineType}</p>
                  {fileNavigation}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" aria-pressed={isFocusMode} onClick={() => { setIdentification(null); setViewNotice(""); setIsFocusMode((current) => !current); }} className="inline-flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50">
                    <Focus className="h-4 w-4" /> {isFocusMode ? "Sair do modo foco" : "Modo foco"}
                  </button>
                  <button type="button" onClick={() => void requestFullscreen()} className="inline-flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50">
                    {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />} {isFullscreen ? "Sair da tela cheia" : "Tela cheia"}
                  </button>
                  <button type="button" onClick={downloadCurrentFrame} className="inline-flex items-center gap-2 rounded-lg bg-ink-900 px-3 py-2 text-xs font-semibold text-white hover:bg-ink-700">
                    <Download className="h-4 w-4" /> Baixar quadro PNG
                  </button>
                </div>
              </div>
              {viewNotice && <p role="status" className="shrink-0 bg-vital-50 px-4 py-2 text-xs text-vital-900">{viewNotice}</p>}
              {errorMessage && <div role="alert" className="flex shrink-0 items-center justify-between gap-2 bg-cordis-50 px-4 py-2 text-sm text-cordis-900"><p>{errorMessage}</p><button type="button" onClick={() => setErrorMessage("")} aria-label="Fechar mensagem" className="rounded-lg p-2"><X className="h-4 w-4" /></button></div>}
              {study.warnings.length > 0 && <div className="max-h-24 shrink-0 overflow-y-auto bg-amber-50 px-4 py-2 text-xs text-amber-900">{study.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
              <VividIqViewport aspectRatio={displayGeometry.aspectRatio} expanded={isExpanded}>
                <canvas ref={canvasRef} aria-label={`Cine do Vivid iq, quadro ${frameIndex + 1} de ${study.frameCount}`} className="block h-full w-full bg-black" />
              </VividIqViewport>

              <div className={`shrink-0 space-y-3 p-3 sm:p-4 ${isExpanded ? "max-h-[36dvh] overflow-y-auto" : ""}`}>
                <div>
                  <div className="mb-2 flex items-center justify-between gap-4 text-xs font-medium text-ink-500">
                    <span>{formatSeconds(currentSeconds)}</span>
                    <span>Quadro {frameIndex + 1} de {study.frameCount}</span>
                    <span>{formatSeconds(study.durationSeconds)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={study.frameCount - 1}
                    value={frameIndex}
                    onChange={(event) => {
                      stopPlayback();
                      goToFrame(Number(event.target.value));
                    }}
                    aria-label="Posicao no cine"
                    aria-valuetext={`Quadro ${frameIndex + 1} de ${study.frameCount}, ${formatSeconds(currentSeconds)}`}
                    className="h-6 w-full cursor-pointer accent-cordis-600"
                  />
                  <div role="img" aria-label={`Trecho selecionado: quadros ${segmentStart + 1} a ${rangeEnd + 1}`} className="relative mt-1 h-1 rounded-full bg-ink-100">
                    <span className="absolute h-1 rounded-full bg-vital-500" style={{ left: `${Math.min(99.7, segmentStart / Math.max(1, study.frameCount - 1) * 100)}%`, width: `${Math.max(0.3, (rangeEnd - segmentStart) / Math.max(1, study.frameCount - 1) * 100)}%` }} />
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      stopPlayback();
                      goToFrame(0);
                    }}
                    aria-label="Primeiro quadro"
                    disabled={frameIndex === 0 && !isPlaying}
                    className="rounded-xl border border-ink-200 p-2.5 text-ink-700 hover:bg-ink-50 disabled:opacity-40"
                  >
                    <ChevronsLeft className="h-5 w-5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => stepFrame(-1)}
                    aria-label="Quadro anterior"
                    disabled={frameIndex === 0 && !isPlaying}
                    className="rounded-xl border border-ink-200 p-2.5 text-ink-700 hover:bg-ink-50 disabled:opacity-40"
                  >
                    <ChevronLeft className="h-5 w-5" />
                  </button>
                  <button
                    type="button"
                    onClick={togglePlayback}
                    className="inline-flex min-w-32 items-center justify-center gap-2 rounded-xl bg-cordis-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-cordis-700"
                  >
                    {isPlaying ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
                    {isPlaying ? "Pausar" : "Reproduzir"}
                  </button>
                  <button
                    type="button"
                    onClick={() => stepFrame(1)}
                    aria-label="Proximo quadro"
                    disabled={frameIndex === study.frameCount - 1 && !isPlaying}
                    className="rounded-xl border border-ink-200 p-2.5 text-ink-700 hover:bg-ink-50 disabled:opacity-40"
                  >
                    <ChevronRight className="h-5 w-5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      stopPlayback();
                      goToFrame(study.frameCount - 1);
                    }}
                    aria-label="Ultimo quadro"
                    disabled={frameIndex === study.frameCount - 1 && !isPlaying}
                    className="rounded-xl border border-ink-200 p-2.5 text-ink-700 hover:bg-ink-50 disabled:opacity-40"
                  >
                    <ChevronsRight className="h-5 w-5" />
                  </button>
                  <label className="ml-0 flex items-center gap-2 rounded-xl border border-ink-200 px-3 py-2 text-sm text-ink-700 sm:ml-2">
                    <Gauge className="h-4 w-4" />
                    <span className="sr-only">Velocidade</span>
                    <select
                      value={playbackSpeed}
                      onChange={(event) => setPlaybackSpeed(Number(event.target.value))}
                      className="bg-transparent font-semibold outline-none"
                    >
                      {PLAYBACK_SPEEDS.map((speed) => (
                        <option key={speed} value={speed}>{speed}x</option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-ink-500">A {segmentStart + 1} → B {rangeEnd + 1} · {(rangeEnd - segmentStart + 1).toLocaleString("pt-BR")} quadros{loopPlayback ? " · Repetição ativa" : ""}</p>
                  <form aria-label="Navegação por quadro" noValidate onSubmit={jumpToFrame} className="flex flex-wrap items-center gap-2">
                    <label htmlFor="vivid-frame-target" className="text-xs font-medium text-ink-600">Ir para o quadro</label>
                    <input id="vivid-frame-target" type="number" inputMode="numeric" min={1} max={study.frameCount} step={1} value={frameTarget} placeholder={String(frameIndex + 1)} aria-invalid={Boolean(frameTargetError)} aria-describedby={frameTargetError ? "vivid-frame-error" : undefined} onChange={(event) => { setFrameTarget(event.target.value); setFrameTargetError(""); }} className="w-24 rounded-lg border border-ink-200 px-2 py-2 text-sm text-ink-900" />
                    <button type="submit" className="rounded-lg border border-ink-200 px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50">Ir</button>
                    {frameTargetError && <p id="vivid-frame-error" role="alert" className="w-full text-xs text-cordis-700">{frameTargetError}</p>}
                  </form>
                </div>

                <details className="rounded-xl border border-ink-100">
                  <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-ink-700">Trecho e ajustes</summary>
                  <div className="space-y-4 p-3 pt-1">
                  <div className="space-y-3 rounded-xl bg-ink-50 p-3 text-sm text-ink-700">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p>Trecho A–B: quadros <strong>{segmentStart + 1}–{rangeEnd + 1}</strong></p>
                    <label className="inline-flex cursor-pointer items-center gap-2 font-semibold">
                      <input type="checkbox" checked={loopPlayback} onChange={(event) => setLoopPlayback(event.target.checked)} className="accent-vital-600" />
                      <Repeat2 className="h-4 w-4" /> Repetir trecho
                    </label>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => { stopPlayback(); setSegmentStart(frameIndex); if (frameIndex > rangeEnd) setSegmentEnd(frameIndex); }} className="rounded-lg border border-ink-200 bg-white px-3 py-2 hover:bg-ink-100">Marcar início (A)</button>
                    <button type="button" onClick={() => { stopPlayback(); setSegmentEnd(frameIndex); if (frameIndex < segmentStart) setSegmentStart(frameIndex); }} className="rounded-lg border border-ink-200 bg-white px-3 py-2 hover:bg-ink-100">Marcar fim (B)</button>
                    <button type="button" onClick={() => { stopPlayback(); goToFrame(segmentStart); }} className="rounded-lg border border-ink-200 bg-white px-3 py-2 hover:bg-ink-100">Ir para A</button>
                    <button type="button" onClick={() => { stopPlayback(); goToFrame(rangeEnd); }} className="rounded-lg border border-ink-200 bg-white px-3 py-2 hover:bg-ink-100">Ir para B</button>
                    <button type="button" onClick={() => { stopPlayback(); setSegmentStart(0); setSegmentEnd(null); }} className="rounded-lg border border-ink-200 bg-white px-3 py-2 hover:bg-ink-100">Usar cine inteiro</button>
                  </div>
                  <p className="text-xs text-ink-500">Posicione o quadro e marque o início e o fim. Com o player em foco: Espaço reproduz/pausa, ←/→ navega e F alterna tela cheia.</p>
                </div>

                <div className="grid gap-4 border-t border-ink-100 pt-5 lg:grid-cols-[1fr_1fr_auto_auto] lg:items-end">
                  <label className="block">
                    <span className="mb-2 flex items-center justify-between text-xs font-semibold text-ink-600">
                      <span className="flex items-center gap-2"><Sun className="h-4 w-4" /> Brilho</span>
                      <span>{brightness > 0 ? "+" : ""}{brightness}</span>
                    </span>
                    <input
                      type="range"
                      min={-100}
                      max={100}
                      value={brightness}
                      onChange={(event) => setBrightness(Number(event.target.value))}
                      className="h-2 w-full accent-vital-600"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-2 flex items-center justify-between text-xs font-semibold text-ink-600">
                      <span className="flex items-center gap-2"><Activity className="h-4 w-4" /> Contraste</span>
                      <span>{contrast.toFixed(2).replace(".", ",")}x</span>
                    </span>
                    <input
                      type="range"
                      min={0.5}
                      max={2}
                      step={0.05}
                      value={contrast}
                      onChange={(event) => setContrast(Number(event.target.value))}
                      className="h-2 w-full accent-vital-600"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => setLateralFlip((current) => !current)}
                    aria-pressed={!lateralFlip}
                    className={`inline-flex items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-semibold ${!lateralFlip ? "border-vital-500 bg-vital-50 text-vital-800" : "border-ink-200 text-ink-700 hover:bg-ink-50"}`}
                  >
                    <FlipHorizontal2 className="h-4 w-4" /> {lateralFlip ? "Inverter lado" : "Lado invertido"}
                  </button>
                  <button
                    type="button"
                    onClick={resetImageAdjustments}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-ink-200 px-4 py-2.5 text-sm font-semibold text-ink-700 hover:bg-ink-50"
                  >
                    <RotateCcw className="h-4 w-4" /> Restaurar imagem
                  </button>
                </div>
                  </div>
                </details>

                {!isExpanded && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-100 pt-5">
                  <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => fileInputRef.current?.click()} className="inline-flex items-center gap-2 rounded-xl border border-ink-200 px-4 py-2.5 text-sm font-semibold text-ink-700 hover:bg-ink-50">
                    <FileVideo className="h-4 w-4" /> Substituir arquivos
                  </button>
                  </div>
                  <p className="text-xs text-ink-500">Espaço: reproduzir · ←/→: quadros · F: tela cheia{isFocusMode ? " · Esc: sair do foco" : ""}</p>
                </div>}
                {!isExpanded && <p className="text-xs text-ink-500">O PNG inclui o quadro inteiro, tempo e ajustes de imagem. A ampliação é apenas para visualização.</p>}
              </div>
            </section>

            <section className="rounded-2xl border border-ink-100 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink-900">Identificação do exame</h2>
                  <p className="mt-1 text-xs text-ink-500">Leitura opcional dos campos do DICOM, somente nesta sessão. Não incluída no PNG.</p>
                </div>
                <button type="button" onClick={toggleIdentification} aria-expanded={Boolean(identification)} aria-controls="vivid-identification" className="rounded-xl border border-ink-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:bg-ink-50">
                  {identification ? "Ocultar identificação" : "Mostrar identificação do exame"}
                </button>
              </div>
              {identification && (
                <div id="vivid-identification" className="mt-4 space-y-3 border-t border-ink-100 pt-4">
                  <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
                    <div><dt className="text-ink-500">Paciente</dt><dd className="break-words font-semibold text-ink-900">{identification.patientName || "Não informado"}</dd></div>
                    <div><dt className="text-ink-500">Data do estudo</dt><dd className="font-semibold text-ink-900">{identification.studyDate || "Não informada"}{identification.studyTime ? ` · ${identification.studyTime}` : ""}</dd></div>
                    <div><dt className="text-ink-500">Aquisição</dt><dd className="font-semibold text-ink-900">{identification.acquisitionDateTime || "Não informada"}</dd></div>
                    <div><dt className="text-ink-500">Data do conteúdo</dt><dd className="font-semibold text-ink-900">{identification.contentDate || "Não informada"}{identification.contentTime ? ` · ${identification.contentTime}` : ""}</dd></div>
                    <div><dt className="text-ink-500">Fuso do estudo</dt><dd className="font-semibold text-ink-900">{identification.timezoneOffset || "Não informado no arquivo"}</dd></div>
                  </dl>
                  <p className="text-xs text-ink-500">Datas e nome registrados pelo equipamento; nenhum vínculo automático com pacientes do sistema.</p>
                  {identification.patientNameRaw && (
                    <details className="text-xs text-ink-600"><summary className="cursor-pointer">Nome original no DICOM</summary><p className="mt-2 break-all font-mono">{identification.patientNameRaw}</p></details>
                  )}
                  {identification.warnings.map((warning) => <p key={warning} className="text-xs text-amber-800">{warning}</p>)}
                </div>
              )}
            </section>
            <details className="rounded-2xl border border-ink-100 bg-white p-4">
              <summary className="cursor-pointer text-sm font-semibold text-ink-700">Informações técnicas do exame</summary>
              <section className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-sm sm:col-span-2 xl:col-span-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Equipamento</p>
                <p className="mt-2 text-sm font-semibold text-ink-900">{study.equipment}</p>
                <p className="mt-1 text-xs text-ink-500">{study.cineType}</p>
              </div>
              <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Cine</p>
                <p className="mt-2 text-lg font-bold text-ink-900">{study.frameCount.toLocaleString("pt-BR")} quadros</p>
                <p className="mt-1 text-xs text-ink-500">
                  {formatFrameDimensions(study)} px brutos
                </p>
                <p className="mt-1 text-xs text-vital-700">
                  {displayGeometryLabel(displayGeometry.source)}
                </p>
              </div>
              <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Duracao</p>
                <p className="mt-2 text-lg font-bold text-ink-900">{formatSeconds(study.durationSeconds)}</p>
                <p className="mt-1 text-xs text-ink-500">linha temporal do equipamento</p>
              </div>
              <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Taxa media</p>
                <p className="mt-2 text-lg font-bold text-ink-900">{study.frameRate.toFixed(1).replace(".", ",")} fps</p>
                <p className="mt-1 text-xs text-ink-500">estimada pelos timestamps</p>
              </div>
              <div className="rounded-2xl border border-ink-100 bg-white p-4 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">Arquivo local</p>
                <p className="mt-2 text-lg font-bold text-ink-900">{formatBytes(study.fileSize)}</p>
                <p className="mt-1 text-xs text-ink-500">sem copia no servidor</p>
              </div>
            </section>

            </details>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileInput}
              className="sr-only"
              aria-label="Selecionar outro arquivo DICOM"
            />
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
