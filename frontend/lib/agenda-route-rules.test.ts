import { describe, expect, it } from "vitest";

import { DEFAULT_AGENDA_ROTA_REGRAS, normalizarAgendaRotaRegras } from "./agenda-route-rules";

describe("horarios minimos do primeiro atendimento", () => {
  it("nao publica endereco residencial em valores padrao", () => {
    const base = normalizarAgendaRotaRegras(null).base;
    expect(base.address).toBe("");
    expect(base.zip_code).toBe("");
  });

  it("inclui os horarios regionais em configuracoes antigas sem alterar os demais ajustes", () => {
    const regras = normalizarAgendaRotaRegras({
      route_policy: { end_of_route_window_start: "15:30" },
    });

    expect(regras.route_policy.end_of_route_window_start).toBe("15:30");
    expect(regras.route_policy.first_appointment_city_floors).toEqual(
      DEFAULT_AGENDA_ROTA_REGRAS.route_policy.first_appointment_city_floors
    );
  });

  it("aceita horario regional configurado e rejeita horario invalido", () => {
    const regras = normalizarAgendaRotaRegras({
      route_policy: {
        first_appointment_city_floors: { maracanau: "09:30", itaitinga: "25:00" },
      },
    });

    expect(regras.route_policy.first_appointment_city_floors.maracanau).toBe("09:30");
    expect(regras.route_policy.first_appointment_city_floors.itaitinga).toBe("09:00");
  });

  it("preserva municipios adicionais ao carregar e salvar outra configuracao", () => {
    const respostaApi = {
      route_policy: {
        first_appointment_city_floors: {
          caucaia: "08:40",
          fortaleza: "09:15",
          aquiraz: "10:00",
        },
      },
    };
    const carregado = normalizarAgendaRotaRegras(respostaApi);
    const payload = normalizarAgendaRotaRegras({
      ...carregado,
      thresholds: { ...carregado.thresholds, safe_margin_min: 10 },
    });
    const recarregado = normalizarAgendaRotaRegras(JSON.parse(JSON.stringify(payload)));

    expect(recarregado.route_policy.first_appointment_city_floors).toEqual({
      ...DEFAULT_AGENDA_ROTA_REGRAS.route_policy.first_appointment_city_floors,
      caucaia: "08:40",
      fortaleza: "09:15",
      aquiraz: "10:00",
    });
    expect(recarregado.thresholds.safe_margin_min).toBe(10);
    expect(respostaApi.route_policy.first_appointment_city_floors).toEqual({
      caucaia: "08:40",
      fortaleza: "09:15",
      aquiraz: "10:00",
    });
  });

  it("normaliza municipios adicionais e horarios com os mesmos fallbacks do backend", () => {
    const regras = normalizarAgendaRotaRegras({
      route_policy: {
        first_appointment_city_floors: {
          " MARACANAÚ ": "09:15",
          Aquiraz: "08:45",
          " AQUIRAZ ": "25:00",
          "Eusébio": "25:00",
          "São Gonçalo---do Amarante": " 10:30 ",
          "Horizonte": "09:99",
          " -- ": "11:00",
        },
      },
    });

    expect(regras.route_policy.first_appointment_city_floors).toEqual({
      caucaia: "08:30",
      maracanau: "09:15",
      eusebio: "09:00",
      itaitinga: "09:00",
      aquiraz: "08:45",
      "sao goncalo do amarante": "10:30",
      horizonte: "08:00",
    });
  });

  it("preserva os quatro padroes e cinquenta municipios adicionais retornados pela API", () => {
    const pisosApi = {
      ...DEFAULT_AGENDA_ROTA_REGRAS.route_policy.first_appointment_city_floors,
      ...Object.fromEntries(Array.from({ length: 50 }, (_, indice) => [`municipio ${indice}`, "10:00"])),
    };
    const carregado = normalizarAgendaRotaRegras({
      route_policy: { first_appointment_city_floors: pisosApi },
    });
    const payload = normalizarAgendaRotaRegras(carregado);

    expect(Object.keys(payload.route_policy.first_appointment_city_floors)).toHaveLength(54);
    expect(payload.route_policy.first_appointment_city_floors).toEqual(pisosApi);
  });

  it.each([null, [], "aquiraz=10:00"])("mantem os pisos padrao com mapa invalido: %j", (pisos) => {
    const regras = normalizarAgendaRotaRegras({
      route_policy: { first_appointment_city_floors: pisos },
    });

    expect(regras.route_policy.first_appointment_city_floors).toEqual(
      DEFAULT_AGENDA_ROTA_REGRAS.route_policy.first_appointment_city_floors
    );
  });
});

