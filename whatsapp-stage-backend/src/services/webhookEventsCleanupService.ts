import { query } from "./dbService";
import { logger } from "../utils/logger";

const CLEANUP_EXECUTOR_AUTOMATIC = "automatic";
const CLEANUP_EXECUTOR_MANUAL = "manual";
const CLEANUP_POLL_SECONDS = 60;

interface CleanupConfig {
  enabled: boolean;
  retentionDays: number;
  intervalMinutes: number;
  batchSize: number;
}

interface CleanupRunSnapshot {
  status: "success" | "error";
  deletedRows: number;
  durationMs: number;
  startedAt: string;
  finishedAt: string;
  errorMessage?: string | null;
}

interface CleanupRuntimeState {
  enabled: boolean;
  workerRunning: boolean;
  inProgress: boolean;
  lastRun: CleanupRunSnapshot | null;
}

let workerTimer: NodeJS.Timeout | null = null;
let runInProgress = false;
let lastRunAtMonotonic: number | null = null;
let lastRunSnapshot: CleanupRunSnapshot | null = null;

function parseBoolean(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  return fallback;
}

function parseIntSetting(
  value: string | undefined,
  fallback: number,
  minValue: number,
  maxValue: number
): number {
  const raw = (value || "").trim();
  if (!raw) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  if (parsed < minValue) {
    return minValue;
  }
  if (parsed > maxValue) {
    return maxValue;
  }
  return parsed;
}

export function getWebhookEventsCleanupConfig(): CleanupConfig {
  return {
    enabled: parseBoolean(process.env.WHATSAPP_WEBHOOK_EVENTS_CLEANUP_ENABLED, true),
    retentionDays: parseIntSetting(process.env.WHATSAPP_WEBHOOK_EVENTS_RETENTION_DAYS, 30, 1, 3650),
    intervalMinutes: parseIntSetting(process.env.WHATSAPP_WEBHOOK_EVENTS_CLEANUP_INTERVAL_MINUTES, 60, 5, 1440),
    batchSize: parseIntSetting(process.env.WHATSAPP_WEBHOOK_EVENTS_CLEANUP_BATCH_SIZE, 2000, 100, 50000)
  };
}

async function deleteExpiredRows(retentionDays: number, batchSize: number): Promise<number> {
  let totalDeleted = 0;
  while (true) {
    const deletedBatch = await query<{ deleted_count: string }>(
      `
        WITH to_delete AS (
          SELECT id
          FROM webhook_events
          WHERE received_at < (now() - make_interval(days => $1::int))
          ORDER BY received_at ASC
          LIMIT $2
        ),
        deleted AS (
          DELETE FROM webhook_events
          WHERE id IN (SELECT id FROM to_delete)
          RETURNING id
        )
        SELECT COUNT(*)::text AS deleted_count
        FROM deleted
      `,
      [retentionDays, batchSize]
    );

    const deletedCount = Number.parseInt(deletedBatch.rows[0]?.deleted_count || "0", 10);
    if (!Number.isFinite(deletedCount) || deletedCount <= 0) {
      break;
    }

    totalDeleted += deletedCount;
    if (deletedCount < batchSize) {
      break;
    }
  }
  return totalDeleted;
}

async function persistCleanupRun(params: {
  executor: string;
  status: "success" | "error";
  retentionDays: number;
  deletedRows: number;
  durationMs: number;
  startedAt: string;
  finishedAt: string;
  errorMessage?: string | null;
}): Promise<void> {
  await query(
    `
      INSERT INTO webhook_event_cleanup_runs (
        executor,
        status,
        retention_days,
        deleted_rows,
        duration_ms,
        error_message,
        started_at,
        finished_at
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7::timestamptz, $8::timestamptz)
    `,
    [
      params.executor,
      params.status,
      params.retentionDays,
      params.deletedRows,
      params.durationMs,
      params.errorMessage ?? null,
      params.startedAt,
      params.finishedAt
    ]
  );
}

