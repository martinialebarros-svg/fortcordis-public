export function digitsOnly(value: unknown): string {
  return String(value ?? "").replace(/\D+/g, "");
}

/**
 * Meta may identify the same Brazilian WhatsApp account with or without the
 * mobile ninth digit after country code and DDD. Use the legacy eight-digit
 * representation only as an internal identity key.
 */
export function canonicalWhatsAppIdentity(value: unknown): string {
  const digits = digitsOnly(value);

  if (/^55\d{2}9\d{8}$/.test(digits)) {
    return `${digits.slice(0, 4)}${digits.slice(5)}`;
  }

  return digits;
}

/**
 * Rebuilds the Brazilian mobile ninth digit for Graph API destinations.
 *
 * OFF BY DEFAULT, on purpose. Production has been delivering to the 12-digit
 * identity form for a long time - measured in 2026-08-24: 96 outbound messages
 * `sent`/`delivered`/`read` against 1 failure, across 30 conversations. There
 * is no reason to rewrite a destination format that demonstrably works.
 *
 * The rebuild exists for the Meta TEST number used by stage, which only talks
 * to pre-verified recipients. That allowlist stores the number WITH the ninth
 * digit, so sending the 12-digit form is rejected with `OAuthException/131030`
 * - "recipient not in allowed list". That is an allowlist mismatch, not a
 * format error, and it does not apply to a live production number.
 *
 * Enable with `WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT=true`.
 */
export function shouldForceBrMobileNinthDigit(): boolean {
  return process.env.WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT === "true";
}

export function whatsappGraphRecipient(value: unknown): string {
  const digits = digitsOnly(value);
  if (!shouldForceBrMobileNinthDigit()) {
    return digits;
  }

  const identity = canonicalWhatsAppIdentity(digits);

  if (/^55\d{2}[6-9]\d{7}$/.test(identity)) {
    return `${identity.slice(0, 4)}9${identity.slice(4)}`;
  }

  return digits;
}

export function areEquivalentWhatsAppNumbers(left: unknown, right: unknown): boolean {
  const leftDigits = digitsOnly(left);
  const rightDigits = digitsOnly(right);

  if (!leftDigits || !rightDigits) {
    return false;
  }

  return canonicalWhatsAppIdentity(leftDigits) === canonicalWhatsAppIdentity(rightDigits);
}
