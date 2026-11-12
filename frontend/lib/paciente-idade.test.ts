import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { calcularIdadeComFonte, changePatientAge, importedPatientAge, normalizarNascimento, parsePatientAge, patientAgeForm, patientAgePayload } from "./paciente-idade";
import { extrairIdadePaciente } from "./paciente";
import { lowWeightAgeContext } from "./echo-low-weight-reference";

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-04T15:00:00Z")); });
afterEach(() => vi.useRealTimers());
describe("fonte de idade", () => {
  it("idade digitada ganha sem apagar nascimento ou fabricar aniversário", () => {
    const form = changePatientAge({ data_nascimento: "2026-11-03", idade: "0m" }, "idade", "12 anos");
    expect(form).toMatchObject({ data_nascimento: "2026-11-03", idade_informada: "12 anos", idade_referencia: "2026-11-04", idade_fonte: "idade" });
    expect(extrairIdadePaciente(form)).toBe("12a (estimada)");
    expect(lowWeightAgeContext(extrairIdadePaciente(form))).toBe("adult");
  });
  it("avança no calendário sem reancorar ao abrir ou salvar outros campos", () => {
    const source = { idade_fonte: "idade", idade_informada: "8 meses", idade_referencia: "2025-01-31" };
    expect(calcularIdadeComFonte(source, "2025-02-28")).toBe("9m (estimada)");
    expect(calcularIdadeComFonte(source, "2026-01-31")).toBe("1a 8m (estimada)");
    expect(calcularIdadeComFonte(source, "2024-04-01")).toBe("");
    expect(patientAgePayload(patientAgeForm(source)).idade_referencia).toBe("2025-01-31");
  });
  it("conserva dias e semanas sem nascimento", () => {
    const source = { idade_fonte: "idade", idade_informada: "2 semanas", idade_referencia: "2026-11-01" };
    expect(calcularIdadeComFonte(source)).toBe("17d (estimada)");
    expect(calcularIdadeComFonte(source, "2026-10-01")).toBe("");
    expect(parsePatientAge("0,5 anos")).toEqual([6, 0]);
  });
  it("data exata usa meses completos e ano isolado permanece intervalo", () => {
    expect(normalizarNascimento("04/11/2025")).toBe("2025-11-04");
    const source = { idade_fonte: "nascimento", data_nascimento: "2025-11-04" };
    expect(calcularIdadeComFonte(source)).toBe("1a");
    expect(calcularIdadeComFonte(source, "2026-11-03")).toBe("11m");
    expect(calcularIdadeComFonte({ ...source, data_nascimento: "2014" })).toBe("11–12 anos (estimada pelo ano)");
    expect(lowWeightAgeContext(calcularIdadeComFonte({ ...source, data_nascimento: "2025" }))).toBe("unknown");
    expect(lowWeightAgeContext(calcularIdadeComFonte({ ...source, data_nascimento: "2026" }))).toBe("juvenile");
  });
  it("não presume a fonte dos cadastros antigos", () => {
    expect(extrairIdadePaciente({ observacoes: "Idade: 12 anos" })).toBe("12 anos");
    expect(patientAgeForm({ idade: "12 anos" }).idade_informada).toBe("");
  });
  it.each(["-1 ano", "adulto", "1 ano ou 5 meses", "1a 2a"])("rejeita declaração ambígua %s", (age) => expect(parsePatientAge(age)).toBeNull());
});

it("normaliza a data-base vazia e conserva dias declarados", () => {
  expect(changePatientAge({}, "idade", "12 anos", "").idade_referencia).toBe("2026-11-04");
  const source = { idade_fonte: "idade", idade_informada: "1 mês 29 dias", idade_referencia: "2026-10-01" };
  expect(calcularIdadeComFonte(source, "2026-10-03")).toBe("2m (estimada)");
  expect(calcularIdadeComFonte(source, "2026-08-01")).toBe("");
});
it("importa nascimento observado sem transformar idade calculada em declaração", () => {
  const birth = importedPatientAge({}, { nascimento: "20250820", idade: "10 meses" }, "2026-07-11");
  expect(birth).toMatchObject({ data_nascimento: "2025-08-20", idade_fonte: "nascimento", idade_informada: "", idade_referencia: "" });
  const age = importedPatientAge({}, { idade: "8 anos" }, "2026-07-11");
  expect(age).toMatchObject({ idade_fonte: "idade", idade_informada: "8 anos", idade_referencia: "2026-07-11", data_nascimento: "" });
});
