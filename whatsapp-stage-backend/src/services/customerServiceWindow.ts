export const CUSTOMER_SERVICE_WINDOW_HOURS = 24;
const CUSTOMER_SERVICE_WINDOW_MS = CUSTOMER_SERVICE_WINDOW_HOURS * 60 * 60 * 1000;

export interface CustomerServiceWindow {
  last_inbound_at: string | null;
  expires_at: string | null;
  is_open: boolean;
}

type DateInput = Date | string | null | undefined;

function normalizeDate(value: DateInput): Date | null {
  if (!value) {
    return null;
  }

  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function describeCustomerServiceWindow(
  lastInboundAt: DateInput,
  now: Date = new Date()
): CustomerServiceWindow {
  const inboundAt = normalizeDate(lastInboundAt);
  const currentTime = normalizeDate(now);

  if (!inboundAt || !currentTime) {
    return {
      last_inbound_at: null,
      expires_at: null,
      is_open: false
    };
  }

  const expiresAt = new Date(inboundAt.getTime() + CUSTOMER_SERVICE_WINDOW_MS);

  return {
    last_inbound_at: inboundAt.toISOString(),
    expires_at: expiresAt.toISOString(),
    is_open: currentTime.getTime() < expiresAt.getTime()
  };
}
