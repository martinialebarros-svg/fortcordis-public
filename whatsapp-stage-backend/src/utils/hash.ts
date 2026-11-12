import crypto from "crypto";

export function sha256HexFromBuffer(value: Buffer): string {
  return crypto.createHash("sha256").update(value).digest("hex");
}

export function sha256HexFromText(value: string): string {
  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}
