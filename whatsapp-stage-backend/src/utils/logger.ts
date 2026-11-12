const isProd = process.env.NODE_ENV === "production";

const REDACTED = "[REDACTED]";
const TRUNCATED = "[TRUNCATED]";
const MAX_DEPTH = 6;
const MAX_ARRAY_ITEMS = 30;
const MAX_OBJECT_KEYS = 80;
const MAX_STRING_LENGTH = 512;
const SENSITIVE_KEY_REGEX =
  /(authorization|token|secret|password|signature|raw_body|payload|cookie|access_token|x-whatsapp-internal-token)/i;

function truncateString(value: string): string {
  if (value.length <= MAX_STRING_LENGTH) {
    return value;
  }
  return `${value.slice(0, MAX_STRING_LENGTH)}${TRUNCATED}`;
}

function sanitizeValue(value: unknown, depth: number): unknown {
  if (value === null || value === undefined) {
    return value;
  }

  if (depth > MAX_DEPTH) {
    return TRUNCATED;
  }

  if (typeof value === "string") {
    return truncateString(value);
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }

  if (Array.isArray(value)) {
    const trimmed = value.slice(0, MAX_ARRAY_ITEMS).map((item) => sanitizeValue(item, depth + 1));
    if (value.length > MAX_ARRAY_ITEMS) {
      trimmed.push(TRUNCATED);
    }
    return trimmed;
  }

  if (typeof value === "object") {
    const source = value as Record<string, unknown>;
    const entries = Object.entries(source).slice(0, MAX_OBJECT_KEYS);
    const sanitized: Record<string, unknown> = {};

    for (const [key, innerValue] of entries) {
      if (SENSITIVE_KEY_REGEX.test(key)) {
        sanitized[key] = REDACTED;
        continue;
      }
      sanitized[key] = sanitizeValue(innerValue, depth + 1);
    }

    const totalKeys = Object.keys(source).length;
    if (totalKeys > MAX_OBJECT_KEYS) {
      sanitized.__truncated__ = `${totalKeys - MAX_OBJECT_KEYS} keys`;
    }

    return sanitized;
  }

  try {
    return truncateString(String(value));
  } catch {
    return "[UNSERIALIZABLE]";
  }
}

export function sanitizeLogMeta(meta: unknown): unknown {
  return sanitizeValue(meta, 0);
}

function formatMessage(level: string, message: string, meta?: unknown): string {
  const ts = new Date().toISOString();
  if (meta === undefined) {
    return `[${ts}] [${level}] ${message}`;
  }
  return `[${ts}] [${level}] ${message} ${JSON.stringify(sanitizeLogMeta(meta))}`;
}

export const logger = {
  info(message: string, meta?: unknown): void {
    console.log(formatMessage("INFO", message, meta));
  },

  warn(message: string, meta?: unknown): void {
    console.warn(formatMessage("WARN", message, meta));
  },

  error(message: string, meta?: unknown): void {
    console.error(formatMessage("ERROR", message, meta));
  },

  debug(message: string, meta?: unknown): void {
    if (!isProd) {
      console.debug(formatMessage("DEBUG", message, meta));
    }
  }
};