describe("transicao regional controlada", () => {
  it("mantem a transicao desativada em configuracoes antigas e preserva o limite normal", () => {
    const regras = normalizarAgendaRotaRegras({
      thresholds: { max_neighbor_travel_min: 30, safe_margin_min: 5 },
      route_policy: { end_of_route_window_start: "15:30" },
    });

    expect(regras.route_policy).toMatchObject({
      regional_transition_enabled: false,
      regional_transition_max_travel_min: 50,
      regional_transition_margin_min: 15,
      regional_transition_max_legs_per_day: 1,
      recurrent_clinic_history_days: 60,
      end_of_route_window_start: "15:30",
    });
    expect(regras.thresholds.max_neighbor_travel_min).toBe(30);
    expect(regras.thresholds.safe_margin_min).toBe(5);
  });

  it("aceita strings e preserva transicao, pisos e demais ajustes no round trip", () => {
    const entrada = {
      thresholds: { max_neighbor_travel_min: 30, same_location_transition_min: 0 },
      route_policy: {
        regional_transition_enabled: "sim",
        regional_transition_max_travel_min: "45",
        regional_transition_margin_min: "20",
        first_appointment_city_floors: { Aquiraz: "10:00" },
        reject_clear_inefficiency: false,
      },
    };
    const regras = normalizarAgendaRotaRegras(entrada);
    const recarregado = normalizarAgendaRotaRegras(JSON.parse(JSON.stringify(regras)));

    expect(recarregado).toEqual(regras);
    expect(recarregado.route_policy).toMatchObject({
      regional_transition_enabled: true,
      regional_transition_max_travel_min: 45,
      regional_transition_margin_min: 20,
      reject_clear_inefficiency: false,
    });
    expect(recarregado.route_policy.first_appointment_city_floors.aquiraz).toBe("10:00");
    expect(recarregado.thresholds.same_location_transition_min).toBe(0);
    expect(entrada.route_policy.regional_transition_max_travel_min).toBe("45");
  });

  it.each([null, 0, -1, "2", 99])("mantem cota e janela fixas para entrada %j", (valor) => {
    const { route_policy: politica } = normalizarAgendaRotaRegras({
      route_policy: {
        regional_transition_max_travel_min: 999,
        regional_transition_margin_min: 0,
        regional_transition_max_legs_per_day: valor,
        recurrent_clinic_history_days: valor,
      },
    });

    expect(politica.regional_transition_max_travel_min).toBe(50);
    expect(politica.regional_transition_margin_min).toBe(15);
    expect(politica.regional_transition_max_legs_per_day).toBe(1);
    expect(politica.recurrent_clinic_history_days).toBe(60);
  });

  it.each([null, "invalido", [], {}])("usa fallback seguro para valores invalidos: %j", (valor) => {
    const { route_policy: politica } = normalizarAgendaRotaRegras({
      route_policy: {
        regional_transition_enabled: valor,
        regional_transition_max_travel_min: valor,
        regional_transition_margin_min: valor,
      },
    });

    expect(politica.regional_transition_enabled).toBe(false);
    expect(politica.regional_transition_max_travel_min).toBe(50);
    expect(politica.regional_transition_margin_min).toBe(15);
  });

  it("preserva desativacao explicita e limita valores extremos", () => {
    const { route_policy: politica } = normalizarAgendaRotaRegras({
      route_policy: {
        regional_transition_enabled: "0",
        regional_transition_max_travel_min: 0,
        regional_transition_margin_min: 999,
      },
    });

    expect(politica.regional_transition_enabled).toBe(false);
    expect(politica.regional_transition_max_travel_min).toBe(1);
    expect(politica.regional_transition_margin_min).toBe(120);
  });
});
