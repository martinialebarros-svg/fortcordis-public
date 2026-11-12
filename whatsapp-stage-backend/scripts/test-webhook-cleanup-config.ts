import assert from "assert";
import { getWebhookEventsCleanupConfig } from "../src/services/webhookEventsCleanupService";

function withEnv(overrides: Record<string, string | undefined>, fn: () => void): void {
  const keys = Object.keys(overrides);
  const previous: Record<string, string | undefined> = {};
  for (const key of keys) {
    previous[key] = process.env[key];
    const value = overrides[key];
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  try {
    fn();
  } finally {
    for (const key of keys) {
      const value = previous[key];
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

function run(): void {
  withEnv(
    {
      WHATSAPP_WEBHOOK_EVENTS_CLEANUP_ENABLED: undefined,
      WHATSAPP_WEBHOOK_EVENTS_RETENTION_DAYS: undefined,
      WHATSAPP_WEBHOOK_EVENTS_CLEANUP_INTERVAL_MINUTES: undefined,
      WHATSAPP_WEBHOOK_EVENTS_CLEANUP_BATCH_SIZE: undefined
    },
    () => {
      const cfg = getWebhookEventsCleanupConfig();
      assert.strictEqual(cfg.enabled, true);
      assert.strictEqual(cfg.retentionDays, 30);
      assert.strictEqual(cfg.intervalMinutes, 60);
      assert.strictEqual(cfg.batchSize, 2000);
    }
  );

  withEnv(
    {
      WHATSAPP_WEBHOOK_EVENTS_CLEANUP_ENABLED: "false",
      WHATSAPP_WEBHOOK_EVENTS_RETENTION_DAYS: "0",
      WHATSAPP_WEBHOOK_EVENTS_CLEANUP_INTERVAL_MINUTES: "2",
      WHATSAPP_WEBHOOK_EVENTS_CLEANUP_BATCH_SIZE: "50"
    },
    () => {
      const cfg = getWebhookEventsCleanupConfig();
      assert.strictEqual(cfg.enabled, false);
      assert.strictEqual(cfg.retentionDays, 1);
      assert.strictEqual(cfg.intervalMinutes, 5);
      assert.strictEqual(cfg.batchSize, 100);
    }
  );

  console.log("Webhook cleanup config test passed.");
}

run();
