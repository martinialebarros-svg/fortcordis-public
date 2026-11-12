export const ATENDIMENTO_OPERATIONAL_TIME_ZONE = "America/Fortaleza";
const ATENDIMENTO_OPERATIONAL_OFFSET = "-03:00";

const formatOperationalLocalInput = (date: Date) => {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: ATENDIMENTO_OPERATIONAL_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const parts = Object.fromEntries(
    formatter
      .formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value])
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
};

const parseOperationalDate = (value?: string | null) => {
  const raw = String(value || "").trim();
  if (!raw) return null;

  let normalized = raw.replace(" ", "T");
  const hasExplicitTimezone =
    /T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  if (!hasExplicitTimezone) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
      normalized = `${normalized}T00:00:00`;
    } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(normalized)) {
      normalized = `${normalized}:00`;
    }
    normalized = `${normalized}${ATENDIMENTO_OPERATIONAL_OFFSET}`;
  }

  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
};

export const localInputToOperationalIso = (value?: string | null) => {
  const raw = String(value || "").trim();
  const match = raw.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(:\d{2}(?:\.\d+)?)?$/);
  if (!match) return null;

  const normalized = `${match[1]}${match[2] || ":00"}${ATENDIMENTO_OPERATIONAL_OFFSET}`;
  return Number.isNaN(new Date(normalized).getTime()) ? null : normalized;
};

export const nowLocalInput = () => formatOperationalLocalInput(new Date());

export const isoToLocalInput = (value?: string | null) => {
  if (!value) return nowLocalInput();
  const date = parseOperationalDate(value);
  return date ? formatOperationalLocalInput(date) : nowLocalInput();
};

export const isoToOptionalLocalInput = (value?: string | null) => {
  if (!value) return "";
  const date = parseOperationalDate(value);
  return date ? formatOperationalLocalInput(date) : "";
};

export const formatDate = (value?: string | null) => {
  if (!value) return "-";
  const date = parseOperationalDate(value);
  if (!date) return value;
  return date.toLocaleString("pt-BR", { timeZone: ATENDIMENTO_OPERATIONAL_TIME_ZONE });
};

export const formatBytes = (value?: number | null) => {
  if (!value || value <= 0) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
};

export const parseDownloadFilename = (contentDisposition: string | undefined, fallback: string) => {
  if (!contentDisposition) return fallback;
  const utf8Match = contentDisposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    const raw = utf8Match[1].trim().replace(/^"(.*)"$/, "$1");
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw || fallback;
    }
  }
  const plainMatch = contentDisposition.match(/filename\s*=\s*"?([^";]+)"?/i);
  if (plainMatch?.[1]) return plainMatch[1].trim();
  return fallback;
};

export const normalizePeso = (value: unknown): number | null => {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return Number(numeric);
};

export const parseDecimalInput = (value?: string | number | null): number | null => {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim().replace(",", ".");
  if (!raw) return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return parsed;
};

export const parseStringListInput = (value: string): string[] =>
  value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