export async function runWebhookEventsCleanup(executor: string = CLEANUP_EXECUTOR_MANUAL): Promise<CleanupRunSnapshot | null> {
  if (runInProgress) {
    return null;
  }

  const config = getWebhookEventsCleanupConfig();
  if (!config.enabled && executor === CLEANUP_EXECUTOR_AUTOMATIC) {
    return null;
  }

  runInProgress = true;
  const startedAtDate = new Date();
  const startedAt = startedAtDate.toISOString();
  const startedMonotonic = Date.now();

  try {
    const deletedRows = await deleteExpiredRows(config.retentionDays, config.batchSize);
    const finishedAt = new Date().toISOString();
    const durationMs = Math.max(0, Date.now() - startedMonotonic);
    const snapshot: CleanupRunSnapshot = {
      status: "success",
      deletedRows,
      durationMs,
      startedAt,
      finishedAt
    };

    await persistCleanupRun({
      executor,
      status: snapshot.status,
      retentionDays: config.retentionDays,
      deletedRows: snapshot.deletedRows,
      durationMs: snapshot.durationMs,
      startedAt: snapshot.startedAt,
      finishedAt: snapshot.finishedAt
    });

    lastRunAtMonotonic = Date.now();
    lastRunSnapshot = snapshot;
    return snapshot;
  } catch (error) {
    const finishedAt = new Date().toISOString();
    const durationMs = Math.max(0, Date.now() - startedMonotonic);
    const message = error instanceof Error ? error.message : String(error);
    const snapshot: CleanupRunSnapshot = {
      status: "error",
      deletedRows: 0,
      durationMs,
      startedAt,
      finishedAt,
      errorMessage: message
    };

    try {
      await persistCleanupRun({
        executor,
        status: snapshot.status,
        retentionDays: config.retentionDays,
        deletedRows: snapshot.deletedRows,
        durationMs: snapshot.durationMs,
        startedAt: snapshot.startedAt,
        finishedAt: snapshot.finishedAt,
        errorMessage: snapshot.errorMessage
      });
    } catch (persistError) {
      logger.error("Failed to persist webhook cleanup run", {
        message: persistError instanceof Error ? persistError.message : String(persistError)
      });
    }

    logger.error("Webhook events cleanup failed", {
      message
    });
    lastRunAtMonotonic = Date.now();
    lastRunSnapshot = snapshot;
    return snapshot;
  } finally {
    runInProgress = false;
  }
}

async function maybeRunAutomaticCleanup(): Promise<void> {
  const config = getWebhookEventsCleanupConfig();
  if (!config.enabled || runInProgress) {
    return;
  }

  if (lastRunAtMonotonic !== null) {
    const elapsedMs = Date.now() - lastRunAtMonotonic;
    if (elapsedMs < config.intervalMinutes * 60_000) {
      return;
    }
  }

  await runWebhookEventsCleanup(CLEANUP_EXECUTOR_AUTOMATIC);
}

export function startWebhookEventsCleanupWorker(): void {
  if (workerTimer) {
    return;
  }

  const config = getWebhookEventsCleanupConfig();
  if (!config.enabled) {
    logger.info("Webhook events cleanup worker disabled by configuration.");
    return;
  }

  workerTimer = setInterval(() => {
    void maybeRunAutomaticCleanup();
  }, CLEANUP_POLL_SECONDS * 1000);

  void maybeRunAutomaticCleanup();
}

export function shutdownWebhookEventsCleanupWorker(): void {
  if (!workerTimer) {
    return;
  }
  clearInterval(workerTimer);
  workerTimer = null;
}

export function getWebhookEventsCleanupRuntimeState(): CleanupRuntimeState {
  const config = getWebhookEventsCleanupConfig();
  return {
    enabled: config.enabled,
    workerRunning: workerTimer !== null,
    inProgress: runInProgress,
    lastRun: lastRunSnapshot
  };
}
