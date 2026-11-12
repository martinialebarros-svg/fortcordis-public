export const OPERATIONAL_TIME_ZONE = "America/Fortaleza";

const DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const MIDNIGHT_DATE_TIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})[T ]00:00:00(?:\.0+)?(?:Z|[+-]\d{2}:?\d{2})?$/i;
const TIMEZONE_SUFFIX_PATTERN = /(?:z|[+-]\d{2}:?\d{2})$/i;

export type CalendarDateParts = {
  year: string;
  month: string;
  day: string;
};

function partsFromMatch(match: RegExpMatchArray | null): CalendarDateParts | null {
  if (!match) return null;
  return { year: match[1], month: match[2], day: match[3] };
}

export function calendarDateParts(value?: string | null): CalendarDateParts | null {
  const raw = String(value || "").trim();
  return partsFromMatch(raw.match(DATE_ONLY_PATTERN)) || partsFromMatch(raw.match(MIDNIGHT_DATE_TIME_PATTERN));
}

function formatPartsForInput(parts: CalendarDateParts): string {
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function formatPartsPtBr(parts: CalendarDateParts): string {
  return `${parts.day}/${parts.month}/${parts.year}`;
}

function parseOperationalDateTime(value?: string | null): Date | null {
  const raw = String(value || "").trim();
  if (!raw) return null;

  const normalized = raw.includes(" ") && !raw.includes("T") ? raw.replace(" ", "T") : raw;
  const parsed = new Date(TIMEZONE_SUFFIX_PATTERN.test(normalized) ? normalized : `${normalized}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function partsAtOperationalTimeZone(value: Date): CalendarDateParts {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: OPERATIONAL_TIME_ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(value)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );

  return {
    year: String(parts.year),
    month: String(parts.month),
    day: String(parts.day),
  };
}

/**
 * Returns a date-only value suitable for a native `<input type="date">`.
 * Existing records saved at UTC midnight keep their original calendar date.
 */
export function calendarDateInput(value?: string | null): string {
  const preserved = calendarDateParts(value);
  if (preserved) return formatPartsForInput(preserved);

  const parsed = parseOperationalDateTime(value);
  return parsed ? formatPartsForInput(partsAtOperationalTimeZone(parsed)) : "";
}

export function operationalTodayDateInput(now = new Date()): string {
  return formatPartsForInput(partsAtOperationalTimeZone(now));
}

/**
 * Calendar dates are sent at midnight in Fortaleza instead of midnight UTC.
 * That prevents a selected date from becoming the previous day on read-back.
 */
export function calendarDateToOperationalIso(value?: string | null): string | null {
  const normalized = calendarDateInput(value);
  return normalized ? `${normalized}T00:00:00-03:00` : null;
}

export function formatCalendarDate(value?: string | null, fallback = "-"): string {
  const preserved = calendarDateParts(value);
  if (preserved) return formatPartsPtBr(preserved);

  const parsed = parseOperationalDateTime(value);
  if (!parsed) return value || fallback;
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: OPERATIONAL_TIME_ZONE,
  }).format(parsed);
}

export function formatOperationalDate(value?: string | null, fallback = "-"): string {
  const raw = String(value || "").trim();
  if (!raw) return fallback;

  const dateOnly = partsFromMatch(raw.match(DATE_ONLY_PATTERN));
  if (dateOnly) return formatPartsPtBr(dateOnly);

  const parsed = parseOperationalDateTime(raw);
  if (!parsed) return raw;
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: OPERATIONAL_TIME_ZONE,
  }).format(parsed);
}
