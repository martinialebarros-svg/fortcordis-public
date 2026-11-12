import { describe, expect, it } from "vitest";
import { clinicCoordinates } from "./clinic-coordinates";
describe("coordenadas de clínicas", () => {
  it.each([[null, null], [undefined, undefined], ["", ""], [" ", -38], [false, -38], [91, -38], [-3, 181], [NaN, -38], [0, 0], [-3, null]])("rejeita par inválido %s/%s", (lat, lng) => {
    expect(clinicCoordinates(lat, lng)).toEqual({ latitude: null, longitude: null });
  });
  it("aceita coordenadas válidas numéricas e serializadas", () => {
    expect(clinicCoordinates("-3.7", -38.5)).toEqual({ latitude: -3.7, longitude: -38.5 });
    expect(clinicCoordinates(0, -38)).toEqual({ latitude: 0, longitude: -38 });
  });
});
