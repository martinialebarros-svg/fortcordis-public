import axios, { AxiosError } from "axios";
import { spawn } from "child_process";
import { existsSync } from "fs";
import ffmpegPath from "ffmpeg-static";
import { logger } from "../utils/logger";
import {
  APPROVED_TEMPLATE_LANGUAGE,
  APPROVED_UTILITY_TEMPLATES,
  ApprovedUtilityTemplateKey,
  assertTemplateDeliveryApproved,
  getTemplateBodyParameterCount,
  templateRequiresDocumentHeader
} from "../templates/approvedTemplates";

const graphApiVersion = process.env.WHATSAPP_GRAPH_API_VERSION || "v26.0";
const GRAPH_API_BASE_URL = `https://graph.facebook.com/${graphApiVersion}`;
const DEFAULT_TIMEOUT_MS = 10000;
const MEDIA_UPLOAD_TIMEOUT_MS = 30000;
const AUDIO_TRANSCODE_TIMEOUT_MS = 20000;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function computeBackoffWithJitter(attempt: number): number {
  const baseMs = 300 * 2 ** (attempt - 1);
  const jitterMs = Math.floor(Math.random() * 125);
  return baseMs + jitterMs;
}

function shouldRetry(error: AxiosError): boolean {
  const status = error.response?.status;

  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
    return true;
  }

  if (!error.response) {
    return true;
  }

  if (status === 429) {
    return true;
  }

  return typeof status === "number" && status >= 500;
}

function extractMetaError(data: unknown): { code?: string; message?: string } {
  if (!data || typeof data !== "object") {
    return {};
  }

  const maybeError = (data as { error?: unknown }).error;
  if (!maybeError || typeof maybeError !== "object") {
    return {};
  }

  const codeRaw = (maybeError as { code?: unknown }).code;
  const messageRaw = (maybeError as { message?: unknown }).message;

  return {
    code: codeRaw !== undefined ? String(codeRaw) : undefined,
    message: typeof messageRaw === "string" ? messageRaw : undefined
  };
}

export class WhatsAppGraphApiError extends Error {
  status?: number;
  code?: string;
  responseBody?: unknown;
  providerMessage?: string;
  isRetryable: boolean;
  attempt: number;

  constructor(params: {
    message: string;
    status?: number;
    code?: string;
    responseBody?: unknown;
    providerMessage?: string;
    isRetryable: boolean;
    attempt: number;
  }) {
    super(params.message);
    this.name = "WhatsAppGraphApiError";
    this.status = params.status;
    this.code = params.code;
    this.responseBody = params.responseBody;
    this.providerMessage = params.providerMessage;
    this.isRetryable = params.isRetryable;
    this.attempt = params.attempt;
  }

  get response(): { status?: number; data?: unknown } | undefined {
    if (this.status === undefined && this.responseBody === undefined) {
      return undefined;
    }

    return {
      status: this.status,
      data: this.responseBody
    };
  }
}

function normalizeAxiosError(error: AxiosError, attempt: number): WhatsAppGraphApiError {
  const status = error.response?.status;
  const responseBody = error.response?.data;
  const meta = extractMetaError(responseBody);
  const retryable = shouldRetry(error);

  const providerMessage = meta.message || (typeof error.message === "string" ? error.message : "Unknown Graph API error");
  const message = `WhatsApp Graph API request failed${status ? ` (HTTP ${status})` : ""}: ${providerMessage}`;

  return new WhatsAppGraphApiError({
    message,
    status,
    code: meta.code || error.code || undefined,
    responseBody,
    providerMessage,
    isRetryable: retryable,
    attempt
  });
}

interface SendTextMessageParams {
  maxAttempts?: number;
  phoneNumberId: string;
  accessToken: string;
  to: string;
  body: string;
  type?: string;
}

interface GraphMessageResponse {
  messaging_product: string;
  contacts?: Array<{ input: string; wa_id: string }>;
  messages?: Array<{ id: string }>;
  [key: string]: unknown;
}

export interface ReservationTemplateParams {
  phoneNumberId: string;
  accessToken: string;
  to: string;
  templateName: string;
  languageCode: string;
  bodyParameters: [string, string, string, string, string];
  confirmPayload: string;
  changePayload: string;
}

export interface ApprovedUtilityTemplateParams {
  phoneNumberId: string;
  accessToken: string;
  to: string;
  templateKey: ApprovedUtilityTemplateKey;
  bodyParameters: string[];
  quickReplyPayloads: string[];
  documentHeader?: {
    mediaId: string;
    filename: string;
  };
}

