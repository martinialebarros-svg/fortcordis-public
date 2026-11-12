export interface AgendaRotaBaseConfig {
  label: string;
  address: string;
  zip_code: string;
  lat: number | null;
  lng: number | null;
}

export interface AgendaRotaThresholdsConfig {
  nearby_anchor_max_travel_min: number;
  distant_clinic_min_travel_from_base_min: number;
  low_frequency_max_bookings_30d: number;
  max_insertion_detour_min: number;
  max_neighbor_travel_min: number;
  safe_margin_min: number;
  same_location_transition_min: number;
}

export interface AgendaRotaOfferPolicyConfig {
  default_first_offer_days_ahead: number[];
  distant_low_frequency_first_offer_days_ahead: number[];
  allow_d2_if_anchor_exists: boolean;
  emergency_first_offer_days_ahead: number[];
}

export interface AgendaRotaRoutePolicyConfig {
  end_of_route_window_start: string;
  first_appointment_city_floors: {
    [municipio: string]: string;
    caucaia: string;
    maracanau: string;
    eusebio: string;
    itaitinga: string;
  };
  prefer_near_base_at_end_of_route: boolean;
  bonus_near_base_score: number;
  penalty_far_base_score: number;
  reject_clear_inefficiency: boolean;
  regional_transition_enabled: boolean;
  regional_transition_max_travel_min: number;
  regional_transition_margin_min: number;
  regional_transition_max_legs_per_day: 1;
  recurrent_clinic_history_days: 60;
}

export interface AgendaRotaFallbackPolicyConfig {
  suggest_alternative_slots_when_blocked: boolean;
  max_alternative_suggestions: number;
  allow_extra_slot_start_or_end_route_for_emergency: boolean;
}

export interface AgendaRotaRenderingPolicyConfig {
  use_custom_window: boolean;
  window_start: string;
  window_end: string;
  slot_interval_min: number;
}

export interface AgendaRotaClinicOverrideConfig {
  clinic_name: string;
  force_days_ahead: number[];
  prefer_only_when_anchor_exists: boolean;
  notes: string;
}

export interface AgendaRotaRegrasConfig {
  version: string;
  base: AgendaRotaBaseConfig;
  thresholds: AgendaRotaThresholdsConfig;
  offer_policy: AgendaRotaOfferPolicyConfig;
  route_policy: AgendaRotaRoutePolicyConfig;
  fallback_policy: AgendaRotaFallbackPolicyConfig;
  rendering_policy: AgendaRotaRenderingPolicyConfig;
  clinic_overrides: AgendaRotaClinicOverrideConfig[];
}

export const DEFAULT_AGENDA_ROTA_REGRAS: AgendaRotaRegrasConfig = {
  version: "1.0.0",
  base: {
    label: "Casa (base operacional)",
    address: "",
    zip_code: "",
    lat: null,
    lng: null,
  },
  thresholds: {
    nearby_anchor_max_travel_min: 20,
    distant_clinic_min_travel_from_base_min: 35,
    low_frequency_max_bookings_30d: 3,
    max_insertion_detour_min: 25,
    max_neighbor_travel_min: 45,
    safe_margin_min: 5,
    same_location_transition_min: 5,
  },
  offer_policy: {
    default_first_offer_days_ahead: [2],
    distant_low_frequency_first_offer_days_ahead: [3, 4],
    allow_d2_if_anchor_exists: true,
    emergency_first_offer_days_ahead: [1, 2],
  },
  route_policy: {
    end_of_route_window_start: "16:00",
    first_appointment_city_floors: {
      caucaia: "08:30",
      maracanau: "09:00",
      eusebio: "09:00",
      itaitinga: "09:00",
    },
    prefer_near_base_at_end_of_route: true,
    bonus_near_base_score: 15,
    penalty_far_base_score: 10,
    reject_clear_inefficiency: true,
    regional_transition_enabled: false,
    regional_transition_max_travel_min: 50,
    regional_transition_margin_min: 15,
    regional_transition_max_legs_per_day: 1,
    recurrent_clinic_history_days: 60,
  },
  fallback_policy: {
    suggest_alternative_slots_when_blocked: true,
    max_alternative_suggestions: 3,
    allow_extra_slot_start_or_end_route_for_emergency: true,
  },
  rendering_policy: {
    use_custom_window: false,
    window_start: "08:00",
    window_end: "18:00",
    slot_interval_min: 30,
  },
  clinic_overrides: [],
};

