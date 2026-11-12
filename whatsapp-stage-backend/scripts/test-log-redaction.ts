import assert from "assert";
import { sanitizeLogMeta } from "../src/utils/logger";

function run(): void {
  const input = {
    authorization: "Bearer abc.def.ghi",
    token: "secret-token-value",
    nested: {
      payload: {
        foo: "bar"
      },
      signature_header: "sha256=abcdef",
      safeKey: "safe"
    },
    longText: "x".repeat(800),
    list: [
      { access_token: "abc" },
      { ok: true }
    ]
  };

  const sanitized = sanitizeLogMeta(input) as Record<string, unknown>;

  assert.strictEqual(sanitized.authorization, "[REDACTED]");
  assert.strictEqual(sanitized.token, "[REDACTED]");

  const nested = sanitized.nested as Record<string, unknown>;
  assert.strictEqual(nested.payload, "[REDACTED]");
  assert.strictEqual(nested.signature_header, "[REDACTED]");
  assert.strictEqual(nested.safeKey, "safe");

  assert.ok(String(sanitized.longText).includes("[TRUNCATED]"));

  const list = sanitized.list as Array<Record<string, unknown>>;
  assert.strictEqual(list[0].access_token, "[REDACTED]");
  assert.strictEqual(list[1].ok, true);

  console.log("Log redaction test passed.");
}

run();
