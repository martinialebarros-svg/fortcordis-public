import { describe, expect, it } from "vitest";

import {
  buildClinicLinksPayload,
  clinicLinksFromPartner,
  resumoDoVinculo,
  toggleClinicBroadcast,
  toggleClinicLink,
} from "./portal-partner-clinic-links";

describe("vinculo do veterinario parceiro com clinicas", () => {
  it("marca a clinica com a difusao desligada por padrao", () => {
    const links = toggleClinicLink([], 7);

    expect(links).toEqual([{ clinica_id: 7, receber_todos_laudos: false }]);
  });

  it("desmarcar a clinica remove o vinculo e preserva os demais", () => {
    const links = toggleClinicLink(
      [
        { clinica_id: 7, receber_todos_laudos: true },
        { clinica_id: 9, receber_todos_laudos: false },
      ],
      7,
    );

    expect(links).toEqual([{ clinica_id: 9, receber_todos_laudos: false }]);
  });

  it("marca tres clinicas, que e o caso do veterinario volante", () => {
    const links = [7, 9, 11].reduce(toggleClinicLink, [] as ReturnType<typeof toggleClinicLink>);

    expect(links.map((link) => link.clinica_id)).toEqual([7, 9, 11]);
  });

  it("o interruptor de difusao muda so a clinica alvo", () => {
    const links = toggleClinicBroadcast(
      [
        { clinica_id: 7, receber_todos_laudos: false },
        { clinica_id: 9, receber_todos_laudos: false },
      ],
      9,
    );

    expect(links).toEqual([
      { clinica_id: 7, receber_todos_laudos: false },
      { clinica_id: 9, receber_todos_laudos: true },
    ]);
  });

  it("o interruptor volta a desligar no segundo clique", () => {
    const ligado = toggleClinicBroadcast([{ clinica_id: 7, receber_todos_laudos: false }], 7);
    const desligado = toggleClinicBroadcast(ligado, 7);

    expect(desligado).toEqual([{ clinica_id: 7, receber_todos_laudos: false }]);
  });

  it("carrega o que esta salvo no parceiro para o formulario", () => {
    const links = clinicLinksFromPartner([
      { clinica_id: 7, clinica_nome: "Animal Care", receber_todos_laudos: true },
      { clinica_id: 9, clinica_nome: "Bicho Feliz", receber_todos_laudos: false },
    ]);

    expect(links).toEqual([
      { clinica_id: 7, receber_todos_laudos: true },
      { clinica_id: 9, receber_todos_laudos: false },
    ]);
  });

  it("parceiro sem vinculo nenhum vira lista vazia", () => {
    expect(clinicLinksFromPartner(undefined)).toEqual([]);
    expect(clinicLinksFromPartner(null)).toEqual([]);
  });

  it("o payload do veterinario leva os vinculos", () => {
    const payload = buildClinicLinksPayload("veterinario", [
      { clinica_id: 7, receber_todos_laudos: true },
    ]);

    expect(payload).toEqual([{ clinica_id: 7, receber_todos_laudos: true }]);
  });

  it("o veterinario sem clinica marcada envia lista vazia, que limpa os vinculos", () => {
    expect(buildClinicLinksPayload("veterinario", [])).toEqual([]);
  });

  it("parceiro do tipo clinica nao envia o campo, e o backend deixa tudo como esta", () => {
    expect(buildClinicLinksPayload("clinica", [{ clinica_id: 7 }])).toBeUndefined();
  });

  it("explica o que cada estado do vinculo significa", () => {
    expect(resumoDoVinculo({ clinica_id: 7, receber_todos_laudos: true })).toContain(
      "Recebe todo laudo",
    );
    expect(resumoDoVinculo({ clinica_id: 7, receber_todos_laudos: false })).toContain(
      "em que for nomeado",
    );
  });
});
