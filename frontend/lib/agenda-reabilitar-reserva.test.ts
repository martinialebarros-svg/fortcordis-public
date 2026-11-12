import { describe, expect, it } from "vitest";
import {
  calcularPrazoReabilitacao,
  normalizarPrazoReabilitacaoHoras,
  parseDataHoraAgenda,
  podeReabilitarReserva,
} from "./agenda-reabilitar-reserva";

describe("podeReabilitarReserva", () => {
  it("libera o botao apenas para reservas expiradas", () => {
    expect(podeReabilitarReserva("Expirado")).toBe(true);
    expect(podeReabilitarReserva("Reservado")).toBe(false);
    expect(podeReabilitarReserva("Cancelado")).toBe(false);
    expect(podeReabilitarReserva(null)).toBe(false);
  });
});

describe("normalizarPrazoReabilitacaoHoras", () => {
  it("aceita valores dentro da faixa suportada pelo backend", () => {
    expect(normalizarPrazoReabilitacaoHoras("3")).toBe(3);
    expect(normalizarPrazoReabilitacaoHoras("0,5")).toBe(0.5);
    expect(normalizarPrazoReabilitacaoHoras(72)).toBe(72);
  });

  it("rejeita valores fora da faixa ou nao numericos", () => {
    expect(normalizarPrazoReabilitacaoHoras("")).toBeNull();
    expect(normalizarPrazoReabilitacaoHoras("abc")).toBeNull();
    expect(normalizarPrazoReabilitacaoHoras(0.25)).toBeNull();
    expect(normalizarPrazoReabilitacaoHoras(73)).toBeNull();
  });
});

describe("parseDataHoraAgenda", () => {
  it("interpreta o formato devolvido pela API como horario local", () => {
    const data = parseDataHoraAgenda("2099-05-25 11:00:00");
    expect(data?.getFullYear()).toBe(2099);
    expect(data?.getMonth()).toBe(4);
    expect(data?.getDate()).toBe(25);
    expect(data?.getHours()).toBe(11);
    expect(data?.getMinutes()).toBe(0);
  });

  it("aceita ISO com T e devolve null para valores invalidos", () => {
    expect(parseDataHoraAgenda("2099-05-25T11:30")?.getHours()).toBe(11);
    expect(parseDataHoraAgenda("")).toBeNull();
    expect(parseDataHoraAgenda("25/05/2099")).toBeNull();
  });
});

describe("calcularPrazoReabilitacao", () => {
  it("conta as horas pedidas a partir de agora quando cabe antes do atendimento", () => {
    const agora = new Date(2099, 4, 25, 8, 0, 0);
    const preview = calcularPrazoReabilitacao(3, "2099-05-25 15:00:00", agora);

    expect(preview.prazo).toBe("2099-05-25T11:00");
    expect(preview.prazoLegivel).toBe("25/05/2099 às 11:00");
    expect(preview.encurtado).toBe(false);
    expect(preview.indisponivel).toBe(false);
  });

  it("encurta o prazo para terminar antes do horario reservado", () => {
    const agora = new Date(2099, 4, 25, 10, 0, 0);
    const preview = calcularPrazoReabilitacao(3, "2099-05-25 11:00:00", agora);

    expect(preview.prazo).toBe("2099-05-25T10:55");
    expect(preview.encurtado).toBe(true);
    expect(preview.indisponivel).toBe(false);
  });

  it("marca como indisponivel quando o horario reservado esta proximo demais", () => {
    const agora = new Date(2099, 4, 25, 10, 58, 0);
    const preview = calcularPrazoReabilitacao(3, "2099-05-25 11:00:00", agora);

    expect(preview.indisponivel).toBe(true);
    expect(preview.prazo).toBe("");
  });

  it("mantem o prazo pedido quando o inicio do agendamento e desconhecido", () => {
    const agora = new Date(2099, 4, 25, 8, 30, 0);
    const preview = calcularPrazoReabilitacao(6, null, agora);

    expect(preview.prazo).toBe("2099-05-25T14:30");
    expect(preview.encurtado).toBe(false);
  });
});
