import type { VividIqStudy } from "./vivid-iq-dicom.mjs";

const DEFAULT_FRAME_SECONDS = 1 / 30;
const TIMESTAMP_TOLERANCE_SECONDS = 1e-9;

export function buildVividIqGrayscaleLut(brightness: number, contrast: number): Uint32Array {
  const safeBrightness = Number.isFinite(brightness) ? brightness : 0;
  const safeContrast = Number.isFinite(contrast) ? contrast : 1;
  const colors = new Uint32Array(256);
  for (let source = 0; source < colors.length; source += 1) {
    const gray = Math.round(Math.max(0, Math.min(
      255,
      (source - 128) * safeContrast + 128 + safeBrightness,
    )));
    colors[source] = (0xff000000 | (gray << 16) | (gray << 8) | gray) >>> 0;
  }
  return colors;
}

export function resolveVividIqPlayback(
  study: Pick<VividIqStudy, "frames" | "frameCount">,
  anchorFrame: number,
  elapsedSeconds: number,
  speed: number,
  startFrame: number,
  endFrame: number,
  loop: boolean,
): { frameIndex: number; ended: boolean } {
  const declaredCount = Number.isFinite(study.frameCount)
    ? Math.max(0, Math.trunc(study.frameCount))
    : study.frames.length;
  const count = Math.min(declaredCount, study.frames.length);
  if (count === 0) {
    return { frameIndex: 0, ended: true };
  }

  const clampIndex = (index: number, fallback: number) => Math.max(0, Math.min(
    count - 1,
    Number.isFinite(index) ? Math.trunc(index) : fallback,
  ));
  const firstBound = clampIndex(startFrame, 0);
  const lastBound = clampIndex(endFrame, count - 1);
  const start = Math.min(firstBound, lastBound);
  const end = Math.max(firstBound, lastBound);
  const anchor = Math.max(start, Math.min(end, clampIndex(anchorFrame, start)));
  const timestamp = (index: number) => {
    const value = study.frames[index].timestampSeconds;
    return Number.isFinite(value) ? value : index * DEFAULT_FRAME_SECONDS;
  };
  const startTimestamp = timestamp(start);
  const segmentDuration = Math.max(0, timestamp(end) - startTimestamp);
  const elapsed = Number.isFinite(elapsedSeconds) ? Math.max(0, elapsedSeconds) : 0;
  const playbackSpeed = Number.isFinite(speed) && speed > 0 ? speed : 1;
  let targetOffset = Math.max(0, timestamp(anchor) - startTimestamp) + elapsed * playbackSpeed;

  if (loop) {
    const lastDelta = end > start ? timestamp(end) - timestamp(end - 1) : 0;
    const firstDelta = end > start ? timestamp(start + 1) - startTimestamp : 0;
    const lastFrameDuration = lastDelta > 0
      ? lastDelta
      : firstDelta > 0 ? firstDelta : DEFAULT_FRAME_SECONDS;
    const cycleDuration = segmentDuration + lastFrameDuration;
    targetOffset %= cycleDuration;
    if (cycleDuration - targetOffset <= TIMESTAMP_TOLERANCE_SECONDS) {
      targetOffset = 0;
    }
  } else if (targetOffset + TIMESTAMP_TOLERANCE_SECONDS >= segmentDuration) {
    return { frameIndex: end, ended: true };
  }

  let low = start;
  let high = end;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (timestamp(middle) - startTimestamp <= targetOffset + TIMESTAMP_TOLERANCE_SECONDS) {
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return { frameIndex: Math.max(start, Math.min(end, low - 1)), ended: false };
}

export function vividIqCaptureLines({
  frameIndex,
  frameCount,
  currentSeconds,
  brightness,
  contrast,
  lateralInverted,
}: {
  frameIndex: number;
  frameCount: number;
  currentSeconds: number;
  brightness: number;
  contrast: number;
  lateralInverted: boolean;
}): string[] {
  const seconds = currentSeconds.toFixed(2).replace(".", ",");
  const contrastLabel = contrast.toFixed(2).replace(".", ",");
  const brightnessLabel = `${brightness > 0 ? "+" : ""}${brightness}`;
  return [
    "Captura derivada — não calibrada · Vivid IQ",
    `Quadro ${frameIndex + 1} de ${frameCount} · ${seconds} s`,
    `Brilho ${brightnessLabel} · Contraste ${contrastLabel}x · Inversão lateral: ${lateralInverted ? "sim" : "não"}`,
  ];
}