const normalizarInt = (value: unknown, fallback: number, min: number, max: number): number => {
  const parsed = Number.parseInt(String(value ?? fallback), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
};

const normalizarFloat = (value: unknown): number | null => {
  if (value == null || value === "") return null;
  const parsed = Number.parseFloat(String(value).replace(",", "."));
  if (!Number.isFinite(parsed)) return null;
  return parsed;
};

const normalizarBool = (value: unknown, fallback: boolean): boolean => {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const raw = value.trim().toLowerCase();
    if (["1", "true", "yes", "sim", "on"].includes(raw)) return true;
    if (["0", "false", "no", "nao", "não", "off"].includes(raw)) return false;
  }
  return fallback;
};

const normalizarHoraHHMM = (value: unknown, fallback: string): string => {
  const raw = String(value ?? "").trim();
  const match = raw.match(/^(\d{2}):(\d{2})$/);
  if (!match) return fallback;
  const hh = Number.parseInt(match[1], 10);
  const mm = Number.parseInt(match[2], 10);
  if (!Number.isFinite(hh) || !Number.isFinite(mm)) return fallback;
  if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return fallback;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
};

const normalizarPisosMunicipais = (
  value: unknown
): AgendaRotaRoutePolicyConfig["first_appointment_city_floors"] => {
  const pisos = { ...DEFAULT_AGENDA_ROTA_REGRAS.route_policy.first_appointment_city_floors };
  if (!value || typeof value !== "object" || Array.isArray(value)) return pisos;

  for (const [municipio, hora] of Object.entries(value)) {
    // Mantem as chaves de municipio compativeis com normalizar_municipio_agenda.
    const chave = municipio
      .normalize("NFKD")
      .replace(new RegExp("\\p{M}", "gu"), "")
      .toLowerCase()
      .replace(new RegExp("[^\\p{L}\\p{N}]+", "gu"), " ")
      .trim();
    if (!chave) continue;
    const fallback = typeof pisos[chave] === "string" ? pisos[chave] : "08:00";
    pisos[chave] = normalizarHoraHHMM(hora, fallback);
  }

  return pisos;
};

const horaParaMinutos = (value: string): number => {
  const [hh, mm] = value.split(":").map((item) => Number.parseInt(item, 10));
  return (Number.isFinite(hh) ? hh : 0) * 60 + (Number.isFinite(mm) ? mm : 0);
};

export const normalizarDiasAFrente = (value: unknown, fallback: number[]): number[] => {
  const listaRaw = Array.isArray(value)
    ? value
    : String(value ?? "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);

  const dias = new Set<number>();
  for (const item of listaRaw) {
    const parsed = Number.parseInt(String(item), 10);
    if (!Number.isFinite(parsed)) continue;
    if (parsed < 0 || parsed > 30) continue;
    dias.add(parsed);
  }

  const ordenado = Array.from(dias).sort((a, b) => a - b);
  return ordenado.length > 0 ? ordenado : [...fallback];
};

const normalizarClinicOverrides = (value: unknown): AgendaRotaClinicOverrideConfig[] => {
  if (!Array.isArray(value)) return [];
  const normalized: AgendaRotaClinicOverrideConfig[] = [];

  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const clinicName = String(row.clinic_name ?? "").trim();
    if (!clinicName) continue;
    normalized.push({
      clinic_name: clinicName,
      force_days_ahead: normalizarDiasAFrente(
        row.force_days_ahead,
        DEFAULT_AGENDA_ROTA_REGRAS.offer_policy.distant_low_frequency_first_offer_days_ahead
      ),
      prefer_only_when_anchor_exists: normalizarBool(row.prefer_only_when_anchor_exists, true),
      notes: String(row.notes ?? "").trim(),
    });
  }

  return normalized;
};