interface GraphMediaUploadResponse {
  id?: string;
  [key: string]: unknown;
}

export interface UploadWhatsAppPdfParams {
  phoneNumberId: string;
  accessToken: string;
  filename: string;
  content: Buffer;
}

async function sendPayloadWithRetry(params: {
  maxAttempts?: number;
  phoneNumberId: string;
  accessToken: string;
  payload: Record<string, unknown>;
}): Promise<GraphMessageResponse> {
  const url = `${GRAPH_API_BASE_URL}/${params.phoneNumberId}/messages`;
  const maxAttempts = Math.max(1, Math.min(3, params.maxAttempts ?? 3));

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await axios.post<GraphMessageResponse>(url, params.payload, {
        headers: {
          Authorization: `Bearer ${params.accessToken}`,
          "Content-Type": "application/json"
        },
        timeout: DEFAULT_TIMEOUT_MS
      });

      return response.data;
    } catch (error) {
      const axiosError = error as AxiosError;
      const normalizedError = normalizeAxiosError(axiosError, attempt);

      if (attempt >= maxAttempts || !normalizedError.isRetryable) {
        throw normalizedError;
      }

      const backoffMs = computeBackoffWithJitter(attempt);
      logger.warn("Retrying Graph API request", {
        attempt,
        nextWaitMs: backoffMs,
        status: normalizedError.status,
        code: normalizedError.code,
        providerMessage: normalizedError.providerMessage
      });

      await wait(backoffMs);
    }
  }

  throw new Error("Unexpected WhatsApp Graph API retry flow termination");
}

export async function sendWhatsAppMessageWithRetry(
  params: SendTextMessageParams
): Promise<GraphMessageResponse> {
  const { phoneNumberId, accessToken, to, body, type = "text" } = params;

  if (type !== "text") {
    throw new Error(`Message type '${type}' is not supported yet. Use 'text'.`);
  }

  const payload = {
    messaging_product: "whatsapp",
    recipient_type: "individual",
    to,
    type: "text",
    text: {
      body
    }
  };

  return sendPayloadWithRetry({ phoneNumberId, accessToken, payload, maxAttempts: params.maxAttempts });
}

export interface SendDocumentMessageParams {
  phoneNumberId: string;
  accessToken: string;
  to: string;
  mediaId: string;
  filename: string;
  caption?: string;
}

export async function sendWhatsAppDocumentMessageWithRetry(
  params: SendDocumentMessageParams
): Promise<GraphMessageResponse> {
  const payload = {
    messaging_product: "whatsapp",
    recipient_type: "individual",
    to: params.to,
    type: "document",
    document: {
      id: params.mediaId,
      filename: params.filename,
      ...(params.caption ? { caption: params.caption } : {})
    }
  };

  return sendPayloadWithRetry({
    phoneNumberId: params.phoneNumberId,
    accessToken: params.accessToken,
    payload
  });
}

export async function sendWhatsAppReservationTemplateWithRetry(
  params: ReservationTemplateParams
): Promise<GraphMessageResponse> {
  const payload = {
    messaging_product: "whatsapp",
    recipient_type: "individual",
    to: params.to,
    type: "template",
    template: {
      name: params.templateName,
      language: { code: params.languageCode },
      components: [
        {
          type: "body",
          parameters: params.bodyParameters.map((text) => ({ type: "text", text }))
        },
        {
          type: "button",
          sub_type: "quick_reply",
          index: "0",
          parameters: [{ type: "payload", payload: params.confirmPayload }]
        },
        {
          type: "button",
          sub_type: "quick_reply",
          index: "1",
          parameters: [{ type: "payload", payload: params.changePayload }]
        }
      ]
    }
  };

  return sendPayloadWithRetry({
    phoneNumberId: params.phoneNumberId,
    accessToken: params.accessToken,
    payload
  });
}

