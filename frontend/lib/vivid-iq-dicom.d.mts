export interface VividIqFrame {
  offset: number;
  timestampSeconds: number;
  width: number;
  height: number;
  frameSize: number;
}

export interface VividIqFrameDimension {
  width: number;
  height: number;
  frameCount: number;
}

export interface VividIqStudy {
  fileName: string;
  fileSize: number;
  transferSyntax: string;
  modality: string;
  manufacturer: string;
  model: string;
  equipment: string;
  cineType: string;
  previewWidth: number | null;
  previewHeight: number | null;
  width: number;
  height: number;
  displayWidth: number;
  displayHeight: number;
  displayAspectRatio: number;
  displayAspectRatioSource:
    | "ultrasound-region"
    | "preview-image"
    | "estimated-sector"
    | "native-pixels";
  frameSize: number;
  frameDimensions: VividIqFrameDimension[];
  maxFrameWidth: number;
  scanConversion: boolean;
  previewJpegOffset: number | null;
  previewJpegLength: number;
  frameCount: number;
  frameRate: number;
  durationSeconds: number;
  firstTimestamp: number;
  frames: VividIqFrame[];
  warnings: string[];
  sourceBuffer: ArrayBuffer;
}

export class VividIqDicomError extends Error {
  code: string;
  constructor(code: string, message: string);
}

export interface VividIqIdentification {
  patientName: string | null;
  patientNameRaw: string | null;
  studyDate: string | null;
  studyTime: string | null;
  acquisitionDateTime: string | null;
  contentDate: string | null;
  contentTime: string | null;
  timezoneOffset: string | null;
  warnings: string[];
}

export function parseVividIqDicom(buffer: ArrayBuffer, fileName?: string): VividIqStudy;
export function getVividIqIdentification(study: VividIqStudy): VividIqIdentification;
export function getVividIqFramePixels(study: VividIqStudy, frameIndex: number): Uint8Array;
export function getVividIqPreviewJpeg(study: VividIqStudy): Uint8Array | null;
export function createVividIqDisplayMap(
  sourceWidth: number,
  sourceHeight: number,
  outputWidth: number,
  outputHeight: number,
  scanConversion?: boolean,
  lateralFlip?: boolean,
): Int32Array;
export function detectVividIqPreviewAspectRatio(
  pixels: ArrayLike<number>,
  width: number,
  height: number,
  channels?: number,
): number | null;
export function findVividIqFrameAtTimestamp(
  study: VividIqStudy,
  timestampSeconds: number,
): number;

export const VIVID_IQ_MAX_FILE_BYTES: number;
export const VIVID_IQ_MAX_FRAMES: number;
