export interface CustomerServiceWindow {
  last_inbound_at: string | null;
  expires_at: string | null;
  is_open: boolean;
}

export interface CustomerServiceWindowState {
  isOpen: boolean;
  hasInboundMessage: boolean;
  expiresAt: string | null;
}

export function evaluateCustomerServiceWindow(
  serviceWindow: CustomerServiceWindow | null | undefined,
  nowMs: number = Date.now()
): CustomerServiceWindowState {
  if (!serviceWindow?.last_inbound_at || !serviceWindow.expires_at) {
    return {
      isOpen: false,
      hasInboundMessage: false,
      expiresAt: null,
    };
  }

  const expiresAtMs = new Date(serviceWindow.expires_at).getTime();
  if (Number.isNaN(expiresAtMs)) {
    return {
      isOpen: false,
      hasInboundMessage: true,
      expiresAt: null,
    };
  }

  return {
    isOpen: nowMs < expiresAtMs,
    hasInboundMessage: true,
    expiresAt: serviceWindow.expires_at,
  };
}
