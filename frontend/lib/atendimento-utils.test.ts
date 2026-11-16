import { describe, expect, it, vi } from "vitest";
import { isoToLocalInput, isoToOptionalLocalInput, localInputToOperationalIso } from "./atendimento-utils";

describe("data e hora do atendimento", () => {
  it.each([
    ["2026-11-15T20:59:35.970744Z", "2026-11-15T17:59:35.970744"],
    ["2026-11-16T01:03:47+00:00", "2026-11-15T22:03:47"],
    ["2026-11-15T17:59:05-03:00", "2026-11-15T17:59:05"],
    ["2026-11-15 17:59:35", "2026-11-15T17:59:35"],
    ["2026-11-15T17:59", "2026-11-15T17:59:00"],
  ])("preserva a precisão de %s ao carregar e salvar", (fromApi, localValue) => {
    expect(isoToLocalInput(fromApi)).toBe(localValue);
    expect(localInputToOperationalIso(localValue)).toBe(`${localValue}-03:00`);
  });

  it("usa segundos no horário inicial de um novo atendimento", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-11-15T20:59:35.970744Z"));
      expect(isoToLocalInput()).toBe("2026-11-15T17:59:35");
    } finally {
      vi.useRealTimers();
    }
  });

  it("mantém o formato dos campos opcionais que usam precisão de minuto", () => {
    expect(isoToOptionalLocalInput("2026-11-15T20:59:35.970744Z")).toBe("2026-11-15T17:59");
    expect(isoToOptionalLocalInput(null)).toBe("");
  });
});
