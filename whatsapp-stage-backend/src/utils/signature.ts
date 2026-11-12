import crypto from "crypto";

export function generateSignature(rawBody: Buffer, appSecret: string): string {
  const digest = crypto.createHmac("sha256", appSecret).update(rawBody).digest("hex");
  return `sha256=${digest}`;
}

export function verifyXHubSignature(
  rawBody: Buffer | undefined,
  headerSignature: string | undefined,
  appSecret: string
): boolean {
  if (!rawBody || !headerSignature || !appSecret) {
    return false;
  }

  const expected = Buffer.from(generateSignature(rawBody, appSecret));
  const received = Buffer.from(headerSignature);

  if (expected.length !== received.length) {
    return false;
  }

  return crypto.timingSafeEqual(expected, received);
}
