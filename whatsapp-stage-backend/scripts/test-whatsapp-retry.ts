import assert from "assert";
import axios, { AxiosError } from "axios";
import { sendWhatsAppMessageWithRetry, WhatsAppGraphApiError } from "../src/services/whatsappService";

function createAxiosError(params: {
  message: string;
  code?: string;
  status?: number;
  responseBody?: unknown;
  withResponse?: boolean;
}): AxiosError {
  const error = new Error(params.message) as AxiosError;

  error.name = "AxiosError";
  error.code = params.code;
  (error as { isAxiosError?: boolean }).isAxiosError = true;

  if (params.withResponse !== false) {
    error.response = {
      status: params.status ?? 500,
      statusText: "Error",
      headers: {},
      config: {} as never,
      data: params.responseBody ?? {}
    };
  }

  return error;
}

async function run(): Promise<void> {
  const originalPost = axios.post;

  try {
    let attempts = 0;

    (axios.post as unknown as (url: string, payload: unknown, config: unknown) => Promise<unknown>) = async () => {
      attempts += 1;

      if (attempts === 1) {
        throw createAxiosError({
          message: "Rate limited",
          status: 429,
          responseBody: {
            error: {
              code: 4,
              message: "Application request limit reached"
            }
          }
        });
      }

      if (attempts === 2) {
        throw createAxiosError({
          message: "Upstream unavailable",
          status: 503,
          responseBody: {
            error: {
              code: 2,
              message: "Service temporarily unavailable"
            }
          }
        });
      }

      return {
        data: {
          messaging_product: "whatsapp",
          messages: [{ id: "wamid.retry.success" }]
        }
      };
    };

    const success = await sendWhatsAppMessageWithRetry({
      phoneNumberId: "1234567890",
      accessToken: "token",
      to: "5511999999999",
      body: "test"
    });

    assert.strictEqual(attempts, 3, "Expected 3 attempts for 429 + 503 + success flow");
    assert.strictEqual(success.messages?.[0]?.id, "wamid.retry.success", "Expected provider message id on success");

    attempts = 0;

    (axios.post as unknown as (url: string, payload: unknown, config: unknown) => Promise<unknown>) = async () => {
      attempts += 1;

      throw createAxiosError({
        message: "Permanent provider failure",
        status: 500,
        responseBody: {
          error: {
            code: 131000,
            message: "Provider internal error"
          }
        }
      });
    };

    let caught: unknown;

    try {
      await sendWhatsAppMessageWithRetry({
        phoneNumberId: "1234567890",
        accessToken: "token",
        to: "5511999999999",
        body: "test"
      });
    } catch (error) {
      caught = error;
    }

    assert.strictEqual(attempts, 3, "Expected 3 attempts for retryable 500 errors");
    assert.ok(caught instanceof WhatsAppGraphApiError, "Expected normalized WhatsAppGraphApiError");

    const normalized = caught as WhatsAppGraphApiError;
    assert.strictEqual(normalized.status, 500, "Expected HTTP status in normalized error");
    assert.strictEqual(normalized.code, "131000", "Expected Meta error code in normalized error");
    assert.strictEqual(normalized.isRetryable, true, "Expected retryable flag on 500");
    assert.ok(normalized.responseBody, "Expected provider response body in normalized error");

    attempts = 0;

    (axios.post as unknown as (url: string, payload: unknown, config: unknown) => Promise<unknown>) = async () => {
      attempts += 1;

      throw createAxiosError({
        message: "Timeout",
        code: "ECONNABORTED",
        withResponse: false
      });
    };

    caught = undefined;

    try {
      await sendWhatsAppMessageWithRetry({
        phoneNumberId: "1234567890",
        accessToken: "token",
        to: "5511999999999",
        body: "test"
      });
    } catch (error) {
      caught = error;
    }

    assert.strictEqual(attempts, 3, "Expected 3 attempts for timeout errors");
    assert.ok(caught instanceof WhatsAppGraphApiError, "Expected normalized timeout error");

    const timeoutError = caught as WhatsAppGraphApiError;
    assert.strictEqual(timeoutError.status, undefined, "Expected undefined status when no response exists");
    assert.strictEqual(timeoutError.code, "ECONNABORTED", "Expected timeout error code in normalized error");

    console.log("Graph API retry smoke test passed.");
  } finally {
    axios.post = originalPost;
  }
}

void run().catch((error) => {
  console.error("Graph API retry smoke test failed:", error);
  process.exit(1);
});
