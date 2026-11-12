import { describe, expect, it } from "vitest";
import { ajustarPagamentoSugerido } from "./recebimento-desconto";

describe("desconto no recebimento", () => {
  it("reduz a sugestao de 340 para 250 sem criar excedente de 90", () => {
    expect(ajustarPagamentoSugerido([{ valor: "340.00" }], 340, 250)[0].valor).toBe("250.00");
  });
  it("acompanha a retirada do desconto e desconta o credito utilizado", () => {
    expect(ajustarPagamentoSugerido([{ valor: "230.00" }], 250, 340, 20)[0].valor).toBe("320.00");
  });
  it("preserva pagamentos editados e pagamentos divididos", () => {
    const editados = [{ valor: "400.00" }];
    const divididos = [{ valor: "200.00" }, { valor: "140.00" }];
    expect(ajustarPagamentoSugerido(editados, 340, 250)).toBe(editados);
    expect(ajustarPagamentoSugerido(divididos, 340, 250)).toBe(divididos);
  });
  it("permite desconto integral com pagamento sugerido zero", () => {
    expect(ajustarPagamentoSugerido([{ valor: "340.00" }], 340, 0)[0].valor).toBe("0.00");
  });
});