export async function sendWhatsAppApprovedUtilityTemplateWithRetry(
  params: ApprovedUtilityTemplateParams
): Promise<GraphMessageResponse> {
  const definition = APPROVED_UTILITY_TEMPLATES[params.templateKey];
  const expectedBodyParameters = getTemplateBodyParameterCount(params.templateKey);
  const expectedQuickReplies = definition.quickReplies.length;

  if (params.bodyParameters.length !== expectedBodyParameters) {
    throw new Error(
      `Template '${definition.name}' expects ${expectedBodyParameters} body parameters, received ${params.bodyParameters.length}`
    );
  }
  if (params.quickReplyPayloads.length !== expectedQuickReplies) {
    throw new Error(
      `Template '${definition.name}' expects ${expectedQuickReplies} quick reply payloads, received ${params.quickReplyPayloads.length}`
    );
  }
  assertTemplateDeliveryApproved(params.templateKey);

  const requiresDocument = templateRequiresDocumentHeader(params.templateKey);
  if (requiresDocument && !params.documentHeader) {
    throw new Error(`Template '${definition.name}' requires a document header`);
  }
  if (!requiresDocument && params.documentHeader) {
    throw new Error(`Template '${definition.name}' does not accept a document header`);
  }

  const components: Array<Record<string, unknown>> = [
    ...(params.documentHeader
      ? [
          {
            type: "header",
            parameters: [
              {
                type: "document",
                document: {
                  id: params.documentHeader.mediaId,
                  filename: params.documentHeader.filename
                }
              }
            ]
          }
        ]
      : []),
    {
      type: "body",
      parameters: params.bodyParameters.map((text) => ({ type: "text", text }))
    },
    ...params.quickReplyPayloads.map((payload, index) => ({
      type: "button",
      sub_type: "quick_reply",
      index: String(index),
      parameters: [{ type: "payload", payload }]
    }))
  ];

  return sendPayloadWithRetry({
    phoneNumberId: params.phoneNumberId,
    accessToken: params.accessToken,
    payload: {
      messaging_product: "whatsapp",
      recipient_type: "individual",
      to: params.to,
      type: "template",
      template: {
        name: definition.name,
        language: { code: APPROVED_TEMPLATE_LANGUAGE },
        components
      }
    }
  });
}

interface UploadMediaWithRetryParams {
  phoneNumberId: string;
  accessToken: string;
  filename: string;
  content: Buffer;
  mimeType: string;
}

async function uploadMediaWithRetry(params: UploadMediaWithRetryParams): Promise<{ id: string }> {
  const url = `${GRAPH_API_BASE_URL}/${params.phoneNumberId}/media`;
  const maxAttempts = 3;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const formData = new FormData();
    formData.append("messaging_product", "whatsapp");
    formData.append(
      "file",
      new Blob([new Uint8Array(params.content)], { type: params.mimeType }),
      params.filename
    );

    try {
      const response = await axios.post<GraphMediaUploadResponse>(url, formData, {
        headers: {
          Authorization: `Bearer ${params.accessToken}`
        },
        timeout: MEDIA_UPLOAD_TIMEOUT_MS
      });
      const mediaId = String(response.data?.id || "").trim();
      if (!mediaId) {
        throw new Error("Meta media upload response did not include an id");
      }
      return { id: mediaId };
    } catch (error) {
      if (!(error as AxiosError).isAxiosError) {
        throw error;
      }
      const normalizedError = normalizeAxiosError(error as AxiosError, attempt);
      if (attempt >= maxAttempts || !normalizedError.isRetryable) {
        throw normalizedError;
      }
      const backoffMs = computeBackoffWithJitter(attempt);
      logger.warn("Retrying Graph API media upload", {
        attempt,
        nextWaitMs: backoffMs,
        status: normalizedError.status,
        code: normalizedError.code,
        providerMessage: normalizedError.providerMessage
      });
      await wait(backoffMs);
    }
  }

  throw new Error("Unexpected WhatsApp media upload retry flow termination");
}

export async function uploadWhatsAppPdfWithRetry(
  params: UploadWhatsAppPdfParams
): Promise<{ id: string }> {
  if (!params.content.length || params.content.subarray(0, 4).toString("ascii") !== "%PDF") {
    throw new Error("Document content must be a valid PDF");
  }

  return uploadMediaWithRetry({ ...params, mimeType: "application/pdf" });
}

export interface UploadWhatsAppDocumentParams {
  phoneNumberId: string;
  accessToken: string;
  filename: string;
  content: Buffer;
  mimeType: string;
}

export async function uploadWhatsAppDocumentWithRetry(
  params: UploadWhatsAppDocumentParams
): Promise<{ id: string }> {
  if (!params.content.length) {
    throw new Error("Attachment content must not be empty");
  }

  return uploadMediaWithRetry(params);
}

export interface DownloadWhatsAppMediaParams {
  mediaId: string;
  accessToken: string;
}

export interface DownloadedWhatsAppMedia {
  buffer: Buffer;
  mimeType: string;
}