export const normalizarAgendaRotaRegras = (payload: unknown): AgendaRotaRegrasConfig => {
  const source = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const defaultCfg = DEFAULT_AGENDA_ROTA_REGRAS;

  const baseRaw =
    source.base && typeof source.base === "object" ? (source.base as Record<string, unknown>) : {};
  const thresholdsRaw =
    source.thresholds && typeof source.thresholds === "object"
      ? (source.thresholds as Record<string, unknown>)
      : {};
  const offerRaw =
    source.offer_policy && typeof source.offer_policy === "object"
      ? (source.offer_policy as Record<string, unknown>)
      : {};
  const routeRaw =
    source.route_policy && typeof source.route_policy === "object"
      ? (source.route_policy as Record<string, unknown>)
      : {};
  const fallbackRaw =
    source.fallback_policy && typeof source.fallback_policy === "object"
      ? (source.fallback_policy as Record<string, unknown>)
      : {};
  const renderingRaw =
    source.rendering_policy && typeof source.rendering_policy === "object"
      ? (source.rendering_policy as Record<string, unknown>)
      : {};

  const lat = normalizarFloat(baseRaw.lat);
  const lng = normalizarFloat(baseRaw.lng);
  const renderingStart = normalizarHoraHHMM(
    renderingRaw.window_start,
    defaultCfg.rendering_policy.window_start
  );
  const renderingEnd = normalizarHoraHHMM(
    renderingRaw.window_end,
    defaultCfg.rendering_policy.window_end
  );
  const renderingWindowValida = horaParaMinutos(renderingStart) < horaParaMinutos(renderingEnd);

  return {
    version: String(source.version ?? defaultCfg.version).trim() || defaultCfg.version,
    base: {
      label: String(baseRaw.label ?? defaultCfg.base.label).trim() || defaultCfg.base.label,
      address: String(baseRaw.address ?? defaultCfg.base.address).trim() || defaultCfg.base.address,
      zip_code: String(baseRaw.zip_code ?? defaultCfg.base.zip_code).trim() || defaultCfg.base.zip_code,
      lat: lat != null && lat >= -90 && lat <= 90 ? lat : null,
      lng: lng != null && lng >= -180 && lng <= 180 ? lng : null,
    },
    thresholds: {
      nearby_anchor_max_travel_min: normalizarInt(
        thresholdsRaw.nearby_anchor_max_travel_min,
        defaultCfg.thresholds.nearby_anchor_max_travel_min,
        1,
        240
      ),
      distant_clinic_min_travel_from_base_min: normalizarInt(
        thresholdsRaw.distant_clinic_min_travel_from_base_min,
        defaultCfg.thresholds.distant_clinic_min_travel_from_base_min,
        1,
        360
      ),
      low_frequency_max_bookings_30d: normalizarInt(
        thresholdsRaw.low_frequency_max_bookings_30d,
        defaultCfg.thresholds.low_frequency_max_bookings_30d,
        0,
        60
      ),
      max_insertion_detour_min: normalizarInt(
        thresholdsRaw.max_insertion_detour_min,
        defaultCfg.thresholds.max_insertion_detour_min,
        0,
        360
      ),
      max_neighbor_travel_min: normalizarInt(
        thresholdsRaw.max_neighbor_travel_min,
        defaultCfg.thresholds.max_neighbor_travel_min,
        0,
        360
      ),
      safe_margin_min: normalizarInt(
        thresholdsRaw.safe_margin_min,
        defaultCfg.thresholds.safe_margin_min,
        0,
        120
      ),
      same_location_transition_min: normalizarInt(
        thresholdsRaw.same_location_transition_min,
        defaultCfg.thresholds.same_location_transition_min,
        0,
        120
      ),
    },
    offer_policy: {
      default_first_offer_days_ahead: normalizarDiasAFrente(
        offerRaw.default_first_offer_days_ahead,
        defaultCfg.offer_policy.default_first_offer_days_ahead
      ),
      distant_low_frequency_first_offer_days_ahead: normalizarDiasAFrente(
        offerRaw.distant_low_frequency_first_offer_days_ahead,
        defaultCfg.offer_policy.distant_low_frequency_first_offer_days_ahead
      ),
      allow_d2_if_anchor_exists: normalizarBool(
        offerRaw.allow_d2_if_anchor_exists,
        defaultCfg.offer_policy.allow_d2_if_anchor_exists
      ),
      emergency_first_offer_days_ahead: normalizarDiasAFrente(
        offerRaw.emergency_first_offer_days_ahead,
        defaultCfg.offer_policy.emergency_first_offer_days_ahead
      ),
    },
    route_policy: {
      end_of_route_window_start: normalizarHoraHHMM(
        routeRaw.end_of_route_window_start,
        defaultCfg.route_policy.end_of_route_window_start
      ),
      first_appointment_city_floors: normalizarPisosMunicipais(routeRaw.first_appointment_city_floors),
      prefer_near_base_at_end_of_route: normalizarBool(
        routeRaw.prefer_near_base_at_end_of_route,
        defaultCfg.route_policy.prefer_near_base_at_end_of_route
      ),
      bonus_near_base_score: Math.abs(
        normalizarInt(routeRaw.bonus_near_base_score, defaultCfg.route_policy.bonus_near_base_score, -999, 999)
      ),
      penalty_far_base_score: normalizarInt(
        routeRaw.penalty_far_base_score,
        defaultCfg.route_policy.penalty_far_base_score,
        0,
        999
      ),
      reject_clear_inefficiency: normalizarBool(
        routeRaw.reject_clear_inefficiency,
        defaultCfg.route_policy.reject_clear_inefficiency
      ),
      regional_transition_enabled: normalizarBool(
        routeRaw.regional_transition_enabled,
        defaultCfg.route_policy.regional_transition_enabled
      ),
      regional_transition_max_travel_min: normalizarInt(
        routeRaw.regional_transition_max_travel_min,
        defaultCfg.route_policy.regional_transition_max_travel_min,
        1,
        50
      ),
      regional_transition_margin_min: normalizarInt(
        routeRaw.regional_transition_margin_min,
        defaultCfg.route_policy.regional_transition_margin_min,
        15,
        120
      ),
      regional_transition_max_legs_per_day: 1,
      recurrent_clinic_history_days: 60,
    },
    fallback_policy: {
      suggest_alternative_slots_when_blocked: normalizarBool(
        fallbackRaw.suggest_alternative_slots_when_blocked,
        defaultCfg.fallback_policy.suggest_alternative_slots_when_blocked
      ),
      max_alternative_suggestions: normalizarInt(
        fallbackRaw.max_alternative_suggestions,
        defaultCfg.fallback_policy.max_alternative_suggestions,
        1,
        20
      ),
      allow_extra_slot_start_or_end_route_for_emergency: normalizarBool(
        fallbackRaw.allow_extra_slot_start_or_end_route_for_emergency,
        defaultCfg.fallback_policy.allow_extra_slot_start_or_end_route_for_emergency
      ),
    },
    rendering_policy: {
      use_custom_window: normalizarBool(
        renderingRaw.use_custom_window,
        defaultCfg.rendering_policy.use_custom_window
      ),
      window_start: renderingWindowValida ? renderingStart : defaultCfg.rendering_policy.window_start,
      window_end: renderingWindowValida ? renderingEnd : defaultCfg.rendering_policy.window_end,
      slot_interval_min: normalizarInt(
        renderingRaw.slot_interval_min,
        defaultCfg.rendering_policy.slot_interval_min,
        5,
        120
      ),
    },
    clinic_overrides: normalizarClinicOverrides(source.clinic_overrides),
  };
};

export const formatarDiasAFrenteInput = (value: number[]): string => {
  return Array.isArray(value) ? value.join(", ") : "";
};
