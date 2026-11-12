import { describe, expect, it } from "vitest";
import {
  DEFAULT_SAFE_REQUEST_TIMEOUT_MS,
  shouldApplyDefaultSafeRequestTimeout,
} from "./axios";

describe("politica de timeout do cliente HTTP", () => {
  it("limita leitura JSON segura sem timeout explicito", () => {
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "get" })).toBe(true);
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "HEAD", responseType: "json" })).toBe(true);
    expect(DEFAULT_SAFE_REQUEST_TIMEOUT_MS).toBe(15_000);
  });

  it("preserva timeout explicito", () => {
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "get", timeout: 45_000 })).toBe(false);
  });

  it("nao limita automaticamente mutacoes", () => {
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "post" })).toBe(false);
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "delete" })).toBe(false);
  });

  it("nao limita automaticamente respostas binarias", () => {
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "get", responseType: "blob" })).toBe(false);
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "get", responseType: "arraybuffer" })).toBe(false);
    expect(shouldApplyDefaultSafeRequestTimeout({ method: "get", responseType: "stream" })).toBe(false);
  });
});
