export const PORTAL_DISPLAY_TIME_ZONE = "America/Fortaleza";

const ISO_DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const TIMEZONE_SUFFIX_PATTERN = /(?:z|[+-]\d{2}:?\d{2})$/i;

export function parsePortalDateTime(value?: string | null): Date | null {
  const raw = String(value || "").trim();
  if (!raw) {
    return null;
  }

  if (ISO_DATE_ONLY_PATTERN.test(raw)) {
    const [year, month, day] = raw.split("-").map((part) => Number.parseInt(part, 10));
    return new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
  }

  const normalized = raw.includes(" ") && !raw.includes("T") ? raw.replace(" ", "T") : raw;
  const parsed = new Date(TIMEZONE_SUFFIX_PATTERN.test(normalized) ? normalized : `${normalized}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function portalDateTimeMillis(value?: string | null): number {
  const parsed = parsePortalDateTime(value);
  return parsed ? parsed.getTime() : Number.NaN;
}

export function formatPortalDateTime(value?: string | null): string {
  const parsed = parsePortalDateTime(value);
  if (!parsed) {
    return value || "-";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: PORTAL_DISPLAY_TIME_ZONE,
  }).format(parsed);
}

export function formatPortalDate(value?: string | null): string {
  const parsed = parsePortalDateTime(value);
  if (!parsed) {
    return value || "-";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: PORTAL_DISPLAY_TIME_ZONE,
  }).format(parsed);
}
