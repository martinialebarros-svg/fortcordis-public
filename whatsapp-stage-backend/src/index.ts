import "dotenv/config";
import app from "./app";
import { assertWhatsAppAuthPolicyOrThrow } from "./middleware/auth";
import { closeDbPool, ensureDbConnection } from "./services/dbService";
import {
  shutdownWebhookEventsCleanupWorker,
  startWebhookEventsCleanupWorker
} from "./services/webhookEventsCleanupService";
import {
  shutdownChangeRequestAcknowledgementWorker,
  startChangeRequestAcknowledgementWorker
} from "./services/changeRequestAcknowledgementService";
import { logger } from "./utils/logger";

const requiredEnvVars = [
  "WHATSAPP_ACCESS_TOKEN",
  "PHONE_NUMBER_ID",
  "WHATSAPP_VERIFY_TOKEN",
  "WHATSAPP_APP_SECRET",
  "DATABASE_URL",
  "PORT"
] as const;

for (const envVar of requiredEnvVars) {
  if (!process.env[envVar]) {
    throw new Error(`Missing required environment variable: ${envVar}`);
  }
}

const port = Number.parseInt(process.env.PORT ?? "3000", 10);

function errorToMeta(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    const maybeAggregate = error as Error & { errors?: unknown[] };
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
      inner_errors: Array.isArray(maybeAggregate.errors)
        ? maybeAggregate.errors.map((inner) => {
            if (inner instanceof Error) {
              return { name: inner.name, message: inner.message };
            }
            return { value: String(inner) };
          })
        : undefined
    };
  }

  return { value: String(error) };
}

async function start(): Promise<void> {
  assertWhatsAppAuthPolicyOrThrow();
  await ensureDbConnection();
  startWebhookEventsCleanupWorker();
  startChangeRequestAcknowledgementWorker();

  app.listen(port, () => {
    logger.info(`WhatsApp stage backend running on port ${port}`);
  });
}

function setupProcessSignalHandlers(): void {
  const shutdown = async (signal: string) => {
    logger.info(`Received ${signal}, shutting down WhatsApp stage backend.`);
    shutdownWebhookEventsCleanupWorker();
    await shutdownChangeRequestAcknowledgementWorker();
    await closeDbPool();
    process.exit(0);
  };

  process.once("SIGINT", () => {
    void shutdown("SIGINT");
  });
  process.once("SIGTERM", () => {
    void shutdown("SIGTERM");
  });
}

setupProcessSignalHandlers();

void start().catch(async (error: Error) => {
  logger.error("Failed to start server", errorToMeta(error));
  shutdownWebhookEventsCleanupWorker();
  await shutdownChangeRequestAcknowledgementWorker();
  await closeDbPool();
  process.exit(1);
});
