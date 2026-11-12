import { describe, expect, it } from "vitest";
import { extractApiErrorMessage, extractApiErrorMessageSync } from "./api-error";

describe("extractApiErrorMessageSync", () => {
  it("extrai detail como string do response.data", () => {
    const error = { response: { data: { detail: " Paciente nao encontrado. " } } };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("Paciente nao encontrado.");
  });

  it("junta detail como array de strings com '; '", () => {
    const error = { response: { data: { detail: ["Campo A invalido", "Campo B invalido"] } } };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("Campo A invalido; Campo B invalido");
  });

  it("extrai mensagem de detail como objeto de conflito confirmavel (campo mensagem)", () => {
    const error = {
      response: { data: { detail: { codigo: "EXAME_DUPLICADO", mensagem: "Exame ja existe", confirmavel: true } } },
    };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("Exame ja existe");
  });

  it("cai para o campo message quando detail-objeto nao tem mensagem", () => {
    const error = { response: { data: { detail: { message: "erro generico" } } } };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("erro generico");
  });

  it("usa message de nivel superior de response.data quando nao ha detail", () => {
    const error = { response: { data: { message: "falha ao processar" } } };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("falha ao processar");
  });

  it("faz parse de response.data como string JSON e extrai detail", () => {
    const error = { response: { data: JSON.stringify({ detail: "erro serializado" }) } };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("erro serializado");
  });

  it("retorna response.data como string bruta quando nao e JSON", () => {
    const error = { response: { data: "  Internal Server Error  " } };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("Internal Server Error");
  });

  it("usa error.message quando nao ha response.data utilizavel", () => {
    const error = { message: "Network Error" };
    expect(extractApiErrorMessageSync(error, "fallback")).toBe("Network Error");
  });

  it("retorna o fallback quando nada e utilizavel", () => {
    expect(extractApiErrorMessageSync({}, "fallback")).toBe("fallback");
    expect(extractApiErrorMessageSync(null, "fallback")).toBe("fallback");
    expect(extractApiErrorMessageSync(undefined, "fallback")).toBe("fallback");
  });
});

describe("extractApiErrorMessage", () => {
  it("retorna a mensagem sincrona sem tocar em blob quando ja ha detail utilizavel", async () => {
    const error = { response: { data: { detail: "erro json" } } };
    await expect(extractApiErrorMessage(error, "fallback")).resolves.toBe("erro json");
  });

  it("le um response.data Blob com JSON e extrai detail", async () => {
    const blob = new Blob([JSON.stringify({ detail: "erro dentro do blob" })], { type: "application/json" });
    const error = { response: { data: blob } };
    await expect(extractApiErrorMessage(error, "fallback")).resolves.toBe("erro dentro do blob");
  });

  it("le um response.data Blob com texto simples (nao JSON)", async () => {
    const blob = new Blob(["falha ao gerar PDF"], { type: "text/plain" });
    const error = { response: { data: blob } };
    await expect(extractApiErrorMessage(error, "fallback")).resolves.toBe("falha ao gerar PDF");
  });

  it("retorna o fallback quando o Blob esta vazio", async () => {
    const blob = new Blob([""], { type: "text/plain" });
    const error = { response: { data: blob } };
    await expect(extractApiErrorMessage(error, "fallback")).resolves.toBe("fallback");
  });

  it("retorna o fallback quando nao ha nada utilizavel e response.data nao e Blob", async () => {
    await expect(extractApiErrorMessage({}, "fallback")).resolves.toBe("fallback");
  });
});