interface GraphMediaMetadataResponse {
  url?: string;
  mime_type?: string;
  [key: string]: unknown;
}

const MEDIA_DOWNLOAD_TIMEOUT_MS = 15000;

export function transcodeOggOpusToMp3(buffer: Buffer): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    if (!ffmpegPath) {
      reject(new Error("ffmpeg-static did not resolve a binary path for this platform/arch"));
      return;
    }
    if (!existsSync(ffmpegPath)) {
      reject(new Error(`ffmpeg-static resolved path does not exist on disk: ${ffmpegPath} (binary download likely failed during npm install)`));
      return;
    }

    const ffmpeg = spawn(ffmpegPath, [
      "-i", "pipe:0",
      "-f", "mp3",
      "-codec:a", "libmp3lame",
      "-b:a", "128k",
      "pipe:1"
    ]);
    const stdoutChunks: Buffer[] = [];
    let stderrText = "";
    let settled = false;

    const timeoutId = setTimeout(() => {
      if (settled) return;
      settled = true;
      ffmpeg.kill("SIGKILL");
      reject(new Error("Audio transcoding timed out"));
    }, AUDIO_TRANSCODE_TIMEOUT_MS);

    ffmpeg.stdout.on("data", (chunk: Buffer) => stdoutChunks.push(chunk));
    ffmpeg.stderr.on("data", (chunk: Buffer) => {
      stderrText += chunk.toString();
    });
    ffmpeg.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      reject(error);
    });
    ffmpeg.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      if (code === 0 && stdoutChunks.length > 0) {
        resolve(Buffer.concat(stdoutChunks));
      } else {
        reject(new Error(`ffmpeg exited with code ${code}: ${stderrText.slice(-500)}`));
      }
    });
    ffmpeg.stdin.on("error", () => {
      // Tratado pelo evento "close"/"error" do processo acima (ex.: EPIPE se o
      // ffmpeg encerrar antes de consumir todo o stdin).
    });
    ffmpeg.stdin.write(buffer);
    ffmpeg.stdin.end();
  });
}

export async function downloadWhatsAppMedia(
  params: DownloadWhatsAppMediaParams
): Promise<DownloadedWhatsAppMedia> {
  const metadataUrl = `${GRAPH_API_BASE_URL}/${params.mediaId}`;
  const authHeader = { Authorization: `Bearer ${params.accessToken}` };

  try {
    const metadataResponse = await axios.get<GraphMediaMetadataResponse>(metadataUrl, {
      headers: authHeader,
      timeout: DEFAULT_TIMEOUT_MS
    });
    const downloadUrl = String(metadataResponse.data?.url || "").trim();
    if (!downloadUrl) {
      throw new Error("Meta media metadata response did not include a download url");
    }

    const binaryResponse = await axios.get<ArrayBuffer>(downloadUrl, {
      headers: authHeader,
      responseType: "arraybuffer",
      timeout: MEDIA_DOWNLOAD_TIMEOUT_MS
    });

    const mimeType =
      String(binaryResponse.headers["content-type"] || metadataResponse.data?.mime_type || "").trim() ||
      "application/octet-stream";
    const rawBuffer = Buffer.from(binaryResponse.data);

    // O audio de voz do WhatsApp vem em Opus dentro de um conteiner OGG que
    // o decodificador <audio> de varios navegadores (Chrome incluido, nao so
    // Safari) rejeita, mesmo quando o arquivo em si esta correto (players
    // nativos como QuickTime tocam sem problema). Reempacota em mp3, que
    // todo navegador suporta; se a conversao falhar, serve o original.
    if (mimeType.toLowerCase().includes("ogg")) {
      try {
        const transcoded = await transcodeOggOpusToMp3(rawBuffer);
        return { buffer: transcoded, mimeType: "audio/mpeg" };
      } catch (transcodeError) {
        logger.warn("Failed to transcode WhatsApp OGG/Opus audio to mp3, serving original", {
          mediaId: params.mediaId,
          mimeType,
          rawBufferBytes: rawBuffer.length,
          ffmpegPath: ffmpegPath || null,
          message: transcodeError instanceof Error ? transcodeError.message : String(transcodeError)
        });
      }
    }

    return {
      buffer: rawBuffer,
      mimeType
    };
  } catch (error) {
    if (!(error as AxiosError).isAxiosError) {
      throw error;
    }
    throw normalizeAxiosError(error as AxiosError, 1);
  }
}
